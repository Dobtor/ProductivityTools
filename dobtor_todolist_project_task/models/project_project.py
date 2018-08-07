# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class project_project(models.Model):
    _inherit = "project.project"

    # region model operation (Create, Copy)
    # TODO [IMP][REF]
    @api.multi
    def reference_todolist(self, new_project):
        for task in new_project.tasks:
            for todolist in task.todolist_ids:
                self.env['dobtor.todolist.core'].browse(todolist.id).write(
                    {'parent_model': 'project.project,' + str(new_project.id)})
        return True

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        project = super(project_project, self).copy(default)
        self.reference_todolist(project)
        return project

    @api.model
    def create(self, vals):
        if vals['picked_template']:
            item = self.browse(vals['picked_template'])
            project_id = item.new_project({'name': vals['name']})
        else:
            project_id = super(project_project, self).create(vals)
        return project_id
    # endregion

    # region form action

    @api.multi
    def set_template(self):
        """ Action """
        self.ensure_one()
        self.update({'state_id': 'template', 'sequence_state': 1})

    @api.multi
    def new_project(self, default=None):
        """ Action """
        self.ensure_one()
        project_id = self.copy(default)
        project_id.write({
            'state_id': 'new',
            'sequence_state': 0
        })
        return project_id

    @api.multi
    def reset_project(self):
        """ Action """
        self.ensure_one()
        self.write({
            'state_id': 'new',
            'sequence_state': 0
        })
        return
    # endregion

    state_id = fields.Selection(
        string='state',
        selection=[('new', 'New'), ('template', 'Template')]
    )
    sequence_state = fields.Integer(
        compute="count_sequence", string="State Check")

    @api.multi
    def count_sequence(self):
        for item in self:
            if item.state_id == "template":
                item.sequence_state = 1
            else:
                item.sequence_state = 0

    @api.multi
    def _get_template(self):
        return [(x.id, x.name) for x in self.search([('state_id', '=', 'template')])]

    picked_template = fields.Selection(
        string='Project Template',
        selection='_get_template'
    )

    # region upload freature (Attchment)
    @api.multi
    def _get_todolist_ids(slef, obj):
        todolist_ids = []
        for tsak_id in obj.task_ids:
            for todo_id in tsak_id.todolist_ids.ids:
                todolist_ids.append(todo_id)
        return todolist_ids

    @api.multi
    def _get_attachment_domain(self, obj):
        return [
            '|', '|',
            '&',
            ('res_model', '=', 'project.project'),
            ('res_id', 'in', obj.ids),
            '&',
            ('res_model', '=', 'project.task'),
            ('res_id', 'in', obj.task_ids.ids),
            '&',
            ('res_model', '=', 'dobtor.todolist.core'),
            ('res_id', 'in', self._get_todolist_ids(obj))
        ]

    @api.multi
    def _compute_attached_docs_count(self):
        for project in self:
            project.doc_count = self.env['ir.attachment'].search_count(
                self._get_attachment_domain(project))

    @api.multi
    def attachment_tree_view(self):
        self.ensure_one()
        return {
            'name': _('Attachments'),
            'domain': self._get_attachment_domain(self),
            'res_model': 'ir.attachment',
            'type': 'ir.actions.act_window',
            'view_id': False,
            'view_mode': 'kanban,tree,form',
            'view_type': 'form',
            'help': _('''<p class="oe_view_nocontent_create">
                        Documents are attached to the tasks and issues of your project.</p><p>
                        Send messages or log internal notes with attachments to link
                        documents to your project.
                    </p>'''),
            'limit': 80,
            'context': "{'default_res_model': '%s','default_res_id': %d}" % (self._name, self.id)
        }
    # endregion
