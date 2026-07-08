# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import UserError


class MailActivityCancelWizard(models.TransientModel):
    """取消待辦精靈

    功能說明:
    - 取消待辦前必須填寫原因
    - 比照「完成」的記錄方式：於關聯文件 chatter 留痕、原因存入 feedback、
      封存待辦並標記為已取消（cancel_date）
    - 由表單 header / mark-as-done popover / 清單 / 看板的「取消」入口共用
      （action_cancel 一律導向此精靈）
    """
    _name = 'mail.activity.cancel.wizard'
    _inherit = 'mail.activity.action.wizard.mixin'
    _description = 'Cancel Activity Wizard'

    # 待辦資訊（activity_id / summary / activity_type_name / date_deadline /
    # planned_date / estimated_hours / urgency / importance / assignee_id /
    # res_display / note_id）由 mail.activity.action.wizard.mixin 提供。

    reason = fields.Text(
        string='Cancellation Reason',
        required=True,
        help='Please explain why this activity is cancelled',
    )

    def action_cancel_activity(self):
        """確認取消：記錄原因並封存待辦（記錄方式比照完成）。"""
        self.ensure_one()
        activity = self.activity_id
        if not activity.exists():
            raise UserError(_('Activity record does not exist.'))
        if not activity.active:
            raise UserError(_('This activity is archived and cannot be cancelled.'))

        activity._action_cancel(feedback=self.reason)

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
