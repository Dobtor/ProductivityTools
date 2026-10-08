# -*- coding: utf-8 -*-
"""方案知識範本庫：把一次驗收通過的成果存起來，清除重跑時直接套用，不重新叫 AI 生。

★ 為什麼：能力分群與命名、情境與示範資料、流程名稱、實測到的狀態轉換都是 AI 或多輪迭代
  才得到的；全部清掉重跑，AI 每次給的不一樣、迭代也要再走一遍，結果不會一致。範本庫跟
  資料包、角色範本一樣屬於「共用庫」，清除時保留。
★ 套用時機（全量更新裡）：
  · 方案還沒有能力 → 依範本建能力（直接上線，它們當初是核准過的），功能點照功能鍵掛回去；
    範本裡沒有的新功能點才交給 AI 歸類。
  · 方案還沒有情境 → 依範本建情境（敘事、用語、角色、資料包、示範資料）。
  · 流程推導之後 → 還沒命名的流程套用範本的名稱、摘要、歸屬、狀態意思與實測轉換。
★ 以方案產品為鍵（product.template 不會被清掉）。
"""
import json
import logging

from odoo import _, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

LIBRARY_KINDS = [('capabilities', '能力'), ('scenario', '情境'), ('flows', '流程')]


class KnowledgeLibrary(models.Model):
    _name = 'corpaas.knowledge.library'
    _description = '方案知識範本庫'
    _order = 'package_key, kind'

    package_key = fields.Char(required=True, index=True, help='tmpl:<方案產品 id>')
    product_tmpl_id = fields.Many2one('product.template', string='方案產品', ondelete='set null')
    kind = fields.Selection(LIBRARY_KINDS, required=True)
    data_json = fields.Text(required=True)
    saved_at = fields.Datetime(string='存檔時間', readonly=True)
    note = fields.Char(string='說明', readonly=True)

    _sql_constraints = [('key_kind_unique', 'unique(package_key, kind)', '同一方案同一類範本只有一份')]

    def data(self):
        self.ensure_one()
        try:
            return json.loads(self.data_json or 'null')
        except ValueError:
            return None


class SolutionPackage(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_library_at = fields.Datetime(string='範本庫存檔時間', compute='_compute_knowledge_library')
    knowledge_library_note = fields.Char(string='範本庫', compute='_compute_knowledge_library')

    def _knowledge_library_key(self):
        self.ensure_one()
        return 'tmpl:%s' % self.product_tmpl_id.id if self.product_tmpl_id else 'pkg:%s' % self.id

    def _knowledge_library(self, kind):
        self.ensure_one()
        return self.env['corpaas.knowledge.library'].sudo().search(
            [('package_key', '=', self._knowledge_library_key()), ('kind', '=', kind)], limit=1)

    def _compute_knowledge_library(self):
        Lib = self.env['corpaas.knowledge.library'].sudo()
        for rec in self:
            libs = Lib.search([('package_key', '=', rec._knowledge_library_key())]) if rec.id else Lib
            rec.knowledge_library_at = max(libs.mapped('saved_at')) if libs else False
            rec.knowledge_library_note = '、'.join(dict(LIBRARY_KINDS)[x] for x in libs.mapped('kind')) \
                or False

    # ------------------------------------------------------------------
    # 存檔
    # ------------------------------------------------------------------
    def action_knowledge_save_library(self):
        self.ensure_one()
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
            raise AccessError(_('只有知識管理者可以存範本庫。'))
        self._knowledge_save_library(note=_('手動存檔'))
        return True

    def _knowledge_save_library(self, note=None):
        """把上線中的能力、情境、流程存成範本（只存核准上線的內容）。回傳存了幾類。"""
        self.ensure_one()
        Lib = self.env['corpaas.knowledge.library'].sudo()
        now = fields.Datetime.now()
        data = {
            'capabilities': self._knowledge_library_capabilities(),
            'scenario': self._knowledge_library_scenarios(),
            'flows': self._knowledge_library_flows(),
        }
        n = 0
        for kind, payload in data.items():
            if not payload:
                continue
            vals = {'package_key': self._knowledge_library_key(), 'kind': kind,
                    'product_tmpl_id': self.product_tmpl_id.id or False,
                    'data_json': json.dumps(payload, ensure_ascii=False, default=str),
                    'saved_at': now, 'note': note or False}
            rec = self._knowledge_library(kind)
            if rec:
                rec.write(vals)
            else:
                Lib.create(vals)
            n += 1
        return n

    def _knowledge_library_capabilities(self):
        caps = []
        for cap in self.knowledge_capability_ids.filtered('published_rev_no').sorted(
                lambda c: (c.sequence, c.id)):
            snap = cap._last_published_snapshot() or {}
            vals = {k: v for k, v in snap.items()
                    if k in cap._knowledge_revision_fields() and isinstance(v, (str, int, float))}
            caps.append({
                'code': cap.code, 'sequence': cap.sequence, 'values': vals,
                'feature_keys': sorted(f.feature_key for f in cap.feature_ids
                                       if self in f.package_ids)})
        common = self.env['corpaas.knowledge.selection'].sudo().search([
            ('package_id', '=', self.id), ('kind', '=', 'feature'), ('state', '=', 'approved'),
            ('capability_id', '=', False), ('feature_id', '!=', False)]).mapped('feature_id.feature_key')
        return {'caps': caps, 'common': sorted(common)} if caps else None

    def _knowledge_library_scenarios(self):
        out = []
        for sc in self.knowledge_scenario_ids.filtered('published_rev_no'):
            snap = sc._last_published_snapshot() or {}
            out.append({
                'code': sc.code, 'name': snap.get('name') or sc.name,
                'narrative': snap.get('narrative') or '', 'glossary': snap.get('glossary') or '',
                'required_module_names': snap.get('required_module_names') or '',
                'seed_json': snap.get('seed_json') or '[]',
                'packs': sc.pack_ids.mapped('code'), 'roles': sc.role_ids.mapped('code')})
        return out or None

    def _knowledge_library_flows(self):
        out = []
        for f in self.env['corpaas.knowledge.flow'].sudo().search([('package_ids', 'in', self.id)]):
            out.append({
                'model': f.model, 'state_field': f.state_field, 'ai_name': f.ai_name or '',
                'summary': f.summary or '', 'capability': f.capability_id.code or '',
                'meanings': {s.value: s.meaning for s in f.step_ids
                             if 'meaning' in s._fields and s.meaning},
                'observed': [[t.from_value or '', t.to_value or '', t.button_name or '',
                              t.button_label or ''] for t in f.transition_ids
                             if t.ev_shot and t.to_value]})
        return out or None

    # ------------------------------------------------------------------
    # 套用
    # ------------------------------------------------------------------
    def _knowledge_restore_library(self):
        """方案還沒有能力／情境時，依範本建回來（直接上線）。回傳統計。"""
        self.ensure_one()
        stats = {}
        lib = self._knowledge_library('capabilities')
        if lib and not self.knowledge_capability_ids:
            stats['library_caps'] = self._knowledge_restore_capabilities(lib.data() or {})
        lib = self._knowledge_library('scenario')
        if lib and not self.knowledge_scenario_ids:
            stats['library_scenarios'] = self._knowledge_restore_scenarios(lib.data() or [])
        return stats

    def _knowledge_restore_capabilities(self, data):
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        Sel = self.env['corpaas.knowledge.selection'].sudo()
        feats = {f.feature_key: f for f in Feature.search([('package_ids', 'in', self.id)])}
        n = 0
        for item in data.get('caps') or []:
            mine = Feature.browse([feats[k].id for k in item.get('feature_keys') or [] if k in feats])
            vals = dict(item.get('values') or {}, code=item['code'], sequence=item.get('sequence', 10))
            cap = Cap.search([('code', '=', item['code'])], limit=1)
            if cap:
                cap.write(vals)
            else:
                cap = Cap.create(vals)
            cap.write({'package_ids': [(4, self.id)], 'feature_ids': [(4, f.id) for f in mine]})
            mine.write({'classify_pending': False})
            if not cap.published_rev_no or cap.state != 'published':
                cap._do_publish('new', note=_('從範本庫建立'))
            n += 1
        for key in data.get('common') or []:
            f = feats.get(key)
            if f and not Sel.search_count([('package_id', '=', self.id), ('kind', '=', 'feature'),
                                           ('feature_id', '=', f.id)]):
                Sel.create({'package_id': self.id, 'kind': 'feature', 'feature_id': f.id,
                            'state': 'approved'})
                f.classify_pending = False
        return n

    def _knowledge_restore_scenarios(self, data):
        Sc = self.env['corpaas.knowledge.scenario'].sudo()
        Pack = self.env['corpaas.knowledge.seed_pack'].sudo()
        Role = self.env['corpaas.knowledge.role'].sudo()
        n = 0
        for item in data:
            vals = {'name': item['name'], 'code': item['code'], 'narrative': item.get('narrative'),
                    'glossary': item.get('glossary'),
                    'required_module_names': item.get('required_module_names'),
                    'seed_json': item.get('seed_json') or '[]',
                    'pack_ids': [(6, 0, Pack.search([('code', 'in', item.get('packs') or [])]).ids)],
                    'role_ids': [(6, 0, Role.search([('code', 'in', item.get('roles') or [])]).ids)]}
            sc = Sc.search([('code', '=', item['code'])], limit=1)
            if sc:
                sc.write(vals)
            else:
                sc = Sc.create(vals)
            sc.package_ids = [(4, self.id)]
            if not sc.published_rev_no or sc.state != 'published':
                sc._do_publish('new', note=_('從範本庫建立'))
            n += 1
        return n

    def _knowledge_restore_flows(self):
        """流程推導之後：範本裡有、目前還沒命名的流程，套用名稱、歸屬、狀態意思與實測轉換。"""
        self.ensure_one()
        lib = self._knowledge_library('flows')
        if not lib:
            return 0
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        Trans = self.env['corpaas.knowledge.flow.transition'].sudo()
        n = 0
        for item in lib.data() or []:
            flow = Flow.search([('model', '=', item['model']), ('state_field', '=', item['state_field']),
                                ('package_ids', 'in', self.id)], limit=1)
            if not flow:
                continue
            vals = {}
            if item.get('ai_name') and not flow.ai_name:
                # 名稱沿用範本，結構雜湊記成已命名：不再請 AI 重新命名
                vals.update(ai_name=item['ai_name'], summary=item.get('summary') or False,
                            named_hash=flow.structure_hash)
            cap = Cap.search([('code', '=', item.get('capability'))], limit=1) \
                if item.get('capability') else Cap
            if cap and not flow.capability_id:
                vals['capability_id'] = cap.id
            if vals:
                flow.write(vals)
            for step in flow.step_ids:
                meaning = (item.get('meanings') or {}).get(step.value)
                if meaning and 'meaning' in step._fields and not step.meaning:
                    step.meaning = meaning
            have = {(t.from_value or '', t.to_value or '', t.button_name or '')
                    for t in flow.transition_ids}
            for fr, to, btn, label in item.get('observed') or []:
                if (fr, to, btn) in have:
                    flow.transition_ids.filtered(
                        lambda t: (t.from_value or '', t.to_value or '', t.button_name or '')
                        == (fr, to, btn)).write({'ev_shot': True})
                    continue
                Trans.create({'flow_id': flow.id, 'from_value': fr, 'to_value': to,
                              'button_name': btn, 'button_label': label or False, 'ev_shot': True})
            n += 1
        return n
