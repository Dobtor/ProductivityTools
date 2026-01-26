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
        string='Default Timesheet Project',
        domain="[('allow_timesheets', '=', True), '|', ('company_id', '=', False), ('company_id', '=', id)]",
        help='When activity is completed without an associated project, this project will be used to create timesheet entries. '
             'The project must have timesheets enabled.',
    )


class ResConfigSettings(models.TransientModel):
    """系統設定擴展

    在系統設定中顯示預設工時表專案設定。
    """
    _inherit = 'res.config.settings'

    timesheet_project_id = fields.Many2one(
        related='company_id.default_timesheet_project_id',
        string='Default Timesheet Project',
        readonly=False,
        domain="[('allow_timesheets', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
