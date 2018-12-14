# -*- coding: utf-8 -*-
# Copyright 2017-2018 Nova Code (http://www.novacode.nl)
# See LICENSE file for full licensing details.

from datetime import datetime, timedelta

from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError


class ProjectIssue(models.Model):

    _inherit = "project.issue"

    flowcal_event_ids = fields.One2many(
        'calendar.event',
        'flowcal_issue_id',
        context={'flow_calendar_model': 'project.issue'},
        string='Calendar')
    flowcal_event_count = fields.Integer(compute='_compute_flowcal_event_count', string="Calendar Events", default=0)

    @api.depends('flowcal_event_ids')
    def _compute_flowcal_event_count(self):
        for issue in self:
            # TODO Filter only upcoming?
            issue.flowcal_event_count = len(issue.flowcal_event_ids)

    @api.multi
    def write(self, vals):
        """If changed issue user:
        - Remove issue-user its partner from event partner_ids (attendees).
        - Add new issue-user its partner to event partner_ids (attendees).
        """
        results = []
        new_user_id = vals.get('user_id', False)

        if new_user_id:
            new_user = self.env['res.users'].browse(new_user_id)

        for issue in self:
            origin_user = issue.user_id

            if new_user_id and issue.flowcal_event_ids:
                for event in issue.flowcal_event_ids:
                    event.user_id = new_user_id
                    event.partner_ids = [(4, new_user.partner_id.id, False)]

                    partner_ids = event.partner_ids.mapped('id')
                    if origin_user.partner_id.id in partner_ids:
                        event.partner_ids = [(3, origin_user.partner_id.id, False)]

            res = super(ProjectIssue, issue).write(vals)
            results.append(res)

        return (False not in results)

    @api.multi
    def action_flow_calendar_event_load_project_issue(self):
        """Open a window to plan Issue in Calendar, with the
        flowcal_task_project_id and flowcal_task_id loaded in context.
        """
        self.ensure_one()
        ctx = dict(
            default_flowcal_issue_project_id=self.project_id.id,
            default_flowcal_issue_id=self.id,
        )
        return {
            'name': _('Meetings'),
            'type': 'ir.actions.act_window',
            'view_type': 'calendar',
            'view_mode': 'calendar,tree,form',
            'res_model': 'calendar.event',
            'context': ctx,
        }
