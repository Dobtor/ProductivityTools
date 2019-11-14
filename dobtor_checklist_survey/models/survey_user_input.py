# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.addons.http_routing.models.ir_http import slug

class SurveyHistory(models.Model):
    _name = 'dobtor.checklist.user_input.ref'

    @api.depends('checklist_ids')
    def _compute_response_id(self):
        for recode in self:
            recode.reject = recode.checklist_ids.response_id

    checklist_ids = fields.Many2one(
        comodel_name='dobtor.checklist.core',
        string='Check List Item'
    )
    user_input_ids = fields.Many2one(
        comodel_name='survey.user_input',
        string='Survey Create Timestamp',
    )
    user_input_name = fields.Char(string="Form Creator")

    @api.multi
    def open_history(self):
        response = self.user_input_ids
        # grab the token of the response and start surveying
        return {
            'type': 'ir.actions.act_url',
            'name': "print Survey",
            'target': 'self',
            'url': '/survey/print/%s/%s' % (slug(response.survey_id), response.token)
        }


class SurveyUserInput(models.Model):

    _inherit = 'survey.user_input'
    checklist_user_input_ids = fields.One2many(
        string='user_input',
        comodel_name='dobtor.checklist.user_input.ref',
        inverse_name='user_input_ids',
    )
