"""批次匯入 wizard（P3-1 客戶導入流程）。

讓 ChienYi 客戶把既有的 DOCX 文件一次匯入成 doc.document：
    1. 上傳一個 .zip 含多個 .docx
    2. wizard 解開 zip，每個 docx 建立一筆 doc.document
    3. 套用 zip_guard（W1）+ 既有 _docx_to_html_with_format 解析（既有功能）
    4. 回傳建立筆數 + 失敗清單

設計取捨：
    - 不接 portal user（避免大量上傳濫用）
    - 失敗時不 abort，逐筆收集錯誤訊息
    - 預設套上「批次匯入 YYYY-MM-DD」分類，方便事後清理
"""

import io
import logging
import zipfile
import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.doc_zip_guard import (
    ZipBombError,
    inspect_zip_safe,
    DEFAULT_OUTPUT_MAX_BYTES,
    DEFAULT_MAX_ENTRIES,
)

_logger = logging.getLogger(__name__)


class DocBulkImportWizard(models.TransientModel):
    _name = 'doc.bulk.import.wizard'
    _description = '批次匯入文件（P3-1）'

    archive_file = fields.Binary(
        string='ZIP 壓縮檔',
        required=True,
        help='含多個 .docx 的 .zip 檔。每個 .docx 將建立一筆 doc.document。',
    )
    archive_filename = fields.Char(string='檔名')
    target_company_id = fields.Many2one(
        'res.company', string='目標公司',
        default=lambda self: self.env.company,
        required=True,
    )
    skip_failures = fields.Boolean(
        string='略過失敗檔案', default=True,
        help='打開：失敗檔案略過，繼續處理其他檔案；關閉：第一個失敗就 abort。',
    )
    state = fields.Selection([
        ('draft', '待匯入'),
        ('done', '完成'),
        ('failed', '失敗'),
    ], default='draft')
    log_text = fields.Text(string='匯入結果', readonly=True)
    created_count = fields.Integer(string='已建立筆數', readonly=True)
    failed_count = fields.Integer(string='失敗筆數', readonly=True)

    def action_run_import(self):
        """執行批次匯入。"""
        self.ensure_one()
        if not self.archive_file:
            raise UserError(_('請先上傳 ZIP 檔案。'))

        # 解碼 base64 → bytes
        try:
            raw = base64.b64decode(self.archive_file)
        except Exception as e:
            raise UserError(_('檔案解碼失敗：%s') % e)

        # 套用 zip_guard 安全檢查（沿用 W1 的 doc_zip_guard）
        # 對 archive 用較寬的限制：解壓 500MB / 5000 entry（批次匯入合理量）
        try:
            inspect_zip_safe(
                raw,
                max_total_uncompressed=500 * 1024 * 1024,
                max_entries=5000,
            )
        except ZipBombError as e:
            self.write({
                'state': 'failed',
                'log_text': str(e),
            })
            return self._reload_self()

        Doc = self.env['doc.document']
        created_count = 0
        failed_count = 0
        log_lines = []

        category_label = '批次匯入_%s' % fields.Date.today().isoformat()

        try:
            zf = zipfile.ZipFile(io.BytesIO(raw), 'r')
        except zipfile.BadZipFile:
            self.write({
                'state': 'failed',
                'log_text': _('無法開啟 ZIP 壓縮檔：格式不合法。'),
            })
            return self._reload_self()

        try:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if not info.filename.lower().endswith('.docx'):
                    log_lines.append(_('SKIP: %s（非 .docx）') % info.filename)
                    continue
                try:
                    docx_bytes = zf.read(info)
                    # 對單一 docx 也做 zip_guard 檢查
                    inspect_zip_safe(docx_bytes)
                    # 沿用既有 _docx_to_html_with_format（在 doc_controller 內）
                    # 但 wizard 屬於 model 層，引用時用 import 形式
                    from ..controllers.doc_controller import _docx_to_html_with_format
                    body_html = _docx_to_html_with_format(docx_bytes)
                    name = info.filename.rsplit('.docx', 1)[0]
                    if '/' in name:
                        name = name.rsplit('/', 1)[-1]

                    Doc.sudo().create({
                        'name': '%s [%s]' % (name, category_label),
                        'company_id': self.target_company_id.id,
                        'content_html': body_html,
                    })
                    created_count += 1
                    log_lines.append(_('OK: %s') % info.filename)
                except Exception as e:
                    failed_count += 1
                    log_lines.append(_('FAIL: %(name)s — %(err)s') % {
                        'name': info.filename, 'err': str(e),
                    })
                    _logger.warning(
                        "Bulk import failed for %s: %s", info.filename, e,
                    )
                    if not self.skip_failures:
                        break
        finally:
            zf.close()

        self.write({
            'state': 'done' if not failed_count else (
                'done' if self.skip_failures else 'failed'
            ),
            'log_text': '\n'.join(log_lines[:200]) + (
                _('\n... (還有 %d 筆未顯示)') % (len(log_lines) - 200)
                if len(log_lines) > 200 else ''
            ),
            'created_count': created_count,
            'failed_count': failed_count,
        })
        return self._reload_self()

    def _reload_self(self):
        """匯入完後重開同一份 wizard，讓使用者看到結果。"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
