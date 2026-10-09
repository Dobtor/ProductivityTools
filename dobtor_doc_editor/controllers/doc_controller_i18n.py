"""多語文字的路由：語言清單、抽取、轉換、CSV 匯出匯入。
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

from ..models.doc_ins_syntax import _convert_ins_to_jinja  # noqa: F401（import 區塊整份照抄，見檔頭）
from ..models.doc_zip_guard import (
    assert_input_size,
    assert_text_size,
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


class DocI18nController(DocControllerBase, http.Controller):

    @http.route('/dobtor_doc/i18n/languages', type='json', auth='user',
                methods=['POST'])
    def i18n_languages(self, **kw):
        """已安裝語言清單（給 i18n 藥丸的 inspector 用）。"""
        langs = request.env['res.lang'].sudo().search([])
        return [{'code': lang.code, 'name': lang.name} for lang in langs]

    @http.route('/dobtor_doc/i18n/extract', type='json', auth='user',
                methods=['POST'])
    def i18n_extract(self, doc_id=None, template_id=None, **kw):
        """列出範本裡的靜態文字（唯讀，不改任何東西）。"""
        target, _kind = self._resolve_edit_target(
            doc_id, template_id, access='read',
        )
        return {'texts': target.extract_static_texts()}

    @http.route('/dobtor_doc/i18n/convert', type='json', auth='user',
                methods=['POST'])
    def i18n_convert(self, doc_id=None, template_id=None, texts=None,
                     lang=None, **kw):
        """把勾選的靜態文字轉成 i18n 藥丸。"""
        target, _kind = self._resolve_edit_target(
            doc_id, template_id, access='write',
        )
        result = target.convert_texts_to_i18n(texts or [], lang=lang)
        # 回傳新的 content_json：前端要把編輯器內容換成轉換後的結果，
        # 否則使用者繼續編輯會用舊內容把剛才的轉換覆蓋掉
        result['content_json'] = target.content_json or ''
        return result

    @http.route('/dobtor_doc/i18n/export', type='json', auth='user',
                methods=['POST'])
    def i18n_export(self, doc_id=None, template_id=None, **kw):
        """翻譯表 → CSV 字串。"""
        target, _kind = self._resolve_edit_target(
            doc_id, template_id, access='read',
        )
        return {
            'csv': target.export_i18n_csv(),
            'entries': len(target.i18n_entries()),
        }

    @http.route('/dobtor_doc/i18n/import', type='json', auth='user',
                methods=['POST'])
    def i18n_import(self, doc_id=None, template_id=None, csv_content=None, **kw):
        """CSV → 回填翻譯。"""
        # ☠️ 稽核尺 2：原本把 csv_content 原封不動丟下去，沒有任何上限。
        assert_text_size(csv_content, 'csv_content')
        target, _kind = self._resolve_edit_target(
            doc_id, template_id, access='write',
        )
        result = target.import_i18n_csv(csv_content or '')
        result['content_json'] = target.content_json or ''
        return result
