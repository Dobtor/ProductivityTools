"""輸出成品：一次列印的結果。唯讀。

與 doc.template（範本）、doc.document（人寫的文件）的差別在三件事都不同：
擁有者是系統、生命週期是一次性高量、可變性是唯讀。
能編輯已發出的單據等於允許事後改寫記錄，整份輸出紀錄就失去稽核價值。

「印出去之前想改一下」的出路是 action_create_editable_copy()：
複製成一筆 doc.document（那個模型本來就為「人會編輯的文件」設計），
output 本身完全不動，稽核鏈完整。

唯讀是在 ir.model.access.csv 做的（perm_write=0 / perm_unlink=0），
不是只靠前端旗標——只靠前端的話任何人用 RPC 都能繞過。
"""
import base64
import json
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DocOutput(models.Model):
    r"""文件輸出紀錄（系統產生，不是使用者建的）。

    ☠️ **ACL 的形狀是刻意的，別「順手補齊」**（2026-10-09 稽核：可做 3）：

        group_doc_editor   R
        group_doc_manager  R ＋ **U**（可刪，不可寫不可建）
        group_doc_portal   R

    manager 有 unlink 沒有 create/write 看起來像漏的，其實不是：這些紀錄由
    `_record_output()` **以 sudo 建立**（原因寫在那支方法的 docstring：
    列印者可能對 doc.output 沒有 create 權限，它是系統紀錄）。給人工 create
    權限會讓「輸出紀錄」這件事失去意義——它要忠實反映實際印過什麼。
    保留 unlink 是為了讓管理者能清掉錯誤或過期的紀錄（另有 cron
    `_gc_expired_outputs` 做自動清理）。

    形狀由 `tests/test_acl_shapes.py` 釘住。要改 ACL 請先改那支測試，
    並在這裡寫下新的理由——Odoo 的 `ir.model.access.csv` **不支援註解**，
    所以理由只能寫在這裡。
    """

    _name = 'doc.output'
    _description = '文件輸出紀錄'
    # 需要 _parse_content_json / _flatten_content_json / _content_json_to_html /
    # _docx_bytes_from_html——全部在 mixin 上
    _inherit = ['doc.render.mixin']
    _order = 'rendered_at desc, id desc'
    _rec_name = 'display_name'

    doc_report_id = fields.Many2one(
        'doc.report',
        string='輸出定義',
        required=True,
        ondelete='restrict',
        index=True,
    )
    template_id = fields.Many2one(
        'doc.template',
        string='使用範本',
        related='doc_report_id.template_id',
        store=True,
        readonly=True,
    )
    template_version = fields.Integer(
        string='範本版本',
        readonly=True,
        help='產生此輸出時範本的版本號。用途是「追溯當時用哪一版」；'
             '重現則靠本筆自己的 content_json（已凍結），不依賴範本快照還在。',
    )
    # ─── 來源記錄 ────────────────────────────────────────────────────
    # res_model_id 用 Many2one 而非 Char：group by 才會顯示模型的中文名稱。
    # res_name 必須「存下來」而不是 related 即時取，兩個理由：
    #   1. res_id 是 Many2oneReference，無法直接搜尋或分組顯示名稱——清單只會是數字
    #   2. 來源單據日後可能被刪除或改名，而輸出紀錄要能永久回答「當時印的是哪一張」
    res_model_id = fields.Many2one(
        'ir.model',
        string='來源模型',
        required=True,
        ondelete='cascade',
        index=True,
    )
    res_model = fields.Char(
        string='來源模型技術名',
        related='res_model_id.model',
        store=True,
        readonly=True,
        index=True,
    )
    res_id = fields.Many2oneReference(
        string='來源記錄',
        model_field='res_model',
        required=True,
        index=True,
    )
    res_name = fields.Char(
        string='來源單據',
        readonly=True,
        index=True,
        help='產生輸出時來源記錄的名稱。刻意存成純文字，來源被刪除後仍可追溯。',
    )
    # ─── 內容與檔案 ──────────────────────────────────────────────────
    content_json = fields.Text(
        string='內容（凍結）',
        readonly=True,
        help='凍結後的元素樹。本身足以重現當時的輸出，不需另存範本。'
             '保留政策可單獨清掉這欄而保留紀錄與 PDF。',
    )
    attachment_id = fields.Many2one(
        'ir.attachment',
        string='輸出檔案',
        readonly=True,
        ondelete='set null',
    )
    output_format = fields.Selection(
        [('pdf', 'PDF'), ('docx', 'DOCX')],
        string='格式',
        default='pdf',
        readonly=True,
    )
    # ─── 稽核欄位 ────────────────────────────────────────────────────
    rendered_at = fields.Datetime(string='產生時間', readonly=True, index=True)
    rendered_by = fields.Many2one('res.users', string='產生者', readonly=True)
    company_id = fields.Many2one('res.company', string='公司', readonly=True)
    lang = fields.Char(string='語言', readonly=True)

    display_name = fields.Char(compute='_compute_display_name', store=True)
    source_exists = fields.Boolean(
        string='來源仍存在',
        compute='_compute_source_exists',
        help='來源記錄是否還在。已刪除時輸出紀錄仍保留，但無法再重新產生。',
    )

    @api.depends('res_name', 'template_id', 'rendered_at')
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.res_name or _('（來源已刪除）')]
            if rec.template_id:
                parts.append(rec.template_id.name)
            rec.display_name = ' · '.join(parts)

    def _compute_source_exists(self):
        for rec in self:
            rec.source_exists = bool(rec._resolve_source())

    def _resolve_source(self):
        """取回來源記錄；已刪除或無權限時回 None。"""
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return None
        if self.res_model not in self.env:
            return None
        try:
            record = self.env[self.res_model].browse(self.res_id)
            record.check_access('read')
            return record if record.exists() else None
        except Exception:
            return None

    # ─── 建立（只由渲染流程呼叫）─────────────────────────────────────

    @api.model
    def _record_output(self, doc_report, record, tree, attachment=None,
                       output_format='pdf'):
        """留存一筆輸出。tree 是已凍結的元素樹。

        以 sudo 建立：列印者可能對 doc.output 沒有 create 權限（它是系統紀錄，
        不是使用者資料），但不該因此讓列印失敗。
        """
        model_rec = self.env['ir.model'].sudo()._get(record._name)
        vals = {
            'doc_report_id': doc_report.id,
            'template_version': doc_report.template_id.version_number or 0,
            'res_model_id': model_rec.id,
            'res_id': record.id,
            'res_name': record.display_name or '',
            'content_json': json.dumps(tree, ensure_ascii=False) if tree else False,
            'attachment_id': attachment.id if attachment else False,
            'output_format': output_format,
            'rendered_at': fields.Datetime.now(),
            'rendered_by': self.env.user.id,
            'company_id': self.env.company.id,
            'lang': self.env.context.get('lang') or self.env.user.lang,
        }
        return self.sudo().create(vals)

    # ─── 動作 ────────────────────────────────────────────────────────

    def action_open_viewer(self):
        """在編輯器中唯讀瀏覽此輸出。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'dobtor_doc_editor.action_doc_editor',
            'context': {
                'output_id': self.id,
                'doc_name': self.display_name,
            },
            'target': 'fullscreen',
        }

    def action_download(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_('此輸出紀錄沒有附加檔案（可能已被保留政策清理）。'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.attachment_id.id,
            'target': 'new',
        }

    def action_download_docx(self):
        """把這筆輸出匯成 DOCX 下載。

        定案決策四：DOCX 定位是「匯出去編輯」的便利功能，不是正式輸出
        ——它要經 python-docx 轉換，無法保證與畫面一致，當成正式單據會有
        對不上的爭議。正式單據請用 PDF（attachment_id）。

        單筆限定：DOCX 沒有像 PDF 那樣的合併機制，而且 content_json 已凍結，
        一筆輸出就是一份文件，天然不需要多筆。
        """
        self.ensure_one()
        tree = self._parse_content_json(self.content_json)
        if tree is None:
            raise UserError(_(
                '此輸出的內容已被保留政策清理，無法匯出 DOCX。'
            ))
        tmpl = self.template_id
        import copy as _copy
        body = self._content_json_to_html(
            self._flatten_content_json(_copy.deepcopy(tree))
        )
        docx_bytes = self._docx_bytes_from_html(
            body,
            page_format=tmpl.page_format or 'A4',
            margins={
                'top': tmpl.margin_top, 'bottom': tmpl.margin_bottom,
                'left': tmpl.margin_left, 'right': tmpl.margin_right,
            },
            header_text=self._zone_html(tree, 'header'),
            footer_text=self._zone_html(tree, 'footer'),
        )
        attachment = self.env['ir.attachment'].create({
            'name': '%s.docx' % (self.res_name or 'document'),
            'type': 'binary',
            'datas': base64.b64encode(docx_bytes),
            'res_model': 'doc.output',
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument'
                        '.wordprocessingml.document',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'new',
        }

    def _zone_html(self, tree, zone):
        """取頁首/頁尾的 HTML（攤平後）。

        舊版在這裡把 HTML 壓成純文字（當時 _docx_bytes_from_html 只吃文字）。
        現在頁首頁尾走完整的節點轉換，壓成文字會讓頁碼變成字面的「頁碼」兩字，
        而且沒有任何錯誤訊息。
        """
        import copy as _copy
        flat = self._flatten_content_json(_copy.deepcopy(tree))
        return self._content_json_to_html(flat, zone=zone)

    def action_create_editable_copy(self):
        """以此輸出為基礎建立可編輯文件。

        輸出本身不可編輯（稽核要求），但「印出去前想改一下」是真實需求。
        複製成 doc.document：那個模型本來就為「人會編輯的文件」設計，
        協作者、版本快照、autosave 全部適用，不必為此發明第四個實體。
        output 完全不動，稽核鏈完整。
        """
        self.ensure_one()
        if not self.content_json:
            raise UserError(_(
                '此輸出的內容已被保留政策清理，無法建立可編輯副本。'
            ))
        doc = self.env['doc.document'].create({
            'name': _('%s（副本）') % self.display_name,
            'content_json': self.content_json,
            'template_id': self.template_id.id,
            'model_id': self.res_model_id.id,
            'res_id': self.res_id,
            'source_output_id': self.id,
            # 內容已是凍結值，不要讓它在匯出時又被重新求值
            'snapshot_date': self.rendered_at,
            'snapshot_res_id': self.res_id,
        })
        return doc.action_open_editor()

    # ─── 保留政策 ────────────────────────────────────────────────────

    @api.model
    def _gc_expired_outputs(self):
        """排程清理：依 doc.report.retention_days 清掉逾期輸出。

        刻意分兩段清：先清 content_json 與 attachment（佔空間的部分），
        紀錄本身（誰在何時印了什麼）保留。通常想知道的是「印過」這件事，
        而不是需要重新打開編輯器看當時的版面。
        """
        Report = self.env['doc.report'].sudo()
        now = fields.Datetime.now()
        purged = 0
        for report in Report.search([('retention_days', '>', 0)]):
            cutoff = now - timedelta(days=report.retention_days)
            expired = self.sudo().search([
                ('doc_report_id', '=', report.id),
                ('rendered_at', '<', cutoff),
                '|', ('content_json', '!=', False), ('attachment_id', '!=', False),
            ])
            if not expired:
                continue
            expired.mapped('attachment_id').sudo().unlink()
            expired.sudo().write({'content_json': False})
            purged += len(expired)
        return purged
