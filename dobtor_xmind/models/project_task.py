# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


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

    def action_open_in_mindmap(self):
        """開啟心智圖編輯器，切到這個任務的主題所在分頁並選取它（甘特圖右鍵用）。"""
        self.ensure_one()
        topic = self.xmind_topic_id
        if not topic or not topic.exists():
            raise UserError(_('Task "%s" is not linked to a mind map topic.', self.name))
        workbook = topic.sheet_id.workbook_id
        return {
            'type': 'ir.actions.client',
            'tag': 'dobtor_xmind.mindmap_editor',
            'name': workbook.name,
            'params': {
                'workbook_id': workbook.id,
                'sheet_id': topic.sheet_id.id,
                'topic_component_id': topic.component_id,
            },
            'target': 'current',
        }
