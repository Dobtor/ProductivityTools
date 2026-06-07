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
        ('map', '心智圖'),
        ('org_chart_down', '組織圖 (向下)'),
        ('org_chart_up', '組織圖 (向上)'),
        ('tree_right', '樹狀圖 (向右)'),
        ('tree_left', '樹狀圖 (向左)'),
        ('logic_right', '邏輯圖 (向右)'),
        ('logic_left', '邏輯圖 (向左)'),
        ('timeline_horizontal', '時間軸 - 水平'),
        ('timeline_vertical', '時間軸 - 垂直'),
        # 注意：_layoutFishbone(dir=-1)=fishbone_left 渲染為「頭向右」，dir=1=fishbone_right 渲染為「頭向左」
        ('fishbone_right', '魚骨圖 (頭向左)'),
        ('fishbone_left', '魚骨圖 (頭向右)'),
        # 注意：_layoutMatrixH 渲染為「直行」(欄)，_layoutMatrixV 渲染為「橫列」(列)
        ('matrix_vertical', '表格圖 (橫列)'),
        ('matrix_horizontal', '表格圖 (直行)'),
        ('matrix', '表格圖 (橫列)'),  # legacy alias → matrix_vertical
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
