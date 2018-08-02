# -*- coding: utf-8 -*-

from odoo import models, api
from odoo.exceptions import Warning as UserError
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class Task(models.Model):
    _name = "project.task"
    _inherit = ["project.task", "abstract.todolist"]

    @api.model
    def set_todolist_domain(self):
        return [('ref_model', '=', 'project.task')]

    @api.constrains('stage_id')
    def restrict(self):
        if self.stage_id and self.lock_stage:
            todo_list = self.env['dobtor.todolist.core'].search(
                [('ref_name', '=', 'project.task'), ('ref_id', '=', self.id)])
            if todo_list:
                for todo in todo_list:
                    if todo.state in ('todo', 'waiting'):
                        raise ValidationError(
                            _("You can't move it to next stage. Some todos are not completed yet.!"))

    @api.multi
    def copy_default_extend(self, default, new_obj):
        default.update({
            'ref_model': 'project.task,' + str(new_obj.id),
            'parent_model': 'project.project,' + str(new_obj.project_id.id),
        })

    # @api.model
    # def create(self, vals):
    #     task = super(Task, self).create(vals)
    #     if 'todolist_ids' in task:
    #     return task
