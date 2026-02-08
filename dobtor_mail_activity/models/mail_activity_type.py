# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class MailActivityType(models.Model):
    """待辦類型擴展

    新增功能:
    - 預設說明：建立待辦時自動填入的說明內容
    - 自定義指派通知模板：允許為特定待辦類型配置專屬的通知郵件模板
    - 使用自定義通知開關：控制是否使用自定義模板取代系統預設通知
    """
    _inherit = 'mail.activity.type'

    # ===== 預設說明 =====
    default_description = fields.Html(
        string='Default Activity Note',
        help='Default note content when creating activities of this type.',
        translate=True,
    )

    # ===== 自定義通知模板 =====
    notify_template_id = fields.Many2one(
        'mail.template',
        string='Assignment Notification Template',
        help='Email template to use when activity is assigned to a user. '
             'If not set or custom notification is disabled, system default notification will be used.',
        domain="[('model_id.model', '=', res_model)]",
    )

    use_custom_notify = fields.Boolean(
        string='Use Custom Notification',
        default=False,
        help='When enabled, activity assignment notifications will use the email template above '
             'instead of the system default notification format.',
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
                    'title': _('Notice'),
                    'message': _('Custom notification has been disabled, but the notification template setting is retained. '
                                'To completely remove it, please manually clear the "Assignment Notification Template" field.'),
                }
            }
