# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class MailMessage(models.Model):
    """訊息擴展

    新增功能:
    - 追蹤從此訊息建立的待辦：透過 source_message_id 反向關聯
    - 提供快速查詢方法：get_created_activities()
    """
    _inherit = 'mail.message'

    # ===== 建立的待辦（反向關聯）=====
    created_activity_ids = fields.One2many(
        'mail.activity',
        'source_message_id',
        string='Created Activities',
        help='Activities created from this message',
    )

    created_activity_count = fields.Integer(
        string='Activity Count',
        compute='_compute_created_activity_count',
    )

    @api.depends('created_activity_ids')
    def _compute_created_activity_count(self):
        """計算從此訊息建立的待辦數量"""
        for message in self:
            message.created_activity_count = len(message.created_activity_ids)

    def get_created_activities(self, include_archived=False):
        """取得從此訊息建立的所有待辦

        Args:
            include_archived: 是否包含已封存（已完成/已取消）的待辦

        Returns:
            dict: 包含待辦資訊的字典列表
        """
        self.ensure_one()

        if include_archived:
            activities = self.with_context(active_test=False).created_activity_ids
        else:
            activities = self.created_activity_ids

        result = []
        for activity in activities:
            # 判斷待辦狀態
            if activity.active:
                state = 'active'
                state_label = _('In Progress')
            elif activity.done_date:
                state = 'done'
                state_label = _('Completed')
            elif activity.cancel_date:
                state = 'cancelled'
                state_label = _('Cancelled')
            else:
                state = 'archived'
                state_label = _('Archived')

            result.append({
                'id': activity.id,
                'summary': activity.summary or activity.activity_type_id.name or '',
                'state': state,
                'state_label': state_label,
                'user_id': activity.user_id.id if activity.user_id else False,
                'user_name': activity.user_id.name if activity.user_id else _('Unassigned'),
                'date_deadline': activity.date_deadline.strftime('%Y-%m-%d') if activity.date_deadline else False,
                'activity_type_id': activity.activity_type_id.id,
                'activity_type_name': activity.activity_type_id.name,
                'res_model': activity.res_model,
                'res_id': activity.res_id,
                'res_name': activity.res_name,
            })

        return result

    @api.model
    def get_created_activities_batch(self, message_ids, include_archived=False):
        """批次取得多個訊息建立的待辦

        Args:
            message_ids: 訊息 ID 列表
            include_archived: 是否包含已封存的待辦

        Returns:
            dict: {message_id: [activity_info, ...], ...}
        """
        if not message_ids:
            return {}

        Activity = self.env['mail.activity']
        if include_archived:
            Activity = Activity.with_context(active_test=False)

        activities = Activity.search([
            ('source_message_id', 'in', message_ids),
        ])

        result = {}
        for activity in activities:
            msg_id = activity.source_message_id.id
            if activity.active:
                state, state_label = 'active', _('In Progress')
            elif activity.done_date:
                state, state_label = 'done', _('Completed')
            elif activity.cancel_date:
                state, state_label = 'cancelled', _('Cancelled')
            else:
                state, state_label = 'archived', _('Archived')

            result.setdefault(msg_id, []).append({
                'id': activity.id,
                'summary': activity.summary or activity.activity_type_id.name or '',
                'state': state,
                'state_label': state_label,
                'user_id': activity.user_id.id if activity.user_id else False,
                'user_name': activity.user_id.name if activity.user_id else _('Unassigned'),
                'date_deadline': activity.date_deadline.strftime('%Y-%m-%d') if activity.date_deadline else False,
                'activity_type_id': activity.activity_type_id.id,
                'activity_type_name': activity.activity_type_id.name,
                'res_model': activity.res_model,
                'res_id': activity.res_id,
                'res_name': activity.res_name,
            })

        return result

    def action_view_created_activities(self):
        """查看從此訊息建立的待辦"""
        self.ensure_one()

        # 取得所有待辦（包含封存）
        activities = self.with_context(active_test=False).created_activity_ids

        if len(activities) == 1:
            # 單一待辦：直接開啟表單
            return {
                'type': 'ir.actions.act_window',
                'name': _('Activity'),
                'res_model': 'mail.activity',
                'res_id': activities.id,
                'view_mode': 'form',
                'target': 'current',
                'context': {'active_test': False},
            }
        else:
            # 多個待辦：開啟列表視圖
            return {
                'type': 'ir.actions.act_window',
                'name': _('Activities Created from This Message'),
                'res_model': 'mail.activity',
                'view_mode': 'list,form',
                'domain': [('id', 'in', activities.ids)],
                'context': {'active_test': False},
            }

    def action_create_activity_from_message(self):
        """從訊息建立待辦（開啟 wizard）"""
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Activity from Message'),
            'res_model': 'mail.activity.from.message.wizard',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {
                'default_message_id': self.id,
            }
        }
