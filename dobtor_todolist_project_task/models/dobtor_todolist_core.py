# -*- coding: utf-8 -*-

from odoo import models, api


TODO_STATES = {'done': 'Done',
               'todo': 'TODO',
               'waiting': 'Waiting',
               'cancelled': 'Cancelled'}


class DobtorTodoListCore(models.Model):
    _inherit = 'dobtor.todolist.core'

    @api.model
    def set_ref_models(self):
        selection = super(DobtorTodoListCore, self).set_ref_models()
        selection.append(('project.task', 'Project task'))
        return selection

    @api.multi
    def _handle_vals(self, vals):
        ref_model = vals.get('ref_model')
        if ref_model:
            if 'project.task' in str(ref_model):
                task = self.env['project.task'].browse(
                    int(vals['ref_model'].split(',')[1]))
                if task and task.project_id:
                    vals.update(
                        {'parent_model': 'project.project,' + str(task.project_id.id)})
        return vals

    @api.model
    def create(self, vals):
        vals = self._handle_vals(vals)
        record = super(DobtorTodoListCore, self).create(vals)
        return record

    @api.multi
    def write(self, vals):
        vals = self._handle_vals(vals)
        record = super(DobtorTodoListCore, self).write(vals)
        return record

    @api.onchange('ref_model')
    def change_parent(self):
        if self.ref_model:
            if ('project.task' in str(self.ref_model)):
                self.parent_model = self.ref_model.project_id
            else:
                self.parent_model = None
        pass
