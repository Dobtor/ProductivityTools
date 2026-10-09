"""檔案匯入的路由。

    /dobtor_doc/import            DOCX / ODT → HTML 或 IElement[]
    /dobtor_doc_editor/test       視覺回歸 harness 的頁面
    /dobtor_doc_editor/test_data  harness 要的 IElement[]

拆模組步驟 3（2026-10-09）從 dobtor_doc_editor 搬過來。

☠️ 繼承核心的 `DocControllerBase`（它**不是** Controller，見核心該檔檔頭）是為了
拿到 `json_http_route`——`type='http'` 的路由拋例外時 Odoo 會回 HTML 錯誤頁，而
前端用 JSON 解析。核心有一則測試讀原始碼擋「新增 type='http' JSON 路由忘記掛
decorator」，本模組也有自己的一則（tests/test_import_routes.py）。

☠️ 兩條 `/dobtor_doc_editor/test*` 路由刻意**保留原本的網址**：`scripts/` 下的
視覺回歸與 perf harness 都寫死這個路徑，改網址等於同時改那十幾支腳本。網址裡的
`dobtor_doc_editor` 是歷史，不代表它屬於核心模組。
"""
import base64
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile

from odoo import http
from odoo.http import request

from odoo.addons.dobtor_doc_editor.controllers.doc_controller_base import DocControllerBase
from odoo.addons.dobtor_doc_editor.models.doc_zip_guard import (
    assert_input_size,
    inspect_zip_safe,
    ZipBombError,
)

from .doc_convert import (
    _docx_to_html_with_format,
    _lo_convert_to_html,
    _odt_to_html,
    _ts_parse_docx_to_elements,
)

_logger = logging.getLogger(__name__)


class DocImportController(DocControllerBase, http.Controller):

    @http.route('/dobtor_doc/import', type='http', auth='user', methods=['POST'], csrf=False)
    @DocControllerBase.json_http_route
    def import_document(self, **kw):
        """匯入 DOCX / ODT 檔案。

        Engine 並行通道（Phase E）：
            engine=libreoffice（預設）：傳統 LibreOffice → HTML 路徑（穩定）
            engine=ts                 ：本模組 TS OOXML Parser → IElement[] 路徑
                                        前端可直接餵給 canvas-editor 初始化（content_json）
            engine=both               ：兩條都跑，回傳 html + elements + 比對 log
                                        debug 模式：可快速肉眼比對 LibreOffice 與 TS 路徑差異

        前端策略（doc_editor.js）：
            - 優先使用 elements（如有），呼叫 editor.command.executeSetValue(elements)
            - 否則 fallback 到 html（既有路徑）

        ODT / 其他格式仍只能走 LibreOffice。

        ☠️ engine=ts 需要 `tools/dist/parse_docx_cli.cjs`（`npm run build:cli` 產出）
        與容器內的 node。2026-10-09 之前那個產物**沒有進 git**（被 .gitignore 的
        `dist/` 排除），所以這條通道在任何部署上都沒真的運作過；取回時已補上
        `!tools/dist/parse_docx_cli.cjs` 的例外並把產物進版控（ADR-032）。

        Args:
            engine: 'libreoffice' / 'ts' / 'both'（從 form 或 query string 取）
        """
        def _json_resp(data):
            return request.make_response(
                json.dumps(data, ensure_ascii=False),
                headers={'Content-Type': 'application/json; charset=utf-8'},
            )

        upload = request.httprequest.files.get('file')
        if not upload:
            return _json_resp({'error': '未收到檔案'})

        filename = upload.filename or ''
        ext = os.path.splitext(filename)[1].lower()

        # 解析 engine 參數（form > query > 預設）
        engine = (
            request.httprequest.form.get('engine')
            or request.httprequest.args.get('engine')
            or 'libreoffice'
        ).lower()
        if engine not in ('libreoffice', 'ts', 'both'):
            engine = 'libreoffice'

        # ODT 不支援 TS 路徑（無 ODT parser），自動降級
        if ext == '.odt' and engine in ('ts', 'both'):
            engine = 'libreoffice'



        # Sprint Y58：opt-in flag（form > query > 預設 false）。
        # 預設值維持與 Sprint 358-359 後的行為一致 — 不啟用 floatTextBox 展平、
        # 不透傳 wp:anchor 屬性。caller 想要時送 `float_textbox=1` / `anchored_image=1`。
        def _truthy(val):
            return str(val or '').strip().lower() in ('1', 'true', 'yes', 'on')

        float_textbox = _truthy(
            request.httprequest.form.get('float_textbox')
            or request.httprequest.args.get('float_textbox')
        )
        anchored_image = _truthy(
            request.httprequest.form.get('anchored_image')
            or request.httprequest.args.get('anchored_image')
        )

        try:
            file_bytes = upload.read()

            # ── Zip Bomb 防護（W1 P0-2）：DOCX 才檢查；ODT 也是 zip 但結構不同 ──
            if ext in ('.docx', '.odt'):
                try:
                    assert_input_size(file_bytes)
                    inspect_zip_safe(file_bytes)
                except ZipBombError as e:
                    _logger.warning(
                        "import_document rejected by zip_guard: %s (file=%s, uid=%s)",
                        e, filename, request.env.user.id,
                    )
                    return _json_resp({'error': str(e)})

            page_margins = None
            body_html = None
            elements = None
            audit = {}  # debug 比對資訊

            # ── TS 路徑（engine=ts 或 both）──
            if engine in ('ts', 'both') and ext == '.docx':
                ts_elements = _ts_parse_docx_to_elements(
                    file_bytes,
                    float_textbox=float_textbox,
                    anchored_image=anchored_image,
                )
                if ts_elements is not None:
                    elements = ts_elements
                    audit['ts_element_count'] = len(ts_elements)
                else:
                    audit['ts_failed'] = True
                    if engine == 'ts':
                        # 純 ts 模式失敗時自動 fallback libreoffice（避免使用者卡住）
                        engine = 'libreoffice'


            # ── LibreOffice 路徑（engine=libreoffice 或 both）──
            if engine in ('libreoffice', 'both'):
                if ext in ('.docx', '.odt'):
                    lo_result = _lo_convert_to_html(file_bytes, ext)
                    if lo_result is not None:
                        body_html, page_margins = lo_result
                        audit['lo_html_len'] = len(body_html)
                    elif ext == '.docx':
                        body_html = _docx_to_html_with_format(file_bytes)
                        audit['lo_fallback'] = 'docx_python'
                    else:
                        body_html = _odt_to_html(file_bytes)
                        audit['lo_fallback'] = 'odt_python'
                else:
                    if not shutil.which('soffice'):
                        return _json_resp({
                            'error': f'不支援的格式（{ext}）。支援格式：.docx、.odt'
                        })
                    lo_result = _lo_convert_to_html(file_bytes, ext)
                    if lo_result is None:
                        return _json_resp({'error': f'LibreOffice 無法轉換格式：{ext}'})
                    body_html, page_margins = lo_result

            resp = {'engine': engine}
            if body_html is not None:
                resp['html'] = body_html
            if elements is not None:
                resp['elements'] = elements
            if page_margins:
                resp['margins'] = page_margins
            if engine == 'both':
                resp['audit'] = audit

            # 至少要有一條路徑成功
            if body_html is None and elements is None:
                return _json_resp({
                    'error': 'TS 與 LibreOffice 皆無法轉換此檔案',
                    'audit': audit,
                })

            return _json_resp(resp)

        except Exception as e:
            return _json_resp({'error': str(e)})

    @http.route('/dobtor_doc_editor/test', type='http', auth='user', methods=['GET'])
    def test_render(self, fixture=None, **kw):
        """渲染 fixture .docx 為 clean canvas-editor 頁面（無 Odoo header/sidebar）。

        Phase F 視覺回歸 pipeline 入口。puppeteer 對此 URL 截圖，
        對比 tests/fixtures/<category>/golden/<fixture>-<page>.png。
        """
        if not fixture:
            return request.make_response('missing ?fixture=<rel_path>', status=400)

        # 安全：fixture 必須是 tests/fixtures/ 下的相對路徑、無 .. traversal
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fixtures_root = os.path.join(module_dir, 'tests', 'fixtures')
        abs_path = os.path.normpath(os.path.join(fixtures_root, fixture))
        if not abs_path.startswith(fixtures_root + os.sep):
            return request.make_response('invalid fixture path', status=400)
        if not abs_path.lower().endswith('.docx'):
            return request.make_response('only .docx supported', status=400)
        if not os.path.isfile(abs_path):
            return request.make_response(f'fixture not found: {fixture}', status=404)

        return request.render('dobtor_doc_editor.test_layout', {
            'fixture_name': fixture,
        })

    @http.route('/dobtor_doc_editor/test_data', type='json', auth='user', methods=['POST'])
    def test_data(self, fixture=None, float_textbox=False, anchored_image=False, **kw):
        """回傳指定 fixture 的 IElement[]（Phase F test_harness.js 用）。

        參數：
            fixture:        tests/fixtures/ 下的相對路徑（如 '01_simple/xxx.docx'）
            float_textbox:  Sprint Y58 opt-in 展平 wp:anchor + w:txbxContent 文字
            anchored_image: Sprint Y58 opt-in 透傳 wp:anchor 屬性

        回傳：{'elements': [...IElement...]} 或 {'error': str}
        """
        if not fixture:
            return {'error': 'missing fixture parameter'}

        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fixtures_root = os.path.join(module_dir, 'tests', 'fixtures')
        abs_path = os.path.normpath(os.path.join(fixtures_root, fixture))
        if not abs_path.startswith(fixtures_root + os.sep):
            return {'error': 'invalid fixture path'}
        if not abs_path.lower().endswith('.docx') or not os.path.isfile(abs_path):
            return {'error': f'fixture not found: {fixture}'}

        with open(abs_path, 'rb') as fp:
            file_bytes = fp.read()

        elements = _ts_parse_docx_to_elements(
            file_bytes,
            float_textbox=bool(float_textbox),
            anchored_image=bool(anchored_image),
        )
        if elements is None:
            return {'error': 'TS parser failed (CLI not built or runtime error)'}

        return {'elements': elements, 'fixture': fixture}
