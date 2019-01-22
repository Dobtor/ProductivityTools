# -*- coding: utf-8 -*-
# Copyright 2017-2018 Nova Code (http://www.novacode.nl)
# See LICENSE file for full licensing details.

from datetime import datetime

from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError
from bs4 import BeautifulSoup

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

    description = fields.Html(string="Description", states={'done': [('readonly', True)]})

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

class Attendee(models.Model):
    
    _inherit = 'calendar.attendee'

    @api.model
    def modify_body_html(self, template):
        soup = BeautifulSoup(template.body_html, 'html.parser')
        if soup:
            lis = soup.find_all('li')
            need_update = False
            for li in lis:
                if li.text == 'Description: ${object.event_id.description}':
                    li.string = 'Description: ${object.event_id.description|safe}'
                    need_update = True
            if need_update:
                template.update({
                    'body_html' : str(soup)
                })
        return template

    @api.multi
    def _send_mail_to_attendees(self, template_xmlid, force_send=False):
        """ Send mail for event invitation to event attendees.
            :param template_xmlid: xml id of the email template to use to send the invitation
            :param force_send: if set to True, the mail(s) will be sent immediately (instead of the next queue processing)
        """
        res = False

        if self.env['ir.config_parameter'].get_param('calendar.block_mail') or self._context.get("no_mail_to_attendees"):
            return res

        calendar_view = self.env.ref('calendar.view_calendar_event_calendar')
        invitation_template = self.env.ref(template_xmlid)
        
        invitation_template = self.modify_body_html(invitation_template)

        # get ics file for all meetings
        ics_files = self.mapped('event_id').get_ics_file()

        # prepare rendering context for mail template
        colors = {
            'needsAction': 'grey',
            'accepted': 'green',
            'tentative': '#FFFF00',
            'declined': 'red'
        }
        rendering_context = dict(self._context)
        rendering_context.update({
            'color': colors,
            'action_id': self.env['ir.actions.act_window'].search([('view_id', '=', calendar_view.id)], limit=1).id,
            'dbname': self._cr.dbname,
            'base_url': self.env['ir.config_parameter'].get_param('web.base.url', default='http://localhost:8069'),
        })
        
        invitation_template = invitation_template.with_context(rendering_context)

        # send email with attachments
        mails_to_send = self.env['mail.mail']
        for attendee in self:
            if attendee.email or attendee.partner_id.email:
                ics_file = ics_files.get(attendee.event_id.id)
                mail_id = invitation_template.send_mail(attendee.id)

                vals = {}
                if ics_file:
                    vals['attachment_ids'] = [(0, 0, {'name': 'invitation.ics',
                                                      'datas_fname': 'invitation.ics',
                                                      'datas': str(ics_file).encode('base64')})]
                vals['model'] = None  # We don't want to have the mail in the tchatter while in queue!
                vals['res_id'] = False
                current_mail = self.env['mail.mail'].browse(mail_id)
                current_mail.mail_message_id.write(vals)
                mails_to_send |= current_mail

        if force_send and mails_to_send:
            res = mails_to_send.send()

        return res