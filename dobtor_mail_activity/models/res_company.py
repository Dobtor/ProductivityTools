# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """系統設定擴展

    工時相關設定（啟用工時記錄、預設工時專案）在 dobtor_mail_activity_project。
    """
    _inherit = 'res.config.settings'

    group_weekly_report = fields.Boolean(
        string='Enable Weekly Report Management',
        implied_group='dobtor_mail_activity.group_weekly_report',
    )
