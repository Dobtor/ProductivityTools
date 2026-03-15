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
        ('roundedElbow', 'Rounded Elbow'),
        ('arrowedCurve', 'Arrowed Curve'),
    ], string='Line Type', default='curved')
    line_style = fields.Selection([
        ('solid', 'Solid'),
        ('dashed', 'Dashed'),
        ('dotted', 'Dotted'),
        ('dash-dot', 'Dash-Dot'),
    ], string='Line Style', default='dashed')
    line_color = fields.Char('Line Color', default='#999999')
    line_width = fields.Integer('Line Width', default=2)
    arrow_begin = fields.Selection([
        ('none', 'None'),
        ('arrow', 'Arrow'),
        ('arrow-open', 'Arrow Open'),
        ('diamond', 'Diamond'),
        ('diamond-filled', 'Diamond Filled'),
        ('circle', 'Circle'),
        ('circle-filled', 'Circle Filled'),
        ('square', 'Square'),
    ], string='Start Arrow', default='none')
    arrow_end = fields.Selection([
        ('none', 'None'),
        ('arrow', 'Arrow'),
        ('arrow-open', 'Arrow Open'),
        ('diamond', 'Diamond'),
        ('diamond-filled', 'Diamond Filled'),
        ('circle', 'Circle'),
        ('circle-filled', 'Circle Filled'),
        ('square', 'Square'),
    ], string='End Arrow', default='arrow')
    arrow_size = fields.Selection([
        ('small', 'Small'),
        ('medium', 'Medium'),
        ('large', 'Large'),
    ], string='Arrow Size', default='medium')
    control_point_x = fields.Float('Control Point X')
    control_point_y = fields.Float('Control Point Y')
