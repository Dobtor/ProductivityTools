# -*- coding: utf-8 -*-
"""指紋重新基準的對照（B6）。

★ 核心發現腳本範圍「定義」改了（elements_json 不同，例如範本被修過）時不發事件，
  改呼叫 `_knowledge_fingerprint_rebaselined(old → new)`：畫面沒變，只是同一個畫面
  換了一個雜湊。出口把引用 old 的範本／步驟區塊／文章／素材原地改成 new，不分岔、不叫 AI。
☠️ 範本是跨方案共用的：方案 A 先重新基準、方案 B 還沒 refresh（目前指紋仍是 old）→
  記一筆 old → new，B 查「目前指紋」時經這張表換算，才不會在兩次 refresh 之間掉文章。
"""
from odoo import api, fields, models


class KnowledgeManualRebase(models.Model):
    _name = 'corpaas.knowledge.manual.rebase'
    _description = '操作說明：指紋重新基準對照'
    _order = 'id'

    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True)
    old_hash = fields.Char(required=True, index=True)
    new_hash = fields.Char(required=True)
    package_id = fields.Many2one('infrastructure.solution.package', ondelete='set null',
                                 help='最先重新基準的方案')
    role_code = fields.Char()

    @api.model
    def resolve(self, feature, scope_hash):
        """沿對照鏈換算到最新的指紋（同一個 old 只認最早那筆）。"""
        seen = set()
        cur = scope_hash
        while cur and cur not in seen:
            seen.add(cur)
            row = self.sudo().search([('feature_id', '=', feature.id), ('old_hash', '=', cur)],
                                     limit=1)
            if not row:
                break
            cur = row.new_hash
        return cur
