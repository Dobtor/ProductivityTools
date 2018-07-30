# -*- coding: utf-8 -*-

from odoo import models, fields, api


class project_template_task(models.Model):
    _inherit = "project.task.type"
    project_check = fields.Boolean(string="Project Check")

    # TODO [FIX] : if user modify name field
    @api.multi
    def get_type_template(self):
        return self.search([('name', '=', 'Template')], limit=1)

    # TODO [FIX] : if user modify name field
    @api.multi
    def get_type_new(self):
        return self.search([('name', '=', 'New')], limit=1)

    # TODO [FIX] : if user modify name field
    @api.multi
    def get_type_inprogress(self):
        return self.search([('name', '=', 'In Progress')], limit=1)
