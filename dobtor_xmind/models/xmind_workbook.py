# -*- coding: utf-8 -*-
import json
import zipfile
import base64
from io import BytesIO
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class XmindWorkbook(models.Model):
    _name = 'xmind.workbook'
    _description = 'XMind Workbook'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Name', required=True, tracking=True)
    description = fields.Text('Description')
    sheet_ids = fields.One2many('xmind.sheet', 'workbook_id', 'Sheets')
    sheet_count = fields.Integer('Sheet Count', compute='_compute_sheet_count')

    # File storage
    attachment_id = fields.Many2one('ir.attachment', 'XMind File Backup',
                                     help='Original .xmind file backup')
    json_data = fields.Text('JSON Data', help='Complete mindmap structure in JSON')

    # Theme settings
    theme = fields.Selection([
        ('robust', 'Robust'),
        ('snowbrush', 'Snowbrush'),
        ('business', 'Business')
    ], string='Theme', default='robust')

    # Metadata
    creator = fields.Char('Creator', default=lambda self: self.env.user.name)
    last_modified = fields.Datetime('Last Modified', default=fields.Datetime.now)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived')
    ], string='State', default='draft', tracking=True)

    @api.depends('sheet_ids')
    def _compute_sheet_count(self):
        for record in self:
            record.sheet_count = len(record.sheet_ids)

    def action_view_editor(self):
        """Open the visual mindmap editor"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'xmind_editor',
            'params': {
                'workbook_id': self.id,
            },
            'target': 'current',
        }

    def action_create_sheet(self):
        """Create a new sheet in this workbook"""
        self.ensure_one()
        sheet = self.env['xmind.sheet'].create({
            'name': _('New Sheet'),
            'workbook_id': self.id,
        })
        # Create root topic for the sheet
        root_topic = self.env['xmind.topic'].create({
            'title': _('Central Topic'),
            'sheet_id': sheet.id,
            'is_root': True,
        })
        sheet.root_topic_id = root_topic.id
        return sheet

    def get_mindmap_data(self):
        """Get mindmap data in jsMind format for frontend editor"""
        self.ensure_one()
        if not self.sheet_ids:
            return {'meta': {'name': self.name}, 'data': []}

        sheet = self.sheet_ids[0]  # Get first sheet
        if not sheet.root_topic_id:
            return {'meta': {'name': self.name}, 'data': []}

        def build_topic_tree(topic):
            node = {
                'id': str(topic.id),
                'topic': topic.title,
                'expanded': True,
            }
            if topic.note:
                node['note'] = topic.note
            if topic.markers:
                node['markers'] = json.loads(topic.markers)
            if topic.labels:
                node['labels'] = json.loads(topic.labels)

            children = []
            for child in topic.child_ids.sorted('sequence'):
                children.append(build_topic_tree(child))
            if children:
                node['children'] = children

            return node

        root_data = build_topic_tree(sheet.root_topic_id)

        return {
            'meta': {
                'name': self.name,
                'author': self.creator,
                'version': '1.0',
            },
            'format': 'node_tree',
            'data': root_data,
        }

    def save_mindmap_data(self, data):
        """Save mindmap data from frontend editor"""
        self.ensure_one()

        if not data or 'data' not in data:
            return False

        sheet = self.sheet_ids[0] if self.sheet_ids else self.action_create_sheet()

        def save_topic_tree(node_data, parent_id=False, sequence=0):
            topic_vals = {
                'title': node_data.get('topic', 'Untitled'),
                'sheet_id': sheet.id,
                'parent_id': parent_id,
                'sequence': sequence,
                'is_root': not parent_id,
            }

            if 'note' in node_data:
                topic_vals['note'] = node_data['note']
            if 'markers' in node_data:
                topic_vals['markers'] = json.dumps(node_data['markers'])
            if 'labels' in node_data:
                topic_vals['labels'] = json.dumps(node_data['labels'])

            # Check if topic exists (by id in node_data)
            existing_topic = False
            if 'id' in node_data and node_data['id'].isdigit():
                existing_topic = self.env['xmind.topic'].browse(int(node_data['id'])).exists()

            if existing_topic:
                existing_topic.write(topic_vals)
                topic = existing_topic
            else:
                topic = self.env['xmind.topic'].create(topic_vals)

            # Process children
            if 'children' in node_data:
                for idx, child_data in enumerate(node_data['children']):
                    save_topic_tree(child_data, topic.id, idx * 10)

            return topic

        # Clear existing topics if needed
        if sheet.root_topic_id:
            sheet.root_topic_id.unlink()

        root_topic = save_topic_tree(data['data'])
        sheet.root_topic_id = root_topic.id

        # Update JSON data backup
        self.json_data = json.dumps(data)
        self.last_modified = fields.Datetime.now()

        return True

    def export_to_xmind(self):
        """Export workbook to .xmind file format"""
        self.ensure_one()

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Generate content.json
            content = self._generate_xmind_content()
            zf.writestr('content.json', json.dumps(content, indent=2))

            # Generate manifest.json
            manifest = {
                'file-entries': {
                    'content.json': {},
                    'metadata.json': {},
                }
            }
            zf.writestr('manifest.json', json.dumps(manifest, indent=2))

            # Generate metadata.json
            metadata = {
                'creator': {
                    'name': 'Odoo XMind Editor',
                    'version': '14.0.1.0.0'
                }
            }
            zf.writestr('metadata.json', json.dumps(metadata, indent=2))

        buffer.seek(0)
        file_data = base64.b64encode(buffer.read())

        # Create attachment
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}.xmind',
            'type': 'binary',
            'datas': file_data,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/x-xmind',
        })

        self.attachment_id = attachment.id

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _generate_xmind_content(self):
        """Generate XMind content.json structure"""
        sheets_data = []

        for sheet in self.sheet_ids:
            if not sheet.root_topic_id:
                continue

            def topic_to_xmind(topic):
                topic_data = {
                    'id': topic.component_id or f'topic_{topic.id}',
                    'class': 'topic',
                    'title': topic.title,
                }

                if topic.note:
                    topic_data['notes'] = {
                        'plain': {'content': topic.note}
                    }

                if topic.markers:
                    markers = json.loads(topic.markers)
                    topic_data['markers'] = [{'markerId': m} for m in markers]

                if topic.labels:
                    topic_data['labels'] = json.loads(topic.labels)

                children = topic.child_ids.sorted('sequence')
                if children:
                    topic_data['children'] = {
                        'attached': [topic_to_xmind(child) for child in children]
                    }

                return topic_data

            sheet_data = {
                'id': f'sheet_{sheet.id}',
                'class': 'sheet',
                'title': sheet.name,
                'rootTopic': topic_to_xmind(sheet.root_topic_id),
            }

            if self.theme:
                sheet_data['theme'] = {'id': self.theme}

            sheets_data.append(sheet_data)

        return sheets_data

    @api.model
    def import_from_xmind(self, file_data):
        """Import workbook from .xmind file"""
        buffer = BytesIO(base64.b64decode(file_data))

        with zipfile.ZipFile(buffer, 'r') as zf:
            content_data = json.loads(zf.read('content.json'))

        return self._import_from_content(content_data)

    @api.model
    def _import_from_content(self, content_data):
        """Create workbook from XMind content structure"""
        if not content_data:
            raise UserError(_('Invalid XMind file: empty content'))

        # Get first sheet for workbook name
        first_sheet = content_data[0] if isinstance(content_data, list) else content_data
        workbook_name = first_sheet.get('title', 'Imported Mindmap')

        workbook = self.create({
            'name': workbook_name,
            'state': 'active',
        })

        # Import each sheet
        sheets = content_data if isinstance(content_data, list) else [content_data]
        for sheet_data in sheets:
            sheet = self.env['xmind.sheet'].create({
                'name': sheet_data.get('title', 'Sheet'),
                'workbook_id': workbook.id,
            })

            # Import root topic
            if 'rootTopic' in sheet_data:
                root_topic = self._import_topic(sheet_data['rootTopic'], sheet.id)
                sheet.root_topic_id = root_topic.id

        # Store original JSON
        workbook.json_data = json.dumps(content_data)

        return workbook

    def _import_topic(self, topic_data, sheet_id, parent_id=False, sequence=0):
        """Recursively import topic from XMind structure"""
        topic_vals = {
            'title': topic_data.get('title', 'Untitled'),
            'component_id': topic_data.get('id'),
            'sheet_id': sheet_id,
            'parent_id': parent_id,
            'sequence': sequence,
            'is_root': not parent_id,
        }

        # Import notes
        if 'notes' in topic_data:
            notes = topic_data['notes']
            if 'plain' in notes:
                topic_vals['note'] = notes['plain'].get('content', '')

        # Import markers
        if 'markers' in topic_data:
            marker_ids = [m.get('markerId') for m in topic_data['markers'] if m.get('markerId')]
            topic_vals['markers'] = json.dumps(marker_ids)

        # Import labels
        if 'labels' in topic_data:
            topic_vals['labels'] = json.dumps(topic_data['labels'])

        topic = self.env['xmind.topic'].create(topic_vals)

        # Import children
        if 'children' in topic_data:
            children = topic_data['children']
            if 'attached' in children:
                for idx, child_data in enumerate(children['attached']):
                    self._import_topic(child_data, sheet_id, topic.id, idx * 10)

        return topic
