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
    _description = '待辦延期歷史'
    _order = 'postpone_date desc'

    activity_id = fields.Many2one(
        'mail.activity',
        string='待辦',
        required=True,
        ondelete='cascade',
        index=True,
    )

    original_planned_date = fields.Date(
        string='原計畫日期',
        help='延期前的計畫執行日期',
    )

    original_week = fields.Char(
        string='原週次',
        help='延期前的週次，格式: 2026-W02',
    )

    postpone_date = fields.Datetime(
        string='延期時間',
        default=fields.Datetime.now,
        readonly=True,
    )

    postpone_by = fields.Many2one(
        'res.users',
        string='延期者',
        default=lambda self: self.env.user,
        help='執行此延期操作的用戶',
    )

    reason = fields.Text(
        string='延期原因',
        required=True,
        help='說明為何需要延期',
    )

    # ===== 顯示用計算欄位 =====
    display_name = fields.Char(
        string='顯示名稱',
        compute='_compute_display_name',
    )

    @api.depends('original_planned_date', 'original_week', 'postpone_date')
    def _compute_display_name(self):
        """計算顯示名稱"""
        for record in self:
            date_str = record.postpone_date.strftime('%Y-%m-%d %H:%M') if record.postpone_date else ''
            original = record.original_planned_date.strftime('%Y-%m-%d') if record.original_planned_date else record.original_week or _('無')
            record.display_name = '%s (%s)' % (date_str, original)

    @api.constrains('reason')
    def _check_reason(self):
        """確保延期原因不為空"""
        for record in self:
            if not record.reason or not record.reason.strip():
                raise ValidationError(_('請填寫延期原因。'))

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
