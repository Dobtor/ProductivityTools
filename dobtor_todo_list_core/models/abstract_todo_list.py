# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.tools import html_escape as escape
from odoo.exceptions import Warning as UserError
from odoo.tools.translate import _


class AbstractTodoList(models.AbstractModel):
    _name = 'abstract.todo.list'

    default_user = fields.Many2one('res.users',
                                   compute='_compute_default_user')
    todo_list_ids = fields.One2many(
        comodel_name='dobtor.todo.list.core',
        inverse_name='ref_id',
        domain=lambda self: [('ref_name', '=', self._name)],
        string='Todo Item',
    )
    kanban_todo_lists = fields.Text(compute='_compute_kanban_todo_lists')

    lock_stage = fields.Boolean(string="Lock Stage", default=True)

    default_tree_view_ref = fields.Char(
        string='default tree view ref',
        compute='_compute_tree_view_ref',
        default='dobtor_todo_list_core.todo_list_template_tree_view',
    )

    # region model operation (CRUD)
    @api.multi
    def handle_vals(self, vals, data):
        if 'todo_list_ids' in vals:
            for todo_list in vals['todo_list_ids']:
                if todo_list[0] == 0 and todo_list[2]:
                    todo_list[2].update(data)
        return vals

    @api.multi
    def unlink(self):
        for item in self:
            if item.todo_list_ids:
                raise UserError(
                    _('Please remove existing todo-list in the relation linked to the accounts you want to delete.'
                      ))
        return super().unlink()

    @api.model
    def create(self, vals):
        self.handle_vals(vals, {'ref_name': self._name})
        obj = super().create(vals)
        if 'todo_list_ids' in vals:
            for item in vals['todo_list_ids']:
                todo_list = self.env['dobtor.todo.list.core'].search([
                    ('ref_id', '=', obj.id), ('ref_name', '=', obj._name)
                ])
                todo_list.write(
                    {'ref_model': u'{0},{1}'.format(obj._name, str(obj.id))})
        return obj

    @api.multi
    def write(self, vals):
        for record in self:
            self.handle_vals(
                vals,
                {'ref_model': u'{0},{1}'.format(record._name, str(record.id))})
            return super().write(vals)

    # endregion

    # region Depp copy
    @api.multi
    def copy_default_extend(self, default=None, new_obj=None):
        pass

    @api.multi
    def map_todo_list(self, new_obj):
        for todo_list in self.todo_list_ids:
            defaults = todo_list.defaults_copy()
            self.copy_default_extend(defaults, new_obj)
            self.browse(new_obj.id).write(
                {'todo_list_ids': todo_list.copy(defaults)})
        return True

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        new_obj = super().copy(default)
        if 'todo_list_ids' not in default:
            self.map_todo_list(new_obj)
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
            record.default_tree_view_ref = 'dobtor_todo_list_core.todo_list_template_tree_view'

    @api.multi
    def _compute_kanban_todo_lists(self):
        """ UI render """
        for record in self:
            result_string1 = ''
            result_string2 = ''
            result_string3 = ''

            for todo in record.todo_list_ids:
                bounding_length = 25
                tmp_todo_name = (todo.name)[:bounding_length] + '...' if len(
                    todo.name) > bounding_length else todo.name
                if todo.state == 'todo' and todo.user_id:
                    if record.env.user == todo.user_id and record.env.user == todo.reviewer_id:
                        tmp_string3 = escape(u': {0}'.format(tmp_todo_name))
                        result_string3 += u'<li><b>TODO</b>{}</li>'.format(
                            tmp_string3)
                    elif record.env.user == todo.user_id:
                        tmp_string1_1 = escape(u'{0}'.format(
                            todo.reviewer_id.name))
                        tmp_string1_2 = escape(u'{0}'.format(tmp_todo_name))
                        result_string1 += u'<li><b>TODO</b> from <em>{0}</em>: {1}</li>'.format(
                            tmp_string1_1, tmp_string1_2)
                    elif record.env.user == todo.reviewer_id:
                        tmp_string2_1 = escape(u'{0}'.format(
                            todo.user_id.name))
                        tmp_string2_2 = escape(u'{0}'.format(tmp_todo_name))
                        result_string2 += u'<li>TODO for <em>{0}</em>: {1}</li>'.format(
                            tmp_string2_1, tmp_string2_2)
            record.kanban_todo_lists = '<ul>' + result_string1 + \
                result_string3 + result_string2 + '</ul>'

    # endregion

    # region upload freature (Attchment)
    @api.multi
    def _get_attachment_domain(self, obj):
        return [
            '|', '&', ('res_model', '=', obj._name), ('res_id', 'in', obj.ids),
            '&', ('res_model', '=', 'dobtor.todo.list.core'),
            ('res_id', 'in', obj.todo_list_ids.ids)
        ]

    doc_count = fields.Integer(compute='_compute_attached_docs_count',
                               string="Number of documents attached")

    @api.multi
    def _compute_attached_docs_count(self):
        for record in self:
            record.doc_count = self.env['ir.attachment'].search_count(
                self._get_attachment_domain(record))

    @api.multi
    def attachment_tree_view(self):
        self.ensure_one()
        return {
            'name':
            _('Attachments'),
            'domain':
            self._get_attachment_domain(self),
            'res_model':
            'ir.attachment',
            'type':
            'ir.actions.act_window',
            'view_id':
            False,
            'view_mode':
            'kanban,tree,form',
            'view_type':
            'form',
            'limit':
            80,
            'context':
            "{'form_view_ref': 'dobtor_todo_list_core.view_todo_list_core_attachment_form','default_res_model': '%s','default_res_id': %d}"
            % (self._name, self.id)
        }

    # endregion
