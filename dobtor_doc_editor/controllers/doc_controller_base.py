"""所有 doc 路由共用的入口守衛。

這些 helper 原本在 DocEditorController 裡。路由拆成四個 Controller 之後
它們是共用的，所以放一個**不是 Controller** 的純 Python 基底——
Odoo 走 http.Controller.__subclasses__() 註冊，基底不繼承 Controller
就不會被當成一組路由。
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


class DocControllerBase:

    # ─── type='http' 路由的 JSON 保證 ───────────────────────────────
    #
    # ☠️ `type='http'` 的路由拋出未處理例外時，Odoo 回的是**HTML 錯誤頁**，
    # 不是 JSON。前端那幾支都用 `await resp.json()` 解析——拿到 HTML 會
    # 丟 SyntaxError，而 OWL 把它吞成 console 的一行，使用者看到的是
    # 「按了沒反應」。
    #
    # 實際存在的缺口（2026-10-09 稽核發現）：upload_template 與
    # import_document 的 try/except 都**沒有包到開頭**——
    #   upload_template：`_require_document()` 在 try 之前（4 行）
    #   import_document：取檔案、驗副檔名與 engine 都在 try 之前（11 行）
    # 也就是「文件不存在」「沒有寫入權限」「副檔名不支援」這些**正常的錯誤
    # 路徑**全部回 HTML。
    #
    # 這個 decorator 讓那一類路由「不可能回非 JSON」：任何漏出來的例外都變成
    # 一個帶 error 的 JSON。這也讓測試裡「回應不是 JSON」這個症狀只剩一個
    # 可能的來源——auth 層把請求導去登入頁——不再有歧義。
    @staticmethod
    def json_http_route(func):
        """包住 type='http' 但回 JSON 的路由，保證永遠回 JSON。"""
        import functools
        import json as _json
        import logging as _logging

        _log = _logging.getLogger(__name__)

        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                # UserError / MissingError / AccessError 都是「正常的錯誤路徑」，
                # 給 400 與可讀訊息；其餘當 500 但仍然是 JSON。
                from odoo.exceptions import AccessError, MissingError, UserError
                expected = isinstance(e, (UserError, MissingError, AccessError))
                if not expected:
                    _log.exception('[doc] %s 未預期的例外', func.__name__)
                message = str(getattr(e, 'args', None) and e.args[0] or e) \
                    if expected else '伺服器錯誤，請稍後再試'
                return request.make_response(
                    _json.dumps({'success': False, 'error': message}),
                    headers={'Content-Type': 'application/json'},
                    status=400 if expected else 500,
                )

        return wrapper

    def _resolve_edit_target(self, doc_id=None, template_id=None, output_id=None,
                            access='read'):
        """回傳 (record, kind)；kind 為 'document' / 'template' / 'output'。

        access：'read' / 'write' / 'unlink'，直接餵給 check_access（Odoo 18 統一入口）。
        找不到記錄或無權限時 raise（json route 會把例外回給前端）。

        output 是唯讀的輸出紀錄：access 一律降為 'read'。
        它的 ACL 本來就 perm_write=0，但降級在這裡讓錯誤訊息清楚
        （「輸出紀錄不可編輯」而不是一句 AccessError）。
        """
        given = [bool(doc_id), bool(template_id), bool(output_id)]
        if sum(given) > 1:
            raise UserError('doc_id / template_id / output_id 只能擇一指定。')
        if output_id:
            if access != 'read':
                raise UserError('輸出紀錄不可編輯——它是已產生的成品。'
                                '需要修改請用「建立可編輯副本」。')
            record = request.env['doc.output'].browse(int(output_id))
            kind = 'output'
        elif template_id:
            record = request.env['doc.template'].browse(int(template_id))
            kind = 'template'
        elif doc_id:
            record = request.env['doc.document'].browse(int(doc_id))
            kind = 'document'
        else:
            raise UserError('必須指定 doc_id / template_id / output_id 其中之一。')
        if not record.exists():
            raise MissingError(f'{kind} 記錄不存在或已被刪除。')
        # Odoo 18：check_access_rule() / check_access_rights() 已 deprecated，
        # 合併為 check_access()（同時檢查 ir.model.access 與 ir.rule）。
        record.check_access(access)
        return record, kind

    def _resolve_template(self, doc_id=None, template_id=None, access='read'):
        """解析「要操作哪個範本」。

        文件模式下範本由 doc.template_id 推導，且權限檢查落在文件上
        （沿用既有行為——doc.template.field 的實際寫入權限由 ACL 控管，
        見 security/ir.model.access.csv：只有 group_doc_manager 有 write）。
        範本模式下直接就是該範本。

        回傳 (template, error_dict)；error_dict 非 None 時呼叫端應直接回傳它。
        """
        record, kind = self._resolve_edit_target(doc_id, template_id, access=access)
        if kind == 'template':
            return record, None
        if not record.template_id:
            return None, {'success': False, 'error': '此文件未關聯範本'}
        record.template_id.check_access('read')
        return record.template_id, None

    def _require_document(self, doc_id, access='read'):
        """文件專用路由的入口守衛。

        Phase 1 起編輯器可能在「範本模式」，此時前端的 state.docId 是 null。
        沒有這道守衛的話，doc_id=None → browse(None) 回空 recordset →
        check_access 對空集合直接通過 → 後續欄位讀出來全是預設值，
        於是匯出得到一份空白 PDF、預覽得到空頁——靜默錯誤。
        寧可在這裡明確擋下並告訴使用者原因。
        """
        if not doc_id:
            raise UserError('此功能僅適用於文件；目前編輯的是範本，請先從文件開啟。')
        doc = request.env['doc.document'].browse(int(doc_id))
        if not doc.exists():
            raise MissingError('文件不存在或已被刪除。')
        doc.check_access(access)
        return doc

    def _load_template_payload(self, template):
        """範本模式的 /load 回傳值。

        刻意與文件模式維持同一組 key，讓前端 _applyLoadedPayload 只有一條路徑。
        範本沒有的東西（res_id、頁首頁尾、DOCX 模板、頁面邊距）一律給預設值，
        而不是省略 key——省略會讓前端讀到 undefined 再各自 fallback，容易漏。
        """
        return {
            'id': template.id,
            'name': template.name,
            'content_json': template.content_json or '',
            'content_html': template.get_content_html(),
            'header_html': '',
            'footer_html': '',
            'page_format': template.page_format or 'A4',
            'margin_top': template.margin_top,
            'margin_bottom': template.margin_bottom,
            'margin_left': template.margin_left,
            'margin_right': template.margin_right,
            'model_id': template.model_id.id if template.model_id else False,
            'model_name': template.model_id.model if template.model_id else False,
            # 範本不綁定單一記錄——設計期沒有 record 可取值，藥丸顯示標籤文字
            'res_id': False,
            # 範本模式下「自身的 alias」就是範本級 alias；沒有上層可繼承
            'field_aliases': template.field_aliases or {},
            'template_field_aliases': {},
            'template_name': template.name,
            # has_template 指的是「上傳的 DOCX 模板檔」，範本記錄本身沒有
            'has_template': False,
            'template_filename': '',
            'template_variables': [],
            'has_different_first_page': False,
            'first_header_html': '',
            'first_footer_html': '',
            'write_date': template.write_date.isoformat() if template.write_date else None,
            'version_number': template.version_number or 0,
            'edit_target': 'template',
            # 範本沒有綁定記錄，永遠不會有快照——藥丸一律顯示標籤文字
            'snapshot_date': None,
            'snapshot_is_stale': False,
        }

    def _load_output_payload(self, output):
        """輸出紀錄模式的 /load 回傳值。唯讀。

        與另兩種模式維持同一組 key（前端只有一條解析路徑），差別在
        readonly=True 與 edit_target='output'。前端據此關掉 autosave、
        收斂工具列與兩側面板。

        content_json 已是凍結後的元素樹——藥丸顯示的就是當時的值，
        不重新求值（否則就不是「當時印出去的那一份」了）。
        """
        source = output._resolve_source()
        return {
            'id': output.id,
            'name': output.display_name or '',
            'content_json': output.content_json or '',
            'content_html': '',
            'header_html': '',
            'footer_html': '',
            'page_format': output.template_id.page_format or 'A4',
            'margin_top': output.template_id.margin_top,
            'margin_bottom': output.template_id.margin_bottom,
            'margin_left': output.template_id.margin_left,
            'margin_right': output.template_id.margin_right,
            'model_id': output.res_model_id.id if output.res_model_id else False,
            'model_name': output.res_model or False,
            'res_id': output.res_id or False,
            # 輸出不需要 alias——它已經凍結，沒有待替換的 token
            'field_aliases': {},
            'template_field_aliases': {},
            'template_name': output.template_id.name if output.template_id else '',
            'has_template': False,
            'template_filename': '',
            'template_variables': [],
            'has_different_first_page': False,
            'first_header_html': '',
            'first_footer_html': '',
            'write_date': output.rendered_at.isoformat() if output.rendered_at else None,
            'version_number': output.template_version or 0,
            'edit_target': 'output',
            # 快照資訊：輸出的「凍結時間」就是列印時間
            'snapshot_date': output.rendered_at.isoformat() if output.rendered_at else None,
            'snapshot_is_stale': False,
            # 唯讀：前端據此關 autosave、收工具列；伺服端另有 ACL 把關
            'readonly': True,
            'output_meta': {
                'res_name': output.res_name or '',
                'rendered_by': output.rendered_by.name or '',
                'template_version': output.template_version or 0,
                'output_format': output.output_format or 'pdf',
                'has_attachment': bool(output.attachment_id),
                'source_exists': bool(source),
            },
        }

    def _telemetry_doc_id(self, doc_id):
        """把前端傳來的 doc_id 收斂成真的 doc.document id。

        兩個遙測 model 的 doc_id 都是指向 doc.document 的外鍵，但編輯器可以
        編範本（doc.template）與輸出（doc.output）——前端若把那邊的 id 當
        doc_id 送上來，INSERT 會違反外鍵。這裡先確認記錄存在，不存在就存
        False（遙測筆數比綁對文件重要）。
        """
        try:
            rid = int(doc_id)
        except (TypeError, ValueError):
            return False
        if rid <= 0:
            return False
        return rid if request.env['doc.document'].sudo().browse(rid).exists() else False

    def _field_control_spec(self, field, record, aliases=None):
        """把一個 doc.template.field 轉成前端 canvas-editor control 所需的設定。

        record：doc 綁定的 Odoo record（可能為 None）；用來算 current_code
                （chip 開啟時的預設選中值＝該 record 該欄位的當前值）。
        aliases：doc._collect_field_aliases()，用來算此欄位對應的文件內 token 字面字串
                （含 {{ varname }} 與 《中文》兩種格式），供前端在內容中尋找並升級。

        odoo 來源優先用 record 的 model 解析 Selection（拿得到 current_code）；
        沒 record 時退而用 template.model_id，只給選項、不給預設值。
        """
        value_sets = []
        current_code = None
        if field.option_source == 'odoo' and field.selection_field_name:
            model_name = None
            if record is not None and record.exists():
                model_name = record._name
            elif field.template_id.model_id:
                model_name = field.template_id.model_id.model
            if model_name and model_name in request.env:
                fdef = request.env[model_name]._fields.get(field.selection_field_name)
                if fdef and fdef.type == 'selection':
                    for tech, label in fdef._description_selection(request.env):
                        value_sets.append({'value': label, 'code': tech})
                    if (record is not None and record.exists()
                            and field.selection_field_name in record._fields):
                        val = record[field.selection_field_name]
                        if val:
                            current_code = val
        elif field.option_source == 'custom':
            for opt in field.option_ids.sorted('sequence'):
                value_sets.append({'value': opt.value, 'code': opt.code or opt.value})

        # 此欄位對應的文件內 token 字面字串：以 placeholder_text（varname）為錨，
        # 找 field_aliases 中對映到同一 expression 的所有 key。
        # varname-like key → {{ key }}；中文等非 varname key → 《key》。
        # 讓前端能同時升級 {{ timing }}（新文件）與 《檢查時機》（已遷移文件）。
        varname = field.placeholder_text or ''
        tokens = []
        if varname:
            tokens.append('{{ %s }}' % varname)
            if aliases:
                expr = aliases.get(varname)
                if expr:
                    for k, v in aliases.items():
                        if v != expr or k == varname:
                            continue
                        if re.match(r'^[A-Za-z_]\w*$', k):
                            tokens.append('{{ %s }}' % k)
                        else:
                            tokens.append('《%s》' % k)
        tokens = list(dict.fromkeys(tokens))  # 去重、保序

        return {
            'field_id': field.id,
            'placeholder_text': varname,
            'control_type': field.field_type,
            'value_sets': value_sets,
            'input_able': field.input_able,
            'is_multi_select': field.is_multi_select,
            'current_code': current_code,
            'concept_id': str(field.id),
            'tokens': tokens,
        }
