# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import UserError


class MailActivityReassignWizard(models.TransientModel):
    """變更待辦指派精靈

    功能說明:
    - 將待辦從目前負責人轉給新負責人
    - 建立新待辦給新負責人，取消原待辦
    - 記錄指派歷史
    - 若待辦有來源訊息，將新負責人加入該頻道
    - 發送通知給新負責人
    """
    _name = 'mail.activity.reassign.wizard'
    _inherit = 'mail.activity.action.wizard.mixin'
    _description = 'Reassign Activity Wizard'

    # 待辦資訊（含 assignee_id = 目前指派人）由
    # mail.activity.action.wizard.mixin 提供。

    # ===== 變更資訊 =====
    new_user_id = fields.Many2one(
        'res.users',
        string='New Assignee',
        required=True,
        domain="[('id', '!=', assignee_id)]",
    )
    reason = fields.Text(
        string='Change Reason',
        help='Explain the reason for reassignment',
    )

    def _validate_reassign(self):
        """驗證變更指派操作"""
        self.ensure_one()

        if not self.new_user_id:
            raise UserError(_('Please select a new assignee.'))

        if self.new_user_id == self.assignee_id:
            raise UserError(_('New assignee cannot be the same as current assignee.'))

        if not self.activity_id.exists():
            raise UserError(_('Activity record does not exist.'))

        if not self.activity_id.active:
            raise UserError(_('This activity is archived and cannot be reassigned.'))

    def _format_reassign_note(self, now_str):
        """格式化變更指派備註"""
        self.ensure_one()

        note = _(
            '\n\n--- %(date)s Reassigned ---\nFrom %(from_user)s to %(to_user)s',
            date=now_str,
            from_user=self.assignee_id.name if self.assignee_id else _('Unassigned'),
            to_user=self.new_user_id.name,
        )
        if self.reason:
            note += _('\nReason: %(reason)s', reason=self.reason)

        return note

    def _prepare_new_activity_values(self, reassign_note):
        """準備新待辦的值"""
        self.ensure_one()
        activity = self.activity_id

        vals = {
            'activity_type_id': activity.activity_type_id.id,
            'summary': activity.summary,
            'note': (activity.note or '') + reassign_note,
            'date_deadline': activity.date_deadline,
            'user_id': self.new_user_id.id,
            'res_model_id': activity.res_model_id.id,
            'res_id': activity.res_id,
            # 保留優先級欄位
            'urgency': activity.urgency,
            'importance': activity.importance,
            'estimated_hours': activity.estimated_hours,
            # 保留排程欄位
            'schedule_status': activity.schedule_status,
            'planned_date': activity.planned_date,
            'scheduled_date': activity.scheduled_date,
            'schedule_origin': activity.schedule_origin,
            # 記錄轉移來源（原待辦）
            'transferred_from_model': 'mail.activity',
            'transferred_from_id': activity.id,
        }

        # 保留筆記關聯
        if activity.note_id:
            vals['note_id'] = activity.note_id.id

        # 保留來源訊息關聯
        if activity.source_message_id:
            vals['source_message_id'] = activity.source_message_id.id

        return vals

    def _create_assignment_history(self, new_activity):
        """建立指派歷史記錄"""
        self.ensure_one()
        return self.env['mail.activity.assignment.history'].sudo().create({
            'activity_id': new_activity.id,
            'previous_user_id': self.assignee_id.id if self.assignee_id else False,
            'new_user_id': self.new_user_id.id,
            'reason': self.reason or _('Reassignment'),
        })

    def _cancel_original_activity(self, cancel_note):
        """取消原待辦"""
        self.ensure_one()
        now = fields.Datetime.now()

        self.activity_id.write({
            'active': False,
            'cancel_date': now,
            'note': (self.activity_id.note or '') + cancel_note,
        })

    def _add_new_user_to_channel(self):
        """將新負責人加入來源訊息所在的頻道"""
        self.ensure_one()
        if self.activity_id.source_message_id:
            self.env['mail.activity']._add_user_to_channel_from_message(
                self.activity_id.source_message_id, self.new_user_id
            )


    def action_confirm(self):
        """確認變更指派"""
        self.ensure_one()
        self._validate_reassign()

        # 顯示於備註的時間戳需轉本地時區（Datetime.now() 為 UTC，UTC+8 使用者會少 8 小時）
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        now_str = now.strftime('%Y-%m-%d %H:%M')

        # 準備變更記錄文字
        reassign_note = self._format_reassign_note(now_str)

        # 建立新待辦給新負責人
        new_activity_vals = self._prepare_new_activity_values(reassign_note)
        new_activity = self.env['mail.activity'].create(new_activity_vals)

        # 將新負責人加入來源訊息所在的頻道
        self._add_new_user_to_channel()

        # 建立指派歷史記錄
        self._create_assignment_history(new_activity)

        # 取消原待辦
        cancel_note = _(
            '\n\n--- %(date)s Reassigned to %(to_user)s ---',
            date=now_str,
            to_user=self.new_user_id.name,
        )
        if self.reason:
            cancel_note += _('\nReason: %(reason)s', reason=self.reason)

        self._cancel_original_activity(cancel_note)

        # 通知與 systray 計數由 mail.activity.create() 覆寫統一處理
        # （其到期過濾邏輯已對新負責人發送 count_diff，此處不可重複發送以免重複計數）

        # 刷新視圖（原待辦會從當前用戶的列表中移除）
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
