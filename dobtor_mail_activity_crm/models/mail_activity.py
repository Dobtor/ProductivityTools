# -*- coding: utf-8 -*-

from odoo import models


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    def _get_timesheet_project(self):
        """關聯商機有專案 → 以商機專案登錄工時（優先於待辦專案／公司預設）。"""
        self.ensure_one()
        if self.res_model == 'crm.lead' and self.res_id:
            lead = self.env['crm.lead'].browse(self.res_id).exists()
            if lead.project_id:
                return lead.project_id
        return super()._get_timesheet_project()
