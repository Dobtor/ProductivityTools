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
    name = fields.Text(required=True, string="Description")
    creater = fields.Many2one('res.users', 'Creater',
                              readonly=True, default=lambda self: self.env.user)
    reviewer_id = fields.Many2one(
        'res.users', 'Reviewer', default=lambda self: self.env.user)
    user_id = fields.Many2one('res.users', 'Assigned to', required=True)
    hide_button = fields.Boolean(compute='_compute_hide_button')
    recolor = fields.Boolean(compute='_compute_recolor')
    ref_model = fields.Reference(
        selection='set_ref_models', string="Refer To", default=None)
    ref_id = fields.Integer(string='ref_id')
    ref_name = fields.Char(string='ref_name')
    parent_model = fields.Reference(
        selection='referencable_models', string="Parent", default=None)
    parent_id = fields.Integer(string='parent_id')
    parent_name = fields.Char(string='parent_name')
    partner_id = fields.Many2one(
        'res.partner', default=lambda self: self.env.user.partner_id)
    date_assign = fields.Datetime(
        'Assigning Date', default=fields.Datetime.now)
    date_complete = fields.Datetime('Complete Date')
    date_deadline = fields.Datetime("Deadline")
    planned_hours = fields.Float(string='Planned Hours', default=0)
    out_of_deadline = fields.Boolean(
        string="Out of deadline", default=False, compute="_compute_check_deadline")
    sequence = fields.Integer()
    description = fields.Html(string='Description')

    # region perferment Performance into tree view
    ref_model_name = fields.Char(
        compute='_compute_model_name', string="Refer To")
    ref_parent_model_name = fields.Char(
        compute='_compute_parent_model_name', string="Parent")

    @api.depends('ref_name', 'ref_id')
    @api.multi
    def _compute_model_name(self):
        for record in self:
            if record.ref_name:
                record.ref_model_name = self.env[record.ref_name].browse(
                    record.ref_id).name

    @api.depends('parent_name', 'parent_id')
    @api.multi
    def _compute_parent_model_name(self):
        for record in self:
            if record.parent_name:
                record.ref_parent_model_name = self.env[record.parent_name].browse(
                    record.parent_id).name
    # endregion

    @api.model
    def set_ref_models(self):
        return []

    @api.model
    def referencable_models(self):
        models = self.env['res.request.link'].search([])
        return [(model.object, model.name) for model in models]

    @api.multi
    def _compute_check_deadline(self):
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
    def _handle_ref_model(self, vals):
        if 'ref_model' in vals and vals['ref_model']:
            vals['ref_id'] = vals['ref_model'].split(',')[1]
            vals['ref_name'] = vals['ref_model'].split(',')[0]
        return vals

    @api.multi
    def _handle_parent_model(self, vals):
        if 'parent_model' in vals and vals['parent_model']:
            vals['parent_id'] = vals['parent_model'].split(',')[1]
            vals['parent_name'] = vals['parent_model'].split(',')[0]
        return vals

    @api.multi
    def write(self, vals):
        vals = self._handle_ref_model(vals)
        vals = self._handle_parent_model(vals)
        old_names = dict(zip(self.mapped('id'), self.mapped('name')))
        result = super(DobtorTodoListCore, self).write(vals)
        for r in self:
            if (vals.get('state')):
                self.send_todolist_email(
                    r.name, r.state, r.reviewer_id.id, r.user_id.id, r.ref_model)
                if self.env.user != r.reviewer_id and self.env.user != r.user_id:
                    raise UserError(
                        _('Only users related to that subtask can change state.'))
            if vals.get('name'):
                self.send_todolist_email(
                    r.name, r.state, r.reviewer_id.id, r.user_id.id, r.ref_model, old_name=old_names[r.id])
                if self.env.user != r.reviewer_id and self.env.user != r.user_id:
                    raise UserError(
                        _('Only users related to that subtask can change state.'))
            if vals.get('user_id'):
                self.send_todolist_email(
                    r.name, r.state, r.reviewer_id.id, r.user_id.id, r.ref_model)
        return result

    @api.model
    def create(self, vals):
        vals = self._handle_ref_model(vals)
        vals = self._handle_parent_model(vals)
        result = super(DobtorTodoListCore, self).create(vals)
        # vals = self._add_missing_default_values(vals)
        self.send_todolist_email(
            result.name, result.state, result.reviewer_id.id, result.user_id.id)
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

    # region upload freature (Attchment)
    attachment_number = fields.Integer(
        compute='_compute_attachment_number', string='Number of Attachments')

    @api.multi
    def _compute_attachment_number(self):
        attachment_data = self.env['ir.attachment'].read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['res_id'])
        attachment = dict((res['res_id'], res['res_id_count'])
                          for res in attachment_data)
        for record in self:
            record.attachment_number = attachment.get(record.id, 0)

    @api.multi
    def action_get_attachment_view(self):
        self.ensure_one()
        res = self.env['ir.actions.act_window'].for_xml_id(
            'base', 'action_attachment')
        res['domain'] = [
            ('res_model', '=', self._name),
            ('res_id', 'in', self.ids)
        ]
        res['context'] = {
            'default_res_model': self._name,
            'default_res_id': self.id
        }
        return res

    @api.multi
    def attachment_form_view(self):
        self.ensure_one()
        return {
            'name': _('Attachments'),
            'res_model': 'ir.attachment',
            'type': 'ir.actions.act_window',
            'view_id': self.env.ref('dobtor_todolist_core.view_todolist_core_attachment_form').id,
            'view_mode': 'form',
            'view_type': 'form',
            'context': "{'default_res_model': '%s','default_res_id': %d}" % (self._name, self.id)
        }

    # endregion

    # region Send mail
    @api.multi
    def send_todolist_email(self, todo_name, todo_state, todo_reviewer_id, todo_user_id, ref_model=None, old_name=None):
        reviewer = self.env["res.users"].browse(todo_reviewer_id)
        user = self.env["res.users"].browse(todo_user_id)
        state = TODO_STATES[todo_state]
        if todo_state == 'done':
            state = '<span style="color:#080">' + state + '</span>'
        if todo_state == 'todo':
            state = '<span style="color:#A00">' + state + '</span>'
        if todo_state == 'cancelled':
            state = '<span style="color:#777">' + state + '</span>'
        if todo_state == 'waiting':
            state = '<span style="color:#b818ce">' + state + '</span>'

        subtype = 'dobtor_todolist_core.todolist_core_subtype'

        body = ''
        partner_ids = []
        if user == self.env.user and reviewer == self.env.user:
            body = '<p>' + '<strong>' + state + \
                '</strong>: ' + escape(todo_name)
            subtype = False
        elif self.env.user == reviewer:
            body = '<p>' + escape(user.name) + ', <br><strong>' + \
                state + '</strong>: ' + escape(todo_name)
            partner_ids = [user.partner_id.id]
        elif self.env.user == user:
            body = '<p>' + escape(reviewer.name) + ', <em style="color:#999">I updated todolist item assigned to me:</em> <br><strong>' + \
                state + '</strong>: ' + escape(todo_name)
            partner_ids = [reviewer.partner_id.id]
        else:
            body = '<p>' + escape(user.name) + ', ' + escape(reviewer.name) + ', <em style="color:#999">I updated todolist item, now its assigned to ' + \
                escape(user.name) + ': </em> <br><strong>' + \
                state + '</strong>: ' + escape(todo_name)
            partner_ids = [user.partner_id.id, reviewer.partner_id.id]
        if old_name:
            body = body + '<br><em style="color:#999">Updated from</em><br><strong>' + \
                state + '</strong>: ' + escape(old_name) + '</p>'
        else:
            body = body + '</p>'

        self.message_post(subject='Your todo list',
                          message_type='comment',
                          subtype=subtype,
                          body=body,
                          partner_ids=partner_ids)
    # endregion
    @api.multi
    def action_form_todolist(self):
        return {
            'name': _('Todolist'),
            'res_model': self._name,
            'type': 'ir.actions.act_window',
            'view_id': False,
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'current',
            'res_id': self.id,
        }
