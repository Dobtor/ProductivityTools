# -*- coding: utf-8 -*-

from odoo import models, fields, api


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    @api.multi
    def _compute_tree_view_ref(self):
        for record in self:
            record.default_tree_view_ref = 'dobtor_todolist_survey.todolist_survey_template_tree_view'
