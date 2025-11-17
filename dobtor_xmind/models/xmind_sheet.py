# -*- coding: utf-8 -*-
from odoo import api, fields, models


class XmindSheet(models.Model):
    _name = 'xmind.sheet'
    _description = 'XMind Sheet'
    _order = 'sequence, id'

    name = fields.Char('Title', required=True)
    workbook_id = fields.Many2one('xmind.workbook', 'Workbook',
                                   required=True, ondelete='cascade')
    root_topic_id = fields.Many2one('xmind.topic', 'Root Topic',
                                     ondelete='set null')
    topic_ids = fields.One2many('xmind.topic', 'sheet_id', 'Topics')
    topic_count = fields.Integer('Topic Count', compute='_compute_topic_count')

    sequence = fields.Integer('Sequence', default=10)

    # Theme override (if different from workbook)
    theme_override = fields.Selection([
        ('robust', 'Robust'),
        ('snowbrush', 'Snowbrush'),
        ('business', 'Business')
    ], string='Theme Override')

    @api.depends('topic_ids')
    def _compute_topic_count(self):
        for record in self:
            record.topic_count = len(record.topic_ids)

    def action_view_topics(self):
        """View all topics in this sheet as tree"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Topics - {self.name}',
            'res_model': 'xmind.topic',
            'view_mode': 'tree,form',
            'domain': [('sheet_id', '=', self.id)],
            'context': {
                'default_sheet_id': self.id,
            },
        }
