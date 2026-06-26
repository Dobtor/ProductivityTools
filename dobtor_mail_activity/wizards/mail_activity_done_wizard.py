# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivityDoneWizard(models.TransientModel):
    """完成待辦精靈

    功能說明:
    - 記錄實際執行工時（支援多次登錄）
    - 添加完成回饋和附件
    - 可選擇安排下一次待辦
    - 「登錄後繼續」不完成待辦，只登錄工時
    - 觸發工時表記錄建立
    """
    _name = 'mail.activity.done.wizard'
    _inherit = 'mail.activity.action.wizard.mixin'
    _description = 'Complete Activity Wizard'

    # 待辦資訊（activity_id / summary / activity_type_name / date_deadline /
    # planned_date / estimated_hours / urgency / importance / assignee_id /
    # res_display / note_id）由 mail.activity.action.wizard.mixin 提供。

    # ===== 工時資訊 =====
    accumulated_hours = fields.Float(
        string='Accumulated Hours',
        compute='_compute_accumulated_hours',
        readonly=True,
    )
    actual_hours = fields.Float(
        string='Hours to Log',
        required=True,
        help='Time spent on this activity (hours)',
    )

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

    # ===== 下一個待辦相關 =====
    schedule_next = fields.Boolean(
        string='Schedule Next Activity',
        default=False,
    )
    next_activity_type_id = fields.Many2one(
        'mail.activity.type',
        string='Next Activity Type',
    )
    next_date_deadline = fields.Date(
        string='Next Deadline',
    )
    next_summary = fields.Char(
        string='Next Summary',
    )
    next_user_id = fields.Many2one(
        'res.users',
        string='Next Assignee',
        default=lambda self: self.env.user,
    )

    # ===== 刪除權限 =====
    can_delete = fields.Boolean(
        string='Can Delete',
        compute='_compute_can_delete',
        help='Only the activity creator or a system administrator may delete it.',
    )

    # ===== 計算方法 =====

    @api.depends('activity_id', 'activity_id.actual_hours')
    def _compute_accumulated_hours(self):
        """計算已累計工時（activity.actual_hours）"""
        for wizard in self:
            wizard.accumulated_hours = wizard.activity_id.actual_hours or 0.0

    @api.depends('activity_id')
    def _compute_can_delete(self):
        """建立者或最高管理者（base.group_system）才可刪除該待辦。"""
        is_admin = self.env.user.has_group('base.group_system')
        for wizard in self:
            activity = wizard.activity_id
            wizard.can_delete = bool(activity) and (
                is_admin or activity.create_uid.id == self.env.uid
            )

    @api.model
    def default_get(self, fields_list):
        """預設值處理：取得 activity_id（mixin）後預填執行工時"""
        res = super().default_get(fields_list)

        # 預填執行工時：預估工時減去已累計工時
        if res.get('activity_id'):
            activity = self.env['mail.activity'].browse(res['activity_id'])
            if activity.exists() and activity.estimated_hours:
                remaining = activity.estimated_hours - activity.actual_hours
                res['actual_hours'] = max(remaining, 0)

        return res

    @api.onchange('schedule_next')
    def _onchange_schedule_next(self):
        """當選擇安排下一次時，預填類型和摘要"""
        if self.schedule_next and self.activity_id:
            if not self.next_activity_type_id:
                self.next_activity_type_id = self.activity_id.activity_type_id
            if not self.next_summary:
                self.next_summary = self.activity_id.summary

    # ===== 驗證方法 =====

    def _validate_actual_hours(self):
        """驗證執行工時"""
        self.ensure_one()
        if self.actual_hours < 0:
            raise UserError(_('Hours cannot be negative.'))

    # ===== 工時記錄方法 =====

    def _log_hours(self):
        """記錄本次執行工時（核心 hook）。

        核心模式（未安裝工時表整合）：直接累加到 activity.actual_hours。
        安裝 timesheet 橋接模組（dobtor_mail_activity_timesheet）後，此方法
        會被覆寫為建立 account.analytic.line 工時表記錄，並由工時表加總
        自動更新 actual_hours。
        """
        self.ensure_one()
        if self.actual_hours <= 0:
            return
        activity = self.activity_id
        activity.actual_hours = (activity.actual_hours or 0.0) + self.actual_hours

    def _get_attachment_ids(self):
        """取得附件 ID 列表"""
        return self.attachment_ids.ids if self.attachment_ids else None

    # ===== Action 方法 =====

    def action_log_and_continue(self):
        """登錄工時後繼續（不完成待辦）"""
        self.ensure_one()

        if self.actual_hours <= 0:
            raise UserError(_('Please enter valid hours (must be greater than 0)'))

        # 記錄本次工時
        self._log_hours()

        # 關閉精靈並刷新視圖
        return {
            'type': 'ir.actions.client',
            'tag': 'soft_reload',
        }

    def action_done(self):
        """完成待辦"""
        self.ensure_one()
        self._validate_actual_hours()

        activity = self.activity_id

        # 先記錄本次工時（如果有填寫且大於 0）
        if self.actual_hours > 0:
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
        """完成並安排下一次待辦"""
        self.ensure_one()
        self._validate_actual_hours()

        # 驗證下一次待辦資訊
        if not self.next_activity_type_id:
            raise UserError(_('Please select next activity type.'))
        if not self.next_date_deadline:
            raise UserError(_('Please select next deadline.'))

        activity = self.activity_id

        # 先記錄本次工時（如果有填寫且大於 0）
        if self.actual_hours > 0:
            self._log_hours()

        # 執行完成動作
        activity._action_done(
            feedback=self.feedback,
            attachment_ids=self._get_attachment_ids(),
        )

        # 建立下一個待辦
        next_activity_vals = {
            'activity_type_id': self.next_activity_type_id.id,
            'date_deadline': self.next_date_deadline,
            'summary': self.next_summary or activity.summary,
            'user_id': self.next_user_id.id if self.next_user_id else False,
            'res_model_id': activity.res_model_id.id,
            'res_id': activity.res_id,
        }

        # 保留筆記關聯
        if activity.note_id:
            next_activity_vals['note_id'] = activity.note_id.id

        self.env['mail.activity'].create(next_activity_vals)

        # 刷新視圖
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

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
