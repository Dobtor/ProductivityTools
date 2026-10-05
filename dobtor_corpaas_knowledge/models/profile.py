# -*- coding: utf-8 -*-
"""方案設定檔（通用化第二階段）：每個方案的分析條件寫成資料，提示詞與閘門都讀這裡。

★ 2026-10 從零驗證：13 個修正有 7 個是「規則只寫在提示詞、AI 沒照做也沒人檢查」。
  條件搬成欄位後，同一套程式換方案只要改設定，不改提示詞。
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

READERS = [('tenant_user', '已導入的租戶使用者'), ('prospect', '評估中的潛在客戶'),
           ('admin', '租戶的系統管理員')]


class SolutionPackageProfile(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_reader = fields.Selection(
        READERS, string='主要讀者', default='tenant_user',
        help='決定角色挑使用者或管理員等級、文章語氣')
    knowledge_max_scenarios = fields.Integer(
        string='情境數上限', default=1,
        help='每多一個情境，每個功能就要多寫一篇、多拍一套；原則上一個方案一家虛構公司')
    knowledge_cap_min = fields.Integer(string='能力數下限', default=6)
    knowledge_cap_max = fields.Integer(string='能力數上限', default=10)
    knowledge_shot_threshold = fields.Integer(
        string='截圖成功率門檻（%）', default=85)
    knowledge_empty_max_pct = fields.Integer(
        string='空白畫面上限（%）', default=10,
        help='送審前重播檢查：沒有資料的畫面比例超過這個值就算「有問題」')

    @api.constrains('knowledge_cap_min', 'knowledge_cap_max', 'knowledge_max_scenarios',
                    'knowledge_shot_threshold', 'knowledge_empty_max_pct')
    def _check_knowledge_profile(self):
        for rec in self:
            if rec.knowledge_cap_min < 1 or rec.knowledge_cap_max < rec.knowledge_cap_min:
                raise ValidationError(_('能力數範圍不合理：%s–%s')
                                      % (rec.knowledge_cap_min, rec.knowledge_cap_max))
            if rec.knowledge_max_scenarios < 1:
                raise ValidationError(_('情境數上限至少 1。'))
            if not (0 <= rec.knowledge_shot_threshold <= 100
                    and 0 <= rec.knowledge_empty_max_pct <= 100):
                raise ValidationError(_('百分比要在 0–100 之間。'))

    def _knowledge_profile(self):
        """給提示詞與閘門用的設定（沒設的用預設值）。"""
        self.ensure_one()
        return {
            'reader': self.knowledge_reader or 'tenant_user',
            'reader_label': dict(READERS).get(self.knowledge_reader or 'tenant_user'),
            'max_scenarios': self.knowledge_max_scenarios or 1,
            'cap_min': self.knowledge_cap_min or 6,
            'cap_max': self.knowledge_cap_max or 10,
            'shot_threshold': self.knowledge_shot_threshold or 85,
            'empty_max_pct': self.knowledge_empty_max_pct if self.knowledge_empty_max_pct
            is not False else 10,
        }
