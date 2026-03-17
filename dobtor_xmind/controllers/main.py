# -*- coding: utf-8 -*-
import json
import uuid
from odoo import http, Command
from odoo.http import request
from odoo.exceptions import AccessError


class XMindController(http.Controller):

    def _check_workbook_access(self, workbook_id, mode='read'):
        """Validate workbook exists and user has access"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return None
        try:
            workbook.check_access_rights(mode)
            workbook.check_access_rule(mode)
        except AccessError:
            return None
        return workbook

    @http.route('/xmind/workbook/<int:workbook_id>/data', type='json', auth='user')
    def get_workbook_data(self, workbook_id, **kwargs):
        """Get mindmap data for visual editor"""
        workbook = self._check_workbook_access(workbook_id, 'read')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}

        return {
            'id': workbook.id,
            'name': workbook.name,
            'mindmap_data': workbook.get_mindmap_data(),
            'sheet_settings': self._get_sheet_settings(workbook),
            'relationships': self._get_relationships(workbook),
            'summaries': self._get_summaries(workbook),
            'boundaries': self._get_boundaries(workbook),
            'callouts': self._get_callouts(workbook),
            'floating_topics': self._get_floating_topics(workbook),
        }

    def _get_relationships(self, workbook):
        """Get relationship data for the first sheet"""
        if not workbook.sheet_ids:
            return []

        sheet = workbook.sheet_ids[0]
        result = []
        for rel in sheet.relationship_ids:
            if not rel.source_topic_id.component_id or not rel.target_topic_id.component_id:
                continue
            result.append({
                'sourceId': rel.source_topic_id.component_id,
                'targetId': rel.target_topic_id.component_id,
                'title': rel.title or '',
                'options': {
                    'shapeType': rel.line_type or 'curved',
                    'lineStyle': rel.line_style or 'dashed',
                    'lineColor': rel.line_color or '#999999',
                    'lineWidth': rel.line_width or 2,
                    'startMarker': rel.arrow_begin or 'none',
                    'endMarker': rel.arrow_end or 'arrow',
                    'markerSize': rel.arrow_size or 'medium',
                    'label': rel.title or '',
                },
                'controlPoints': [{'x': rel.control_point_x, 'y': rel.control_point_y}]
                    if rel.control_point_x or rel.control_point_y else [],
            })
        return result

    def _get_summaries(self, workbook):
        """Get summary data for the first sheet"""
        if not workbook.sheet_ids:
            return []

        sheet = workbook.sheet_ids[0]
        result = []
        for summary in sheet.summary_ids:
            topic_ids = summary.topic_ids.mapped('component_id')
            summary_topic_cid = summary.summary_topic_id.component_id if summary.summary_topic_id else ''
            if topic_ids and summary_topic_cid:
                result.append({
                    'topicIds': list(topic_ids),
                    'summaryNodeId': summary_topic_cid,
                    'options': {
                        'lineColor': summary.line_color or '#666666',
                        'lineWidth': summary.line_width or 2,
                    },
                })
        return result

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
            'spacing_major': sheet.spacing_major or 30,
            'spacing_minor': sheet.spacing_minor or 20,
            'line_corner': sheet.line_corner or 5,
            'branch_line_class': sheet.branch_line_class or 'curve',
        }

    def _get_boundaries(self, workbook):
        """Get boundary data for the first sheet"""
        if not workbook.sheet_ids:
            return []
        sheet = workbook.sheet_ids[0]
        result = []
        for b in sheet.boundary_ids:
            topic_ids = b.topic_ids.mapped('component_id')
            if topic_ids:
                result.append({
                    'topicIds': list(topic_ids),
                    'options': {
                        'shape': b.shape or 'rounded',
                        'fillColor': b.fill_color or 'rgba(195,214,155,0.2)',
                        'borderColor': b.border_color or '#77933C',
                        'borderWidth': b.border_width or 3,
                        'borderStyle': b.border_style or 'dotted',
                        'title': b.title or '',
                    },
                })
        return result

    def _get_callouts(self, workbook):
        """Get callout data for the first sheet"""
        if not workbook.sheet_ids:
            return []
        sheet = workbook.sheet_ids[0]
        result = []
        for c in self._get_sheet_callouts(sheet):
            result.append({
                'parentNodeId': c.topic_id.component_id,
                'options': {
                    'title': c.title,
                    'content': c.note or '',
                    'backgroundColor': c.background_color or '#fffacd',
                    'borderColor': c.border_color or '#ffd700',
                    'shape': c.shape or 'callout',
                    'offsetX': c.offset_x or 80,
                    'offsetY': c.offset_y or -50,
                },
            })
        return result

    def _get_sheet_callouts(self, sheet):
        """Get all callouts for topics in a sheet"""
        topics = sheet.topic_ids
        return request.env['xmind.callout'].search([('topic_id', 'in', topics.ids)])

    def _get_floating_topics(self, workbook):
        """Get floating topics for the first sheet"""
        if not workbook.sheet_ids:
            return []
        sheet = workbook.sheet_ids[0]
        return [{
            'id': ft.id,
            'component_id': ft.component_id,
            'title': ft.title,
            'note': ft.note or '',
            'x': ft.position_x,
            'y': ft.position_y,
            'style': {
                'background': ft.background_color or '#FFFFFF',
                'color': ft.text_color or '#303030',
                'fontSize': ft.font_size or 13,
                'fontWeight': ft.font_weight or 'normal',
            },
        } for ft in sheet.floating_topic_ids]

    @http.route('/xmind/workbook/<int:workbook_id>/floating_topics', type='json', auth='user')
    def save_floating_topics(self, workbook_id, floating_topics, **kwargs):
        """Save all floating topics (full replace)"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists() or not workbook.sheet_ids:
            return {'error': 'Workbook not found'}

        sheet = workbook.sheet_ids[0]
        # Clear existing
        sheet.floating_topic_ids.unlink()

        # Create new
        for ft in floating_topics:
            style = ft.get('style', {})
            request.env['xmind.floating.topic'].create({
                'sheet_id': sheet.id,
                'component_id': ft.get('component_id', str(uuid.uuid4())),
                'title': ft.get('title', 'Floating Topic'),
                'note': ft.get('note', ''),
                'position_x': int(ft.get('x', 100)),
                'position_y': int(ft.get('y', 100)),
                'background_color': style.get('background', '#FFFFFF'),
                'text_color': style.get('color', '#303030'),
                'font_size': int(style.get('fontSize', 13)),
                'font_weight': style.get('fontWeight', 'normal'),
            })
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/boundaries', type='json', auth='user')
    def save_boundaries(self, workbook_id, boundaries, **kwargs):
        """Save all boundaries (full replace)"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists() or not workbook.sheet_ids:
            return {'error': 'Workbook not found'}
        sheet = workbook.sheet_ids[0]
        sheet.boundary_ids.unlink()

        for b in boundaries:
            opts = b.get('options', {})
            topic_ids = []
            for cid in b.get('topicIds', []):
                t = request.env['xmind.topic'].search([
                    ('sheet_id', '=', sheet.id), ('component_id', '=', cid)
                ], limit=1)
                if t:
                    topic_ids.append(t.id)
            if topic_ids:
                request.env['xmind.boundary'].create({
                    'sheet_id': sheet.id,
                    'title': opts.get('title', ''),
                    'shape': opts.get('shape', 'rounded'),
                    'fill_color': opts.get('fillColor', 'rgba(195,214,155,0.2)'),
                    'border_color': opts.get('borderColor', '#77933C'),
                    'border_width': opts.get('borderWidth', 3),
                    'border_style': opts.get('borderStyle', 'dotted'),
                    'topic_ids': [Command.set(topic_ids)],
                })
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/summaries/save', type='json', auth='user')
    def save_summaries(self, workbook_id, summaries, **kwargs):
        """Save all summaries (full replace)"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists() or not workbook.sheet_ids:
            return {'error': 'Workbook not found'}
        sheet = workbook.sheet_ids[0]
        sheet.summary_ids.unlink()

        for s in summaries:
            opts = s.get('options', {})
            topic_ids = []
            for cid in s.get('topicIds', []):
                t = request.env['xmind.topic'].search([
                    ('sheet_id', '=', sheet.id), ('component_id', '=', cid)
                ], limit=1)
                if t:
                    topic_ids.append(t.id)
            summary_topic = None
            if s.get('summaryNodeId'):
                summary_topic = request.env['xmind.topic'].search([
                    ('sheet_id', '=', sheet.id), ('component_id', '=', s['summaryNodeId'])
                ], limit=1)
            if topic_ids:
                request.env['xmind.summary'].create({
                    'sheet_id': sheet.id,
                    'summary_topic_id': summary_topic.id if summary_topic else False,
                    'topic_ids': [Command.set(topic_ids)],
                    'line_color': opts.get('lineColor', '#C3D69B'),
                    'line_width': opts.get('lineWidth', 5),
                })
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/callouts', type='json', auth='user')
    def save_callouts(self, workbook_id, callouts, **kwargs):
        """Save all callouts (full replace)"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists() or not workbook.sheet_ids:
            return {'error': 'Workbook not found'}
        sheet = workbook.sheet_ids[0]
        # Clear existing callouts for all topics in sheet
        existing = request.env['xmind.callout'].search([
            ('topic_id', 'in', sheet.topic_ids.ids)
        ])
        existing.unlink()

        for c in callouts:
            opts = c.get('options', {})
            parent_cid = c.get('parentNodeId', '')
            if parent_cid:
                topic = request.env['xmind.topic'].search([
                    ('sheet_id', '=', sheet.id), ('component_id', '=', parent_cid)
                ], limit=1)
                if topic:
                    request.env['xmind.callout'].create({
                        'topic_id': topic.id,
                        'title': opts.get('title', 'Note'),
                        'note': opts.get('content', ''),
                        'background_color': opts.get('backgroundColor', '#fffacd'),
                        'border_color': opts.get('borderColor', '#ffd700'),
                        'shape': opts.get('shape', 'callout'),
                        'offset_x': opts.get('offsetX', 80),
                        'offset_y': opts.get('offsetY', -50),
                    })
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/save', type='json', auth='user')
    def save_workbook_data(self, workbook_id, data, **kwargs):
        """Save mindmap data from visual editor"""
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}

        workbook.save_mindmap_data(data)
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/settings', type='json', auth='user')
    def save_sheet_settings(self, workbook_id, settings, **kwargs):
        """Save sheet layout and theme settings"""
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}

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
                options = rel.get('options', {})
                control_points = rel.get('controlPoints', [])
                cp = control_points[0] if control_points else {}
                request.env['xmind.relationship'].create({
                    'sheet_id': sheet.id,
                    'source_topic_id': source.id,
                    'target_topic_id': target.id,
                    'title': options.get('label', '') or rel.get('title', ''),
                    'line_type': options.get('shapeType', 'curved'),
                    'line_style': options.get('lineStyle', 'dashed'),
                    'line_color': options.get('lineColor', '#999999'),
                    'line_width': options.get('lineWidth', 2),
                    'arrow_begin': options.get('startMarker', 'none'),
                    'arrow_end': options.get('endMarker', 'arrow'),
                    'arrow_size': options.get('markerSize', 'medium'),
                    'control_point_x': cp.get('x', 0),
                    'control_point_y': cp.get('y', 0),
                })

        return {'success': True}

    @http.route('/xmind/markers', type='json', auth='user')
    def get_markers(self, **kwargs):
        """Get available markers (excluding hidden ones from picker)"""
        markers = request.env['xmind.marker'].search([('hidden', '=', False)])
        return [{
            'id': m.id,
            'name': m.name,
            'code': m.code,
            'category': m.category,
            'icon': m.icon,
            'color': m.color,
        } for m in markers]

    @http.route('/xmind/workbook/<int:workbook_id>/revisions', type='json', auth='user')
    def get_revisions(self, workbook_id, **kwargs):
        """List revision history for a workbook"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return {'error': 'Workbook not found'}

        return [{
            'id': r.id,
            'name': r.name,
            'date': r.create_date.strftime('%Y-%m-%d %H:%M:%S') if r.create_date else '',
            'user': r.user_id.name or '',
            'topic_count': r.topic_count,
            'is_auto': r.is_auto,
        } for r in workbook.revision_ids[:30]]

    @http.route('/xmind/workbook/<int:workbook_id>/revisions/<int:revision_id>/restore', type='json', auth='user')
    def restore_revision(self, workbook_id, revision_id, **kwargs):
        """Restore a specific revision"""
        revision = request.env['xmind.revision'].browse(revision_id)
        if not revision.exists() or revision.workbook_id.id != workbook_id:
            return {'error': 'Revision not found'}

        revision.action_restore()
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/revisions/<int:revision_id>/preview', type='json', auth='user')
    def preview_revision(self, workbook_id, revision_id, **kwargs):
        """Get snapshot data for preview"""
        revision = request.env['xmind.revision'].browse(revision_id)
        if not revision.exists() or revision.workbook_id.id != workbook_id:
            return {'error': 'Revision not found'}

        return {'data': json.loads(revision.snapshot)}

    # ===== Multi-Sheet Management Endpoints =====

    @http.route('/xmind/workbook/<int:workbook_id>/sheets', type='json', auth='user')
    def get_sheets(self, workbook_id, **kwargs):
        """List all sheets in a workbook"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return {'sheets': []}
        return {
            'sheets': [{
                'id': s.id,
                'name': s.name,
                'sequence': s.sequence,
            } for s in workbook.sheet_ids.sorted('sequence')]
        }

    @http.route('/xmind/workbook/<int:workbook_id>/sheet/create', type='json', auth='user')
    def create_sheet(self, workbook_id, name, **kwargs):
        """Create a new sheet"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return {'error': 'Workbook not found'}
        sheet = request.env['xmind.sheet'].create({
            'workbook_id': workbook.id,
            'name': name,
            'sequence': len(workbook.sheet_ids) * 10 + 10,
        })
        # Create root topic
        request.env['xmind.topic'].create({
            'sheet_id': sheet.id,
            'title': name,
            'component_id': str(uuid.uuid4()),
        })
        return {'success': True, 'sheet_id': sheet.id}

    @http.route('/xmind/workbook/<int:workbook_id>/sheet/<int:sheet_id>/data', type='json', auth='user')
    def get_sheet_data(self, workbook_id, sheet_id, **kwargs):
        """Get mindmap data for a specific sheet"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        sheet = request.env['xmind.sheet'].browse(sheet_id)
        if not workbook.exists() or not sheet.exists() or sheet.workbook_id.id != workbook_id:
            return {'error': 'Sheet not found'}

        root = sheet.topic_ids.filtered(lambda t: not t.parent_id)[:1]
        if root:
            mindmap_data = {
                'meta': {'name': sheet.name, 'author': '', 'version': '1.0'},
                'format': 'node_tree',
                'data': workbook._topic_to_jsmind(root),
            }
        else:
            mindmap_data = {
                'meta': {'name': sheet.name, 'author': '', 'version': '1.0'},
                'format': 'node_tree',
                'data': {'id': 'root', 'topic': sheet.name, 'expanded': True, 'children': [], 'data': {}},
            }
        return {
            'mindmap_data': mindmap_data,
            'name': sheet.name,
            'sheet_settings': {
                'layout': sheet.layout_type or 'map',
                'theme': sheet.theme or 'primary',
            },
        }

    @http.route('/xmind/workbook/<int:workbook_id>/sheet/<int:sheet_id>/rename', type='json', auth='user')
    def rename_sheet(self, workbook_id, sheet_id, name, **kwargs):
        """Rename a sheet"""
        sheet = request.env['xmind.sheet'].browse(sheet_id)
        if not sheet.exists() or sheet.workbook_id.id != workbook_id:
            return {'error': 'Sheet not found'}
        sheet.write({'name': name})
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/sheet/<int:sheet_id>/delete', type='json', auth='user')
    def delete_sheet(self, workbook_id, sheet_id, **kwargs):
        """Delete a sheet"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        sheet = request.env['xmind.sheet'].browse(sheet_id)
        if not sheet.exists() or sheet.workbook_id.id != workbook_id:
            return {'error': 'Sheet not found'}
        if len(workbook.sheet_ids) <= 1:
            return {'error': 'Cannot delete the last sheet'}
        sheet.unlink()
        return {'success': True}
