# -*- coding: utf-8 -*-
"""說明覆蓋率（K23）與缺口主題（K24）。

覆蓋率：方案 × 功能點，交叉看「租戶用多少」與「有沒有說明」，最常用卻沒說明的排最前。
每次知識更新收尾時重算，也可以手動重算。
缺口主題：使用者問了、AI 判定方案裡根本沒有對應功能的問句，每週分群成主題——
那是「該做什麼新功能／新說明」的訊號，不是同義詞能補的。
"""
import json
import logging

from odoo import _, api, fields, models

from ..services import hub_client, search_lib

_logger = logging.getLogger(__name__)

COVERAGE_STATES = [
    ('article', '有說明文章'),
    ('official', '連 Odoo 官方文件'),
    ('missing', '缺說明'),
]


class KnowledgeCoverage(models.Model):
    _name = 'corpaas.knowledge.coverage'
    _description = '說明覆蓋率'
    _order = 'status_rank, usage_score desc'

    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True)
    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True)
    kind = fields.Selection(related='feature_id.kind', store=True)
    module = fields.Char(related='feature_id.module', store=True)
    module_origin = fields.Selection(related='feature_id.module_origin', store=True)
    customized = fields.Boolean(string='專用模組改過', help='依這個方案的黃金庫')
    usage_score = fields.Float(readonly=True)
    usage_source = fields.Selection(related='feature_id.usage_source', store=True)
    capability_names = fields.Char(string='能力', readonly=True)
    flow_id = fields.Many2one('corpaas.knowledge.flow', string='流程', ondelete='set null')
    status = fields.Selection(COVERAGE_STATES, required=True, index=True)
    classification = fields.Selection(
        [('own_adv', '專用進階'), ('own_base', '專用功能'),
         ('std_adv', '標準進階'), ('std_base', '標準功能')], string='功能分類', index=True)
    core = fields.Boolean(string='方案核心')
    status_rank = fields.Integer(help='排序：缺說明在前')
    computed_at = fields.Datetime(readonly=True)


class KnowledgeGap(models.Model):
    _name = 'corpaas.knowledge.gap'
    _description = '說明缺口主題'
    _order = 'state, query_count desc'

    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True)
    topic = fields.Char(required=True)
    query_count = fields.Integer(string='問句數')
    samples = fields.Text(string='問句範例', help='一行一個')
    state = fields.Selection([('new', '待評估'), ('planned', '已排入'),
                              ('dismissed', '不處理')], default='new', index=True)
    last_seen = fields.Datetime(readonly=True)

    def action_plan(self):
        self.write({'state': 'planned'})
        return True

    @api.model
    def _gc(self, days=180):
        old = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        recs = self.search([('state', '=', 'dismissed'), ('write_date', '<', old)])
        n = len(recs)
        recs.unlink()
        return n

    def action_dismiss(self):
        self.write({'state': 'dismissed'})
        return True


class KnowledgeHelpLog(models.Model):
    _inherit = 'corpaas.knowledge.help.log'

    unmatched = fields.Boolean(index=True, help='AI 判定方案裡沒有對應功能（同義詞補不了）')
    clustered = fields.Boolean(help='已分群進缺口主題')

    @api.model
    def _gc(self, days=180):
        """處理過的查詢紀錄（已補同義詞、已分群、或有命中）留半年。"""
        old = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        recs = self.search([('create_date', '<', old), '|', '|', ('handled', '=', True),
                            ('clustered', '=', True), ('missed', '=', False)])
        n = len(recs)
        recs.unlink()
        return n

    @api.model
    def _cron_cluster_gaps(self, batch=200):
        """每週：沒有對應功能的問句 → AI 分群成主題（K24）。"""
        logs = self.search([('unmatched', '=', True), ('clustered', '=', False)], limit=batch)
        Gap = self.env['corpaas.knowledge.gap'].sudo()
        for pkg in logs.mapped('package_id'):
            recs = logs.filtered(lambda r: r.package_id == pkg)
            queries = list(dict.fromkeys(q for q in recs.mapped('query') if q))
            if not queries:
                recs.write({'clustered': True})
                continue
            existing = Gap.search([('package_id', '=', pkg.id), ('state', '!=', 'dismissed')])
            prompt = (
                "使用者在方案「%s」問了這些問題，但方案裡沒有對應的功能。請把意思相近的歸成"
                "同一個主題（主題名用 4–12 字的中文名詞片語）；能歸入既有主題就沿用原名。\n"
                "格式：{\"topics\":[{\"topic\":…,\"queries\":[…]}]}\n\n"
                "既有主題：%s\n\n問題：%s"
            ) % (pkg.display_name, json.dumps(existing.mapped('topic'), ensure_ascii=False),
                 json.dumps(queries, ensure_ascii=False))
            try:
                data = self.env['corpaas.knowledge.ai'].ask('gap_cluster', prompt, package=pkg)
            except hub_client.HubError as e:
                _logger.warning('[knowledge] 缺口分群略過 %s：%s', pkg.display_name, e)
                continue
            now = fields.Datetime.now()
            for item in (data or {}).get('topics') or []:
                topic = (item.get('topic') or '').strip()
                qs = [q for q in item.get('queries') or [] if isinstance(q, str)]
                if not topic or not qs:
                    continue
                key = search_lib.normalize_name(topic)
                gap = existing.filtered(lambda g: search_lib.normalize_name(g.topic) == key)[:1]
                if gap:
                    gap.write({'query_count': gap.query_count + len(qs), 'last_seen': now,
                               'samples': '\n'.join(search_lib.merge_lines(
                                   gap.samples, qs).splitlines()[:10])})
                else:
                    existing |= Gap.create({'package_id': pkg.id, 'topic': topic,
                                            'query_count': len(qs), 'last_seen': now,
                                            'samples': '\n'.join(qs[:10])})
            recs.write({'clustered': True})
        return True


class SolutionPackage(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_pending_count = fields.Integer(compute='_compute_knowledge_pending',
                                             string='待審數')
    knowledge_pending_days = fields.Float(compute='_compute_knowledge_pending',
                                          string='待審平均天數')
    knowledge_coverage_rate = fields.Float(compute='_compute_knowledge_coverage_rate',
                                           string='說明覆蓋率（%）')

    def _compute_knowledge_pending(self):
        """核准瓶頸的指標（K22／K23）：待審的圈選提案＋官方文件對照。"""
        Sel = self.env['corpaas.knowledge.selection'].sudo()
        now = fields.Datetime.now()
        for rec in self:
            props = Sel.search([('package_id', '=', rec.id), ('state', '=', 'proposed')]) \
                if rec.id else Sel
            rec.knowledge_pending_count = len(props)
            ages = [(now - p.create_date).total_seconds() / 86400.0 for p in props]
            rec.knowledge_pending_days = round(sum(ages) / len(ages), 1) if ages else 0.0

    def _compute_knowledge_coverage_rate(self):
        Cov = self.env['corpaas.knowledge.coverage'].sudo()
        for rec in self:
            rows = Cov.search([('package_id', '=', rec.id)]) if rec.id else Cov
            covered = len(rows.filtered(lambda r: r.status != 'missing'))
            rec.knowledge_coverage_rate = round(100.0 * covered / len(rows), 1) if rows else 0.0

    def _knowledge_rebuild_coverage(self):
        """重算覆蓋率：每個現存功能點一列。"""
        Cov = self.env['corpaas.knowledge.coverage'].sudo()
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        hooks = self.env['corpaas.knowledge.hooks']
        for rec in self:
            feats = self.env['corpaas.knowledge.feature'].sudo().search([
                ('package_ids', 'in', rec.id), ('missing', '=', False)])
            covered = hooks._knowledge_covered_features(rec, feats)
            official = set(self.env['corpaas.knowledge.official_doc'].sudo().search([
                ('feature_id', 'in', feats.ids), ('state', '=', 'approved')
            ]).mapped('feature_id').ids)
            flows = Flow.search([('package_ids', 'in', rec.id)])
            flow_of = {}
            for flow in flows:
                for f in flow.feature_ids:
                    flow_of.setdefault(f.id, flow.id)
            classes = {c.feature_id.id: c for c in self.env['corpaas.knowledge.feature.class']
                       .sudo().search([('package_id', '=', rec.id)])}
            now = fields.Datetime.now()
            Cov.search([('package_id', '=', rec.id)]).unlink()
            vals = []
            for f in feats:
                if f.id in covered:
                    status = 'article'
                elif f.id in official and not f.attr_for(rec, 'customized'):
                    status = 'official'
                else:
                    status = 'missing'
                vals.append({
                    'package_id': rec.id, 'feature_id': f.id,
                    'usage_score': f.attr_for(rec, 'usage_score') or 0,
                    'customized': bool(f.attr_for(rec, 'customized')),
                    'capability_names': ', '.join(f.capability_ids.mapped('name')) or False,
                    'flow_id': flow_of.get(f.id, False), 'status': status,
                    'classification': classes[f.id].classification if f.id in classes else False,
                    'core': classes[f.id].core if f.id in classes else False,
                    'status_rank': {'missing': 0, 'official': 1, 'article': 2}[status],
                    'computed_at': now})
            Cov.create(vals)
        return True

    def action_knowledge_coverage(self):
        self.ensure_one()
        self._knowledge_rebuild_coverage()
        return {
            'type': 'ir.actions.act_window', 'name': _('說明覆蓋率'),
            'res_model': 'corpaas.knowledge.coverage', 'view_mode': 'list,pivot',
            'domain': [('package_id', '=', self.id)],
            'context': {'search_default_g_status': 1},
        }
