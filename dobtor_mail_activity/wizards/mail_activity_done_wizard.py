# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivityDoneWizard(models.TransientModel):
    """完成待辦精靈

    功能說明:
    - 添加完成回饋和附件
    - 可選擇安排下一次待辦
    工時（登錄、「登錄後繼續」、補登）由 dobtor_mail_activity_project 擴充；
    核心不記工時。
    """
    _name = 'mail.activity.done.wizard'
    _inherit = 'mail.activity.action.wizard.mixin'
    _description = 'Complete Activity Wizard'

    # 待辦資訊（activity_id / summary / activity_type_name / date_deadline /
    # planned_date / estimated_hours / urgency / importance / assignee_id /
    # res_display）由 mail.activity.action.wizard.mixin 提供（note_id 由 dobtor_meeting_minutes 擴充）。

    # ===== 完成資訊 =====
    feedback = fields.Text(
        string='Feedback/Notes',
        help='Feedback or notes upon activity completion',
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'mail_activity_done_wizard_attachment_rel',
        'wizard_id',
        'attachment_id',
        string='Attachments',
    )

    # ===== 刪除權限 =====
    can_delete = fields.Boolean(
        string='Can Delete',
        compute='_compute_can_delete',
        help='Only the activity creator or a system administrator may delete it.',
    )

    # ===== 計算方法 =====

    @api.depends('activity_id')
    def _compute_can_delete(self):
        """建立者或最高管理者（base.group_system）才可刪除該待辦。"""
        is_admin = self.env.user.has_group('base.group_system')
        for wizard in self:
            activity = wizard.activity_id
            wizard.can_delete = bool(activity) and (
                is_admin or activity.create_uid.id == self.env.uid
            )

    # ===== 工時 hook =====

    def _log_hours(self):
        """記錄本次執行工時（hook）。核心不記工時；專案橋接實作工時表登錄。"""
        self.ensure_one()

    def _get_attachment_ids(self):
        """取得附件 ID 列表"""
        return self.attachment_ids.ids if self.attachment_ids else None

    # ===== Action 方法 =====

    def action_done(self):
        """完成待辦"""
        self.ensure_one()
        activity = self.activity_id

        # 先記錄本次工時（hook；核心為 no-op）
        self._log_hours()

        # 執行完成動作
        activity._action_done(
            feedback=self.feedback,
            attachment_ids=self._get_attachment_ids(),
        )

        # 刷新視圖
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_done_and_schedule_next(self):
        """完成當前待辦，並鏈式開啟「建立待辦」精靈安排下一個。

        依需求：先把當前待辦設為完成（記錄工時），再開啟
        mail.activity.create.wizard，帶入上一筆待辦的標題（summary）、
        類型與關聯（res 文件 / 客戶 / 專案 / 來源參考）作為新待辦預設值，
        使用者於新精靈編輯後儲存。
        """
        self.ensure_one()
        activity = self.activity_id

        # 記錄本次工時（hook）並完成當前待辦
        self._log_hours()
        activity._action_done(
            feedback=self.feedback,
            attachment_ids=self._get_attachment_ids(),
        )

        # 帶入本待辦的標題/類型/關聯，鏈式開啟建立待辦精靈
        # （完成後欄位仍在，與已完成待辦的「延續新增待辦」共用同一路徑）
        return activity._continue_todo_action()

    def action_postpone(self):
        """延至下週（開啟延期 wizard）"""
        self.ensure_one()
        return self.activity_id.action_postpone_wizard()

    def action_delete_activity(self):
        """刪除該待辦（建立者或最高管理者限定）。

        回傳 act_window_close 並帶回 deleted_activity_id，供編輯器同步移除
        對應的內嵌膠囊；其他開啟情境（清單/看板）則由父視圖自動刷新。
        """
        self.ensure_one()
        activity = self.activity_id
        if not activity:
            return {'type': 'ir.actions.act_window_close'}
        if not (self.env.user.has_group('base.group_system')
                or activity.create_uid.id == self.env.uid):
            raise UserError(_('Only the activity creator or an administrator can delete this to-do.'))
        activity_id = activity.id
        # 權限已於上方依「建立者/最高管理者」把關；用 sudo 執行 unlink，
        # 避免建立者非指派人時被預設記錄規則擋下。
        activity.sudo().unlink()
        return {
            'type': 'ir.actions.act_window_close',
            'infos': {'deleted_activity_id': activity_id},
        }
