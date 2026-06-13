# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class XMindRelationship(models.Model):
    _name = 'xmind.relationship'
    _description = 'Mind Map Relationship'

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
    line_color = fields.Char('Line Color', default='#77933C')
    line_width = fields.Integer('Line Width', default=3)
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
    cp0_x = fields.Float('Control Point 0 X')
    cp0_y = fields.Float('Control Point 0 Y')
    cp1_x = fields.Float('Control Point 1 X')
    cp1_y = fields.Float('Control Point 1 Y')
    cp_is_relative = fields.Boolean('CPs are Relative Offsets', default=False)

    @api.constrains('source_topic_id', 'target_topic_id', 'sheet_id')
    def _check_endpoints(self):
        for rel in self:
            if rel.source_topic_id and rel.source_topic_id == rel.target_topic_id:
                raise ValidationError(
                    "A relationship cannot connect a topic to itself.")
            for endpoint in (rel.source_topic_id, rel.target_topic_id):
                if endpoint and endpoint.sheet_id != rel.sheet_id:
                    raise ValidationError(
                        "Relationship endpoints must belong to the same sheet "
                        "as the relationship.")
