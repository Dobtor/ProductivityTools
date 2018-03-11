# -*- coding: utf-8 -*-

import openerp
from openerp import models, fields, api
from openerp.addons.base.res import res_request
from openerp.tools import html_escape as escape
from openerp.exceptions import Warning as UserError
from openerp.tools.translate import _

TODO_STATES = {'done': 'Done',
                  'todo': 'TODO',
                  'waiting': 'Waiting',
                  'cancelled': 'Cancelled'}

def referencable_models(self):
    return res_request.referencable_models(
        self, self.env.cr, self.env.uid, context=self.env.context)

class DobtorTodoListCore(models.Model):
    _name = "dobtor.todolist.core"
    _inherit = ["mail.thread", 'ir.needaction_mixin']
    _description = 'Dobtor Todo List Core'
    state = fields.Selection([(k, v) for k, v in TODO_STATES.items()],
                             'Status', required=True, copy=False, default='todo')
    name = fields.Char(required=True, string="Description")
    reviewer_id = fields.Many2one('res.users', 'Reviewer', readonly=True, default=lambda self: self.env.user)
    user_id = fields.Many2one('res.users', 'Assigned to', required=True)
    hide_button = fields.Boolean(compute='_compute_hide_button')
    recolor = fields.Boolean(compute='_compute_recolor')
    ref_model = fields.Reference(referencable_models, "Refer To", default=None)
    ref_id = fields.Integer(string='ref_id')
    ref_name = fields.Char(string='ref_name')
    parent_model = fields.Reference(referencable_models, "Parent", default=None)
    parent_id = fields.Integer(string='parent_id')
    parent_name = fields.Char(string='parent_name')
    survey_id = fields.Many2one("survey.survey", "Survey")
    partner_id = fields.Many2one('res.partner', default=lambda self: self.env.user.partner_id)
    response_id = fields.Many2one('survey.user_input', "Response", ondelete="set null", oldname="response")
    date_assign = fields.Datetime('Assigning Date', select=True, default=fields.Datetime.now)
    date_complete = fields.Datetime('Complete Date', select=True)
    date_deadline = fields.Datetime("Deadline", select=True)
    planned_hours = fields.Float(string='Planned Hours', default=0)
    out_of_deadline = fields.Boolean("Out of deadline", default=False, compute="check_deadline")
    sequence = fields.Integer()

    @api.multi
    def check_deadline(self):
        for record in self:
            if record.date_deadline and record.date_deadline <= fields.Datetime.now():
                record.out_of_deadline = True
            else:
                record.out_of_deadline = False

    @api.multi
    def _compute_recolor(self):
        for record in self:
            if self.env.user == record.user_id and record.state == 'todo':
                record.recolor = True

    @api.multi
    def _compute_hide_button(self):
        for record in self:
            if self.env.user not in [record.reviewer_id, record.user_id]:
                record.hide_button = True

    @api.multi
    def _compute_reviewer_id(self):
        for record in self:
            record.reviewer_id = record.create_uid

    @api.model
    def _needaction_domain_get(self):
        if self._needaction:
            return [('state', '=', 'todo'), ('user_id', '=', self.env.uid)]
        return []

    @api.multi
    def write(self, vals):
        if 'ref_model' in vals and vals['ref_model']:
            vals['ref_id'] = vals['ref_model'].split(',')[1]
            vals['ref_name'] = vals['ref_model'].split(',')[0]
        if 'parent_model' in vals and vals['parent_model']:
            vals['parent_id'] = vals['parent_model'].split(',')[1]
            vals['parent_name'] = vals['parent_model'].split(',')[0]
        result = super(DobtorTodoListCore, self).write(vals)
        return result

    @api.model
    def create(self, vals):
        print("todo create")
        if 'ref_model' in vals and vals['ref_model']:
            vals['ref_id'] = vals['ref_model'].split(',')[1]
            vals['ref_name'] = vals['ref_model'].split(',')[0]
        if 'parent_model' in vals and vals['parent_model']:
            vals['parent_id'] = vals['parent_model'].split(',')[1]
            vals['parent_name'] = vals['parent_model'].split(',')[0]
        result = super(DobtorTodoListCore, self).create(vals)
        vals = self._add_missing_default_values(vals)
        # task = self.env['project.task'].browse(vals.get('task_id'))
        # task.send_subtask_email(vals['name'], vals['state'], vals['reviewer_id'], vals['user_id'])
        return result

    @api.multi
    def change_state_done(self):
        for record in self:
            record.state = 'done'
            record.date_complete = fields.Datetime.now()

    @api.multi
    def change_state_todo(self):
        for record in self:
            record.state = 'todo'
            record.date_complete = None

    @api.multi
    def change_state_cancelled(self):
        for record in self:
            record.state = 'cancelled'
            record.date_complete = None

    @api.multi
    def change_state_waiting(self):
        for record in self:
            record.state = 'waiting'
            record.date_complete = None

    @api.multi
    def open_survey(self):
        if not self.response_id:
            response = self.env['survey.user_input'].create({'survey_id': self.survey_id.id, 'partner_id': self.partner_id.id})
            self.response_id = response.id
        else:
            response = self.response_id
        # grab the token of the response and start surveying
        return self.survey_id.with_context(survey_token=response.token).action_start_survey()

    @api.onchange('user_id')
    def change_user_id(self):
        if self.user_id:
            self.date_assign = fields.Datetime.now()
        else:
            self.date_assign = None

    
    
    
        
        