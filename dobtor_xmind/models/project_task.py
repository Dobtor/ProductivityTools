# -*- coding: utf-8 -*-
from odoo import models, fields


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Stable link back to the mind-map topic this task was synced from (1:1).
    xmind_topic_id = fields.Many2one(
        'xmind.topic', string='Mind Map Topic', ondelete='set null', index=True,
        copy=False)
