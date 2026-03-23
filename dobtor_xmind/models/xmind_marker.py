# -*- coding: utf-8 -*-
from odoo import models, fields


class XMindMarker(models.Model):
    _name = 'xmind.marker'
    _description = 'XMind Marker'
    _order = 'category, sequence'

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Marker code must be unique.'),
    ]

    name = fields.Char('Name', required=True)
    code = fields.Char('Code', required=True, index=True)
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
    short_label = fields.Char('Short Label', help='2-3 char label shown instead of icon (for month/weekday)')
    color = fields.Char('Color', default='#333333')
    hidden = fields.Boolean('Hidden', default=False,
                            help='Hidden markers are not shown in the picker but can be applied via import')
