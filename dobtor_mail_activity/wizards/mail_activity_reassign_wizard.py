# -*- coding: utf-8 -*-

from odoo import api, fields, models, Command, _
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
    _description = '變更待辦指派精靈'

    # ===== 待辦資訊（唯讀）=====
    activity_id = fields.Many2one(
        'mail.activity',
        string='待辦',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    current_user_id = fields.Many2one(
        'res.users',
        string='目前負責人',
        related='activity_id.user_id',
        readonly=True,
    )
    activity_summary = fields.Char(
        string='待辦摘要',
        related='activity_id.summary',
        readonly=True,
    )
    activity_deadline = fields.Date(
        string='截止日期',
        related='activity_id.date_deadline',
        readonly=True,
    )
    activity_type_name = fields.Char(
        string='待辦類型',
        related='activity_id.activity_type_id.name',
        readonly=True,
    )

    # ===== 變更資訊 =====
    new_user_id = fields.Many2one(
        'res.users',
        string='新負責人',
        required=True,
        domain="[('id', '!=', current_user_id)]",
    )
    reason = fields.Text(
        string='變更原因',
        help='說明變更指派的原因',
    )

    @api.model
    def default_get(self, fields_list):
        """預設值處理：從 context 取得 activity_id"""
        res = super().default_get(fields_list)

        # 從 context 取得 activity_id
        if 'activity_id' not in res and self.env.context.get('default_activity_id'):
            res['activity_id'] = self.env.context.get('default_activity_id')

        return res

    def _validate_reassign(self):
        """驗證變更指派操作"""
        self.ensure_one()

        if not self.new_user_id:
            raise UserError(_('請選擇新的負責人。'))

        if self.new_user_id == self.current_user_id:
            raise UserError(_('新負責人不能與目前負責人相同。'))

        if not self.activity_id.exists():
            raise UserError(_('待辦記錄不存在。'))

        if not self.activity_id.active:
            raise UserError(_('此待辦已封存，無法變更指派。'))

    def _format_reassign_note(self, now_str):
        """格式化變更指派備註"""
        self.ensure_one()

        note = _('\n\n--- %s 變更指派 ---\n由 %s 轉給 %s') % (
            now_str,
            self.current_user_id.name if self.current_user_id else _('未指派'),
            self.new_user_id.name,
        )
        if self.reason:
            note += _('\n原因: %s') % self.reason

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
            'res_model': activity.res_model,
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
            'previous_user_id': self.current_user_id.id if self.current_user_id else False,
            'new_user_id': self.new_user_id.id,
            'reason': self.reason or _('變更指派'),
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

    def _send_notification_to_new_user(self):
        """發送通知給新負責人"""
        self.ensure_one()
        if self.new_user_id.partner_id:
            # 使用 Odoo 18 的 _bus_send 方法
            self.new_user_id._bus_send(
                'mail.activity/updated',
                {'activity_created': True}
            )

    def action_confirm(self):
        """確認變更指派"""
        self.ensure_one()
        self._validate_reassign()

        now = fields.Datetime.now()
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
        cancel_note = _('\n\n--- %s 已變更指派給 %s ---') % (
            now_str,
            self.new_user_id.name,
        )
        if self.reason:
            cancel_note += _('\n原因: %s') % self.reason

        self._cancel_original_activity(cancel_note)

        # 發送通知給新負責人
        self._send_notification_to_new_user()

        # 刷新視圖（原待辦會從當前用戶的列表中移除）
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
