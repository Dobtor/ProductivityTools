# -*- coding: utf-8 -*-
"""AI 產出的行銷 HTML 清洗（純函式，可單獨測）。

★ 共同規則：對外 HTML 只能用 Odoo snippet 與 Bootstrap 5 class，不能有 <style> <script> <svg>；
  連結一律由系統產生——AI 寫的 <a> 只留文字。圖片由素材挑選，AI 寫的 <img> 也拿掉。
★ 白名單制（標籤、class、屬性都是）：只拿掉黑名單擋不住 AI 自己發明的 class／id／data-*
  （會被網站編輯器當成 snippet 選項、或撞到頁面上既有的 id 錨點）。
"""
from lxml import etree
from lxml import html as lxml_html

DROP_WITH_CONTENT = {'style', 'script', 'svg', 'iframe', 'object', 'embed', 'form',
                     'link', 'meta', 'img', 'video', 'audio', 'canvas', 'noscript',
                     'template', 'button', 'input', 'select', 'textarea'}
#: 允許的標籤（HTML_RULES 列的那些）；其他標籤拆掉外殼、留文字。
ALLOWED_TAGS = {'p', 'ul', 'ol', 'li', 'strong', 'em', 'b', 'i', 'br', 'h4', 'h5',
                'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span'}
#: 允許的 class（共同規則的 Bootstrap 5／snippet class）。
ALLOWED_CLASSES = {'s_alert', 'alert', 'alert-info', 'table', 'table-bordered',
                   'table-striped', 'align-middle', 'table-light', 'badge',
                   'text-bg-primary', 'd-flex'}
#: 允許的屬性；id、data-*、style、on*、href/src 一律拿掉（表格合併儲存格要留 colspan/rowspan）。
ALLOWED_ATTRS = {'class', 'colspan', 'rowspan', 'scope'}


def clean(src):
    if not src or not str(src).strip():
        return ''
    try:
        root = lxml_html.fragment_fromstring(str(src), create_parent='div')
    except (etree.ParserError, ValueError):
        return ''
    for el in list(root.iter()):
        if el is root:
            continue
        if not isinstance(el.tag, str):
            # 註解、處理指令
            el.drop_tree()
            continue
        tag = el.tag.lower().split('}')[-1]
        if tag in DROP_WITH_CONTENT:
            el.drop_tree()
        elif tag not in ALLOWED_TAGS:
            el.drop_tag()
    for el in root.iter():
        if el is root or not isinstance(el.tag, str):
            continue
        for attr in list(el.attrib):
            if attr.lower() not in ALLOWED_ATTRS:
                del el.attrib[attr]
        if 'class' in el.attrib:
            kept = [c for c in el.attrib['class'].split() if c in ALLOWED_CLASSES]
            if kept:
                el.attrib['class'] = ' '.join(dict.fromkeys(kept))
            else:
                del el.attrib['class']
    out = lxml_html.tostring(root, encoding='unicode')
    return out[len('<div>'):-len('</div>')] if out.startswith('<div>') else out
