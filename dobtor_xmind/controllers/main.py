# -*- coding: utf-8 -*-
import json
from odoo import http
from odoo.http import request


class XMindController(http.Controller):

    @http.route('/xmind/workbook/<int:workbook_id>/data', type='json', auth='user')
    def get_workbook_data(self, workbook_id, **kwargs):
        """Get mindmap data for visual editor"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return {'error': 'Workbook not found'}

        return {
            'id': workbook.id,
            'name': workbook.name,
            'mindmap_data': workbook.get_mindmap_data(),
            'sheet_settings': self._get_sheet_settings(workbook),
        }

    def _get_sheet_settings(self, workbook):
        """Get sheet layout and theme settings"""
        if not workbook.sheet_ids:
            return {
                'layout': 'map',
                'theme': 'primary',
            }

        sheet = workbook.sheet_ids[0]
        return {
            'layout': sheet.layout_type or 'map',
            'theme': sheet.theme or 'primary',
        }

    @http.route('/xmind/workbook/<int:workbook_id>/save', type='json', auth='user')
    def save_workbook_data(self, workbook_id, data, **kwargs):
        """Save mindmap data from visual editor"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return {'error': 'Workbook not found'}

        workbook.save_mindmap_data(data)
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/settings', type='json', auth='user')
    def save_sheet_settings(self, workbook_id, settings, **kwargs):
        """Save sheet layout and theme settings"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return {'error': 'Workbook not found'}

        if not workbook.sheet_ids:
            request.env['xmind.sheet'].create({
                'workbook_id': workbook.id,
                'name': workbook.name,
                'layout_type': settings.get('layout', 'map'),
                'theme': settings.get('theme', 'primary'),
            })
        else:
            workbook.sheet_ids[0].write({
                'layout_type': settings.get('layout', 'map'),
                'theme': settings.get('theme', 'primary'),
            })

        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/relationships', type='json', auth='user')
    def save_relationships(self, workbook_id, relationships, **kwargs):
        """Save relationship lines between topics"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists() or not workbook.sheet_ids:
            return {'error': 'Workbook or sheet not found'}

        sheet = workbook.sheet_ids[0]

        # Clear existing relationships
        sheet.relationship_ids.unlink()

        # Create new relationships
        for rel in relationships:
            source = request.env['xmind.topic'].search([
                ('sheet_id', '=', sheet.id),
                ('component_id', '=', rel.get('source_id'))
            ], limit=1)
            target = request.env['xmind.topic'].search([
                ('sheet_id', '=', sheet.id),
                ('component_id', '=', rel.get('target_id'))
            ], limit=1)

            if source and target:
                request.env['xmind.relationship'].create({
                    'sheet_id': sheet.id,
                    'source_topic_id': source.id,
                    'target_topic_id': target.id,
                    'title': rel.get('title', ''),
                    'line_type': rel.get('line_type', 'curved'),
                    'line_color': rel.get('line_color', '#999999'),
                    'line_width': rel.get('line_width', 2),
                })

        return {'success': True}

    @http.route('/xmind/markers', type='json', auth='user')
    def get_markers(self, **kwargs):
        """Get available markers"""
        markers = request.env['xmind.marker'].search([])
        return [{
            'id': m.id,
            'name': m.name,
            'code': m.code,
            'category': m.category,
            'icon': m.icon,
            'color': m.color,
        } for m in markers]
