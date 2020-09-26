# -*- coding: utf-8 -*-

from odoo.exceptions import ValidationError
from odoo.tools.translate import _
from odoo import models, fields, api, _

class TaskType(models.Model):
    _name = "task.type"

    name = fields.Char(string='Name',required=True)
    task_ids = fields.One2many('project.task','task_type_id',String="Task")