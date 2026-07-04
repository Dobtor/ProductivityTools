# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    """公司擴展

    新增預設工時表專案欄位，用於：
    - 待辦完成時自動建立工時表記錄
    - 當待辦關聯文件無專案時的預設專案
    """
    _inherit = 'res.company'

    # 需求九：「啟用工時記錄」功能開關（公司層）。
    # 本模組硬相依 hr_timesheet（一律安裝），此開關為純功能開關：
    # 關閉時隱藏活動表單 Timesheet 分頁、完成待辦不建立工時表記錄、
    # actual_hours 不加總。crm.lead.project_id 與此開關無關，恆可選。
    dobtor_activity_timesheet_enabled = fields.Boolean(
        string='Enable Activity Timesheet Recording',
        default=True,
        help='When enabled, completing an activity logs time into timesheet '
             'entries and the Timesheet tab is shown on the activity form. '
             'Disabling only hides timesheet features; CRM project selection '
             'is unaffected.',
    )

    # 注意：domain 不以 allow_timesheets 過濾（該欄位由 hr_timesheet 提供）；
    # 建立工時表記錄時於完成精靈驗證 project.allow_timesheets。
    default_timesheet_project_id = fields.Many2one(
        'project.project',
        string='Default Timesheet Project',
        domain="['|', ('company_id', '=', False), ('company_id', '=', id)]",
        help='When activity is completed without an associated project, this project will be used to create timesheet entries. '
             'The project must have timesheets enabled (validated by the timesheet bridge).',
    )


class ResConfigSettings(models.TransientModel):
    """系統設定擴展

    在系統設定中顯示預設工時表專案設定。
    """
    _inherit = 'res.config.settings'

    dobtor_activity_timesheet_enabled = fields.Boolean(
        related='company_id.dobtor_activity_timesheet_enabled',
        string='Enable Activity Timesheet Recording',
        readonly=False,
    )
    # 啟用週報管理（feature flag，以群組隱含切換週報選單/視圖顯示）
    group_weekly_report = fields.Boolean(
        string='Enable Weekly Report Management',
        implied_group='dobtor_mail_activity.group_weekly_report',
    )
    timesheet_project_id = fields.Many2one(
        related='company_id.default_timesheet_project_id',
        string='Default Timesheet Project',
        readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
