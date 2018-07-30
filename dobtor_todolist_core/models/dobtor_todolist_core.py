# -*- coding: utf-8 -*-

import odoo
from odoo import models, fields, api
#from odoo.addons.base.res import res_request
from odoo.tools import html_escape as escape
from odoo.exceptions import Warning as UserError
from odoo.tools.translate import _

TODO_STATES = {'done': 'Done',
                  'todo': 'TODO',
                  'waiting': 'Waiting',
                  'cancelled': 'Cancelled'}

class DobtorTodoListCore(models.Model):
    _name = "dobtor.todolist.core"
    _inherit = ["mail.thread", 'ir.needaction_mixin']
    _description = 'Dobtor Todo List Core'
    state = fields.Selection([(k, v) for k, v in TODO_STATES.items()],
                             'Status', required=True, copy=False, default='todo')
    name = fields.Char(required=True, string="Description")
    creater = fields.Many2one('res.users', 'Creater', readonly=True, default=lambda self: self.env.user)
    reviewer_id = fields.Many2one('res.users', 'Reviewer', default=lambda self: self.env.user)
    user_id = fields.Many2one('res.users', 'Assigned to', required=True)
    hide_button = fields.Boolean(compute='_compute_hide_button')
    recolor = fields.Boolean(compute='_compute_recolor')
    ref_model = fields.Reference(selection='referencable_models', string="Refer To", default=None)
    ref_id = fields.Integer(string='ref_id')
    ref_name = fields.Char(string='ref_name')
    parent_model = fields.Reference(selection='referencable_models', string="Parent", default=None)
    parent_id = fields.Integer(string='parent_id')
    parent_name = fields.Char(string='parent_name')
    partner_id = fields.Many2one('res.partner', default=lambda self: self.env.user.partner_id)
    date_assign = fields.Datetime('Assigning Date', default=fields.Datetime.now)
    date_complete = fields.Datetime('Complete Date')
    date_deadline = fields.Datetime("Deadline")
    planned_hours = fields.Float(string='Planned Hours', default=0)
    out_of_deadline = fields.Boolean("Out of deadline", default=False, compute="check_deadline")
    sequence = fields.Integer()

    @api.model
    def referencable_models(self):
        models = self.env['res.request.link'].search([])
        return [(model.object, model.name) for model in models] 

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
        # print("todo create")
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

    @api.onchange('user_id')
    def change_user_id(self):
        if self.user_id:
            self.date_assign = fields.Datetime.now()
        else:
            self.date_assign = None

    
    @api.multi
    def defaults_copy(self, default=None):
        defaults = dict(default or {})
        for item in self:
            defaults.update({
                'name': item.name,
                'creater': item.creater.id,
                'reviewer_id': item.reviewer_id.id,
                'user_id': item.user_id.id,
            })
        return defaults

