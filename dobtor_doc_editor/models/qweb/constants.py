"""轉換器的模組層級常數與正則。

單獨一支是為了避免循環 import：五層需要這些常數，而
doc_qweb_converter.py 需要那五層（同 doc_editor_shared.js 的理由）。
"""
import json
import logging
import re
from odoo import models

_logger = logging.getLogger(__name__)

# QWeb 報表的根變數。報表範本習慣用 doc / o / docs 當單筆記錄的名字。
_ROOT_VARS = ('doc', 'o', 'object', 'record')

# 只是外殼、不含內容的範本——往下追 t-call 時要跳過它們
_WRAPPER_TEMPLATES = frozenset({
    'web.html_container', 'web.html_preview_container',
    'web.basic_layout', 'web.minimal_layout',
})

# 外框：它的內容對應「外框範本」，本文在 <t t-out="0"/> 的位置
_LAYOUT_TEMPLATES = frozenset({
    'web.external_layout', 'web.internal_layout', 'web.address_layout',
})

# 稅額彙總子範本 → 內建區塊
_TAX_TOTALS_TEMPLATES = frozenset({
    'sale.document_tax_totals', 'account.document_tax_totals',
    'purchase.document_tax_totals',
})
_TAX_TOTALS_COMPANY_TEMPLATES = frozenset({
    'account.document_tax_totals_company_currency_template',
})

# t-options 的 widget → 本模組對應的包法
_WIDGET_WRAPPERS = {
    'monetary': 'format_money(%s)',
    # 日期一律走語言格式：原生印 10/08/2026，ISO 的 2026-10-08 在單據上
    # 是看得出來的差別（實測比對原生輸出時第一個跳出來的就是它）
    'date': "format_date(%s, 'lang')",
    'datetime': "format_date(%s, 'lang_datetime')",
    'integer': "format_number(%s, ',.0f')",
    'float': 'format_number(%s)',
    'contact': 'format_address(%s)',
}

_BLOCK_TAGS = frozenset({
    'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
    'section', 'header', 'footer', 'article', 'blockquote', 'pre',
})
_SKIP_TAGS = frozenset({'script', 'style', 'link', 'meta'})

_SIMPLE_PATH_RE = re.compile(r'^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$')
# class 字面值（單引號或雙引號）
_LIT = r"'[^']*'" + r'|"[^"]*"'
# 表達式有沒有綁到沙箱裡的根變數（object / line）。
# 一律用 token 比對，不要寫 'line.' in expr：迴圈變數是 dict 時 QWeb 寫
# 下標（line['date']），帶點的字串比對會判成「不是明細欄位」，
# 藥丸的 source 就變成 record——印出來是空的，而且沒有任何訊息。
_ROOT_TOKEN_RE = re.compile(r'\b(object|line)\b')
_LINE_TOKEN_RE = re.compile(r'\bline\b')
