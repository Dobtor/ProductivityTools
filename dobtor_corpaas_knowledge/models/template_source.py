# -*- coding: utf-8 -*-
"""範本資料來源分級（A4）：黃金庫裡可能有什麼資料，決定說明庫要不要跑清除（D1）。

  · 空白：範本只記模組清單（沒勾「含資料庫」），黃金庫是建空庫裝模組——沒有業務資料。
  · 純示範：我們自己做的示範庫，裡面只有虛構資料。
  · 來自客戶庫：可能有客戶與個資 → 嚴格清除＋截圖前逐筆檢查（今天的做法）。

★ 預設從範本推得出來就推（沒含資料庫＝空白），推不出來一律當「來自客戶庫」：
  分級錯成寬鬆會把個資拍進對外文件，錯成嚴格只是多跑一次清除。
"""
from odoo import api, fields, models

DATA_SOURCES = [('blank', '空白'), ('demo', '純示範'), ('customer', '來自客戶庫')]


class TemplateVersionDataSource(models.Model):
    _inherit = 'infrastructure.template.version'

    knowledge_data_source = fields.Selection(
        DATA_SOURCES, string='資料來源', compute='_compute_knowledge_data_source',
        store=True, readonly=False,
        help='空白／純示範：說明庫不跑清除、截圖前不逐筆檢查（沒有個資可清）。\n'
             '來自客戶庫：說明庫嚴格清除業務資料，截圖前檢查畫面上每筆記錄。')

    @api.depends('include_db')
    def _compute_knowledge_data_source(self):
        for rec in self:
            if not rec.knowledge_data_source:
                rec.knowledge_data_source = 'customer' if rec.include_db else 'blank'


class DatabaseDataSource(models.Model):
    _inherit = 'infrastructure.database'

    def _knowledge_needs_purge(self):
        """這座黃金庫複製出來的說明庫要不要清除業務資料。"""
        self.ensure_one()
        version = self.template_version_id
        return not version or (version.knowledge_data_source or 'customer') == 'customer'
