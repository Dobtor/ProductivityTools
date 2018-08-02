# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.tools import html_escape as escape


class AbstractTodolist(models.AbstractModel):
    _name = 'abstract.todolist'

    @api.model
    def set_todolist_domain(self):
        return []


    default_user = fields.Many2one(
        'res.users', compute='_compute_default_user')
    todolist_ids = fields.One2many(
        comodel_name='dobtor.todolist.core',
        inverse_name='ref_id',
        domain=set_todolist_domain,
        string='Todo Item',
        ondelete='cascade'
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
                    result_string3 += u'<li><b>TODO</b>{}</li>'.format(
                        tmp_string3)
                elif todo.state == 'todo' and record.env.user == todo.user_id:
                    tmp_string1_1 = escape(
                        u'{0}'.format(todo.reviewer_id.name))
                    tmp_string1_2 = escape(u'{0}'.format(tmp_todo_name))
                    result_string1 += u'<li><b>TODO</b> from <em>{0}</em>: {1}</li>'.format(
                        tmp_string1_1, tmp_string1_2)
                elif todo.state == 'todo' and record.env.user == todo.reviewer_id:
                    tmp_string2_1 = escape(u'{0}'.format(todo.user_id.name))
                    tmp_string2_2 = escape(u'{0}'.format(tmp_todo_name))
                    result_string2 += u'<li>TODO for <em>{0}</em>: {1}</li>'.format(
                        tmp_string2_1, tmp_string2_2)
            record.kanban_todolists = '<ul>' + result_string1 + \
                result_string3 + result_string2 + '</ul>'


    @api.multi
    def copy_default_extend(self, default=None, new_obj=None):
        pass

    @api.multi
    def map_todolist(self, new_obj):
        for todolist in self.todolist_ids:
            defaults = todolist.defaults_copy()
            self.copy_default_extend(defaults, new_obj)
            self.browse(new_obj.id).write(
                {'todolist_ids': todolist.copy(defaults)})
        return True

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        new_obj = super(AbstractTodolist, self).copy(default)
        if 'todolist_ids' not in default:
            self.map_todolist(new_obj)
        return new_obj
