"""文件本身的路由：載入、存檔、設定、預覽、匯出匯入、版本。

類別名刻意不改（DocEditorController）——它是這個模組最早的
Controller，外部可能以名稱引用。
"""
import base64
import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
import os
import zipfile
import html as html_mod
from lxml import etree
from odoo import http
from odoo.exceptions import MissingError, UserError
from odoo.http import request

from ..models.doc_ins_syntax import _convert_ins_to_jinja
from ..models.doc_zip_guard import (
    assert_input_size,
    inspect_zip_safe,
    ZipBombError,
)

_logger = logging.getLogger(__name__)

# ─── DOCX XML 命名空間 ────────────────────────────────────────────────────────
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML = "http://www.w3.org/XML/1998/namespace"

# DOCX 段落樣式名稱 → HTML 標籤對應表（大小寫不敏感）
_HEADING_STYLES = {
    'heading1': 'h1', 'heading 1': 'h1',
    'heading2': 'h2', 'heading 2': 'h2',
    'heading3': 'h3', 'heading 3': 'h3',
    'heading4': 'h4', 'heading 4': 'h4',
    'heading5': 'h5', 'heading 5': 'h5',
    'heading6': 'h6', 'heading 6': 'h6',
}
from .doc_controller_base import DocControllerBase
# doc_convert 已隨檔案匯入搬到 dobtor_doc_import 模組（拆模組步驟 3）。
# 核心只留 models/doc_ins_syntax.py 的 _convert_ins_to_jinja（範本上傳用）。


class DocEditorController(DocControllerBase, http.Controller):

    @http.route('/dobtor_doc/load', type='json', auth='user', methods=['POST'])
    def load_document(self, doc_id=None, template_id=None, output_id=None, **kw):
        """載入編輯對象（doc.document 或 doc.template）的內容與設定。

        回傳值含 `write_date`，給前端做樂觀鎖（P2-2）：
            前端在後續 save 帶回 if_unmodified_since=write_date，
            後端比對若已變動則拒絕並回 409。
            範本模式同樣適用——範本開放直接編輯後，兩個管理者同開會互蓋。
        """
        record, kind = self._resolve_edit_target(
            doc_id, template_id, output_id, access='read',
        )
        if kind == 'template':
            return self._load_template_payload(record)
        if kind == 'output':
            return self._load_output_payload(record)
        doc = record
        return {
            'id': doc.id,
            'name': doc.name,
            'content_json': doc.content_json or '',
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
            'res_id': doc.res_id or False,
            'field_aliases': doc.field_aliases or {},
            'template_field_aliases': (doc.template_id.field_aliases or {}) if doc.template_id else {},
            'template_name': doc.template_id.name if doc.template_id else '',
            'has_template': bool(doc.template_docx),
            'template_filename': doc.template_filename or '',
            'template_variables': json.loads(doc.template_variables) if doc.template_variables else [],
            'has_different_first_page': doc.has_different_first_page,
            'first_header_html': doc.first_header_html or '',
            'first_footer_html': doc.first_footer_html or '',
            # P2-2 樂觀鎖用：給前端記下最後一次同步的 write_date
            'write_date': doc.write_date.isoformat() if doc.write_date else None,
            'version_number': doc.version_number or 0,
            'edit_target': 'document',
            # Phase 3 快照：前端據此顯示凍結時間，並判斷是否還需要跑舊的
            # 「自動預覽模式」（已快照的文件內容就是值，不必再即時渲染一次）
            'snapshot_date': doc.snapshot_date.isoformat() if doc.snapshot_date else None,
            'snapshot_is_stale': doc.snapshot_is_stale,
        }

    @http.route('/dobtor_doc/save', type='json', auth='user', methods=['POST'])
    def save_document(self, doc_id=None, template_id=None,
                      content_html=None, content_json=None,
                      header_html=None, footer_html=None, name=None,
                      if_unmodified_since=None, **kw):
        """儲存文件內容（content_json 為主，content_html 為備份）。

        P2-2 樂觀鎖：
            前端傳入 if_unmodified_since（從 load 回傳的 write_date），
            後端比對若 write_date 已變動 → 拒絕並回 409 形式（response 帶 conflict=True）。
            這避免兩個 user 同時編輯時，後存的人覆蓋前者沒看到的修改。

            前端收到 conflict=True 時應：
                1. 提示「文件已被他人修改」
                2. 自動 reload 拿最新內容
                3. 把使用者編輯的內容存到 IndexedDB 暫存（offline_manager）
        """
        if not doc_id and not template_id:
            return {'success': False, 'error': 'doc_id 或 template_id required'}
        doc, kind = self._resolve_edit_target(doc_id, template_id, access='write')

        # P2-2 樂觀鎖檢查（文件與範本共用同一套；範本模式尤其需要，
        # 因為範本是共用資源，被覆蓋的影響範圍是「所有使用它的文件」）
        if if_unmodified_since:
            current_wd = doc.write_date.isoformat() if doc.write_date else None
            # 用字串比對而非 datetime parse — 兩端都用 isoformat 應一致
            # 容忍微秒誤差：取秒為單位比對（或前端送什麼後端就比對什麼）
            if current_wd and current_wd != if_unmodified_since:
                _logger.info(
                    "Optimistic lock conflict on %s id=%s: client had %s, server has %s",
                    kind, doc.id, if_unmodified_since, current_wd,
                )
                return {
                    'success': False,
                    'conflict': True,
                    'error': '文件已被他人修改，請重新載入後再儲存。',
                    'server_write_date': current_wd,
                    'server_version_number': doc.version_number or 0,
                    'server_author_id': (
                        doc.write_uid.id if doc.write_uid else None
                    ),
                    'server_author_name': (
                        doc.write_uid.name if doc.write_uid else ''
                    ),
                }

        vals = {}
        if content_json is not None:
            vals['content_json'] = content_json
        if content_html is not None:
            vals['content_html'] = content_html
        if name is not None:
            vals['name'] = name
        # 頁首/頁尾只存在於 doc.document；範本模式收到也忽略，不讓前端狀態錯亂
        # 直接寫爆一個不存在的欄位。
        if kind == 'document':
            if header_html is not None:
                vals['header_html'] = header_html
            if footer_html is not None:
                vals['footer_html'] = footer_html
        if vals:
            doc.write(vals)
        return {
            'success': True,
            'write_date': doc.write_date.isoformat(),
            'version_number': doc.version_number or 0,
            'edit_target': kind,
        }

    @http.route('/dobtor_doc/save_settings', type='json', auth='user', methods=['POST'])
    def save_settings(self, doc_id=None, template_id=None, **kw):
        """儲存頁面格式與邊距設定（文件與範本雙入口）。

        範本也必須能存版面設定——報表引擎以範本的 page_format/margin_* 當列印依據
        （「編輯器裡看到的就是列印結果」），範本模式若存不進去，使用者調了邊距
        卻印出不同結果，而且不會有任何錯誤訊息。
        """
        target, kind = self._resolve_edit_target(doc_id, template_id, access='write')
        allowed = {'page_format', 'margin_top', 'margin_bottom',
                   'margin_left', 'margin_right'}
        if kind == 'document':
            # 多欄排版目前只有 doc.document 有
            allowed |= {'default_column_count', 'default_column_gap',
                        'column_rule_style'}
        vals = {k: v for k, v in kw.items() if k in allowed}
        if vals:
            target.write(vals)
        return {'success': True, 'edit_target': kind}

    @http.route('/dobtor_doc/upload_template', type='http', auth='user',
                methods=['POST'], csrf=False)
    @DocControllerBase.json_http_route
    def upload_template(self, doc_id, docx_file, **kw):
        """
        上傳 DOCX 模板：
        1. 把 +++INS name+++ 語法轉換為 {{ name }}（段落層級，處理 run 切割）
        2. 偵測 {{ variable }} 佔位符清單
        3. 儲存轉換後的位元組

        Sprint 116 plus:filename 含 null byte → graceful 400(避免 Postgres
        ROLLBACK 造成 500 leak trace);filename 取 basename 防 path traversal
        傳入 DB(深度防禦原則、紀律 #15 廣域應用)。
        """
        doc = self._require_document(doc_id, 'write')

        # Sprint 116 plus:filename 入口 sanitize
        raw_filename = getattr(docx_file, 'filename', '') or ''
        if '\x00' in raw_filename:
            return request.make_response(
                json.dumps({'success': False, 'error': 'invalid filename (null byte)'}),
                headers={'Content-Type': 'application/json'},
                status=400,
            )
        # 取 basename 防 path component 進 DB(深度防禦)
        safe_filename = os.path.basename(raw_filename.replace('\\', '/'))
        # 重新賦值給 docx_file.filename 讓後續邏輯用 sanitized 版本
        try:
            docx_file.filename = safe_filename
        except Exception:
            pass

        raw_bytes = docx_file.read()

        # ── Zip Bomb 防護（W1 P0-2）：檢查原檔大小、解壓總大小、entry 數量 ──
        try:
            assert_input_size(raw_bytes)
            inspect_zip_safe(raw_bytes)
        except ZipBombError as e:
            _logger.warning(
                "upload_template rejected by zip_guard: %s (file=%s, uid=%s)",
                e, getattr(docx_file, 'filename', '?'), request.env.user.id,
            )
            return request.make_response(
                json.dumps({'success': False, 'error': str(e)}),
                headers={'Content-Type': 'application/json'},
                status=400,
            )

        # 整段處理包 try/except：type='http' 路由若拋出未處理例外，Odoo 會回傳
        # HTML 500 錯誤頁，前端 resp.json() 解析失敗 → 「Unexpected token '<'」。
        # 改為一律回傳 JSON，讓真實錯誤（缺套件 / 非 docx / 解析失敗）顯示在 UI。
        variables = []
        try:
            # Step 1：轉換 +++INS+++ → {{ }}
            converted_bytes = _convert_ins_to_jinja(raw_bytes)

            # Step 2：偵測變數清單（從 ZIP 內的 document.xml）
            # 包含：{{ var }}、{{ item.field }}（取根名稱）、{% for v in collection %}（取集合名稱）
            try:
                with zipfile.ZipFile(io.BytesIO(converted_bytes)) as z:
                    xml = z.read('word/document.xml').decode('utf-8')
                # {{ var }} 或 {{ item.field }} → 取根名稱（點號前）
                raw_vars = re.findall(r'\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}', xml)
                root_vars = {v.split('.')[0] for v in raw_vars}
                # {% for v in collection %} 或 {% tr for v in collection %} → 取集合名稱
                for_cols = set(re.findall(
                    r'\{%-?\s+(?:tr\s+)?for\s+\w+\s+in\s+([A-Za-z_][A-Za-z0-9_.]*)\s*-?%\}', xml
                ))
                variables = sorted(root_vars | for_cols)
            except Exception:
                pass

            # Step 3：儲存轉換後的模板 + 變數清單
            doc.write({
                'template_docx': base64.b64encode(converted_bytes).decode(),
                'template_filename': docx_file.filename,
                'template_variables': json.dumps(variables),
            })
        except ImportError as e:
            _logger.exception("upload_template: 缺少 python-docx (doc_id=%s)", doc_id)
            return request.make_response(
                json.dumps({'success': False,
                            'error': '伺服器缺少 python-docx 套件，請安裝：pip install python-docx'}),
                headers={'Content-Type': 'application/json'}, status=500,
            )
        except zipfile.BadZipFile:
            return request.make_response(
                json.dumps({'success': False, 'error': '檔案不是有效的 .docx（無法解析 ZIP）'}),
                headers={'Content-Type': 'application/json'}, status=400,
            )
        except Exception as e:
            _logger.exception("upload_template 處理失敗 (doc_id=%s)", doc_id)
            return request.make_response(
                json.dumps({'success': False, 'error': '模板處理失敗：%s' % e}),
                headers={'Content-Type': 'application/json'}, status=500,
            )

        return request.make_response(
            json.dumps({'success': True, 'variables': variables}),
            headers={'Content-Type': 'application/json'}
        )

    @http.route('/dobtor_doc/fill_template', type='json', auth='user', methods=['POST'])
    def fill_template(self, doc_id, context=None, output_format='pdf', **kw):
        """
        用 docxtpl 填充模板，輸出 PDF（LibreOffice headless）或 DOCX。
        context：{variableName: value} 字典，對應模板中的 {{ variableName }}。
        """
        try:
            from docxtpl import DocxTemplate
        except ImportError:
            return {
                'success': False,
                'error': 'DOCX 模板填值需要 docxtpl 套件，目前環境未安裝。'
                         '請聯絡管理員執行：pip install docxtpl',
            }

        doc = self._require_document(doc_id, 'read')

        if not doc.template_docx:
            return {'success': False, 'error': '此文件尚未上傳 DOCX 模板'}

        raw_bytes = base64.b64decode(doc.template_docx)
        tpl = DocxTemplate(io.BytesIO(raw_bytes))
        tpl.render(context or {})

        filled_buf = io.BytesIO()
        tpl.save(filled_buf)
        filled_bytes = filled_buf.getvalue()

        if output_format == 'docx':
            return {
                'success': True,
                'content': base64.b64encode(filled_bytes).decode(),
                'filename': (doc.name or 'document') + '.docx',
                'mimetype': 'application/vnd.openxmlformats-officedocument'
                            '.wordprocessingml.document',
            }

        # PDF：LibreOffice headless
        # Sprint 70 修正：原註解誤宣稱「/usr/bin/soffice 已確認存在」，但 odoo18 container 是 minimal Ubuntu base、
        # 無 libreoffice 套件 → subprocess.run(check=True) 會 raise FileNotFoundError 500 給 user。
        # 加 graceful fallback（紀律 #11：production filesystem cross-check）。
        if not shutil.which('soffice'):
            return {
                'success': False,
                'error': 'PDF export 需要 LibreOffice — 當前 container 未安裝。請改用 output_format="docx"，'
                         '或聯絡管理員加裝 libreoffice 套件。',
                'fallback': 'docx',
            }
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                docx_path = os.path.join(tmpdir, 'input.docx')
                pdf_path = os.path.join(tmpdir, 'input.pdf')
                with open(docx_path, 'wb') as f:
                    f.write(filled_bytes)
                subprocess.run(
                    ['soffice', '--headless', '--convert-to', 'pdf',
                     '--outdir', tmpdir, docx_path],
                    check=True, timeout=60,
                    env={**os.environ, 'HOME': tmpdir}  # 防止 soffice 鎖定 ~/.config/libreoffice
                )
                with open(pdf_path, 'rb') as f:
                    pdf_bytes = f.read()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            return {
                'success': False,
                'error': f'LibreOffice PDF 轉換失敗：{type(e).__name__} — {str(e)[:200]}',
                'fallback': 'docx',
            }

        return {
            'success': True,
            'content': base64.b64encode(pdf_bytes).decode(),
            'filename': (doc.name or 'document') + '.pdf',
            'mimetype': 'application/pdf',
        }

    @http.route('/dobtor_doc/render_preview', type='json', auth='user', methods=['POST'])
    def render_preview(self, doc_id, record_model, record_id, **kw):
        """將欄位變數渲染為實際值（預覽用）。"""
        doc = self._require_document(doc_id, 'read')
        try:
            record = request.env[record_model].browse(record_id)
            record.check_access('read')
            rendered = doc._render_template(doc.get_content_html(), record, with_chip=True)
            return {'html': rendered}
        except Exception as e:
            return {'error': str(e)}

    @http.route('/dobtor_doc/preview_content_json', type='json', auth='user', methods=['POST'])
    def preview_content_json(self, doc_id, record_id=None, content_json=None, **kw):
        """把 content_json 內所有 token / {{ var }} 替換成實際值，回傳新的 JSON。

        編輯器「預覽模式」用：toggle 切到預覽時暫存原 content_json，呼叫本端點取代渲染後的版本，
        canvas-editor 直接 executeSetValue 上去，使用者可以看見實際值。

        content_json：可選。給了就渲染「這份當前編輯器內容」（保留已建的 control chip，只把
        殘餘 token 文字換成值）；沒給則用 doc 儲存的 content_json。前端開檔升級 chip 後會把
        當前內容傳進來，讓 chip 與其餘 token 的實際值「共存」而非被整份覆蓋。
        """
        doc = self._require_document(doc_id, 'read')
        rec_id = int(record_id) if record_id else doc.res_id
        if not doc.model_id or not rec_id:
            return {'error': '此文件未綁定 model_id 或 res_id'}
        try:
            record = request.env[doc.model_id.model].browse(rec_id)
            record.check_access('read')
            if not record.exists():
                return {'error': f'記錄 {doc.model_id.model}/{rec_id} 不存在'}
        except Exception as e:
            return {'error': f'記錄存取失敗：{e}'}

        # 合併 alias map（template + doc 自己）
        aliases = doc._collect_field_aliases()
        if not aliases:
            return {'error': '尚無 alias 對映'}

        # 拆 token / varname
        import re as _re
        token_alias = {}
        var_alias = {}
        for k, v in aliases.items():
            ks = str(k).strip()
            vs = str(v).strip()
            if not ks or not vs:
                continue
            if _re.match(r'^[A-Za-z_]\w*$', ks):
                var_alias[ks] = vs
            else:
                token_alias[ks] = vs

        # 準備 Jinja2 環境。
        # 補遺五（安全）：這裡原本自己 new 了一個裸 SandboxedEnvironment，
        # 繞過 _DocSandboxedEnvironment 的 ORM 提權黑名單（env/sudo/browse/write），
        # 等於任何有 doc 讀取權的使用者可在預覽路徑跑 {{ object.env[...].sudo()... }}。
        # 一律改走 mixin 的單一建構點。
        env_j = doc._get_sandbox_env(record)

        def _eval(expression):
            try:
                tpl = env_j.from_string('{{ ' + expression + ' }}')
                return tpl.render(object=record, user=request.env.user)
            except Exception:
                return ''

        # 預編譯所有 alias 的渲染結果（cache 重複 token）
        token_to_value = {tk: _eval(expr) for tk, expr in token_alias.items()}
        var_to_value = {vn: _eval(expr) for vn, expr in var_alias.items()}

        _token_pat = _re.compile(r'《([^》]+)》')
        _var_pat = _re.compile(r'\{\{\s*([A-Za-z_]\w*)\s*\}\}')

        def _replace_text(text):
            if not isinstance(text, str) or not text:
                return text
            def _rt(m):
                return token_to_value.get(m.group(1).strip(), m.group(0))
            text = _token_pat.sub(_rt, text)
            def _rv(m):
                return var_to_value.get(m.group(1).strip(), m.group(0))
            return _var_pat.sub(_rv, text)

        # 遞迴掃 content_json：優先用前端傳入的當前內容（含 chip），否則用 doc 儲存的
        import json as _json
        cj = content_json if content_json is not None else doc.content_json
        if isinstance(cj, str):
            try:
                cj = _json.loads(cj)
            except Exception:
                return {'error': 'content_json 無法解析'}
        if not cj:
            return {'error': 'content_json 為空'}

        # 深複製避免改到 cache
        import copy as _copy
        cj = _copy.deepcopy(cj)

        def _walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == 'value' and isinstance(v, str):
                        node[k] = _replace_text(v)
                    else:
                        _walk(v)
            elif isinstance(node, list):
                for it in node:
                    _walk(it)

        _walk(cj)
        return {'success': True, 'content_json': cj}

    @http.route('/dobtor_doc/preview/<int:doc_id>', type='http', auth='user', methods=['GET'])
    def preview_document(self, doc_id, record_id=None, **kw):
        """瀏覽器直接打開的預覽頁（form view「快速預覽」按鈕用）。

        參數：
          record_id：可選；未指定時用 doc.res_id。
        """
        doc = request.env['doc.document'].browse(int(doc_id))
        try:
            doc.check_access('read')
        except Exception:
            return request.not_found()

        # 決定渲染用 record
        rec_id = int(record_id) if record_id else doc.res_id
        rec = None
        rec_model = doc.model_id.model if doc.model_id else None
        if rec_model and rec_id:
            try:
                rec = request.env[rec_model].browse(rec_id)
                rec.check_access('read')
                if not rec.exists():
                    rec = None
            except Exception:
                rec = None

        # 渲染（帶 chip 樣式）
        body = doc._render_template(doc.get_content_html(), rec, with_chip=True) if rec \
            else doc.get_content_html() or '<p><em>（文件無內容）</em></p>'

        doc_name = html_mod.escape(doc.name or '未命名文件')
        record_label = html_mod.escape(rec.display_name) if rec else '（無綁定記錄）'
        full_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>預覽：{doc_name}</title>
<style>
body {{
  font-family: 'Microsoft JhengHei', 'Noto Sans TC', Arial, sans-serif;
  padding: 24px; max-width: 820px; margin: auto;
  background: #f8fafc;
}}
.doc-preview-header {{
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 16px;
  font-size: 13px;
  color: #475569;
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}}
.doc-preview-body {{
  background: #fff;
  padding: 24px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}}
@media print {{
  body {{ padding: 0; max-width: none; background: #fff; }}
  .doc-preview-header {{ display: none; }}
  .doc-preview-body {{ border: 0; padding: 0; }}
  .doc-field-token {{ background: transparent; border: 0; padding: 0; color: inherit; }}
}}
.doc-field-token {{
  background: #e3f2fd;
  border: 1px solid #90caf9;
  border-radius: 3px;
  padding: 1px 4px;
  color: #1565c0;
  font-size: 0.95em;
}}
.doc-field-token:empty::after {{ content: '（無值）'; color: #999; font-style: italic; }}
</style></head><body>
<div class="doc-preview-header">
  <span><strong>{doc_name}</strong> 預覽</span>
  <span>對應記錄：{record_label}</span>
</div>
<div class="doc-preview-body">{body}</div>
</body></html>"""
        return request.make_response(
            full_html,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
        )

    @http.route('/dobtor_doc/export', type='json', auth='user', methods=['POST'])
    def export_document(self, doc_id, format='pdf', quality='high',
                        record_model=None, record_id=None, **kw):
        """匯出文件為 PDF 或 DOCX。quality: 'high'（後端）"""
        doc = self._require_document(doc_id, 'read')

        record = None
        if record_model and record_id:
            try:
                record = request.env[record_model].browse(record_id)
                record.check_access('read')
            except Exception:
                record = None

        # Fallback：若前端沒帶 record，自動從 doc.model_id + doc.res_id 取
        # （讓「即用即匯出」流程不必每次都記得帶綁定資訊）
        if record is None and doc.model_id and doc.res_id:
            try:
                rec = request.env[doc.model_id.model].browse(doc.res_id)
                rec.check_access('read')
                if rec.exists():
                    record = rec
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

            request.env['doc.editor.export.log'].record_export(
                doc, format, with_alias=record is not None,
                file_size=len(file_bytes), source='editor',
            )
            return {
                'filename': filename,
                'data': base64.b64encode(file_bytes).decode(),
                'mimetype': mimetype,
            }
        except Exception as e:
            return {'error': str(e)}

    # `/dobtor_doc/import` 已搬到 dobtor_doc_import 模組（拆模組步驟 3）。
    # 匯入是原本這個模組裡最大的一塊（TS 約 31,000 行、208 支 vitest、
    # 82MB fixture），而它與核心的介面只有 content_json。

    @http.route('/dobtor_doc/save_version', type='json', auth='user', methods=['POST'])
    def save_version(self, doc_id, label=None, **kw):
        """儲存版本快照（W7-8 P1-1：回傳 version_number 與 message_id）。"""
        doc = self._require_document(doc_id, 'write')
        result = doc.action_save_version(label=label)
        return {'success': True, **(result or {})}

    @http.route('/dobtor_doc/versions/list', type='json', auth='user', methods=['POST'])
    def versions_list(self, doc_id=None, template_id=None, **kw):
        """列出編輯對象的所有版本快照（不含 content，輕量）。"""
        target, _kind = self._resolve_edit_target(doc_id, template_id, access='read')
        return {'versions': target.get_version_list()}

    @http.route('/dobtor_doc/versions/get', type='json', auth='user', methods=['POST'])
    def versions_get(self, doc_id=None, template_id=None, version_id=None,
                     message_id=None, **kw):
        """取得單一版本的完整內容（accept version_id 或 legacy message_id）。"""
        target, _kind = self._resolve_edit_target(doc_id, template_id, access='read')
        vid = version_id if version_id is not None else message_id
        content = target.get_version_content(vid)
        if content is None:
            return {'error': '找不到指定的版本快照'}
        return {'success': True, **content}

    @http.route('/dobtor_doc/versions/restore', type='json', auth='user', methods=['POST'])
    def versions_restore(self, doc_id=None, template_id=None, version_id=None,
                         message_id=None, **kw):
        """還原到指定版本（自動先存「還原前」快照）。"""
        target, _kind = self._resolve_edit_target(doc_id, template_id, access='write')
        vid = version_id if version_id is not None else message_id
        try:
            result = target.restore_version(vid)
        except Exception as e:
            return {'error': str(e)}
        return {'success': True, **(result or {})}

    @http.route('/dobtor_doc/versions/diff', type='json', auth='user', methods=['POST'])
    def versions_diff(self, doc_id=None, template_id=None,
                      version_id_a=None, version_id_b=None,
                      message_id_a=None, message_id_b=None, **kw):
        """段落層級 diff 兩個版本（accept version_id_* 或 legacy message_id_*）。"""
        target, _kind = self._resolve_edit_target(doc_id, template_id, access='read')
        a = version_id_a if version_id_a is not None else message_id_a
        b = version_id_b if version_id_b is not None else message_id_b
        result = target.diff_versions(a, b)
        if result is None:
            return {'error': '找不到指定的版本快照'}
        return {'success': True, **result}

    @http.route('/dobtor_doc/aliases/save', type='json', auth='user', methods=['POST'])
    def save_aliases(self, doc_id, aliases, **kw):
        """整批覆寫文件的中文 token → Jinja2 expression 對映。

        aliases: dict[str, str]，key=中文 token、value=Jinja2 expression（不含 {{ }}）。
        例：{"工程名稱": "object.project_id.name"}
        """
        if not isinstance(aliases, dict):
            return {'error': 'aliases 必須為 dict'}
        # 防呆：剝除空 key / 空 value、key 移除前後 《》
        cleaned = {}
        for raw_key, raw_val in aliases.items():
            if not raw_key or not raw_val:
                continue
            key = str(raw_key).strip().strip('《》').strip()
            val = str(raw_val).strip()
            if key and val:
                cleaned[key] = val
        doc = self._require_document(doc_id, 'write')
        doc.write({'field_aliases': cleaned})
        return {'success': True, 'aliases': cleaned}

    @http.route('/dobtor_doc/template_aliases/save', type='json', auth='user', methods=['POST'])
    def save_template_aliases(self, doc_id, aliases, **kw):
        """覆寫 doc 所屬 template 的 alias map。所有使用此範本的 doc 都會生效。"""
        if not isinstance(aliases, dict):
            return {'error': 'aliases 必須為 dict'}
        cleaned = {}
        for raw_k, raw_v in aliases.items():
            if not raw_k or not raw_v:
                continue
            k = str(raw_k).strip().strip('《》').strip()
            v = str(raw_v).strip()
            if k and v:
                cleaned[k] = v
        doc = self._require_document(doc_id, 'write')
        if not doc.template_id:
            return {'error': '此文件未綁定範本，無法寫入範本級 alias'}
        doc.template_id.check_access('write')
        doc.template_id.write({'field_aliases': cleaned})
        return {'success': True, 'aliases': cleaned}
