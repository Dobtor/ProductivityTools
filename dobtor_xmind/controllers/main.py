# -*- coding: utf-8 -*-
import json
import uuid
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError, AccessError


class MindMapController(http.Controller):

    def _check_workbook_access(self, workbook_id, mode='read'):
        """Validate workbook exists and the current user has ``mode`` access.

        Uses the Odoo 18 unified ``check_access`` API (the legacy
        ``check_access_rights`` / ``check_access_rule`` pair is deprecated since
        18.0). Returns the workbook recordset or ``None`` when missing/denied.
        """
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return None
        if not workbook.has_access(mode):
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
            'project': {
                'id': workbook.project_id.id,
                'name': workbook.project_id.name,
                'last_sync_direction': workbook.xmind_last_sync_direction,
            } if workbook.project_id else False,
            'partner': {
                'id': workbook.partner_id.id,
                'name': workbook.partner_id.name,
            } if workbook.partner_id else False,
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
                    'lineColor': rel.line_color or '#77933C',
                    'lineWidth': rel.line_width or 3,
                    'startMarker': rel.arrow_begin or 'none',
                    'endMarker': rel.arrow_end or 'arrow',
                    'markerSize': rel.arrow_size or 'medium',
                    'label': rel.title or '',
                    'labelFontSize': 10,
                    'labelColor': '#595959',
                    'labelItalic': True,
                    'labelBold': False,
                },
                'controlPoints': self._build_control_points(rel),
                'cpIsRelativeOffset': rel.cp_is_relative,
            })
        return result

    def _build_control_points(self, rel):
        """Build control points list from relationship record"""
        cps = []
        if rel.cp0_x or rel.cp0_y:
            cps.append({'x': rel.cp0_x, 'y': rel.cp0_y})
        if rel.cp1_x or rel.cp1_y:
            cps.append({'x': rel.cp1_x, 'y': rel.cp1_y})
        return cps

    def _get_summaries(self, workbook):
        """Get summary data for the first sheet"""
        if not workbook.sheet_ids:
            return []

        sheet = workbook.sheet_ids[0]
        result = []
        for summary in sheet.summary_ids:
            topic_ids = summary.topic_ids.mapped('component_id')
            if topic_ids:
                result.append({
                    'topicIds': list(topic_ids),
                    'summaryNodeId': summary.summary_topic_id.component_id if summary.summary_topic_id else '',
                    'options': {
                        'lineType': summary.line_type or 'square',
                        'lineColor': summary.line_color or '#C3D69B',
                        'lineWidth': summary.line_width or 5,
                        'summaryTitle': summary.title or 'Summary',
                        'summaryFill': summary.fill_color or '#77933C',
                        'summaryColor': summary.text_color or '#FFFFFF',
                        'summaryFontSize': summary.font_size or 10,
                        'summaryItalic': summary.font_italic,
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
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook or not workbook.sheet_ids:
            return {'error': 'Workbook not found or access denied'}
        workbook._replace_floating_topics(workbook.sheet_ids[0], floating_topics)
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/boundaries', type='json', auth='user')
    def save_boundaries(self, workbook_id, boundaries, **kwargs):
        """Save all boundaries (full replace)"""
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook or not workbook.sheet_ids:
            return {'error': 'Workbook not found or access denied'}
        workbook._replace_boundaries(workbook.sheet_ids[0], boundaries)
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/summaries/save', type='json', auth='user')
    def save_summaries(self, workbook_id, summaries, **kwargs):
        """Save all summaries (full replace)"""
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook or not workbook.sheet_ids:
            return {'error': 'Workbook not found or access denied'}
        workbook._replace_summaries(workbook.sheet_ids[0], summaries)
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/callouts', type='json', auth='user')
    def save_callouts(self, workbook_id, callouts, **kwargs):
        """Save all callouts (full replace)"""
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook or not workbook.sheet_ids:
            return {'error': 'Workbook not found or access denied'}
        workbook._replace_callouts(workbook.sheet_ids[0], callouts)
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/save', type='json', auth='user')
    def save_workbook_data(self, workbook_id, data, is_auto=False, **kwargs):
        """Save mindmap data from visual editor"""
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}

        workbook.save_mindmap_data(data, is_auto=bool(is_auto))
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/project_sync', type='json', auth='user')
    def project_sync(self, workbook_id, create=False, confirmed=False, **kwargs):
        """Create (if needed) and sync this mind map into a project + its tasks.
        When the sync would archive tasks, ask the client to confirm first."""
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}
        if not confirmed:
            try:
                orphans = workbook._plan_project_orphans()
            except AccessError:
                orphans = None
            if orphans:
                return {
                    'needs_confirm': True,
                    'archive_count': len(orphans),
                    'archive_names': orphans.mapped('name')[:20],
                }
        try:
            stats = workbook._sync_to_project(create_if_missing=bool(create) or not workbook.project_id)
        except AccessError:
            return {'error': "You don't have the rights to create or edit projects/tasks."}
        except UserError as e:
            return {'error': e.args[0] if e.args else str(e)}
        stats['success'] = True
        return stats

    @http.route('/xmind/workbook/<int:workbook_id>/thumbnail', type='json', auth='user')
    def save_thumbnail(self, workbook_id, thumbnail, **kwargs):
        """Save mind map thumbnail image (base64 PNG)"""
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}
        # thumbnail is base64 data URL: "data:image/png;base64,..."
        import base64
        import binascii
        if not thumbnail or not isinstance(thumbnail, str):
            return {'error': 'Invalid thumbnail'}
        if ',' in thumbnail:
            thumbnail = thumbnail.split(',', 1)[1]
        # Reject oversized payloads (~4 MB of base64) and non-base64 content so a
        # malformed/huge client value can't raise an uncaught 500 or bloat the row.
        if len(thumbnail) > 4 * 1024 * 1024:
            return {'error': 'Thumbnail too large'}
        try:
            base64.b64decode(thumbnail, validate=True)
        except (binascii.Error, ValueError):
            return {'error': 'Invalid thumbnail encoding'}
        workbook.write({'thumbnail': thumbnail})
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
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook or not workbook.sheet_ids:
            return {'error': 'Workbook or sheet not found or access denied'}
        workbook._replace_relationships(workbook.sheet_ids[0], relationships)
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
            'short_label': m.short_label or '',
            'color': m.color,
        } for m in markers]

    @http.route('/xmind/workbook/<int:workbook_id>/revisions', type='json', auth='user')
    def get_revisions(self, workbook_id, **kwargs):
        """List revision history for a workbook"""
        workbook = self._check_workbook_access(workbook_id, 'read')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}

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
        # Restoring rewrites the whole workbook → require write access first.
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}
        revision = request.env['xmind.revision'].browse(revision_id)
        if not revision.exists() or revision.workbook_id.id != workbook_id:
            return {'error': 'Revision not found'}

        revision.action_restore()
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/revisions/<int:revision_id>/preview', type='json', auth='user')
    def preview_revision(self, workbook_id, revision_id, **kwargs):
        """Get snapshot data for preview"""
        workbook = self._check_workbook_access(workbook_id, 'read')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}
        revision = request.env['xmind.revision'].browse(revision_id)
        if not revision.exists() or revision.workbook_id.id != workbook_id:
            return {'error': 'Revision not found'}
        try:
            return {'data': json.loads(revision.snapshot or '{}')}
        except (ValueError, TypeError):
            return {'error': 'Corrupted revision snapshot'}

    # ===== Multi-Sheet Management Endpoints =====

    @http.route('/xmind/workbook/<int:workbook_id>/sheets', type='json', auth='user')
    def get_sheets(self, workbook_id, **kwargs):
        """List all sheets in a workbook"""
        workbook = self._check_workbook_access(workbook_id, 'read')
        if not workbook:
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
        workbook = self._check_workbook_access(workbook_id, 'write')
        if not workbook:
            return {'error': 'Workbook not found or access denied'}
        # Derive the next sequence from the current max (not the count) so a
        # previously-deleted sheet can't cause a sequence collision.
        max_seq = max(workbook.sheet_ids.mapped('sequence') or [0])
        sheet = request.env['xmind.sheet'].create({
            'workbook_id': workbook.id,
            'name': name,
            'sequence': max_seq + 10,
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
        workbook = self._check_workbook_access(workbook_id, 'read')
        sheet = request.env['xmind.sheet'].browse(sheet_id)
        if not workbook or not sheet.exists() or sheet.workbook_id.id != workbook_id:
            return {'error': 'Sheet not found or access denied'}

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
        workbook = self._check_workbook_access(workbook_id, 'write')
        sheet = request.env['xmind.sheet'].browse(sheet_id)
        if not workbook or not sheet.exists() or sheet.workbook_id.id != workbook_id:
            return {'error': 'Sheet not found or access denied'}
        sheet.write({'name': name})
        return {'success': True}

    @http.route('/xmind/workbook/<int:workbook_id>/sheet/<int:sheet_id>/delete', type='json', auth='user')
    def delete_sheet(self, workbook_id, sheet_id, **kwargs):
        """Delete a sheet"""
        workbook = self._check_workbook_access(workbook_id, 'write')
        sheet = request.env['xmind.sheet'].browse(sheet_id)
        if not workbook or not sheet.exists() or sheet.workbook_id.id != workbook_id:
            return {'error': 'Sheet not found or access denied'}
        if len(workbook.sheet_ids) <= 1:
            return {'error': 'Cannot delete the last sheet'}
        sheet.unlink()
        return {'success': True}
