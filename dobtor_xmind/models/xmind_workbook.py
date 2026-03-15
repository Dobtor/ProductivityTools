# -*- coding: utf-8 -*-
import base64
import json
import zipfile
import io
import uuid
import html
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

    # Revisions
    revision_ids = fields.One2many('xmind.revision', 'workbook_id', string='Revisions')

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

        # Create revision snapshot
        self._create_revision(data, is_auto=False)

        return True

    def _create_revision(self, data, is_auto=False):
        """Create a revision snapshot of the current mindmap state."""
        self.env['xmind.revision'].create({
            'workbook_id': self.id,
            'snapshot': json.dumps(data),
            'topic_count': self.topic_count,
            'is_auto': is_auto,
        })
        # Keep max 50 revisions per workbook
        revisions = self.revision_ids.sorted('create_date', reverse=True)
        if len(revisions) > 50:
            revisions[50:].unlink()

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

        # Import markers from node.data
        marker_codes = node.get('data', {}).get('markers', [])
        for code in marker_codes:
            marker = self.env['xmind.marker'].search([('code', '=', code)], limit=1)
            if marker:
                self.env['xmind.topic.marker'].create({
                    'topic_id': topic.id,
                    'marker_id': marker.id,
                })

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
                    'version': '18.0.1.0.0'
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
                file_list = zf.namelist()

                # Check file format (XMind 8+ uses JSON, older versions use XML)
                if 'content.json' in file_list:
                    # XMind 8+ JSON format
                    content_json = zf.read('content.json')
                    content = json.loads(content_json)

                    # Clear existing sheets
                    self.sheet_ids.unlink()

                    # Import sheets
                    for sheet_data in content:
                        self._import_xmind_sheet(sheet_data)

                elif 'content.xml' in file_list:
                    # Old XMind XML format (XMind 7 and earlier)
                    content_xml = zf.read('content.xml')
                    self._import_xmind_xml(content_xml)

                else:
                    raise UserError(_('Invalid XMind file: neither content.json nor content.xml found'))

                self.modified_time = fields.Datetime.now()
        except zipfile.BadZipFile:
            raise UserError(_('Invalid file: not a valid ZIP/XMind archive'))
        except json.JSONDecodeError as e:
            raise UserError(_('Error parsing XMind JSON content: %s') % str(e))
        except Exception as e:
            raise UserError(_('Error importing XMind file: %s') % str(e))

        return True

    # -------------------------------------------------------------------------
    # FreeMind (.mm) Import
    # -------------------------------------------------------------------------

    def import_freemind_file(self):
        """Import FreeMind .mm XML file"""
        self.ensure_one()
        if not self.xmind_file:
            raise UserError(_('Please select a .mm file to import'))

        import xml.etree.ElementTree as ET

        file_data = base64.b64decode(self.xmind_file)
        try:
            root = ET.fromstring(file_data)

            # FreeMind format: <map><node TEXT="root">...</node></map>
            self.sheet_ids.unlink()

            map_node = root if root.tag == 'node' else root.find('node')
            if map_node is None:
                raise UserError(_('Invalid FreeMind file: no root node found'))

            sheet = self.env['xmind.sheet'].create({
                'workbook_id': self.id,
                'name': map_node.get('TEXT', 'Sheet 1'),
            })

            self._import_freemind_node(map_node, sheet)
            self.modified_time = fields.Datetime.now()
        except ET.ParseError as e:
            raise UserError(_('Error parsing FreeMind XML: %s') % str(e))
        return True

    def _import_freemind_node(self, node_elem, sheet, parent=False):
        """Recursively import FreeMind node"""
        import xml.etree.ElementTree as ET

        topic_vals = {
            'sheet_id': sheet.id,
            'title': node_elem.get('TEXT', ''),
            'component_id': node_elem.get('ID', str(uuid.uuid4())),
        }
        if parent:
            topic_vals['parent_id'] = parent.id

        # Import colors
        color = node_elem.get('COLOR', '')
        if color:
            topic_vals['text_color'] = color
        bg = node_elem.get('BACKGROUND_COLOR', '')
        if bg:
            topic_vals['background_color'] = bg

        # Check for richcontent (HTML notes)
        richcontent = node_elem.find('richcontent')
        if richcontent is not None:
            html_content = ET.tostring(richcontent, encoding='unicode', method='text')
            topic_vals['note'] = html_content.strip()

        # Check for link
        link = node_elem.get('LINK', '')
        if link:
            topic_vals['hyperlink'] = link

        topic = self.env['xmind.topic'].create(topic_vals)

        # Import icon -> marker mapping
        for icon_elem in node_elem.findall('icon'):
            builtin = icon_elem.get('BUILTIN', '')
            marker_code = self._freemind_icon_to_marker(builtin)
            if marker_code:
                marker = self.env['xmind.marker'].search([('code', '=', marker_code)], limit=1)
                if marker:
                    self.env['xmind.topic.marker'].create({
                        'topic_id': topic.id,
                        'marker_id': marker.id,
                    })

        # Import children
        for idx, child_elem in enumerate(node_elem.findall('node')):
            child = self._import_freemind_node(child_elem, sheet, topic)
            child.sequence = idx

        return topic

    def _freemind_icon_to_marker(self, builtin):
        """Map FreeMind icon names to XMind marker codes"""
        mapping = {
            'full-1': 'priority-1', 'full-2': 'priority-2', 'full-3': 'priority-3',
            'full-4': 'priority-4', 'full-5': 'priority-5', 'full-6': 'priority-6',
            'button_ok': 'symbol-right', 'button_cancel': 'symbol-wrong',
            'idea': 'symbol-lightbulb', 'help': 'symbol-question',
            'messagebox_warning': 'symbol-warning', 'info': 'symbol-info',
            'yes': 'symbol-right', 'no': 'symbol-wrong',
            'ksmiletris': 'smiley-happy', 'smiley-neutral': 'smiley-neutral',
            'smiley-angry': 'smiley-angry',
            'flag': 'flag-red', 'flag-green': 'flag-green', 'flag-blue': 'flag-blue',
            'clock': 'symbol-clock', 'launch': 'symbol-lightbulb',
            'bookmark': 'star-yellow', 'pencil': 'symbol-info',
        }
        return mapping.get(builtin, '')

    # -------------------------------------------------------------------------
    # MindManager (.mmap) Import
    # -------------------------------------------------------------------------

    def import_mindmanager_file(self):
        """Import MindManager .mmap file (ZIP with Document.xml)"""
        self.ensure_one()
        if not self.xmind_file:
            raise UserError(_('Please select a .mmap file to import'))

        import xml.etree.ElementTree as ET

        file_data = base64.b64decode(self.xmind_file)
        try:
            # .mmap files are ZIP archives containing Document.xml
            with zipfile.ZipFile(io.BytesIO(file_data), 'r') as zf:
                if 'Document.xml' not in zf.namelist():
                    raise UserError(_('Invalid MindManager file: Document.xml not found'))
                doc_xml = zf.read('Document.xml')

            root = ET.fromstring(doc_xml)
            ns = {'mm': 'http://schemas.mindjet.com/MindManager/Application/2003'}

            self.sheet_ids.unlink()

            # Find the central topic
            central = root.find('.//mm:OneTopic/mm:Topic', ns)
            if central is None:
                # Try without namespace
                central = root.find('.//OneTopic/Topic')
            if central is None:
                raise UserError(_('Invalid MindManager file: no central topic found'))

            sheet = self.env['xmind.sheet'].create({
                'workbook_id': self.id,
                'name': self._mm_get_text(central, ns) or 'Sheet 1',
            })

            self._import_mm_topic(central, sheet, ns)
            self.modified_time = fields.Datetime.now()
        except zipfile.BadZipFile:
            raise UserError(_('Invalid file: not a valid MindManager archive'))
        except ET.ParseError as e:
            raise UserError(_('Error parsing MindManager XML: %s') % str(e))
        return True

    def _mm_get_text(self, topic_elem, ns):
        """Extract text from MindManager topic"""
        text_elem = topic_elem.find('mm:Text', ns) or topic_elem.find('Text')
        if text_elem is not None:
            plain = text_elem.get('PlainText', '')
            if plain:
                return plain
        # Fallback
        title_elem = topic_elem.find('mm:TopicText', ns) or topic_elem.find('TopicText')
        if title_elem is not None:
            return title_elem.text or ''
        return ''

    def _import_mm_topic(self, topic_elem, sheet, ns, parent=False):
        """Recursively import MindManager topic"""
        title = self._mm_get_text(topic_elem, ns)
        topic_vals = {
            'sheet_id': sheet.id,
            'title': title or _('Topic'),
            'component_id': topic_elem.get('OId', str(uuid.uuid4())),
        }
        if parent:
            topic_vals['parent_id'] = parent.id

        # Notes
        notes_elem = (
            topic_elem.find('mm:NotesGroup/mm:NotesXhtmlData', ns)
            or topic_elem.find('NotesGroup/NotesXhtmlData')
        )
        if notes_elem is not None and notes_elem.text:
            topic_vals['note'] = notes_elem.text.strip()

        # Hyperlink
        hyperlink_elem = (
            topic_elem.find('mm:Hyperlink', ns)
            or topic_elem.find('Hyperlink')
        )
        if hyperlink_elem is not None:
            topic_vals['hyperlink'] = hyperlink_elem.get('Url', '')

        topic = self.env['xmind.topic'].create(topic_vals)

        # Import sub-topics
        subtopics = topic_elem.find('mm:SubTopics', ns) or topic_elem.find('SubTopics')
        if subtopics is not None:
            children = subtopics.findall('mm:Topic', ns) or subtopics.findall('Topic')
            for idx, child_elem in enumerate(children):
                child = self._import_mm_topic(child_elem, sheet, ns, topic)
                child.sequence = idx

        return topic

    def _import_xmind_xml(self, content_xml):
        """Import old XMind XML format (XMind 7 and earlier)"""
        import xml.etree.ElementTree as ET

        # Clear existing sheets
        self.sheet_ids.unlink()

        root = ET.fromstring(content_xml)
        ns = {'xmap': 'urn:xmind:xmap:xmlns:content:2.0'}

        # Find all sheets
        for sheet_elem in root.findall('.//xmap:sheet', ns):
            sheet_id = sheet_elem.get('id', str(uuid.uuid4()))
            sheet_title = 'Sheet'

            # Get sheet title
            title_elem = sheet_elem.find('xmap:title', ns)
            if title_elem is not None and title_elem.text:
                sheet_title = title_elem.text

            sheet = self.env['xmind.sheet'].create({
                'workbook_id': self.id,
                'name': sheet_title,
                'component_id': sheet_id,
            })

            # Find root topic
            root_topic_elem = sheet_elem.find('xmap:topic', ns)
            if root_topic_elem is not None:
                self._import_xmind_xml_topic(root_topic_elem, sheet, ns)

            # Import relationships
            rels_elem = sheet_elem.find('xmap:relationships', ns)
            if rels_elem is not None:
                for rel_elem in rels_elem.findall('xmap:relationship', ns):
                    self._import_xmind_xml_relationship(rel_elem, sheet, ns)

    def _import_xmind_xml_topic(self, topic_elem, sheet, ns, parent=False):
        """Import topic from XML format"""
        topic_id = topic_elem.get('id', str(uuid.uuid4()))

        # Get title
        title = ''
        title_elem = topic_elem.find('xmap:title', ns)
        if title_elem is not None and title_elem.text:
            title = title_elem.text

        # Get structure class
        structure_class = topic_elem.get('structure-class', '')

        topic_vals = {
            'sheet_id': sheet.id,
            'component_id': topic_id,
            'title': title,
            'structure_class': structure_class,
        }

        if parent:
            topic_vals['parent_id'] = parent.id

        # Get notes
        notes_elem = topic_elem.find('.//xmap:notes/xmap:plain', ns)
        if notes_elem is not None and notes_elem.text:
            topic_vals['note'] = notes_elem.text

        # Get labels
        labels = []
        for label_elem in topic_elem.findall('.//xmap:labels/xmap:label', ns):
            if label_elem.text:
                labels.append(label_elem.text)
        if labels:
            topic_vals['labels'] = ','.join(labels)

        topic = self.env['xmind.topic'].create(topic_vals)

        # Import markers
        for marker_elem in topic_elem.findall('.//xmap:marker-refs/xmap:marker-ref', ns):
            marker_id = marker_elem.get('marker-id', '')
            if marker_id:
                marker = self.env['xmind.marker'].search([
                    ('code', '=', marker_id)
                ], limit=1)
                if marker:
                    self.env['xmind.topic.marker'].create({
                        'topic_id': topic.id,
                        'marker_id': marker.id,
                    })

        # Import children
        children_elem = topic_elem.find('xmap:children', ns)
        if children_elem is not None:
            topics_elem = children_elem.find('xmap:topics', ns)
            if topics_elem is not None:
                for idx, child_elem in enumerate(topics_elem.findall('xmap:topic', ns)):
                    child = self._import_xmind_xml_topic(child_elem, sheet, ns, topic)
                    child.sequence = idx

        return topic

    def _import_xmind_xml_relationship(self, rel_elem, sheet, ns):
        """Import relationship from XML format"""
        rel_id = rel_elem.get('id', str(uuid.uuid4()))
        end1_id = rel_elem.get('end1', '')
        end2_id = rel_elem.get('end2', '')

        # Get title
        title = ''
        title_elem = rel_elem.find('xmap:title', ns)
        if title_elem is not None and title_elem.text:
            title = title_elem.text

        if end1_id and end2_id:
            source = self.env['xmind.topic'].search([
                ('sheet_id', '=', sheet.id),
                ('component_id', '=', end1_id)
            ], limit=1)
            target = self.env['xmind.topic'].search([
                ('sheet_id', '=', sheet.id),
                ('component_id', '=', end2_id)
            ], limit=1)

            if source and target:
                self.env['xmind.relationship'].create({
                    'sheet_id': sheet.id,
                    'source_topic_id': source.id,
                    'target_topic_id': target.id,
                    'title': title,
                    'component_id': rel_id,
                })

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

    # -------------------------------------------------------------------------
    # SVG / PNG Export
    # -------------------------------------------------------------------------

    # Layout constants
    _SVG_NODE_H_GAP = 60       # horizontal gap between parent and child
    _SVG_NODE_V_GAP = 16       # vertical gap between sibling nodes
    _SVG_NODE_PADDING_X = 16   # horizontal padding inside node box
    _SVG_NODE_PADDING_Y = 10   # vertical padding inside node box
    _SVG_CHAR_WIDTH = 8        # approximate width per character
    _SVG_CANVAS_MARGIN = 40    # margin around the whole diagram

    # Default style palette per level
    _SVG_LEVEL_STYLES = {
        0: {'bg': '#428bca', 'fg': '#ffffff', 'font_size': 18, 'font_weight': 'bold', 'rx': 8},
        1: {'bg': '#5cb85c', 'fg': '#ffffff', 'font_size': 14, 'font_weight': 'bold', 'rx': 6},
        2: {'bg': '#f0ad4e', 'fg': '#ffffff', 'font_size': 13, 'font_weight': 'normal', 'rx': 4},
    }
    _SVG_DEFAULT_STYLE = {'bg': '#eeeeee', 'fg': '#333333', 'font_size': 12, 'font_weight': 'normal', 'rx': 4}

    def export_svg(self):
        """Export workbook as SVG file"""
        self.ensure_one()
        svg_content = self._generate_svg()
        self.xmind_file = base64.b64encode(svg_content.encode('utf-8'))
        self.xmind_filename = f'{self.name}.svg'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model=xmind.workbook&id={self.id}&field=xmind_file&filename_field=xmind_filename&download=true',
            'target': 'self',
        }

    def export_png(self):
        """Export workbook as PNG file (requires cairosvg)"""
        self.ensure_one()
        svg_content = self._generate_svg()
        try:
            import cairosvg
            png_data = cairosvg.svg2png(
                bytestring=svg_content.encode('utf-8'),
                output_width=1920,
            )
        except ImportError:
            raise UserError(_(
                'PNG export requires the cairosvg library. '
                'Install with: pip install cairosvg'
            ))
        self.xmind_file = base64.b64encode(png_data)
        self.xmind_filename = f'{self.name}.png'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model=xmind.workbook&id={self.id}&field=xmind_file&filename_field=xmind_filename&download=true',
            'target': 'self',
        }

    def export_pdf(self):
        """Export workbook as PDF file (requires cairosvg)"""
        self.ensure_one()
        svg_content = self._generate_svg()
        try:
            import cairosvg
            pdf_data = cairosvg.svg2pdf(bytestring=svg_content.encode('utf-8'))
        except ImportError:
            raise UserError(_(
                'PDF export requires the cairosvg library. '
                'Install with: pip install cairosvg'
            ))
        self.xmind_file = base64.b64encode(pdf_data)
        self.xmind_filename = f'{self.name}.pdf'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model=xmind.workbook&id={self.id}&field=xmind_file&filename_field=xmind_filename&download=true',
            'target': 'self',
        }

    def _generate_svg(self):
        """Generate a complete SVG string for the first sheet's mind map."""
        self.ensure_one()

        if not self.sheet_ids:
            # Empty workbook -- render a single root node with the workbook name
            return self._svg_wrap(200, 60, self._svg_single_node(self.name, 100, 30))

        sheet = self.sheet_ids[0]
        root_topic = sheet.topic_ids.filtered(lambda t: not t.parent_id)
        if not root_topic:
            return self._svg_wrap(200, 60, self._svg_single_node(sheet.name or self.name, 100, 30))

        root = root_topic[0]

        # Phase 1: compute the size of every node box
        sizes = {}  # topic.id -> (w, h)
        self._compute_node_sizes(root, sizes)

        # Phase 2: compute subtree heights (needed for vertical distribution)
        subtree_h = {}  # topic.id -> total height including children
        self._compute_subtree_heights(root, sizes, subtree_h)

        # Phase 3: assign (cx, cy) positions -- root at (0, 0), children to the right
        positions = {}  # topic.id -> (cx, cy)
        root_w, root_h = sizes[root.id]
        positions[root.id] = (0, 0)
        self._assign_positions(root, positions, sizes, subtree_h, root_w / 2 + self._SVG_NODE_H_GAP, 0)

        # Phase 4: determine bounding box and shift everything into positive space
        all_coords = []
        for tid, (cx, cy) in positions.items():
            w, h = sizes[tid]
            all_coords.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))

        min_x = min(c[0] for c in all_coords)
        min_y = min(c[1] for c in all_coords)
        max_x = max(c[2] for c in all_coords)
        max_y = max(c[3] for c in all_coords)

        margin = self._SVG_CANVAS_MARGIN
        offset_x = -min_x + margin
        offset_y = -min_y + margin
        canvas_w = max_x - min_x + margin * 2
        canvas_h = max_y - min_y + margin * 2

        # Shift positions
        shifted = {tid: (cx + offset_x, cy + offset_y) for tid, (cx, cy) in positions.items()}

        # Phase 5: render SVG elements
        elements = []
        # Draw connections first (behind nodes)
        self._render_connections(root, shifted, sizes, elements)
        # Draw nodes on top
        self._render_nodes(root, shifted, sizes, elements)

        return self._svg_wrap(canvas_w, canvas_h, '\n'.join(elements))

    # -- Helpers for layout computation --

    def _compute_node_sizes(self, topic, sizes):
        """Compute (width, height) for each topic's box."""
        title = topic.title or ''
        font_size = topic.font_size or 14
        char_w = self._SVG_CHAR_WIDTH * (font_size / 14.0)
        text_w = len(title) * char_w
        # Minimum width
        w = max(text_w + self._SVG_NODE_PADDING_X * 2, 60)
        h = font_size + self._SVG_NODE_PADDING_Y * 2
        sizes[topic.id] = (w, h)
        for child in topic.child_ids.sorted('sequence'):
            self._compute_node_sizes(child, sizes)

    def _compute_subtree_heights(self, topic, sizes, subtree_h):
        """Compute total vertical space needed by a topic and all its descendants."""
        children = topic.child_ids.sorted('sequence')
        if not children:
            subtree_h[topic.id] = sizes[topic.id][1]
            return

        total = 0
        for child in children:
            self._compute_subtree_heights(child, sizes, subtree_h)
            total += subtree_h[child.id]
        total += self._SVG_NODE_V_GAP * (len(children) - 1)

        # Subtree height is the max of own height and children's total
        subtree_h[topic.id] = max(sizes[topic.id][1], total)

    def _assign_positions(self, topic, positions, sizes, subtree_h, child_x, parent_cy):
        """Assign center positions to all children of *topic*, starting at child_x."""
        children = topic.child_ids.sorted('sequence')
        if not children:
            return

        # Total height of all children subtrees
        total_children_h = sum(subtree_h[c.id] for c in children) + self._SVG_NODE_V_GAP * (len(children) - 1)
        current_y = parent_cy - total_children_h / 2

        for child in children:
            child_w, child_h = sizes[child.id]
            child_sub_h = subtree_h[child.id]
            # Center of this child within its subtree band
            cy = current_y + child_sub_h / 2
            cx = child_x + child_w / 2
            positions[child.id] = (cx, cy)

            # Recurse for grandchildren
            self._assign_positions(child, positions, sizes, subtree_h, cx + child_w / 2 + self._SVG_NODE_H_GAP, cy)

            current_y += child_sub_h + self._SVG_NODE_V_GAP

    # -- SVG Rendering --

    def _render_connections(self, topic, positions, sizes, elements):
        """Render bezier curve connections from *topic* to each of its children."""
        children = topic.child_ids.sorted('sequence')
        if not children:
            return

        parent_cx, parent_cy = positions[topic.id]
        parent_w, parent_h = sizes[topic.id]
        # Connection starts at right edge of parent
        x1 = parent_cx + parent_w / 2
        y1 = parent_cy

        for child in children:
            child_cx, child_cy = positions[child.id]
            child_w, child_h = sizes[child.id]
            # Connection ends at left edge of child
            x2 = child_cx - child_w / 2
            y2 = child_cy

            # Cubic bezier with control points at horizontal midpoint
            mx = (x1 + x2) / 2
            elements.append(
                f'<path d="M {x1:.1f} {y1:.1f} C {mx:.1f} {y1:.1f}, {mx:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}" '
                f'fill="none" stroke="#999999" stroke-width="1.5" opacity="0.7"/>'
            )
            # Recurse
            self._render_connections(child, positions, sizes, elements)

    def _render_nodes(self, topic, positions, sizes, elements):
        """Render the rectangle + text for *topic* and all descendants."""
        cx, cy = positions[topic.id]
        w, h = sizes[topic.id]
        x = cx - w / 2
        y = cy - h / 2

        level = topic.level or 0
        defaults = self._SVG_LEVEL_STYLES.get(level, self._SVG_DEFAULT_STYLE)

        bg = topic.background_color or defaults['bg']
        fg = topic.text_color or defaults['fg']
        font_size = topic.font_size or defaults['font_size']
        font_weight = topic.font_weight or defaults['font_weight']
        rx = defaults.get('rx', 6)
        border_color = topic.border_color or bg
        border_width = topic.border_width if topic.border_width and topic.border_width > 0 else 1

        title_escaped = html.escape(topic.title or '')

        elements.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{rx}" ry="{rx}" fill="{bg}" stroke="{border_color}" stroke-width="{border_width}"/>'
        )
        elements.append(
            f'<text x="{cx:.1f}" y="{cy + font_size * 0.35:.1f}" '
            f'text-anchor="middle" fill="{fg}" '
            f'font-size="{font_size}px" font-weight="{font_weight}" '
            f'font-family="Arial, Helvetica, sans-serif">{title_escaped}</text>'
        )

        for child in topic.child_ids.sorted('sequence'):
            self._render_nodes(child, positions, sizes, elements)

    def _svg_single_node(self, title, cx, cy):
        """Render a single centered node (for empty workbooks)."""
        escaped = html.escape(title or 'Mind Map')
        w = max(len(title or '') * 10 + 32, 120)
        h = 36
        x = cx - w / 2
        y = cy - h / 2
        return (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="8" ry="8" fill="#428bca" stroke="#3071a9" stroke-width="1"/>'
            f'<text x="{cx:.1f}" y="{cy + 5:.1f}" text-anchor="middle" fill="#ffffff" '
            f'font-size="14px" font-weight="bold" font-family="Arial, Helvetica, sans-serif">'
            f'{escaped}</text>'
        )

    def _svg_wrap(self, width, height, body):
        """Wrap SVG body elements in a complete SVG document."""
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width:.0f}" height="{height:.0f}" '
            f'viewBox="0 0 {width:.0f} {height:.0f}">\n'
            f'<rect width="100%" height="100%" fill="#ffffff"/>\n'
            f'{body}\n'
            f'</svg>'
        )

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
