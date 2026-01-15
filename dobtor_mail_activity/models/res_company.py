# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    """公司擴展

    新增預設工時表專案欄位，用於：
    - 待辦完成時自動建立工時表記錄
    - 當待辦關聯文件無專案時的預設專案
    """
    _inherit = 'res.company'

    default_timesheet_project_id = fields.Many2one(
        'project.project',
        string='預設工時表專案',
        domain="[('allow_timesheets', '=', True), '|', ('company_id', '=', False), ('company_id', '=', id)]",
        help='待辦完成時，若無關聯專案，使用此專案建立工時表記錄。'
             '專案必須啟用工時表功能。',
    )


class ResConfigSettings(models.TransientModel):
    """系統設定擴展

    在系統設定中顯示預設工時表專案設定。
    """
    _inherit = 'res.config.settings'

    default_timesheet_project_id = fields.Many2one(
        related='company_id.default_timesheet_project_id',
        string='預設工時表專案',
        readonly=False,
        domain="[('allow_timesheets', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
