# -*- coding: utf-8 -*-
from odoo import models, fields


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Stable link back to the mind-map topic this task was synced from (1:1).
    xmind_topic_id = fields.Many2one(
        'xmind.topic', string='Mind Map Topic', ondelete='set null', index=True,
        copy=False)
    # True once a task has been created/managed by a mind-map sync. Survives the
    # topic being deleted (which nulls xmind_topic_id), so a re-sync can still detect
    # "its source topic is gone" and archive it.
    xmind_managed = fields.Boolean('Managed by Mind Map', default=False, copy=False)
