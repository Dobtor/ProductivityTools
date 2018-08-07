# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.tools import html_escape as escape
from odoo.exceptions import Warning as UserError
from odoo.tools.translate import _


class AbstractTodolist(models.AbstractModel):
    _name = 'abstract.todolist'

    default_user = fields.Many2one(
        'res.users', compute='_compute_default_user')
    todolist_ids = fields.One2many(
        comodel_name='dobtor.todolist.core',
        inverse_name='ref_id',
        domain=lambda self: [('ref_name', '=', self._name)],
        string='Todo Item',
    )
    kanban_todolists = fields.Text(
        compute='_compute_kanban_todolists'
    )

    lock_stage = fields.Boolean(string="Lock Stage", default=True)
    default_tree_view_ref = fields.Char(
        string='default tree view ref',
        compute='_compute_tree_view_ref'
    )

    # region model operation (CRUD)
    @api.multi
    def handle_vals(self, vals, data):
        if 'todolist_ids' in vals:
            for todolist in vals['todolist_ids']:
                if todolist[0] == 0 and todolist[2]:
                    todolist[2].update(data)
        return vals

    @api.multi
    def unlink(self):
        for item in self:
            if item.todolist_ids:
                raise UserError(
                    _('Please remove existing todolist in the relation linked to the accounts you want to delete.'))
        return super(AbstractTodolist, self).unlink()

    @api.model
    def create(self, vals):
        self.handle_vals(vals, {'ref_name': self._name})
        obj = super(AbstractTodolist, self).create(vals)
        if 'todolist_ids' in vals:
            for item in vals['todolist_ids']:
                todolist = self.env['dobtor.todolist.core'].search(
                    [('ref_id', '=', obj.id), ('ref_name', '=', obj._name)])
                todolist.write(
                    {'ref_model': u'{0},{1}'.format(obj._name, str(obj.id))})
        return obj

    @api.multi
    def write(self, vals):
        for record in self:
            self.handle_vals(
                vals, {'ref_model': u'{0},{1}'.format(record._name, str(record.id))})
            return super(AbstractTodolist, self).write(vals)
    # endregion

    # region Depp copy
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
    # endregion

    # region private method
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
    def _compute_tree_view_ref(self):
        for record in self:
            record.default_tree_view_ref = 'dobtor_todolist_core.todolist_template_tree_view'

    @api.multi
    def _compute_kanban_todolists(self):
        """ UI render """
        for record in self:
            result_string1 = ''
            result_string2 = ''
            result_string3 = ''

            for todo in record.todolist_ids:
                bounding_length = 25
                tmp_todo_name = (todo.name)[
                    :bounding_length] + '...' if len(todo.name) > bounding_length else todo.name
                if todo.state == 'todo':
                    if record.env.user == todo.user_id and record.env.user == todo.reviewer_id:
                        tmp_string3 = escape(u': {0}'.format(tmp_todo_name))
                        result_string3 += u'<li><b>TODO</b>{}</li>'.format(
                            tmp_string3)
                    elif record.env.user == todo.user_id:
                        tmp_string1_1 = escape(
                            u'{0}'.format(todo.reviewer_id.name))
                        tmp_string1_2 = escape(u'{0}'.format(tmp_todo_name))
                        result_string1 += u'<li><b>TODO</b> from <em>{0}</em>: {1}</li>'.format(
                            tmp_string1_1, tmp_string1_2)
                    elif record.env.user == todo.reviewer_id:
                        tmp_string2_1 = escape(
                            u'{0}'.format(todo.user_id.name))
                        tmp_string2_2 = escape(u'{0}'.format(tmp_todo_name))
                        result_string2 += u'<li>TODO for <em>{0}</em>: {1}</li>'.format(
                            tmp_string2_1, tmp_string2_2)
            record.kanban_todolists = '<ul>' + result_string1 + \
                result_string3 + result_string2 + '</ul>'
    # endregion
