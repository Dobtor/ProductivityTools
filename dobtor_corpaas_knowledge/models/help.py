# -*- coding: utf-8 -*-
"""help API 的比對邏輯與紀錄（回饋迴路的資料來源）。"""
from odoo import api, fields, models

from ..services import search_lib


class KnowledgeHelp(models.AbstractModel):
    _name = 'corpaas.knowledge.help'
    _description = '說明檢索'

    @api.model
    def _package_for_database(self, database):
        """租戶庫 → 方案：從範本誕生的庫記著版本；共享租戶的實例就是母體。"""
        db = self.env['infrastructure.database'].sudo().search(
            [('name', '=', database)], limit=1)
        if not db:
            return self.env['infrastructure.solution.package']
        pkg = db.born_from_version_id.package_id
        if not pkg and db.clone_from_id:
            pkg = db.clone_from_id.born_from_version_id.package_id \
                or db.clone_from_id.template_version_id.package_id
        if not pkg:
            pkg = db.instance_id.template_package_id \
                or db.instance_id.corpaas_pin_source_id.template_package_id
        return pkg

    @api.model
    def _match(self, package, query=None, action_xmlid=None, model=None,
               view_type=None, limit=5, groups=None):
        """回傳 [(feature, score)]，高分在前。

        快速路徑（此畫面說明）：action_xmlid／model 精準比對，score=1。
        自然語言：名稱、選單路徑、問法、能力名稱的二元組重疊評分。
        """
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        base = [('package_ids', 'in', package.id), ('missing', '=', False)]
        exact = Feature
        if action_xmlid:
            exact |= Feature.search(base + ['|', ('action_xmlid', '=', action_xmlid),
                                            '&', ('kind', '=', 'action'),
                                            ('anchor', '=', action_xmlid)])
        if model and not exact:
            exact |= Feature.search(base + [('model', '=', model),
                                            ('kind', 'in', ('action', 'menu', 'client'))])
        scored = [(f, 1.0) for f in exact]
        if query:
            seen = set(exact.ids)
            for f in Feature.search(base):
                if f.id in seen:
                    continue
                paths = ' '.join(filter(None, [f.menu_path] + f.entry_ids.mapped('path')))
                s = search_lib.score(query, [
                    (f.name, 3.0), (paths, 2.0), (f.intents or '', 3.0),
                    (' '.join(f.capability_ids.mapped('name')), 1.0)])
                if model and f.model == model:
                    s += 0.15
                if s >= 0.2:
                    scored.append((f, min(s, 0.99)))
        if groups is not None:
            # ★ 角色過濾：功能點本身有群組限制、而使用者一個都沒有 → 他在畫面上看不到，
            #   給他連結只會讓他去找一個不存在的選單。
            # 入口也要看得到：畫面本身沒限群組、但唯一的選單只開給主管，一般使用者照樣找不到。
            scored = [(f, sc) for f, sc in scored if f.visible_to(groups)]
        scored.sort(key=lambda x: (-x[1], -x[0].usage_score))
        return scored[:limit * 3]


class KnowledgeHelpLog(models.Model):
    _name = 'corpaas.knowledge.help.log'
    _description = '說明查詢紀錄'
    _order = 'id desc'

    package_id = fields.Many2one('infrastructure.solution.package', index=True,
                                 ondelete='cascade')
    database = fields.Char(index=True)
    query = fields.Char()
    action_xmlid = fields.Char()
    model = fields.Char()
    hits = fields.Integer()
    top_score = fields.Float()
    missed = fields.Boolean(compute='_compute_missed', store=True, index=True)
    handled = fields.Boolean(help='已交給 AI 提議同義詞或新文章')

    @api.depends('hits', 'top_score', 'query')
    def _compute_missed(self):
        for rec in self:
            rec.missed = bool(rec.query) and (rec.hits == 0 or rec.top_score < 0.35)

    @api.model
    def _cron_feed_misses(self, batch=50):
        """回饋迴路：找不到答案的問句 → AI 提議補同義詞（自動）。"""
        logs = self.search([('missed', '=', True), ('handled', '=', False)], limit=batch)
        by_pkg = {}
        for log in logs:
            by_pkg.setdefault(log.package_id, self.browse())
            by_pkg[log.package_id] |= log
        Ai = self.env['corpaas.knowledge.ai']
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        import json
        for pkg, recs in by_pkg.items():
            if not pkg:
                recs.write({'handled': True})
                continue
            feats = Feature.search([('package_ids', 'in', pkg.id), ('missing', '=', False)],
                                   order='usage_score desc', limit=200)
            prompt = (
                "使用者在方案「%s」問了以下問題但找不到說明。請判斷每個問題對應哪個功能點（用 key），"
                "並給出應補的問法；真的沒有對應功能就回 null。\n"
                "格式：{\"items\":[{\"query\":…,\"key\":…|null,\"intents\":[…]}]}\n\n"
                "問題：%s\n\n功能點：%s"
            ) % (pkg.display_name, json.dumps(recs.mapped('query'), ensure_ascii=False),
                 json.dumps([{'key': f.feature_key, 'name': f.name, 'menu': f.menu_path}
                             for f in feats], ensure_ascii=False))
            try:
                data = Ai.ask('help_misses', prompt, package=pkg)
            except Exception:  # noqa: BLE001
                continue
            by_key = {f.feature_key: f for f in feats}
            for item in (data or {}).get('items') or []:
                if not item.get('key') and item.get('query'):
                    # AI 判定方案裡沒有對應功能：同義詞補不了，交給缺口分群（K24）
                    recs.filtered(lambda r: r.query == item['query']).write({'unmatched': True})
                    continue
                f = by_key.get(item.get('key'))
                intents = [i for i in item.get('intents') or [] if isinstance(i, str)]
                if f and intents:
                    f._knowledge_add_intents(intents)
            recs.write({'handled': True})
        return True
