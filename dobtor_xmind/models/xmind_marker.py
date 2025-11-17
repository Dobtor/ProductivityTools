# -*- coding: utf-8 -*-
from odoo import api, fields, models


class XmindMarker(models.Model):
    _name = 'xmind.marker'
    _description = 'XMind Marker'
    _order = 'group_name, sequence'

    name = fields.Char('Name', required=True)
    marker_id = fields.Char('Marker ID', required=True,
                             help='XMind marker identifier')
    group_name = fields.Selection([
        ('priority', 'Priority'),
        ('smiley', 'Smiley'),
        ('task', 'Task'),
        ('flag', 'Flag'),
        ('star', 'Star'),
        ('people', 'People'),
        ('arrow', 'Arrow'),
        ('symbol', 'Symbol'),
        ('month', 'Month'),
        ('week', 'Week'),
        ('half', 'Half'),
        ('other', 'Other'),
    ], string='Group', required=True)

    icon_class = fields.Char('Icon Class', help='Font Awesome or custom icon class')
    color = fields.Char('Color', help='Marker color (hex)')
    sequence = fields.Integer('Sequence', default=10)
    active = fields.Boolean('Active', default=True)

    @api.model
    def get_markers_by_group(self, group_name=None):
        """Get markers organized by group"""
        domain = [('active', '=', True)]
        if group_name:
            domain.append(('group_name', '=', group_name))

        markers = self.search(domain, order='group_name, sequence')
        result = {}

        for marker in markers:
            if marker.group_name not in result:
                result[marker.group_name] = []
            result[marker.group_name].append({
                'id': marker.id,
                'marker_id': marker.marker_id,
                'name': marker.name,
                'icon_class': marker.icon_class,
                'color': marker.color,
            })

        return result

    @api.model
    def get_marker_choices(self):
        """Get all markers as selection choices for frontend"""
        markers = self.search([('active', '=', True)], order='group_name, sequence')
        return [(m.marker_id, f"{m.group_name}: {m.name}") for m in markers]
