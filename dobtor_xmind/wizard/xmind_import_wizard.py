# -*- coding: utf-8 -*-
import base64
import json
import os
import zipfile
import io

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class XMindImportLine(models.TransientModel):
    _name = 'xmind.import.line'
    _description = 'Mind Map Import Line'

    wizard_id = fields.Many2one('xmind.import.wizard', ondelete='cascade')
    file = fields.Binary('File', required=True, attachment=False)
    filename = fields.Char('Filename')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('error', 'Error'),
    ], default='pending')
    message = fields.Char('Message')
    workbook_id = fields.Many2one('xmind.workbook', string='Created Workbook')


class XMindImportWizard(models.TransientModel):
    _name = 'xmind.import.wizard'
    _description = 'Import Mind Map Files'

    # JSON payload from the custom xmind_multi_file widget: [{name, data(base64)}].
    # Self-contained multi-file upload — no ir.attachment dependency / residue.
    files_json = fields.Text(
        'Upload Files',
        help='Select one or more .xmind, .mm, or .mmap files (multi-select supported)',
    )
    line_ids = fields.One2many('xmind.import.line', 'wizard_id', string='Files')
    import_count = fields.Integer('Imported', compute='_compute_counts')
    error_count = fields.Integer('Errors', compute='_compute_counts')

    @api.depends('line_ids.status')
    def _compute_counts(self):
        for rec in self:
            rec.import_count = len(rec.line_ids.filtered(lambda l: l.status == 'success'))
            rec.error_count = len(rec.line_ids.filtered(lambda l: l.status == 'error'))

    def action_import_all(self):
        """Parse the JSON payload, create one Workbook per file, generate thumbnails.

        Each file is imported inside its own savepoint so that one bad file
        cannot poison the cursor or roll back the successfully-imported ones.
        """
        self.ensure_one()

        try:
            entries = json.loads(self.files_json) if self.files_json else []
        except (ValueError, TypeError):
            raise UserError(_('Could not read the selected files.'))
        if not entries:
            raise UserError(_('Please select at least one file to import.'))

        # Materialize one import line per uploaded file, skipping duplicate
        # filenames (defence in depth — the widget already dedupes on select).
        self.line_ids.unlink()
        seen_names = set()
        for entry in entries:
            entry = entry or {}
            data = entry.get('data')
            if not data:
                continue
            name = entry.get('name') or 'Untitled'
            if name in seen_names:
                continue  # duplicate filename — skip
            seen_names.add(name)
            self.env['xmind.import.line'].create({
                'wizard_id': self.id,
                'file': data,  # base64 string
                'filename': name,
                'status': 'pending',
            })

        created_ids = []

        for line in self.line_ids.filtered(lambda l: l.status == 'pending'):
            try:
                with self.env.cr.savepoint():
                    workbook = self._import_single_file(line)
                    # Generate server-side thumbnail
                    self._generate_thumbnail(workbook)
                line.write({
                    'status': 'success',
                    'message': _('Created: %s') % workbook.name,
                    'workbook_id': workbook.id,
                })
                created_ids.append(workbook.id)
            except Exception as e:
                import logging
                _logger = logging.getLogger(__name__)
                _logger.exception('XMind import failed for %s', line.filename)
                line.write({
                    'status': 'error',
                    'message': str(e)[:200],
                })

        if not created_ids:
            errors = self.line_ids.filtered(lambda l: l.status == 'error').mapped('message')
            error_detail = '\n'.join(errors) if errors else _('Unknown error')
            raise UserError(_('Import failed:\n%s') % error_detail)

        if len(created_ids) == 1:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'xmind.workbook',
                'res_id': created_ids[0],
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'xmind.workbook',
            'view_mode': 'kanban,list,form',
            'domain': [('id', 'in', created_ids)],
            'target': 'current',
        }

    def _generate_thumbnail(self, workbook):
        """Generate a server-side thumbnail PNG from the SVG renderer."""
        try:
            svg_content = workbook._generate_svg()
            # Try cairosvg for high-quality PNG
            try:
                import cairosvg
                png_data = cairosvg.svg2png(
                    bytestring=svg_content.encode('utf-8'),
                    output_width=400,
                )
                workbook.thumbnail = base64.b64encode(png_data)
            except ImportError:
                # Fallback: store SVG as-is (Odoo image widget can handle it via base64)
                workbook.thumbnail = base64.b64encode(svg_content.encode('utf-8'))
        except Exception:
            pass  # Thumbnail generation is best-effort

    def _import_single_file(self, line):
        """Import a single file and return the created workbook."""
        filename = line.filename or 'Untitled'
        file_data = base64.b64decode(line.file)
        ext = os.path.splitext(filename)[1].lower()

        name = os.path.splitext(filename)[0]

        if not ext:
            ext = self._detect_format(file_data)

        if ext in ('.xmind',):
            workbook = self._import_xmind(file_data, name)
        elif ext in ('.mm',):
            workbook = self._import_freemind(file_data, name)
        elif ext in ('.mmap',):
            workbook = self._import_mindmanager(file_data, name)
        else:
            raise UserError(
                _('Unsupported file format: %s. Supported: .xmind, .mm, .mmap') % (ext or _('(none)'))
            )

        return workbook

    def _detect_format(self, file_data):
        """Auto-detect file format from content."""
        if file_data[:4] == b'PK\x03\x04':
            try:
                with zipfile.ZipFile(io.BytesIO(file_data), 'r') as zf:
                    names = zf.namelist()
                    if 'content.json' in names or 'content.xml' in names:
                        return '.xmind'
                    if 'Document.xml' in names:
                        return '.mmap'
            except zipfile.BadZipFile:
                pass
        if file_data[:5] == b'<?xml' or file_data.lstrip()[:5] == b'<map>' or file_data.lstrip()[:5] == b'<map ':
            return '.mm'
        return ''

    def _import_xmind(self, file_data, default_name):
        """Import .xmind file → new Workbook with name from root topic."""
        try:
            with zipfile.ZipFile(io.BytesIO(file_data), 'r') as zf:
                file_list = zf.namelist()

                if 'content.json' in file_list:
                    content = json.loads(zf.read('content.json'))
                    root_title = default_name
                    if content and isinstance(content, list) and len(content) > 0:
                        first_sheet = content[0]
                        root_topic = first_sheet.get('rootTopic', {})
                        if root_topic.get('title'):
                            root_title = root_topic['title']

                    workbook = self.env['xmind.workbook'].create({
                        'name': root_title,
                        'creator': self.env.user.name,
                        'xmind_file': base64.b64encode(file_data),
                        'xmind_filename': default_name + '.xmind',
                    })
                    workbook.import_xmind_file()
                    if root_title != default_name:
                        workbook.name = root_title
                    return workbook

                elif 'content.xml' in file_list:
                    import xml.etree.ElementTree as ET
                    content_xml = zf.read('content.xml')
                    root = ET.fromstring(content_xml)
                    ns = {'xmap': 'urn:xmind:xmap:xmlns:content:2.0'}

                    root_title = default_name
                    sheet_elem = root.find('.//xmap:sheet', ns)
                    if sheet_elem is not None:
                        title_elem = sheet_elem.find('xmap:title', ns)
                        if title_elem is not None and title_elem.text:
                            root_title = title_elem.text
                        topic_elem = sheet_elem.find('xmap:topic/xmap:title', ns)
                        if topic_elem is not None and topic_elem.text:
                            root_title = topic_elem.text

                    workbook = self.env['xmind.workbook'].create({
                        'name': root_title,
                        'creator': self.env.user.name,
                        'xmind_file': base64.b64encode(file_data),
                        'xmind_filename': default_name + '.xmind',
                    })
                    workbook.import_xmind_file()
                    if root_title != default_name:
                        workbook.name = root_title
                    return workbook

                else:
                    raise UserError(_('Invalid XMind file: no content found'))
        except zipfile.BadZipFile:
            raise UserError(_('Invalid file: not a valid ZIP archive'))

    def _import_freemind(self, file_data, default_name):
        """Import .mm file → new Workbook with name from root node TEXT."""
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(file_data)
            map_node = root if root.tag == 'node' else root.find('node')
            root_title = default_name
            if map_node is not None:
                root_title = map_node.get('TEXT', default_name) or default_name

            workbook = self.env['xmind.workbook'].create({
                'name': root_title,
                'creator': self.env.user.name,
                'xmind_file': base64.b64encode(file_data),
                'xmind_filename': default_name + '.mm',
            })
            workbook.import_freemind_file()
            workbook.name = root_title
            return workbook
        except ET.ParseError as e:
            raise UserError(_('Invalid FreeMind XML: %s') % str(e))

    def _import_mindmanager(self, file_data, default_name):
        """Import .mmap file → new Workbook."""
        workbook = self.env['xmind.workbook'].create({
            'name': default_name,
            'creator': self.env.user.name,
            'xmind_file': base64.b64encode(file_data),
            'xmind_filename': default_name + '.mmap',
        })
        workbook.import_mindmanager_file()
        return workbook
