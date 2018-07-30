# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.tools import html_escape as escape
from odoo.exceptions import Warning as UserError
from odoo.exceptions import Warning, ValidationError
from odoo.tools.translate import _ 

TODO_STATES = {'done': 'Done',
                'todo': 'TODO',
                'waiting': 'Waiting',
                'cancelled': 'Cancelled'}

class DobtorTodoListCore(models.Model):
    _inherit = 'dobtor.todolist.core'

    @api.model
    def create(self, vals):
        ref_model = vals.get('ref_model')
        if ref_model:
            if 'project.task' in str(ref_model):
                task = self.env['project.task'].browse(
                    int(vals['ref_model'].split(',')[1]))
                if task and task.project_id:
                    vals.update({'parent_model':'project.project,'+ str(task.project_id.id)})
        record = super(DobtorTodoListCore, self).create(vals)
        if record.ref_model:
            task = record.ref_model
        else:
            task = None
        self.send_todolist_email(record.name, record.state, record.reviewer_id.id, record.user_id.id, task)
        return record
        

    @api.multi
    def write(self, vals):
        old_names = dict(zip(self.mapped('id'), self.mapped('name')))
        ref_model = vals.get('ref_model')
        if ref_model:
            if 'project.task' in str(ref_model):
                task = self.env['project.task'].browse(
                    int(vals['ref_model'].split(',')[1]))
                if task and task.project_id:
                    vals.update({'parent_model':'project.project,'+ str(task.project_id.id)})
        record = super(DobtorTodoListCore, self).write(vals)
        for r in self:
            if (vals.get('state')):
                self.send_todolist_email(r.name, r.state, r.reviewer_id.id, r.user_id.id, r.ref_model)
                if self.env.user != r.reviewer_id and self.env.user != r.user_id:
                    raise UserError(_('Only users related to that subtask can change state.'))
            if vals.get('name'):
                self.send_todolist_email(r.name, r.state, r.reviewer_id.id, r.user_id.id, r.ref_model, old_name=old_names[r.id])
                if self.env.user != r.reviewer_id and self.env.user != r.user_id:
                    raise UserError(_('Only users related to that subtask can change state.'))
            if vals.get('user_id'):
                self.send_todolist_email(r.name, r.state, r.reviewer_id.id, r.user_id.id, r.ref_model)
        return record

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

        if ref_model:
            subtype='dobtor_todolist_project_task.todolist_project_task_subtype'
        else:
            subtype='dobtor_todolist_core.todolist_core_subtype'

        body = ''
        partner_ids = []
        if user == self.env.user and reviewer == self.env.user:
            body = '<p>' + '<strong>' + state + '</strong>: ' + escape(todo_name)
            subtype = False
        elif self.env.user == reviewer:
            body = '<p>' + escape(user.name) + ', <br><strong>' + state + '</strong>: ' + escape(todo_name)
            partner_ids = [user.partner_id.id]
        elif self.env.user == user:
            body = '<p>' + escape(reviewer.name) + ', <em style="color:#999">I updated todolist item assigned to me:</em> <br><strong>' + state + '</strong>: ' + escape(todo_name)
            partner_ids = [reviewer.partner_id.id]
        else:
            body = '<p>' + escape(user.name) + ', ' + escape(reviewer.name) + ', <em style="color:#999">I updated todolist item, now its assigned to ' + escape(user.name) + ': </em> <br><strong>' + state + '</strong>: ' + escape(todo_name)
            partner_ids = [user.partner_id.id, reviewer.partner_id.id]
        if old_name:
            body = body + '<br><em style="color:#999">Updated from</em><br><strong>' + state + '</strong>: ' + escape(old_name) + '</p>'
        else:
            body = body + '</p>'

        if ref_model:
            for r in ref_model:
                if user == self.env.user and reviewer == self.env.user:
                    subtype = False
                
                r.message_post(message_type='comment',
                            subtype=subtype,
                            body=body,
                            partner_ids=partner_ids)
        else:
            self.message_post(subject='Your todo list',message_type='comment',
                        subtype=subtype,
                        body=body,
                        partner_ids=partner_ids)

    @api.onchange('ref_model')
    def change_parent(self):
        if self.ref_model:
            if ('project.task' in str(self.ref_model)):
                self.parent_model = self.ref_model.project_id
            else:
                self.parent_model = None
        pass
        # self.parent_model = self.ref_model.parent_id
            
            
