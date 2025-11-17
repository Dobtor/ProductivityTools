# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields


class XMindRelationship(models.Model):
    _name = 'xmind.relationship'
    _description = 'XMind Relationship'

    sheet_id = fields.Many2one('xmind.sheet', string='Sheet', ondelete='cascade', required=True)
    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()))

    source_topic_id = fields.Many2one('xmind.topic', string='Source Topic', ondelete='cascade', required=True)
    target_topic_id = fields.Many2one('xmind.topic', string='Target Topic', ondelete='cascade', required=True)

    title = fields.Char('Title')
    line_type = fields.Selection([
        ('straight', 'Straight'),
        ('curved', 'Curved'),
        ('angled', 'Angled'),
    ], string='Line Type', default='curved')
    line_color = fields.Char('Line Color', default='#999999')
    line_width = fields.Integer('Line Width', default=2)
