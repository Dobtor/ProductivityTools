# -*- coding: utf-8 -*-

from odoo import models, api
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class Task(models.Model):
    _name = "project.task"
    _inherit = ["project.task", "abstract.checklist"]

    @api.constrains('stage_id')
    @api.multi
    def restrict(self):
        self.ensure_one()
        if self.stage_id and self.lock_stage:
            checklists = self.env['dobtor.checklist.core'].search(
                [('ref_model', '=', u'{0},{1}'.format(self._name, str(self.id)) )])
            if checklists:
                for checklist in checklists:
                    if checklist.state in ('todo', 'waiting'):
                        raise ValidationError(
                            _("You can't move it to next stage. Some todos are not completed yet.!"))

    @api.multi
    def copy_default_extend(self, default, new_obj):
        default.update({
            'ref_model': self._name + ',' + str(new_obj.id),
            'parent_model': 'project.project,' + str(new_obj.project_id.id),
        })

