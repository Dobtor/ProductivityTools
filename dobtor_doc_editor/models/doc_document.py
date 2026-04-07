import base64
import subprocess
import tempfile
import os
from odoo import models, fields, api
from odoo.exceptions import UserError

# 超過此大小（bytes）自動存入 ir.attachment
CONTENT_SIZE_THRESHOLD = 500 * 1024  # 500 KB


class DocDocument(models.Model):
    _name = 'doc.document'
    _description = '文件'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'doc.render.mixin']
    _order = 'write_date desc'

    name = fields.Char(string='文件名稱', required=True, default='未命名文件', tracking=True)

    # 內容欄位（sanitize=False，由 Server-Side Sanitizer 在 create/write 中處理）
    content_html = fields.Html(
        string='內容',
        sanitize=False,
        sanitize_attributes=False,
    )
    header_html = fields.Html(
        string='頁首',
        sanitize=False,
        sanitize_attributes=False,
    )
    footer_html = fields.Html(
        string='頁尾',
        sanitize=False,
        sanitize_attributes=False,
    )

    # 文件設定
    model_id = fields.Many2one(
        'ir.model',
        string='關聯模型',
        ondelete='set null',
        help='用於欄位變數渲染的目標模型',
    )
    template_id = fields.Many2one(
        'doc.template',
        string='使用範本',
        ondelete='set null',
    )
    page_format = fields.Selection([
        ('A4', 'A4'),
        ('A3', 'A3'),
        ('A5', 'A5'),
        ('letter', 'Letter'),
        ('legal', 'Legal'),
    ], string='頁面格式', default='A4')
    margin_top = fields.Integer(string='上邊距 (px)', default=96)
    margin_bottom = fields.Integer(string='下邊距 (px)', default=96)
    margin_left = fields.Integer(string='左邊距 (px)', default=96)
    margin_right = fields.Integer(string='右邊距 (px)', default=96)
    has_different_first_page = fields.Boolean(string='首頁不同頁首/頁尾', default=False)
    first_header_html = fields.Html(string='首頁頁首', sanitize=False)
    first_footer_html = fields.Html(string='首頁頁尾', sanitize=False)

    # 協作者
    collaborator_ids = fields.Many2many(
        'res.users',
        'doc_document_collaborator_rel',
        'document_id', 'user_id',
        string='協作者',
    )

    # 多公司隔離
    company_id = fields.Many2one(
        'res.company',
        string='公司',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    # 大文件 attachment 策略（>500KB 自動存入 ir.attachment）
    content_attachment_id = fields.Many2one(
        'ir.attachment',
        string='內容附件（大文件）',
        ondelete='set null',
    )
    is_large_document = fields.Boolean(string='大文件', default=False)

    # 多欄排版預設值
    default_column_count = fields.Selection([
        ('1', '1 欄'), ('2', '2 欄'), ('3', '3 欄'),
    ], string='預設欄數', default='1')
    default_column_gap = fields.Integer(string='欄間距 (px)', default=24)
    column_rule_style = fields.Selection([
        ('none', '無'), ('solid', '實線'), ('dashed', '虛線'), ('dotted', '點線'),
    ], string='欄分隔線', default='none')

    # 需要 sanitize 的 HTML 欄位清單
    _HTML_FIELDS = ('content_html', 'header_html', 'footer_html',
                    'first_header_html', 'first_footer_html')

    # ─── CRUD Hooks ─────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        sanitizer = self.env['doc.sanitizer']
        for vals in vals_list:
            for field in self._HTML_FIELDS:
                if vals.get(field):
                    vals[field] = sanitizer.sanitize_html(vals[field])
        return super().create(vals_list)

    def write(self, vals):
        sanitizer = self.env['doc.sanitizer']
        for field in self._HTML_FIELDS:
            if vals.get(field):
                vals[field] = sanitizer.sanitize_html(vals[field])

        # 大文件自動存入 attachment
        if 'content_html' in vals and vals['content_html']:
            html = vals['content_html']
            if len(html.encode('utf-8')) > CONTENT_SIZE_THRESHOLD:
                for rec in self:
                    att = rec._store_content_as_attachment(html)
                    vals['content_attachment_id'] = att.id
                    vals['is_large_document'] = True
                    vals['content_html'] = ''
            else:
                vals['is_large_document'] = False

        return super().write(vals)

    def _store_content_as_attachment(self, html):
        """將大文件內容存入 ir.attachment。"""
        self.ensure_one()
        data = base64.b64encode(html.encode('utf-8'))
        if self.content_attachment_id:
            self.content_attachment_id.write({'datas': data})
            return self.content_attachment_id
        return self.env['ir.attachment'].create({
            'name': f'doc_content_{self.id}.html',
            'type': 'binary',
            'datas': data,
            'res_model': 'doc.document',
            'res_id': self.id,
        })

    def get_content_html(self):
        """統一取得 HTML 內容（自動判斷來源）。"""
        self.ensure_one()
        if self.is_large_document and self.content_attachment_id:
            return base64.b64decode(self.content_attachment_id.datas).decode('utf-8')
        return self.content_html or ''

    # ─── Actions ─────────────────────────────────────────────────────

    def action_open_editor(self):
        """開啟全螢幕文件編輯器。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'dobtor_doc_editor.action_doc_editor',
            'context': {
                'doc_id': self.id,
                'doc_name': self.name,
            },
            'target': 'fullscreen',
        }

    def action_export_pdf(self):
        """匯出 PDF 並下載。"""
        self.ensure_one()
        pdf_bytes = self._generate_pdf()
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_bytes),
            'res_model': 'doc.document',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def action_export_docx(self):
        """匯出 DOCX 並下載。"""
        self.ensure_one()
        docx_bytes = self._generate_docx_via_libreoffice()
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}.docx',
            'type': 'binary',
            'datas': base64.b64encode(docx_bytes),
            'res_model': 'doc.document',
            'res_id': self.id,
            'mimetype': ('application/vnd.openxmlformats-officedocument'
                         '.wordprocessingml.document'),
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    # ─── 後端匯出邏輯 ─────────────────────────────────────────────────

    def _build_full_html(self, rendered_body=None):
        """組合完整的 HTML 文件（頁首＋內文＋頁尾），含 CSS 設定。"""
        self.ensure_one()
        body = rendered_body or self.get_content_html()
        header = self.header_html or ''
        footer = self.footer_html or ''

        page_sizes = {
            'A4': ('210mm', '297mm'),
            'A3': ('297mm', '420mm'),
            'letter': ('215.9mm', '279.4mm'),
            'legal': ('215.9mm', '355.6mm'),
        }
        w, h = page_sizes.get(self.page_format, ('210mm', '297mm'))
        mt = self.margin_top
        mr = self.margin_right
        mb = self.margin_bottom
        ml = self.margin_left

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
@page {{
    size: {w} {h};
    margin: {mt}px {mr}px {mb}px {ml}px;
}}
body {{
    font-family: 'Microsoft JhengHei', 'Noto Sans TC', 'Arial', sans-serif;
    font-size: 12pt;
    line-height: 1.6;
    color: #333;
    margin: 0;
    padding: 0;
}}
.doc-header {{ margin-bottom: 12px; border-bottom: 1px solid #ddd; padding-bottom: 8px; }}
.doc-footer {{ margin-top: 12px; border-top: 1px solid #ddd; padding-top: 8px; font-size: 10pt; }}
.doc-page-break {{ page-break-after: always; }}
.doc-field-token {{
    background: #e3f2fd;
    border: 1px solid #90caf9;
    border-radius: 3px;
    padding: 1px 4px;
    font-family: monospace;
    font-size: 0.875em;
    color: #1565c0;
}}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #ccc; padding: 6px; }}
</style>
</head>
<body>
{'<div class="doc-header">' + header + '</div>' if header else ''}
<div class="doc-body">{body}</div>
{'<div class="doc-footer">' + footer + '</div>' if footer else ''}
</body>
</html>"""

    def _generate_pdf(self, record=None):
        """使用 Odoo 內建 wkhtmltopdf 產生 PDF。"""
        self.ensure_one()
        body = self.get_content_html()
        if record:
            body = self._render_template(body, record)

        full_html = self._build_full_html(rendered_body=body)
        Report = self.env['ir.actions.report']
        pdf_bytes = Report._run_wkhtmltopdf(
            [full_html.encode('utf-8')],
            landscape=False,
            specific_paperformat_args={
                'data-report-margin-top': self.margin_top,
                'data-report-margin-bottom': self.margin_bottom,
                'data-report-margin-left': self.margin_left,
                'data-report-margin-right': self.margin_right,
            },
        )
        return pdf_bytes

    def _generate_docx_via_libreoffice(self, record=None):
        """使用 LibreOffice headless 將 HTML 轉換為 DOCX。"""
        self.ensure_one()
        import shutil
        if not shutil.which('soffice'):
            raise UserError(
                'LibreOffice headless (soffice) 未安裝，無法匯出 DOCX。\n'
                '請在 Docker 容器中安裝 LibreOffice：\n'
                'apt-get install -y libreoffice'
            )

        body = self.get_content_html()
        if record:
            body = self._render_template(body, record)

        full_html = self._build_full_html(rendered_body=body)

        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = os.path.join(tmpdir, 'input.html')
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(full_html)

            result = subprocess.run(
                ['soffice', '--headless', '--norestore',
                 '--convert-to', 'docx', '--outdir', tmpdir, html_path],
                capture_output=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise UserError(
                    f'LibreOffice 轉換失敗：{result.stderr.decode("utf-8", errors="replace")}'
                )

            docx_path = os.path.join(tmpdir, 'input.docx')
            if not os.path.exists(docx_path):
                raise UserError('LibreOffice 轉換後找不到輸出檔案。')

            with open(docx_path, 'rb') as f:
                return f.read()

    # ─── 版本快照 ────────────────────────────────────────────────────

    def action_save_version(self, label=None):
        """在 mail thread 中儲存版本快照。"""
        self.ensure_one()
        html = self.get_content_html()
        self.message_post(
            body=f'<div class="doc-version-snapshot">'
                 f'<strong>版本快照</strong> {label or ""}<br/>{html}</div>',
            subtype_xmlid='mail.mt_note',
            message_type='comment',
        )

    def get_version_list(self):
        """取得版本快照清單。"""
        self.ensure_one()
        messages = self.message_ids.filtered(
            lambda m: '<div class="doc-version-snapshot"' in (m.body or '')
        )
        return [
            {'id': msg.id, 'date': str(msg.date), 'author': msg.author_id.name}
            for msg in messages.sorted('date', reverse=True)
        ]

    # ─── DB 索引 ─────────────────────────────────────────────────────

    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS doc_document_company_write_date_idx
            ON doc_document (company_id, write_date DESC);
            CREATE INDEX IF NOT EXISTS doc_document_company_model_idx
            ON doc_document (company_id, model_id) WHERE model_id IS NOT NULL;
        """)
