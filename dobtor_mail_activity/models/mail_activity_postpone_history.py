# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MailActivityPostponeHistory(models.Model):
    """待辦延期歷史

    用途:
    - 記錄待辦的延期操作
    - 追蹤原始排程日期與延期原因
    - 支援延期次數統計
    """
    _name = 'mail.activity.postpone.history'
    _description = 'Activity Postpone History'
    _order = 'postpone_date desc'

    activity_id = fields.Many2one(
        'mail.activity',
        string='Activity',
        required=True,
        ondelete='cascade',
        index=True,
    )

    original_planned_date = fields.Date(
        string='Original Planned Date',
        help='Planned execution date before postponement',
    )

    original_week = fields.Char(
        string='Original Week',
        help='Week before postponement, format: 2026-W02',
    )

    postpone_date = fields.Datetime(
        string='Postpone Date',
        default=fields.Datetime.now,
        readonly=True,
    )

    postpone_by = fields.Many2one(
        'res.users',
        string='Postponed By',
        default=lambda self: self.env.user,
        help='User who performed this postponement',
    )

    reason = fields.Text(
        string='Postponement Reason',
        required=True,
        help='Reason for postponement',
    )

    # ===== 顯示用計算欄位 =====
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
    )

    @api.depends('original_planned_date', 'original_week', 'postpone_date')
    def _compute_display_name(self):
        """計算顯示名稱"""
        for record in self:
            date_str = record.postpone_date.strftime('%Y-%m-%d %H:%M') if record.postpone_date else ''
            original = record.original_planned_date.strftime('%Y-%m-%d') if record.original_planned_date else record.original_week or _('None')
            record.display_name = '%s (%s)' % (date_str, original)

    @api.constrains('reason')
    def _check_reason(self):
        """確保延期原因不為空"""
        for record in self:
            if not record.reason or not record.reason.strip():
                raise ValidationError(_('Please explain the reason for postponement.'))

    @api.model
    def create_postpone_record(self, activity, reason):
        """建立延期記錄的便捷方法

        Args:
            activity: mail.activity 記錄
            reason: 延期原因字串

        Returns:
            新建立的延期歷史記錄
        """
        activity.ensure_one()

        # 計算原週次
        original_week = False
        if activity.planned_date:
            year, week, _ = activity.planned_date.isocalendar()
            original_week = '%d-W%02d' % (year, week)

        return self.create({
            'activity_id': activity.id,
            'original_planned_date': activity.planned_date,
            'original_week': original_week,
            'reason': reason,
        })
