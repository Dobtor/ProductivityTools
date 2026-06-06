# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountAnalyticLine(models.Model):
    """工時表記錄擴展

    新增 activity_id 欄位，用於關聯工時記錄與待辦事項。
    支援從待辦完成精靈多次登錄工時。
    """
    _inherit = 'account.analytic.line'

    activity_id = fields.Many2one(
        'mail.activity',
        string='Related Activity',
        index=True,
        ondelete='set null',
        help='The activity that created this timesheet entry',
    )
