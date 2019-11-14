# -*- coding: utf-8 -*-

from odoo import models, api


TODO_STATES = {'done': 'Done',
               'todo': 'TODO',
               'waiting': 'Waiting',
               'cancelled': 'Cancelled'}


class DobtorCheckListCore(models.Model):
    _inherit = 'dobtor.checklist.core'

    @api.model
    def set_ref_models(self):
        selection = super().set_ref_models()
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
        record = super().create(vals)
        return record

    @api.multi
    def write(self, vals):
        vals = self._handle_vals(vals)
        record = super().write(vals)
        return record

    @api.onchange('ref_model')
    def change_parent(self):
        if self.ref_model:
            if ('project.task' in str(self.ref_model)) and self.ref_model.project_id:
                self.parent_model = self.ref_model.project_id
            else:
                self.parent_model = None
        pass
