# -*- coding: utf-8 -*-

from openerp import models, fields, api
from openerp.tools import html_escape as escape
from openerp.exceptions import Warning as UserError
from openerp.exceptions import Warning, ValidationError
from openerp.tools.translate import _ 

class Crm_Lead(models.Model):
    _inherit = ['crm.lead']

    default_user = fields.Many2one('res.users', compute='_compute_default_user')
    todolist_ids = fields.One2many(
        comodel_name='dobtor.todolist.core',
        inverse_name='ref_id', 
        domain=[('ref_model', 'like', 'crm.lead')],
        string='Todo Item'
    )
    kanban_todolists = fields.Text(
        compute='_compute_kanban_todolists'
    )
    
    lock_stage = fields.Boolean(string="Lock Stage", default=True)

    @api.multi
    def _compute_default_user(self):
        for record in self:
            if self.env.user != record.user_id and self.env.user != record.create_uid:
                record.default_user = record.user_id
            else:
                if self.env.user != record.user_id:
                    record.default_user = record.user_id
                elif self.env.user != record.create_uid:
                    record.default_user = record.create_uid
                elif self.env.user == record.create_uid and self.env.user == record.user_id:
                    record.default_user = self.env.user

    @api.multi
    def _compute_kanban_todolists(self):
        for record in self:
            result_string1 = ''
            result_string2 = ''
            result_string3 = ''

            for todo in record.todolist_ids:
                bounding_length = 25
                tmp_list = (todo.name).split()
                for index in range(len(tmp_list)):
                    if (len(tmp_list[index]) > bounding_length):
                        tmp_list[index] = tmp_list[index][:bounding_length] + '...'
                tmp_todo_name = " ".join(tmp_list)
                if todo.state == 'todo' and record.env.user == todo.user_id and record.env.user == todo.reviewer_id:
                    tmp_string3 = escape(u': {0}'.format(tmp_todo_name))
                    result_string3 += u'<li><b>TODO</b>{}</li>'.format(tmp_string3)
                elif todo.state == 'todo' and record.env.user == todo.user_id:
                    tmp_string1_1 = escape(u'{0}'.format(todo.reviewer_id.name))
                    tmp_string1_2 = escape(u'{0}'.format(tmp_todo_name))
                    result_string1 += u'<li><b>TODO</b> from <em>{0}</em>: {1}</li>'.format(tmp_string1_1, tmp_string1_2)
                elif todo.state == 'todo' and record.env.user == todo.reviewer_id:
                    tmp_string2_1 = escape(u'{0}'.format(todo.user_id.name))
                    tmp_string2_2 = escape(u'{0}'.format(tmp_todo_name))
                    result_string2 += u'<li>TODO for <em>{0}</em>: {1}</li>'.format(tmp_string2_1, tmp_string2_2)
            record.kanban_todolists = '<ul>' + result_string1 + result_string3 + result_string2 + '</ul>'

    @api.multi
    def unlink(self):
        if self.todolist_ids:
            raise UserError(_('Please remove existing todolist in the task linked to the accounts you want to delete.'))
        return super(Task, self).unlink()
    
    @api.constrains('stage_id')
    def restrict(self):
        if self.stage_id and self.lock_stage:
            todo_list = self.env['dobtor.todolist.core'].search([('ref_name', '=', 'project.task'), ('ref_id', '=', self.id)])
            if todo_list:
                print("restrict")
                for todo in todo_list:
                    if todo.state in ('todo', 'waiting'):
                        raise ValidationError(_("You can't move it to next stage. Some todos are not completed yet.!"))


    