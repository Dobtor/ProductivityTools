"""遙測與測試夾具的路由。

test_render / test_data 是視覺回歸用的（views/test_layout.xml 以
網址載入 static/src/.../test_harness.js）——不是死碼。
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
from .doc_controller_base import DocControllerBase
from .doc_convert import (
    _ts_parse_docx_to_elements,
    _docx_to_html_with_format,
    _w_paragraph_to_html,
    _w_runs_to_html,
    _w_run_to_html,
    _w_table_to_html,
    _odt_to_html,
    _lo_convert_to_html,
    _extract_page_margins,
    _lo_postprocess,
    _convert_ins_to_jinja,
)


class DocDevtoolsController(DocControllerBase, http.Controller):

    @http.route('/dobtor_doc/telemetry/error', type='json', auth='user', methods=['POST'])
    def telemetry_error(self, error_type='other', message='', stack_trace='',
                        user_agent='', url='', doc_id=None, extra=None, **kw):
        """前端錯誤上報。

        受信賴的最小欄位 — 拒絕儲存超過 size 的 message / stack 以防 abuse。
        """
        ALLOWED_TYPES = (
            'js_error', 'promise_rejection', 'canvas_error',
            'save_failure', 'import_failure', 'export_failure', 'other',
        )
        if error_type not in ALLOWED_TYPES:
            error_type = 'other'

        # 截斷防止濫用（DB 欄位本身 size=512/256，但前端可能傳更長）
        message = (message or '')[:500]
        user_agent = (user_agent or '')[:250]
        url = (url or '')[:500]
        # stack_trace 是 Text 沒長度限制，但截到 8K 避免 DB 爆量
        stack_trace = (stack_trace or '')[:8000]

        try:
            # savepoint 不是保險起見而已：try/except 只接得住 Python 例外，
            # PostgreSQL 這邊的交易已經是 aborted，接下來 Odoo 自己的
            # env.cr.commit() 會丟 InFailedSqlTransaction——遙測失敗就變成
            # 整筆請求失敗。瀏覽器 tour 的 log 就是這樣抓到的。
            with request.env.cr.savepoint():
                request.env['doc.editor.error.log'].sudo().create({
                    'doc_id': self._telemetry_doc_id(doc_id),
                    'user_id': request.env.user.id,
                    'company_id': request.env.company.id,
                    'error_type': error_type,
                    'message': message,
                    'stack_trace': stack_trace,
                    'user_agent': user_agent,
                    'url': url,
                    'extra': extra or {},
                })
            return {'success': True}
        except Exception as e:
            _logger.warning("Failed to log telemetry error: %s", e)
            # 不擾斷前端，靜默吞掉（telemetry 失敗不應影響使用者）
            return {'success': False}

    @http.route('/dobtor_doc/telemetry/metric', type='json', auth='user', methods=['POST'])
    def telemetry_metric(self, metric_type=None, value=None,
                         doc_id=None, page_count=None, extra=None, **kw):
        """前端效能指標上報。

        每筆代表一個 metric event。前端可批次合併多個 metric type 一次發。
        """
        if not metric_type or value is None:
            return {'success': False, 'error': 'metric_type + value required'}
        # metric_type 不限白名單（彈性高），但截 size 避免 abuse
        metric_type = str(metric_type)[:64]

        try:
            value_f = float(value)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'value must be numeric'}

        try:
            with request.env.cr.savepoint():
                request.env['doc.editor.perf.metric'].sudo().create({
                    'doc_id': self._telemetry_doc_id(doc_id),
                    'user_id': request.env.user.id,
                    'metric_type': metric_type,
                    'value': value_f,
                    'page_count': int(page_count) if page_count else 0,
                    'extra': extra or {},
                })
            return {'success': True}
        except Exception as e:
            _logger.warning("Failed to log telemetry metric: %s", e)
            return {'success': False}

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

