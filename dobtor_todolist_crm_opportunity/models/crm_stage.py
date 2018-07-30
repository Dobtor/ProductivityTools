# -*- coding: utf-8 -*-

from odoo import models, fields, api


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    # TODO [FIX] : if user modify name field
    @api.multi
    def get_stage_new(self):
        return self.search([('name', '=', 'New')], limit=1)

