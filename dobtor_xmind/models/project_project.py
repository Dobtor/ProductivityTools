# -*- coding: utf-8 -*-
from odoo import models, fields


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # Reverse of xmind.workbook.project_id (1:1 in practice — at most one mind map
    # per project). Used for navigation and the reverse create/sync (P3).
    xmind_workbook_ids = fields.One2many(
        'xmind.workbook', 'project_id', string='Mind Maps')
    xmind_workbook_count = fields.Integer(
        compute='_compute_xmind_workbook_count', string='Mind Map Count')

    def _compute_xmind_workbook_count(self):
        for project in self:
            project.xmind_workbook_count = len(project.xmind_workbook_ids)
