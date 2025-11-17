# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields


class XMindBoundary(models.Model):
    """
    Boundary (Enclosure) - Groups topics visually with a border
    Like XMind 2's BoundaryPart
    """
    _name = 'xmind.boundary'
    _description = 'XMind Boundary'

    sheet_id = fields.Many2one('xmind.sheet', string='Sheet', ondelete='cascade', required=True)
    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()))

    title = fields.Char('Title')

    # Topics enclosed by this boundary
    topic_ids = fields.Many2many('xmind.topic', string='Enclosed Topics')

    # Styling
    fill_color = fields.Char('Fill Color', default='rgba(255, 255, 0, 0.2)')
    border_color = fields.Char('Border Color', default='#ffc107')
    border_width = fields.Integer('Border Width', default=2)
    border_style = fields.Selection([
        ('solid', 'Solid'),
        ('dashed', 'Dashed'),
        ('dotted', 'Dotted'),
    ], string='Border Style', default='solid')
    shape = fields.Selection([
        ('rect', 'Rectangle'),
        ('rounded', 'Rounded Rectangle'),
        ('wave', 'Wave'),
        ('scallops', 'Scallops'),
    ], string='Shape', default='rounded')


class XMindSummary(models.Model):
    """
    Summary - Summarizes multiple sibling topics with a bracket
    Like XMind 2's SummaryPart
    """
    _name = 'xmind.summary'
    _description = 'XMind Summary'

    sheet_id = fields.Many2one('xmind.sheet', string='Sheet', ondelete='cascade', required=True)
    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()))

    # Topics being summarized (must be siblings)
    topic_ids = fields.Many2many('xmind.topic', string='Summarized Topics')

    # The summary topic (conclusion)
    summary_topic_id = fields.Many2one('xmind.topic', string='Summary Topic', ondelete='cascade')

    # Styling
    line_color = fields.Char('Line Color', default='#666666')
    line_width = fields.Integer('Line Width', default=2)


class XMindCallout(models.Model):
    """
    Callout - A floating annotation attached to a topic
    Like XMind 2's floating topics with special connection
    """
    _name = 'xmind.callout'
    _description = 'XMind Callout'

    topic_id = fields.Many2one('xmind.topic', string='Parent Topic', ondelete='cascade', required=True)
    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()))

    title = fields.Char('Title', required=True)
    note = fields.Text('Content')

    # Position relative to parent (in pixels)
    offset_x = fields.Integer('Offset X', default=50)
    offset_y = fields.Integer('Offset Y', default=-30)

    # Styling
    background_color = fields.Char('Background Color', default='#fffacd')
    text_color = fields.Char('Text Color', default='#333333')
    border_color = fields.Char('Border Color', default='#ffd700')
    shape = fields.Selection([
        ('rect', 'Rectangle'),
        ('rounded', 'Rounded'),
        ('callout', 'Callout Bubble'),
    ], string='Shape', default='callout')


class XMindFloatingTopic(models.Model):
    """
    Floating Topic - Independent topic not connected to main tree
    Like XMind 2's detached topics
    """
    _name = 'xmind.floating.topic'
    _description = 'XMind Floating Topic'

    sheet_id = fields.Many2one('xmind.sheet', string='Sheet', ondelete='cascade', required=True)
    component_id = fields.Char('Component ID', default=lambda self: str(uuid.uuid4()))

    title = fields.Char('Title', required=True)
    note = fields.Text('Note')

    # Absolute position on canvas
    position_x = fields.Integer('Position X', default=100)
    position_y = fields.Integer('Position Y', default=100)

    # Styling (same as regular topics)
    background_color = fields.Char('Background Color', default='#e0e0e0')
    text_color = fields.Char('Text Color', default='#333333')
    font_size = fields.Integer('Font Size', default=14)
    font_weight = fields.Selection([
        ('normal', 'Normal'),
        ('bold', 'Bold'),
    ], string='Font Weight', default='normal')


class XMindAttachment(models.Model):
    """
    Attachment - File or image attached to a topic
    Like XMind 2's attachments and images
    """
    _name = 'xmind.attachment'
    _description = 'XMind Attachment'

    topic_id = fields.Many2one('xmind.topic', string='Topic', ondelete='cascade', required=True)

    name = fields.Char('Name', required=True)
    attachment_type = fields.Selection([
        ('file', 'File'),
        ('image', 'Image'),
        ('sticker', 'Sticker'),
    ], string='Type', default='file')

    file = fields.Binary('File', attachment=True)
    filename = fields.Char('Filename')

    # For stickers/images - display properties
    width = fields.Integer('Width', default=100)
    height = fields.Integer('Height', default=100)
    position = fields.Selection([
        ('above', 'Above Topic'),
        ('below', 'Below Topic'),
        ('left', 'Left of Topic'),
        ('right', 'Right of Topic'),
        ('inline', 'Inline'),
    ], string='Position', default='above')
