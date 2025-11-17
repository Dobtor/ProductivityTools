# -*- coding: utf-8 -*-
import json
import base64
from odoo import http
from odoo.http import request


class XmindController(http.Controller):

    @http.route('/xmind/workbook/<int:workbook_id>/data', type='json', auth='user')
    def get_workbook_data(self, workbook_id, **kw):
        """Get mindmap data for frontend editor"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return {'error': 'Workbook not found'}

        return workbook.get_mindmap_data()

    @http.route('/xmind/workbook/<int:workbook_id>/save', type='json', auth='user')
    def save_workbook_data(self, workbook_id, data, **kw):
        """Save mindmap data from frontend editor"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return {'error': 'Workbook not found'}

        success = workbook.save_mindmap_data(data)
        return {'success': success}

    @http.route('/xmind/export/<int:workbook_id>', type='http', auth='user')
    def export_xmind_file(self, workbook_id, **kw):
        """Export workbook as .xmind file"""
        workbook = request.env['xmind.workbook'].browse(workbook_id)
        if not workbook.exists():
            return request.not_found()

        # Generate the file
        import zipfile
        from io import BytesIO

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            content = workbook._generate_xmind_content()
            zf.writestr('content.json', json.dumps(content, indent=2))

            manifest = {
                'file-entries': {
                    'content.json': {},
                    'metadata.json': {},
                }
            }
            zf.writestr('manifest.json', json.dumps(manifest, indent=2))

            metadata = {
                'creator': {
                    'name': 'Odoo XMind Editor',
                    'version': '14.0.1.0.0'
                }
            }
            zf.writestr('metadata.json', json.dumps(metadata, indent=2))

        buffer.seek(0)
        file_content = buffer.read()

        filename = f'{workbook.name}.xmind'
        return request.make_response(
            file_content,
            headers=[
                ('Content-Type', 'application/x-xmind'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
                ('Content-Length', len(file_content)),
            ]
        )

    @http.route('/xmind/import', type='http', auth='user', methods=['POST'], csrf=False)
    def import_xmind_file(self, **kw):
        """Import .xmind file"""
        file = kw.get('file')
        if not file:
            return json.dumps({'error': 'No file uploaded'})

        try:
            file_data = base64.b64encode(file.read())
            workbook = request.env['xmind.workbook'].import_from_xmind(file_data)
            return json.dumps({
                'success': True,
                'workbook_id': workbook.id,
                'workbook_name': workbook.name,
            })
        except Exception as e:
            return json.dumps({'error': str(e)})

    @http.route('/xmind/markers', type='json', auth='user')
    def get_markers(self, **kw):
        """Get all available markers"""
        return request.env['xmind.marker'].get_markers_by_group()

    @http.route('/xmind/topic/<int:topic_id>/add_child', type='json', auth='user')
    def add_child_topic(self, topic_id, title='New Topic', **kw):
        """Add a child topic"""
        topic = request.env['xmind.topic'].browse(topic_id)
        if not topic.exists():
            return {'error': 'Topic not found'}

        child = topic.add_child_topic(title)
        return {
            'success': True,
            'topic_id': child.id,
            'component_id': child.component_id,
        }

    @http.route('/xmind/topic/<int:topic_id>/update', type='json', auth='user')
    def update_topic(self, topic_id, values, **kw):
        """Update topic properties"""
        topic = request.env['xmind.topic'].browse(topic_id)
        if not topic.exists():
            return {'error': 'Topic not found'}

        allowed_fields = ['title', 'note', 'markers', 'labels', 'position_x', 'position_y']
        update_vals = {k: v for k, v in values.items() if k in allowed_fields}

        topic.write(update_vals)
        return {'success': True}

    @http.route('/xmind/topic/<int:topic_id>/delete', type='json', auth='user')
    def delete_topic(self, topic_id, **kw):
        """Delete a topic and its children"""
        topic = request.env['xmind.topic'].browse(topic_id)
        if not topic.exists():
            return {'error': 'Topic not found'}

        if topic.is_root:
            return {'error': 'Cannot delete root topic'}

        topic.unlink()
        return {'success': True}
