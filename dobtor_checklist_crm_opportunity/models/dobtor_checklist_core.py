# -*- coding: utf-8 -*-

from odoo import models, fields, api


class DobtorCheckListCore(models.Model):
    _inherit = 'dobtor.checklist.core'

    @api.model
    def set_ref_models(self):
        selection = super().set_ref_models()
        selection.append(('crm.lead', 'Crm Lead'))
        return selection
