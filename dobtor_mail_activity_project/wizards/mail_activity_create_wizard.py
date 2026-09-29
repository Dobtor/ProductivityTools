# -*- coding: utf-8 -*-

from odoo import api, fields, models


class MailActivityCreateWizard(models.TransientModel):
    """建立待辦精靈 × 專案：選專案、由文件反推專案、專案客戶帶入。"""
    _inherit = 'mail.activity.create.wizard'

    project_id = fields.Many2one('project.project', string='Project')

    @api.onchange('project_id')
    def _onchange_wizard_project(self):
        """選/改專案 → 客戶空則以專案客戶帶入（不覆蓋已選客戶）。"""
        for wiz in self:
            if wiz.project_id and not wiz.partner_id and wiz.project_id.partner_id:
                wiz.partner_id = wiz.project_id.partner_id.id

    def _wizard_fill_project_partner(self):
        """選定 res 後：專案「空時」由文件反推帶入，再由核心補客戶。

        規則：選客戶先 → 選 doc → 帶入專案；選專案先 → 選 doc → 帶入客戶。
        """
        self.ensure_one()
        if self.res_model and self.res_id and not self.project_id:
            project = self.env['mail.activity']._project_from_res(self.res_model, self.res_id)
            if project:
                self.project_id = project.id
        super()._wizard_fill_project_partner()

    def _prepare_extra_activity_values(self):
        vals = super()._prepare_extra_activity_values()
        if self.project_id:
            vals['project_id'] = self.project_id.id
        return vals
