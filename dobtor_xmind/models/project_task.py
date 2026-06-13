# -*- coding: utf-8 -*-
from odoo import models, fields, _


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def action_xmind_schedule_activity(self):
        """Return Odoo's built-in 'Schedule Activity' form (mail.activity) for this
        task, opened in a dialog. Called from the mind-map clock icon. Uses the
        dialog-optimised popup form view (with the Schedule/Done buttons)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Schedule Activity'),
            'res_model': 'mail.activity',
            'view_mode': 'form',
            'views': [[self.env.ref('mail.mail_activity_view_form_popup').id, 'form']],
            'target': 'new',
            'context': {
                'default_res_model_id': self.env['ir.model']._get_id('project.task'),
                'default_res_id': self.id,
            },
        }

    # Stable link back to the mind-map topic this task was synced from (1:1).
    xmind_topic_id = fields.Many2one(
        'xmind.topic', string='Mind Map Topic', ondelete='set null', index=True,
        copy=False)
    # True once a task has been created/managed by a mind-map sync. Survives the
    # topic being deleted (which nulls xmind_topic_id), so a re-sync can still detect
    # "its source topic is gone" and archive it.
    xmind_managed = fields.Boolean('Managed by Mind Map', default=False, copy=False)
