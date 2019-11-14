# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.addons.http_routing.models.ir_http import slug


class DobtorCheckListSurvey(models.Model):
    _inherit = 'dobtor.checklist.core'
    survey_id = fields.Many2one("survey.survey", "Survey")
    response_id = fields.Many2one(
        'survey.user_input', "Response", ondelete="set null", oldname="response", copy=False)
    hide_reject = fields.Boolean(compute='_compute_hide_reject')
    hide_survey = fields.Boolean(compute='_compute_hide_survey')
    checklist_user_input_ids = fields.One2many(
        string='checklist',
        comodel_name='dobtor.checklist.user_input.ref',
        inverse_name='checklist_ids',
    )

    @api.multi
    def open_survey(self):
        if not self.response_id:
            response = self.env['survey.user_input'].create(
                {'survey_id': self.survey_id.id, 'partner_id': self.partner_id.id})
            self.response_id = response.id
            self.checklist_user_input_ids.create(
                {'checklist_ids': self.id, 'user_input_ids': response.id,
                    'user_input_name': self.partner_id.name}
            )
            return self.survey_id.with_context(survey_token=response.token).action_start_survey()
        else:
            response = self.response_id
        # grab the token of the response and start surveying
            return {
                'type': 'ir.actions.act_url',
                'name': "print Survey",
                'target': 'self',
                'url': '/survey/print/%s/%s' % (slug(self.survey_id), response.token)
            }

    @api.multi
    def _compute_hide_survey(self):
        for record in self:
            if self.env.user not in [record.user_id]:
                record.hide_survey = True

    @api.multi
    def _compute_hide_reject(self):
        for record in self:
            if self.env.user not in [record.reviewer_id]:
                record.hide_reject = True

    @api.multi
    def reject_action(self):
        for record in self:
            record.response_id = None
