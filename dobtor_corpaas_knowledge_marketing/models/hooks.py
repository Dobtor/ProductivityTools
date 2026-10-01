# -*- coding: utf-8 -*-
"""行銷出口對核心掛勾的參與（一律 super 串起來）。"""
from odoo import api, models

from odoo.addons.dobtor_corpaas_knowledge.services import search_lib

UPSELL_MIN_SCORE = 0.2


class KnowledgeHooks(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    @api.model
    def _marketing_renamed(self, events):
        """有改名候選（本次事件，或待確認／已確認的改名）的舊功能點：不當成消失（與 manual 一致）。"""
        renamed = events.filtered(lambda e: e.type == 'rename_candidate').mapped('feature_id')
        removed = events.filtered(lambda e: e.type == 'feature_removed').mapped('feature_id')
        if removed and 'corpaas.knowledge.rename' in self.env:
            renamed |= self.env['corpaas.knowledge.rename'].sudo().search([
                ('old_feature_id', 'in', removed.ids),
                ('state', 'in', ('proposed', 'accepted'))]).mapped('old_feature_id')
        return renamed

    @api.model
    def _knowledge_dispatch_events(self, package, events, ctx):
        """宣稱錨定＋本期新增。

        ★ 只處理這個方案的事件，且功能在這個方案真的不在了才算消失（per-package presence）。
        ★ scope_changed（畫面大改）只換圖；form_changed 不動宣稱。
        """
        res = super()._knowledge_dispatch_events(package, events, ctx)
        Pitch = self.env['corpaas.knowledge.pitch'].sudo()
        mine = events.filtered(lambda e: not e.package_id or e.package_id == package)
        renamed = self._marketing_renamed(mine)
        removed = mine.filtered(lambda e: e.type == 'feature_removed').mapped('feature_id')
        removed = removed.filtered(lambda f: f not in renamed and not f.is_present_in(package))
        changed = mine.filtered(lambda e: e.type == 'scope_changed').mapped('feature_id') \
            - removed
        Pitch._marketing_flag_features(removed, '功能消失', package)
        Pitch._marketing_swap_images(changed, package)
        Note = self.env['corpaas.knowledge.release_note'].sudo()
        Note._marketing_flag_removed(removed, package)
        Note._marketing_from_events(package, mine, ctx)
        return res

    @api.model
    def _knowledge_feature_gone(self, feature):
        """功能確定消失（例如改名被否決）：只處理它已經不在的方案；全部都不在就全部處理。"""
        res = super()._knowledge_feature_gone(feature)
        Pitch = self.env['corpaas.knowledge.pitch'].sudo()
        Note = self.env['corpaas.knowledge.release_note'].sudo()
        for feat in feature:
            gone_in = feat.missing_package_ids
            if not gone_in and not feat.package_ids:
                Pitch._marketing_flag_features(feat, '功能消失')
                continue
            for pkg in gone_in:
                Pitch._marketing_flag_features(feat, '功能消失', pkg)
                Note._marketing_flag_removed(feat, pkg)
        return res

    @api.model
    def _knowledge_rename_feature(self, old, new):
        res = super()._knowledge_rename_feature(old, new)
        for model in ('corpaas.knowledge.claim', 'corpaas.knowledge.release_note'):
            recs = self.env[model].sudo().search([('feature_ids', 'in', old.ids)])
            recs.write({'feature_ids': [(3, old.id), (4, new.id)]})
        return res

    @api.model
    def _knowledge_check_feature_ref(self, feature):
        return super()._knowledge_check_feature_ref(feature) or bool(
            self.env['corpaas.knowledge.claim'].sudo().search_count(
                [('feature_ids', 'in', feature.ids)]))

    # ------------------------------------------------------------------
    # help API：加購可得
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_help_links(self, package, matches, query, ctx):
        links = list(super()._knowledge_help_links(package, matches, query, ctx) or [])
        links.extend(self._marketing_upsell_links(package, matches, query))
        return links

    @api.model
    def _marketing_public_base(self):
        icp = self.env['ir.config_parameter'].sudo()
        return (icp.get_param('corpaas_knowledge.public_base_url')
                or icp.get_param('web.base.url') or '').rstrip('/')

    @api.model
    def _marketing_upsell_links(self, package, matches, query):
        """命中的功能在方案不可用、但能力可加購 → kind='upsell' 連到方案商品頁的加購卡片。

        ★ 兩條命中路徑：
          1. `_match` 給的功能點所屬能力在這個方案是 addon（功能在，但能力還缺可販售模組）；
          2. 自然語言問句直接比對 addon 能力——缺的模組不在方案 BOM 裡，它的功能點根本
             不會出現在 `_match`（只找方案內功能點），不另外比對就永遠推不出加購。
        """
        tmpl = package.product_tmpl_id
        # ★ 連到這個方案自己的變體頁（同分支），不是商品的第一個變體
        variant = package.product_id or tmpl.product_variant_ids.filtered(
            lambda v: package.branch_name and v.branch_name == package.branch_name)[:1] \
            or tmpl.product_variant_id
        if not variant:
            return []
        matched = self.env['corpaas.knowledge.feature'].browse(
            [f.id for f, _score in matches or []])
        base = self._marketing_public_base()
        out = []
        for item in tmpl._knowledge_upsell_capabilities(package):
            cap = item['capability']
            hit = cap.feature_ids & matched
            if not hit and query:
                score = search_lib.score(query, [
                    (cap.name, 3.0), (cap.outcome or '', 1.0), (cap.pain or '', 1.0),
                    (' '.join(cap.feature_ids.mapped('name')), 2.0),
                    ('\n'.join(filter(None, cap.feature_ids.mapped('intents'))), 2.0)])
                if score < UPSELL_MIN_SCORE:
                    continue
            elif not hit:
                continue
            feature = hit[:1] or cap.feature_ids[:1]
            anchor = 'kb-addon-%s' % (cap.code or cap.id)
            out.append({
                'feature_key': feature.feature_key or False,
                'title': '加購可得：%s' % cap.name,
                'url': '%s/corpaas/solution/%s#%s' % (base, variant.id, anchor),
                'kind': 'upsell',
                'scenario': False,
                'anchor': anchor,
                'fingerprint': {'elements': [], 'scope_hash': False},
            })
        return out
