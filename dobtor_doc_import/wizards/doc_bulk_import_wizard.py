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

from odoo import fields, models, _
from odoo.exceptions import UserError

from odoo.addons.dobtor_doc_editor.models.doc_zip_guard import ZipBombError, inspect_zip_safe

# ☠️ 這支原本寫在迴圈裡 `from ..controllers.doc_controller import
#    _docx_to_html_with_format`——那是 2026-05 controller 拆層**之前**的位置，
#    函式早就搬到 doc_convert.py 了。因為它在 try 裡面，ImportError 被下面的
#    `except Exception` 吞掉，於是每個檔案都走「跳過」分支：精靈回報成功、
#    建出 0 份文件、log 只說某個例外。拆模組時四則測試一起變紅才抓到。
#    改成檔頭 import：載不到就是模組載入失敗，不會變成靜默跳過。
from ..controllers.doc_convert import _docx_to_html_with_format

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
        # UI 層只給自己所屬的公司。
        # ☠️ 這只是第一層——domain **擋不住 RPC**，真正的把關在
        #    action_run_import 開頭那道檢查。
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
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

        # ☠️ 2026-10-09 實測的真缺陷：這裡原本是 `Doc.sudo().create(...)`，而
        #    target_company_id 沒有任何約束。一個只屬於 A 公司的 doc manager
        #    可以用 RPC 把 target 設成他**連讀都讀不到**的 B 公司，文件就被建到
        #    B 公司去了（實測建出 1 份）。
        #
        #    兩層修正：
        #      1. 這道檢查——domain 擋不住 RPC，所以伺服端要自己判。
        #      2. 底下的 create 去掉 sudo()——讓 doc.document 的 record rule
        #         （rule_doc_document_company）真的發揮作用。
        #
        #    為什麼需要「1」而不是只靠「2」：create 在逐檔的 try/except 裡，
        #    AccessError 會被算進 failed_count，使用者只看到「全部失敗」而不知道
        #    原因。這道檢查讓它變成一句清楚的訊息。
        if self.target_company_id not in self.env.companies:
            raise UserError(_(
                '目標公司「%(company)s」不在你目前啟用的公司範圍內，不能匯入到那裡。',
                company=self.target_company_id.sudo().display_name,
            ))

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
                    body_html = _docx_to_html_with_format(docx_bytes)
                    name = info.filename.rsplit('.docx', 1)[0]
                    if '/' in name:
                        name = name.rsplit('/', 1)[-1]

                    Doc.create({
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
