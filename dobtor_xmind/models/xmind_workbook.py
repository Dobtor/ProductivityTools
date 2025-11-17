# -*- coding: utf-8 -*-
import base64
import json
import zipfile
import io
import uuid
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class XMindWorkbook(models.Model):
    _name = 'xmind.workbook'
    _description = 'XMind Workbook'
    _order = 'write_date desc'

    name = fields.Char('Name', required=True, default='New Mind Map')
    description = fields.Text('Description')
    creator = fields.Char('Creator')
    created_time = fields.Datetime('Created Time', default=fields.Datetime.now)
    modified_time = fields.Datetime('Modified Time')

    sheet_ids = fields.One2many('xmind.sheet', 'workbook_id', string='Sheets')

    # File import/export
    xmind_file = fields.Binary('XMind File', attachment=True)
    xmind_filename = fields.Char('Filename')

    # Thumbnail
    thumbnail = fields.Binary('Thumbnail', attachment=True)

    # Statistics
    topic_count = fields.Integer('Topic Count', compute='_compute_stats', store=True)
    sheet_count = fields.Integer('Sheet Count', compute='_compute_stats', store=True)

    @api.depends('sheet_ids', 'sheet_ids.topic_ids')
    def _compute_stats(self):
        for record in self:
            record.sheet_count = len(record.sheet_ids)
            record.topic_count = sum(len(sheet.topic_ids) for sheet in record.sheet_ids)

    def get_mindmap_data(self):
        """Get mindmap data in jsMind format with XMind 2 features"""
        self.ensure_one()

        default_data = {
            'id': 'root',
            'topic': self.name or _('Central Topic'),
            'expanded': True,
            'children': [],
            'data': {
                'style': {
                    'background': '#428bca',
                    'color': '#ffffff',
                    'font-weight': 'bold',
                    'font-size': '18px',
                }
            }
        }

        if not self.sheet_ids:
            return {
                'meta': {
                    'name': self.name,
                    'author': self.creator or '',
                    'version': '1.0'
                },
                'format': 'node_tree',
                'data': default_data,
            }

        # Use first sheet as main mindmap
        sheet = self.sheet_ids[0]
        root_topic = sheet.topic_ids.filtered(lambda t: not t.parent_id)

        if root_topic:
            data = self._topic_to_jsmind(root_topic[0])
        else:
            data = default_data

        return {
            'meta': {
                'name': self.name,
                'author': self.creator or '',
                'version': '1.0'
            },
            'format': 'node_tree',
            'data': data,
        }

    def _topic_to_jsmind(self, topic):
        """Convert topic to jsMind format with styling"""
        node = {
            'id': topic.component_id or str(uuid.uuid4()),
            'topic': topic.title,
            'expanded': topic.expanded,
            'children': [],
            'data': {
                'note': topic.note or '',
                'markers': topic.marker_ids.mapped('marker_id.code') if topic.marker_ids else [],
                'labels': topic.labels.split(',') if topic.labels else [],
                'style': self._get_topic_style(topic),
            }
        }

        for child in topic.child_ids.sorted('sequence'):
            node['children'].append(self._topic_to_jsmind(child))

        return node

    def _get_topic_style(self, topic):
        """Get topic styling in XMind 2 format"""
        style = {}
        if topic.background_color:
            style['background'] = topic.background_color
        if topic.text_color:
            style['color'] = topic.text_color
        if topic.font_size:
            style['font-size'] = f'{topic.font_size}px'
        if topic.font_weight:
            style['font-weight'] = topic.font_weight
        if topic.border_color:
            style['border-color'] = topic.border_color
        if topic.border_width:
            style['border-width'] = f'{topic.border_width}px'
        return style

    def save_mindmap_data(self, data):
        """Save mindmap data from jsMind editor with command history"""
        self.ensure_one()

        if not self.sheet_ids:
            sheet = self.env['xmind.sheet'].create({
                'workbook_id': self.id,
                'name': self.name,
            })
        else:
            sheet = self.sheet_ids[0]

        # Clear existing topics
        sheet.topic_ids.unlink()

        # Import from jsMind format
        if 'data' in data:
            self._import_jsmind_node(data['data'], sheet, False)

        self.modified_time = fields.Datetime.now()
        return True

    def _import_jsmind_node(self, node, sheet, parent=False):
        """Import node from jsMind data with styling"""
        style_data = node.get('data', {}).get('style', {})

        topic_vals = {
            'sheet_id': sheet.id,
            'component_id': node.get('id', str(uuid.uuid4())),
            'title': node.get('topic', ''),
            'expanded': node.get('expanded', True),
            'note': node.get('data', {}).get('note', ''),
            'labels': ','.join(node.get('data', {}).get('labels', [])),
            'background_color': style_data.get('background', ''),
            'text_color': style_data.get('color', ''),
            'font_size': int(style_data.get('font-size', '14').replace('px', '')) if style_data.get('font-size') else 14,
            'font_weight': style_data.get('font-weight', 'normal'),
            'border_color': style_data.get('border-color', ''),
            'border_width': int(style_data.get('border-width', '1').replace('px', '')) if style_data.get('border-width') else 1,
        }

        if parent:
            topic_vals['parent_id'] = parent.id

        topic = self.env['xmind.topic'].create(topic_vals)

        # Import children
        for idx, child_node in enumerate(node.get('children', [])):
            child = self._import_jsmind_node(child_node, sheet, topic)
            child.sequence = idx

        return topic

    def export_xmind_file(self):
        """Export workbook as .xmind file"""
        self.ensure_one()

        # Create ZIP file structure
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # content.json - main content
            content = self._generate_xmind_content()
            zf.writestr('content.json', json.dumps(content, indent=2))

            # metadata.json
            metadata = {
                'creator': {
                    'name': 'Dobtor XMind Editor',
                    'version': '14.0.1.0.0'
                }
            }
            zf.writestr('metadata.json', json.dumps(metadata, indent=2))

            # manifest.json
            manifest = {
                'file-entries': {
                    'content.json': {},
                    'metadata.json': {}
                }
            }
            zf.writestr('manifest.json', json.dumps(manifest, indent=2))

        zip_buffer.seek(0)
        self.xmind_file = base64.b64encode(zip_buffer.read())
        self.xmind_filename = f'{self.name}.xmind'

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model=xmind.workbook&id={self.id}&field=xmind_file&filename_field=xmind_filename&download=true',
            'target': 'self',
        }

    def _generate_xmind_content(self):
        """Generate XMind content.json structure"""
        sheets_data = []

        for sheet in self.sheet_ids:
            root_topic = sheet.topic_ids.filtered(lambda t: not t.parent_id)
            if root_topic:
                sheet_data = {
                    'id': sheet.component_id or str(uuid.uuid4()),
                    'class': 'sheet',
                    'title': sheet.name,
                    'rootTopic': self._topic_to_xmind(root_topic[0]),
                    'relationships': self._get_relationships(sheet),
                }
                sheets_data.append(sheet_data)

        return sheets_data

    def _topic_to_xmind(self, topic):
        """Convert topic to XMind format"""
        xmind_topic = {
            'id': topic.component_id,
            'class': 'topic',
            'title': topic.title,
            'structureClass': topic.structure_class or 'org.xmind.ui.map.unbalanced',
        }

        if topic.note:
            xmind_topic['notes'] = {
                'plain': {'content': topic.note}
            }

        if topic.labels:
            xmind_topic['labels'] = topic.labels.split(',')

        if topic.marker_ids:
            xmind_topic['markers'] = [
                {'markerId': m.marker_id.code} for m in topic.marker_ids
            ]

        # Style
        style = {}
        if topic.background_color:
            style['background'] = topic.background_color
        if topic.text_color:
            style['color'] = topic.text_color
        if style:
            xmind_topic['style'] = {'properties': style}

        # Children
        if topic.child_ids:
            xmind_topic['children'] = {
                'attached': [
                    self._topic_to_xmind(child) for child in topic.child_ids.sorted('sequence')
                ]
            }

        return xmind_topic

    def _get_relationships(self, sheet):
        """Get relationships for a sheet"""
        relationships = []
        for rel in sheet.relationship_ids:
            relationships.append({
                'id': rel.component_id or str(uuid.uuid4()),
                'end1Id': rel.source_topic_id.component_id,
                'end2Id': rel.target_topic_id.component_id,
                'title': rel.title or '',
            })
        return relationships

    def import_xmind_file(self):
        """Import .xmind file"""
        self.ensure_one()

        if not self.xmind_file:
            raise UserError(_('Please select a .xmind file to import'))

        file_data = base64.b64decode(self.xmind_file)

        try:
            with zipfile.ZipFile(io.BytesIO(file_data), 'r') as zf:
                content_json = zf.read('content.json')
                content = json.loads(content_json)

                # Clear existing sheets
                self.sheet_ids.unlink()

                # Import sheets
                for sheet_data in content:
                    self._import_xmind_sheet(sheet_data)

                self.modified_time = fields.Datetime.now()
        except Exception as e:
            raise UserError(_('Error importing XMind file: %s') % str(e))

        return True

    def _import_xmind_sheet(self, sheet_data):
        """Import XMind sheet data"""
        sheet = self.env['xmind.sheet'].create({
            'workbook_id': self.id,
            'name': sheet_data.get('title', 'Sheet'),
            'component_id': sheet_data.get('id', str(uuid.uuid4())),
        })

        if 'rootTopic' in sheet_data:
            self._import_xmind_topic(sheet_data['rootTopic'], sheet)

        # Import relationships
        for rel_data in sheet_data.get('relationships', []):
            self._import_relationship(rel_data, sheet)

        return sheet

    def _import_xmind_topic(self, topic_data, sheet, parent=False):
        """Import XMind topic data"""
        style_props = topic_data.get('style', {}).get('properties', {})

        topic_vals = {
            'sheet_id': sheet.id,
            'component_id': topic_data.get('id', str(uuid.uuid4())),
            'title': topic_data.get('title', ''),
            'structure_class': topic_data.get('structureClass', ''),
            'background_color': style_props.get('background', ''),
            'text_color': style_props.get('color', ''),
        }

        if parent:
            topic_vals['parent_id'] = parent.id

        # Notes
        if 'notes' in topic_data:
            notes = topic_data['notes']
            if 'plain' in notes:
                topic_vals['note'] = notes['plain'].get('content', '')

        # Labels
        if 'labels' in topic_data:
            topic_vals['labels'] = ','.join(topic_data['labels'])

        topic = self.env['xmind.topic'].create(topic_vals)

        # Import markers
        if 'markers' in topic_data:
            for marker_data in topic_data['markers']:
                marker = self.env['xmind.marker'].search([
                    ('code', '=', marker_data.get('markerId', ''))
                ], limit=1)
                if marker:
                    self.env['xmind.topic.marker'].create({
                        'topic_id': topic.id,
                        'marker_id': marker.id,
                    })

        # Import children
        children_data = topic_data.get('children', {})
        attached = children_data.get('attached', [])
        for idx, child_data in enumerate(attached):
            child = self._import_xmind_topic(child_data, sheet, topic)
            child.sequence = idx

        return topic

    def _import_relationship(self, rel_data, sheet):
        """Import relationship data"""
        source = self.env['xmind.topic'].search([
            ('sheet_id', '=', sheet.id),
            ('component_id', '=', rel_data.get('end1Id'))
        ], limit=1)
        target = self.env['xmind.topic'].search([
            ('sheet_id', '=', sheet.id),
            ('component_id', '=', rel_data.get('end2Id'))
        ], limit=1)

        if source and target:
            self.env['xmind.relationship'].create({
                'sheet_id': sheet.id,
                'source_topic_id': source.id,
                'target_topic_id': target.id,
                'title': rel_data.get('title', ''),
                'component_id': rel_data.get('id', str(uuid.uuid4())),
            })

    def action_open_editor(self):
        """Open visual mindmap editor"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'dobtor_xmind.mindmap_editor',
            'params': {
                'workbook_id': self.id,
            },
            'target': 'current',
        }
