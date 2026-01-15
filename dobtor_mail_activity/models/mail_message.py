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
        string='建立的待辦',
        help='從此訊息建立的待辦事項',
    )

    created_activity_count = fields.Integer(
        string='待辦數量',
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
                state_label = _('進行中')
            elif activity.done_date:
                state = 'done'
                state_label = _('已完成')
            elif activity.cancel_date:
                state = 'cancelled'
                state_label = _('已取消')
            else:
                state = 'archived'
                state_label = _('已封存')

            result.append({
                'id': activity.id,
                'summary': activity.summary or activity.activity_type_id.name or '',
                'state': state,
                'state_label': state_label,
                'user_id': activity.user_id.id if activity.user_id else False,
                'user_name': activity.user_id.name if activity.user_id else _('未指派'),
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
                'name': _('待辦事項'),
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
                'name': _('從此訊息建立的待辦'),
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
            'name': _('從訊息建立待辦'),
            'res_model': 'mail.activity.from.message.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_message_id': self.id,
            }
        }
