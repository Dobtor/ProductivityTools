# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields, api


class XMindSheet(models.Model):
    _name = 'xmind.sheet'
    _description = 'XMind Sheet'
    _order = 'sequence, id'

    name = fields.Char('Sheet Name', required=True, default='Sheet 1')
    sequence = fields.Integer('Sequence', default=10)
    workbook_id = fields.Many2one('xmind.workbook', string='Workbook', ondelete='cascade', required=True)

    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()))

    topic_ids = fields.One2many('xmind.topic', 'sheet_id', string='Topics')
    relationship_ids = fields.One2many('xmind.relationship', 'sheet_id', string='Relationships')
    boundary_ids = fields.One2many('xmind.boundary', 'sheet_id', string='Boundaries')
    summary_ids = fields.One2many('xmind.summary', 'sheet_id', string='Summaries')
    floating_topic_ids = fields.One2many('xmind.floating.topic', 'sheet_id', string='Floating Topics')

    # Layout settings
    layout_type = fields.Selection([
        ('map', 'Mind Map'),
        ('logic_right', 'Logic Right'),
        ('logic_left', 'Logic Left'),
        ('tree_right', 'Tree Right'),
        ('tree_left', 'Tree Left'),
        ('org_chart_down', 'Org Chart Down'),
        ('org_chart_up', 'Org Chart Up'),
        ('updown', 'Up-Down'),
        ('fishbone_left', 'Fishbone Left'),
        ('fishbone_right', 'Fishbone Right'),
        ('matrix', 'Matrix'),
        ('timeline_horizontal', 'Timeline Horizontal'),
        ('timeline_vertical', 'Timeline Vertical'),
    ], string='Layout Type', default='map')

    # Theme
    theme = fields.Selection([
        ('default', 'Default'),
        ('primary', 'Primary'),
        ('warning', 'Warning'),
        ('danger', 'Danger'),
        ('success', 'Success'),
        ('info', 'Info'),
        ('greensea', 'Green Sea'),
        ('nephrite', 'Nephrite'),
        ('belizehole', 'Belize Hole'),
        ('wisteria', 'Wisteria'),
        ('asphalt', 'Asphalt'),
        ('orange', 'Orange'),
        ('pumpkin', 'Pumpkin'),
        ('pomegranate', 'Pomegranate'),
        ('clouds', 'Clouds'),
        ('asbestos', 'Asbestos'),
    ], string='Theme', default='primary')

    # Spacing (XMind 2 layout properties)
    spacing_major = fields.Integer('Major Spacing (H)', default=30,
                                   help='Horizontal space between parent and child nodes')
    spacing_minor = fields.Integer('Minor Spacing (V)', default=20,
                                   help='Vertical space between sibling nodes')
    line_corner = fields.Integer('Line Corner Radius', default=5,
                                 help='Corner radius for elbow connections')

    # Branch connection style
    branch_line_class = fields.Selection([
        ('straight', 'Straight'),
        ('roundedElbow', 'Rounded Elbow'),
        ('curve', 'Curve'),
        ('arrowedCurve', 'Arrowed Curve'),
    ], string='Branch Line Style', default='curve')
