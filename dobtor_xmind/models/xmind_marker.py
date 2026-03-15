# -*- coding: utf-8 -*-
from odoo import models, fields


class XMindMarker(models.Model):
    _name = 'xmind.marker'
    _description = 'XMind Marker'
    _order = 'category, sequence'

    name = fields.Char('Name', required=True)
    code = fields.Char('Code', required=True)
    category = fields.Selection([
        ('priority', 'Priority'),
        ('smiley', 'Smiley'),
        ('task', 'Task'),
        ('flag', 'Flag'),
        ('star', 'Star'),
        ('people', 'People'),
        ('arrow', 'Arrow'),
        ('symbol', 'Symbol'),
        ('month', 'Month'),
        ('weekday', 'Weekday'),
        ('half', 'Half Star'),
        ('other', 'Other'),
    ], string='Category', default='other')
    sequence = fields.Integer('Sequence', default=10)
    icon = fields.Char('Icon Class', help='FontAwesome or custom icon class')
    color = fields.Char('Color', default='#333333')
