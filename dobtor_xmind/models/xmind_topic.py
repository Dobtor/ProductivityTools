# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields, api


class XMindTopic(models.Model):
    _name = 'xmind.topic'
    _description = 'XMind Topic'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'parent_path, sequence'

    name = fields.Char('Name', related='title', store=True)
    title = fields.Char('Title', required=True)
    sequence = fields.Integer('Sequence', default=10)

    sheet_id = fields.Many2one('xmind.sheet', string='Sheet', ondelete='cascade', required=True)
    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()), index=True)

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
        ('rectangle', 'Rectangle'),
        ('rounded', 'Rounded Rectangle'),
        ('ellipse', 'Ellipse'),
        ('circle', 'Circle'),
        ('underline', 'Underline'),
        ('diamond', 'Diamond'),
        ('parallelogram', 'Parallelogram'),
        ('hexagon', 'Hexagon'),
        ('cloud', 'Cloud'),
        ('noBorder', 'No Border'),
        ('fishhead_left', 'Fishhead Left'),
        ('fishhead_right', 'Fishhead Right'),
        ('stroke', 'Stroke Circle'),
    ], string='Shape', default='rounded')
    font_family = fields.Char('Font Family')
    font_style = fields.Selection([
        ('normal', 'Normal'),
        ('italic', 'Italic'),
    ], string='Font Style', default='normal')
    text_decoration = fields.Char('Text Decoration')
    text_align = fields.Selection([
        ('left', 'Left'),
        ('center', 'Center'),
        ('right', 'Right'),
    ], string='Text Alignment', default='left')

    # Branch connection line style
    line_type = fields.Char('Connection Line Type')  # curved, straight, roundedElbow, angular, none
    line_color = fields.Char('Connection Line Color')
    line_width = fields.Integer('Connection Line Width', default=0)  # 0 = inherit from theme
    line_style = fields.Char('Connection Line Pattern')  # solid, dashed, dotted
    # True when the user deliberately picked a branch line type in the panel, so the
    # renderer honours it over the layout-mode default (even when chosen type == default).
    line_type_explicit = fields.Boolean('Line Type Explicitly Set', default=False)

    # Per-topic child numbering format (none / 1 / a / A / i / I / 1.1)
    numbering = fields.Char('Numbering Format')

    # Stable link to the project.task this topic syncs with (1:1, map ⇄ project).
    task_id = fields.Many2one('project.task', string='Project Task',
                              ondelete='set null', index=True, copy=False)

    # Structure
    structure_class = fields.Char('Structure Class', default='')
    right_number = fields.Integer('Right Number', default=-2)  # -2=not set, -1=all right, N=first N go right
    is_summary_node = fields.Boolean('Is Summary Node', default=False)

    # Markers
    marker_ids = fields.One2many('xmind.topic.marker', 'topic_id', string='Markers')

    # Task Info (XMind 8 "Task Information")
    task_start_date = fields.Date('Task Start')
    task_end_date = fields.Date('Task End')
    task_progress = fields.Integer('Progress %', default=0)  # 0..100
    task_assignee = fields.Char('Assignee')
    has_task = fields.Boolean('Has Task Info', compute='_compute_has_task', store=True)

    # Computed fields
    level = fields.Integer('Level', compute='_compute_level', store=True)
    has_children = fields.Boolean('Has Children', compute='_compute_has_children', store=True)

    @api.depends('task_start_date', 'task_end_date', 'task_progress', 'task_assignee')
    def _compute_has_task(self):
        for record in self:
            record.has_task = bool(
                record.task_start_date or record.task_end_date
                or record.task_progress or record.task_assignee
            )

    def write(self, vals):
        res = super().write(vals)
        if 'title' in vals and not self.env.context.get('_syncing_name'):
            for record in self:
                if record.parent_id:
                    continue
                workbook = record.sheet_id.workbook_id
                if not workbook:
                    continue
                first_sheet = workbook.sheet_ids[:1]
                if first_sheet and record.sheet_id == first_sheet:
                    workbook.with_context(_syncing_name=True).write(
                        {'name': vals['title']}
                    )
        return res

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
