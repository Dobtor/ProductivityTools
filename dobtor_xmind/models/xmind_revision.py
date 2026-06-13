# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api


class XMindRevision(models.Model):
    _name = 'xmind.revision'
    _description = 'Mind Map Workbook Revision'
    _order = 'create_date desc'

    workbook_id = fields.Many2one(
        'xmind.workbook', string='Workbook',
        ondelete='cascade', required=True, index=True,
    )
    name = fields.Char('Label', compute='_compute_name', store=True)
    snapshot = fields.Text('Snapshot (JSON)', required=True)
    user_id = fields.Many2one(
        'res.users', string='Saved By',
        default=lambda self: self.env.user,
    )
    topic_count = fields.Integer('Topics')
    is_auto = fields.Boolean('Auto-save', default=False)

    @api.depends('create_date', 'is_auto')
    def _compute_name(self):
        for rec in self:
            prefix = 'Auto' if rec.is_auto else 'Manual'
            ts = rec.create_date.strftime('%Y-%m-%d %H:%M') if rec.create_date else ''
            rec.name = f'{prefix} — {ts}'

    def action_restore(self):
        """Restore workbook to this revision's snapshot."""
        self.ensure_one()
        data = json.loads(self.snapshot)
        self.workbook_id.save_mindmap_data(data)
        return True
