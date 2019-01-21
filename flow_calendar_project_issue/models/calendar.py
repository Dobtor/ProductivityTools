# -*- coding: utf-8 -*-
# Copyright 2017-2018 Nova Code (http://www.novacode.nl)
# See LICENSE file for full licensing details.

from datetime import datetime

from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError

ISSUE_EVENT_PREFIX = 'P'


class Meeting(models.Model):

    _inherit = "calendar.event"

    flowcal_issue_project_id = fields.Many2one(
        'project.project', string='Issue Project',
        ondelete='cascade', related='flowcal_issue_id.project_id')

    flowcal_issue_id = fields.Many2one(
        'project.issue',
        domain="[('project_id', '=', flowcal_issue_project_id)]",
        ondelete='cascade',
        string='Issue')
    flowcal_issue_stage_id = fields.Many2one(
        'project.task.type',
        related='flowcal_issue_id.stage_id',
        string='Issue Stage')

    @api.model
    def default_get(self, flds):
        res = super(Meeting, self).default_get(flds)

        if self._context.get('flowcal_issue_id', False):
            issue = self.env['project.issue'].browse(self._context.get('flowcal_issue_id', False))
            res['name'] = self._issue_event_name(issue)

        return res

    @api.one
    @api.constrains('user_id')
    def _check_user_id_is_issue_owner(self):
        if self.flowcal_issue_id and self.flowcal_issue_id.user_id and self.flowcal_issue_id.user_id != self.user_id:
            raise ValidationError(
                _("Owner of the Calendar Event should be the same user as the assigned Issue responsible."))

    @api.onchange('flowcal_issue_id')
    def _onchange_issue_id(self):
        if self._context.get('default_flow_calendar_model', False) == 'project.issue' \
           and not self.id:

            if self.flowcal_issue_id:
                self.name = self._issue_event_name(self.flowcal_issue_id)

                self.user_id = self.flowcal_issue_id.user_id
                self.partner_ids = self.flowcal_issue_id.user_id.partner_id
            else:
                self.name = '%s: %s' % (ISSUE_EVENT_PREFIX, _('New'))

    def _issue_event_name(self, issue):
        return "%s/%s: %s" % (ISSUE_EVENT_PREFIX, issue.project_id.id, issue.name)

    @api.model
    def create(self, vals):
        if not vals.get('flowcal_issue_id', False):
            return super(Meeting, self).create(vals)

        issue = self.env['project.issue'].browse(vals.get('flowcal_issue_id'))

        # Set Event its user_id (responsible) and partners/attendees to Issue user.
        if issue.user_id:
            vals['user_id'] = issue.user_id.id
            vals['partner_ids'] = [(4, issue.user_id.partner_id.id, False)]

        if vals.get('description', False) and issue.description:
            vals['description'] += "\r\n%s" % issue.description
        elif issue.description:
            vals['description'] = issue.description

        result = super(Meeting, self).create(vals)
        return result

    @api.multi
    def action_flow_calendar_event_from_project_issue(self):
        form_view = self.env.ref("calendar.view_calendar_event_form")

        return {
            "name": self.name,
            "type": "ir.actions.act_window",
            "res_model": "calendar.event",
            "res_id": self.id,
            "view_mode": "form",
            "views": [
                [form_view.id, "form"],
            ],
            "target": "current",
        }
