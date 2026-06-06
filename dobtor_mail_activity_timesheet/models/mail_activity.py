# -*- coding: utf-8 -*-

from odoo import api, fields, models


class MailActivity(models.Model):
    """待辦工時整合（橋接）。

    核心 mail.activity 的 actual_hours 為普通欄位（手動累計）。本橋接模組
    重新定義為由關聯工時表記錄（timesheet_ids）自動加總的計算欄位，並提供
    與 account.analytic.line 的關聯。
    """
    _inherit = 'mail.activity'

    timesheet_ids = fields.One2many(
        'account.analytic.line',
        'activity_id',
        string='Timesheet Entries',
    )

    # 覆寫核心的普通 actual_hours：改為由工時表加總的計算欄位
    actual_hours = fields.Float(
        string='Actual Hours',
        compute='_compute_actual_hours',
        store=True,
        readonly=True,
        help='Total of all logged hours (from linked timesheet entries).',
    )

    @api.depends('timesheet_ids', 'timesheet_ids.unit_amount')
    def _compute_actual_hours(self):
        """計算執行工時：所有登錄工時的總合"""
        for activity in self:
            activity.actual_hours = sum(
                activity.timesheet_ids.mapped('unit_amount')
            )
