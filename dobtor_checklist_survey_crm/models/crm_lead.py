# -*- coding: utf-8 -*-

from odoo import models, fields, api


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    default_tree_view_ref = fields.Char(
        string='default tree view ref',
        compute='_compute_tree_view_ref',
        default='dobtor_checklist_survey.checklist_survey_template_tree_view',
    )

    @api.multi
    def _compute_tree_view_ref(self):
        for record in self:
            record.default_tree_view_ref = 'dobtor_checklist_survey.checklist_survey_template_tree_view'
