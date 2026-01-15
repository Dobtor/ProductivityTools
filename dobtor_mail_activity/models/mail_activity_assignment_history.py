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
    _description = '待辦指派歷史'
    _order = 'changed_date desc'

    activity_id = fields.Many2one(
        'mail.activity',
        string='待辦',
        required=True,
        ondelete='cascade',
        index=True,
    )

    previous_user_id = fields.Many2one(
        'res.users',
        string='原指派人',
        help='變更前的負責人',
    )

    new_user_id = fields.Many2one(
        'res.users',
        string='新指派人',
        help='變更後的負責人',
    )

    changed_by = fields.Many2one(
        'res.users',
        string='變更者',
        default=lambda self: self.env.user,
        help='執行此變更的用戶',
    )

    changed_date = fields.Datetime(
        string='變更時間',
        default=fields.Datetime.now,
        readonly=True,
    )

    reason = fields.Text(
        string='變更原因',
        help='說明為何進行此指派變更',
    )

    # ===== 顯示用計算欄位 =====
    display_name = fields.Char(
        string='顯示名稱',
        compute='_compute_display_name',
    )

    @api.depends('previous_user_id', 'new_user_id', 'changed_date')
    def _compute_display_name(self):
        """計算顯示名稱"""
        for record in self:
            previous = record.previous_user_id.name if record.previous_user_id else _('未指派')
            new = record.new_user_id.name if record.new_user_id else _('未指派')
            date_str = record.changed_date.strftime('%Y-%m-%d %H:%M') if record.changed_date else ''
            record.display_name = '%s: %s -> %s' % (date_str, previous, new)

