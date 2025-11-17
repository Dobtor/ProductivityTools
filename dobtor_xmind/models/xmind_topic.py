# -*- coding: utf-8 -*-
import json
import uuid
from odoo import api, fields, models


class XmindTopic(models.Model):
    _name = 'xmind.topic'
    _description = 'XMind Topic'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'title'
    _order = 'sequence, id'

    title = fields.Char('Title', required=True)
    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()),
                                help='Unique identifier for XMind format')

    # Hierarchy
    parent_id = fields.Many2one('xmind.topic', 'Parent Topic',
                                 ondelete='cascade', index=True)
    child_ids = fields.One2many('xmind.topic', 'parent_id', 'Subtopics')
    parent_path = fields.Char(index=True)
    is_root = fields.Boolean('Is Root Topic', default=False)

    # Relationship to sheet
    sheet_id = fields.Many2one('xmind.sheet', 'Sheet', required=True,
                                ondelete='cascade')
    workbook_id = fields.Many2one('xmind.workbook', 'Workbook',
                                   related='sheet_id.workbook_id', store=True)

    # Content
    note = fields.Text('Note', help='Text note attached to this topic')
    markers = fields.Text('Markers', default='[]',
                          help='JSON array of marker IDs')
    labels = fields.Text('Labels', default='[]',
                         help='JSON array of label strings')

    # Visual properties
    position_x = fields.Float('X Position', default=0)
    position_y = fields.Float('Y Position', default=0)
    sequence = fields.Integer('Sequence', default=10)

    # Attachments
    image_attachment_id = fields.Many2one('ir.attachment', 'Image')
    image_width = fields.Integer('Image Width')
    image_height = fields.Integer('Image Height')

    # Styling
    style_id = fields.Char('Style ID')

    # Summary (for boundary/grouping)
    summary_title = fields.Char('Summary Title')
    summary_edge_id = fields.Many2one('xmind.topic', 'Summary Edge')

    # Computed fields
    child_count = fields.Integer('Child Count', compute='_compute_child_count')
    depth = fields.Integer('Depth', compute='_compute_depth')
    full_path = fields.Char('Full Path', compute='_compute_full_path')

    @api.depends('child_ids')
    def _compute_child_count(self):
        for record in self:
            record.child_count = len(record.child_ids)

    @api.depends('parent_path')
    def _compute_depth(self):
        for record in self:
            if record.parent_path:
                record.depth = len(record.parent_path.split('/')) - 2
            else:
                record.depth = 0

    @api.depends('title', 'parent_id', 'parent_id.full_path')
    def _compute_full_path(self):
        for record in self:
            if record.parent_id and record.parent_id.full_path:
                record.full_path = f"{record.parent_id.full_path} / {record.title}"
            else:
                record.full_path = record.title

    @api.model
    def create(self, vals):
        if not vals.get('component_id'):
            vals['component_id'] = str(uuid.uuid4())
        return super().create(vals)

    def add_marker(self, marker_id):
        """Add a marker to this topic"""
        self.ensure_one()
        markers = json.loads(self.markers or '[]')
        if marker_id not in markers:
            markers.append(marker_id)
            self.markers = json.dumps(markers)

    def remove_marker(self, marker_id):
        """Remove a marker from this topic"""
        self.ensure_one()
        markers = json.loads(self.markers or '[]')
        if marker_id in markers:
            markers.remove(marker_id)
            self.markers = json.dumps(markers)

    def add_label(self, label):
        """Add a label to this topic"""
        self.ensure_one()
        labels = json.loads(self.labels or '[]')
        if label not in labels:
            labels.append(label)
            self.labels = json.dumps(labels)

    def remove_label(self, label):
        """Remove a label from this topic"""
        self.ensure_one()
        labels = json.loads(self.labels or '[]')
        if label in labels:
            labels.remove(label)
            self.labels = json.dumps(labels)

    def add_child_topic(self, title='New Topic'):
        """Add a child topic"""
        self.ensure_one()
        return self.create({
            'title': title,
            'parent_id': self.id,
            'sheet_id': self.sheet_id.id,
            'sequence': (max(self.child_ids.mapped('sequence') or [0]) + 10),
        })

    def get_ancestors(self):
        """Get all ancestor topics"""
        self.ensure_one()
        ancestors = self.env['xmind.topic']
        current = self.parent_id
        while current:
            ancestors |= current
            current = current.parent_id
        return ancestors

    def get_descendants(self):
        """Get all descendant topics (recursive children)"""
        self.ensure_one()
        descendants = self.env['xmind.topic']

        def collect_children(topic):
            nonlocal descendants
            for child in topic.child_ids:
                descendants |= child
                collect_children(child)

        collect_children(self)
        return descendants

    def to_dict(self):
        """Convert topic to dictionary (for JSON export)"""
        self.ensure_one()
        data = {
            'id': self.component_id,
            'title': self.title,
            'note': self.note or '',
            'markers': json.loads(self.markers or '[]'),
            'labels': json.loads(self.labels or '[]'),
            'position': {
                'x': self.position_x,
                'y': self.position_y,
            },
            'children': [child.to_dict() for child in self.child_ids.sorted('sequence')],
        }
        return data
