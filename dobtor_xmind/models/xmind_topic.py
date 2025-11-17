# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields, api


class XMindTopic(models.Model):
    _name = 'xmind.topic'
    _description = 'XMind Topic'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'parent_path, sequence'

    name = fields.Char('Name', compute='_compute_name', store=True)
    title = fields.Char('Title', required=True)
    sequence = fields.Integer('Sequence', default=10)

    sheet_id = fields.Many2one('xmind.sheet', string='Sheet', ondelete='cascade', required=True)
    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()))

    # Hierarchy
    parent_id = fields.Many2one('xmind.topic', string='Parent Topic', ondelete='cascade', index=True)
    child_ids = fields.One2many('xmind.topic', 'parent_id', string='Child Topics')
    parent_path = fields.Char(index=True)

    # Display
    expanded = fields.Boolean('Expanded', default=True)

    # Content
    note = fields.Text('Note')
    labels = fields.Char('Labels (comma separated)')
    hyperlink = fields.Char('Hyperlink')
    hyperlink_title = fields.Char('Hyperlink Title')

    # Attachments
    attachment_ids = fields.One2many('xmind.attachment', 'topic_id', string='Attachments')
    has_attachment = fields.Boolean('Has Attachment', compute='_compute_has_attachment', store=True)
    has_note = fields.Boolean('Has Note', compute='_compute_has_note', store=True)
    has_hyperlink = fields.Boolean('Has Hyperlink', compute='_compute_has_hyperlink', store=True)

    @api.depends('attachment_ids')
    def _compute_has_attachment(self):
        for record in self:
            record.has_attachment = bool(record.attachment_ids)

    @api.depends('note')
    def _compute_has_note(self):
        for record in self:
            record.has_note = bool(record.note and record.note.strip())

    @api.depends('hyperlink')
    def _compute_has_hyperlink(self):
        for record in self:
            record.has_hyperlink = bool(record.hyperlink and record.hyperlink.strip())

    # Styling (XMind 2 features)
    background_color = fields.Char('Background Color')
    text_color = fields.Char('Text Color')
    font_size = fields.Integer('Font Size', default=14)
    font_weight = fields.Selection([
        ('normal', 'Normal'),
        ('bold', 'Bold'),
    ], string='Font Weight', default='normal')
    border_color = fields.Char('Border Color')
    border_width = fields.Integer('Border Width', default=1)
    shape = fields.Selection([
        ('rect', 'Rectangle'),
        ('rounded', 'Rounded Rectangle'),
        ('ellipse', 'Ellipse'),
        ('underline', 'Underline'),
    ], string='Shape', default='rounded')

    # Structure
    structure_class = fields.Char('Structure Class', default='org.xmind.ui.map.unbalanced')

    # Markers
    marker_ids = fields.One2many('xmind.topic.marker', 'topic_id', string='Markers')

    # Computed fields
    level = fields.Integer('Level', compute='_compute_level', store=True)
    has_children = fields.Boolean('Has Children', compute='_compute_has_children', store=True)

    @api.depends('title')
    def _compute_name(self):
        for record in self:
            record.name = record.title

    @api.depends('parent_path')
    def _compute_level(self):
        for record in self:
            if record.parent_path:
                record.level = record.parent_path.count('/') - 1
            else:
                record.level = 0

    @api.depends('child_ids')
    def _compute_has_children(self):
        for record in self:
            record.has_children = bool(record.child_ids)


class XMindTopicMarker(models.Model):
    _name = 'xmind.topic.marker'
    _description = 'Topic Marker Assignment'

    topic_id = fields.Many2one('xmind.topic', string='Topic', ondelete='cascade', required=True)
    marker_id = fields.Many2one('xmind.marker', string='Marker', ondelete='cascade', required=True)
