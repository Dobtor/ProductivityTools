# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class MailActivityType(models.Model):
    """待辦類型擴展

    新增功能:
    - 自定義指派通知模板：允許為特定待辦類型配置專屬的通知郵件模板
    - 使用自定義通知開關：控制是否使用自定義模板取代系統預設通知
    """
    _inherit = 'mail.activity.type'

    # ===== 自定義通知模板 =====
    notify_template_id = fields.Many2one(
        'mail.template',
        string='指派通知模板',
        help='當待辦指派給用戶時使用的郵件模板。'
             '若未設定或未啟用自定義通知，將使用系統預設通知。',
        domain="[('model_id.model', '=', res_model)]",
    )

    use_custom_notify = fields.Boolean(
        string='使用自定義通知',
        default=False,
        help='啟用後，待辦指派通知將使用上方設定的郵件模板，'
             '而非系統預設的通知格式。',
    )

    @api.onchange('res_model')
    def _onchange_res_model_notify_template(self):
        """當模型變更時，清除不相容的通知模板"""
        if self.notify_template_id:
            if self.res_model and self.notify_template_id.model_id.model != self.res_model:
                self.notify_template_id = False

    @api.onchange('use_custom_notify')
    def _onchange_use_custom_notify(self):
        """當停用自定義通知時，給予提示"""
        if not self.use_custom_notify and self.notify_template_id:
            return {
                'warning': {
                    'title': _('提示'),
                    'message': _('已停用自定義通知，但通知模板設定仍保留。'
                                '若需完全移除，請手動清除「指派通知模板」欄位。'),
                }
            }
