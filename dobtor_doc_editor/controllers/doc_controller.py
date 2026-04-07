import base64
import json
import subprocess
import tempfile
import os
from odoo import http
from odoo.http import request


class DocEditorController(http.Controller):

    @http.route('/dobtor_doc/load', type='json', auth='user', methods=['POST'])
    def load_document(self, doc_id, **kw):
        """載入文件資料（HTML 內容＋頁面設定）。"""
        doc = request.env['doc.document'].browse(doc_id)
        doc.check_access_rule('read')
        return {
            'id': doc.id,
            'name': doc.name,
            'content_html': doc.get_content_html(),
            'header_html': doc.header_html or '',
            'footer_html': doc.footer_html or '',
            'page_format': doc.page_format,
            'margin_top': doc.margin_top,
            'margin_bottom': doc.margin_bottom,
            'margin_left': doc.margin_left,
            'margin_right': doc.margin_right,
            'model_id': doc.model_id.id if doc.model_id else False,
            'model_name': doc.model_id.model if doc.model_id else False,
            'has_different_first_page': doc.has_different_first_page,
            'first_header_html': doc.first_header_html or '',
            'first_footer_html': doc.first_footer_html or '',
        }

    @http.route('/dobtor_doc/save', type='json', auth='user', methods=['POST'])
    def save_document(self, doc_id=None, content_html=None, header_html=None,
                      footer_html=None, name=None, **kw):
        """儲存文件 HTML 內容。"""
        if not doc_id:
            return {'success': False, 'error': 'doc_id required'}
        doc = request.env['doc.document'].browse(doc_id)
        doc.check_access_rule('write')
        vals = {}
        if content_html is not None:
            vals['content_html'] = content_html
        if header_html is not None:
            vals['header_html'] = header_html
        if footer_html is not None:
            vals['footer_html'] = footer_html
        if name is not None:
            vals['name'] = name
        if vals:
            doc.write(vals)
        return {'success': True, 'write_date': doc.write_date.isoformat()}

    @http.route('/dobtor_doc/save_settings', type='json', auth='user', methods=['POST'])
    def save_settings(self, doc_id, **kw):
        """儲存頁面格式與邊距設定。"""
        doc = request.env['doc.document'].browse(doc_id)
        doc.check_access_rule('write')
        allowed = ('page_format', 'margin_top', 'margin_bottom',
                   'margin_left', 'margin_right',
                   'default_column_count', 'default_column_gap', 'column_rule_style')
        vals = {k: v for k, v in kw.items() if k in allowed}
        if vals:
            doc.write(vals)
        return {'success': True}

    @http.route('/dobtor_doc/fields', type='json', auth='user', methods=['POST'])
    def get_fields(self, model_name, doc_id=None, **kw):
        """取得指定模型的可用欄位清單。"""
        mixin = request.env['doc.render.mixin']
        try:
            return mixin.get_available_fields(model_name)
        except Exception as e:
            return {'error': str(e)}

    @http.route('/dobtor_doc/render_preview', type='json', auth='user', methods=['POST'])
    def render_preview(self, doc_id, record_model, record_id, **kw):
        """將欄位變數渲染為實際值（預覽用）。"""
        doc = request.env['doc.document'].browse(doc_id)
        doc.check_access_rule('read')
        try:
            record = request.env[record_model].browse(record_id)
            record.check_access_rule('read')
            rendered = doc._render_template(doc.get_content_html(), record)
            return {'html': rendered}
        except Exception as e:
            return {'error': str(e)}

    @http.route('/dobtor_doc/export', type='json', auth='user', methods=['POST'])
    def export_document(self, doc_id, format='pdf', quality='high',
                        record_model=None, record_id=None, **kw):
        """匯出文件為 PDF 或 DOCX。quality: 'high'（後端）"""
        doc = request.env['doc.document'].browse(doc_id)
        doc.check_access_rule('read')

        record = None
        if record_model and record_id:
            try:
                record = request.env[record_model].browse(record_id)
                record.check_access_rule('read')
            except Exception:
                record = None

        try:
            if format == 'pdf':
                file_bytes = doc._generate_pdf(record=record)
                mimetype = 'application/pdf'
                filename = f'{doc.name}.pdf'
            elif format == 'docx':
                file_bytes = doc._generate_docx_via_libreoffice(record=record)
                mimetype = ('application/vnd.openxmlformats-officedocument'
                            '.wordprocessingml.document')
                filename = f'{doc.name}.docx'
            else:
                return {'error': f'不支援的格式：{format}'}

            return {
                'filename': filename,
                'data': base64.b64encode(file_bytes).decode(),
                'mimetype': mimetype,
            }
        except Exception as e:
            return {'error': str(e)}

    @http.route('/dobtor_doc/save_version', type='json', auth='user', methods=['POST'])
    def save_version(self, doc_id, label=None, **kw):
        """儲存版本快照。"""
        doc = request.env['doc.document'].browse(doc_id)
        doc.check_access_rule('write')
        doc.action_save_version(label=label)
        return {'success': True}

    @http.route('/dobtor_doc/import', type='http', auth='user', methods=['POST'], csrf=False)
    def import_document(self, **kw):
        """匯入 DOCX / ODT 檔案，轉換為 HTML。"""
        upload = request.httprequest.files.get('file')
        if not upload:
            return request.make_response(
                json.dumps({'error': '未收到檔案'}),
                headers={'Content-Type': 'application/json'},
            )

        filename = upload.filename or ''
        ext = os.path.splitext(filename)[1].lower()

        # 後端 LibreOffice 轉換
        import shutil
        if not shutil.which('soffice'):
            return request.make_response(
                json.dumps({'error': 'LibreOffice 未安裝，無法轉換。請安裝後重試。'}),
                headers={'Content-Type': 'application/json'},
            )

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                in_path = os.path.join(tmpdir, f'input{ext}')
                upload.save(in_path)
                result = subprocess.run(
                    ['soffice', '--headless', '--norestore',
                     '--convert-to', 'html:HTML', '--outdir', tmpdir, in_path],
                    capture_output=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    raise Exception(result.stderr.decode('utf-8', errors='replace'))

                html_path = os.path.join(tmpdir, 'input.html')
                if not os.path.exists(html_path):
                    raise Exception('找不到轉換後的 HTML 檔案')

                with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
                    html = f.read()

                # 只取 body 內容
                import re
                body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
                body_html = body_match.group(1).strip() if body_match else html

                return request.make_response(
                    json.dumps({'html': body_html}),
                    headers={'Content-Type': 'application/json'},
                )
        except Exception as e:
            return request.make_response(
                json.dumps({'error': str(e)}),
                headers={'Content-Type': 'application/json'},
            )
