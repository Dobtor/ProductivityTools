# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class MailActivityAssignmentHistory(models.Model):
    """待辦指派歷史

    用途:
    - 記錄待辦的指派變更
    - 追蹤誰將待辦從誰轉給誰
    - 提供變更原因的記錄
    """
    _name = 'mail.activity.assignment.history'
    _description = 'Activity Assignment History'
    _order = 'changed_date desc'

    activity_id = fields.Many2one(
        'mail.activity',
        string='Activity',
        required=True,
        ondelete='cascade',
        index=True,
    )

    previous_user_id = fields.Many2one(
        'res.users',
        string='Previous Assignee',
        help='The assignee before the change',
    )

    new_user_id = fields.Many2one(
        'res.users',
        string='New Assignee',
        help='The assignee after the change',
    )

    changed_by = fields.Many2one(
        'res.users',
        string='Changed By',
        default=lambda self: self.env.user,
        help='User who made this change',
    )

    changed_date = fields.Datetime(
        string='Changed Date',
        default=fields.Datetime.now,
        readonly=True,
    )

    reason = fields.Text(
        string='Change Reason',
        help='Reason for this assignment change',
    )

    # ===== 顯示用計算欄位 =====
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
    )

    @api.depends('previous_user_id', 'new_user_id', 'changed_date')
    def _compute_display_name(self):
        """計算顯示名稱"""
        for record in self:
            previous = record.previous_user_id.name if record.previous_user_id else _('Unassigned')
            new = record.new_user_id.name if record.new_user_id else _('Unassigned')
            date_str = record.changed_date.strftime('%Y-%m-%d %H:%M') if record.changed_date else ''
            record.display_name = '%s: %s -> %s' % (date_str, previous, new)

