"""把 6 張出貨範本的 content_html 轉成 content_json。

為什麼需要 migration 而不是改資料檔就好：那個資料檔是
`<data noupdate="1">`，所以改 XML **對既有資料庫完全沒有作用**
（新安裝才會拿到）。noupdate 在這裡是對的——使用者會編輯出貨範本，
升級時不該把他們的修改蓋掉。

所以這支只補「還沒有 content_json 的那幾張」：

  * 使用者已經用編輯器存過的（有 content_json）→ 不動
  * 使用者自己改過 content_html 的 → 照他改過的內容轉，不是照我們出貨的
  * 兩種都沒有 → 跳過並留 log

轉換用 doc.render.mixin._html_to_content_json()，正確性由
TestHtmlToContentJson 的來回轉換測試保護。

☠️ 轉換時去掉 {{ var }} placeholder：那些變數靠
doc.linked.mixin._doc_render_context() 帶入，而那支方法沒有任何消費者
（實測過，那幾格今天就是印空白）。留著的話在 content_json 路徑會變成
印出「{{ subject }}」字樣，比今天的空白更糟。
"""
import logging
import re

_logger = logging.getLogger(__name__)

XMLIDS = (
    'doc_template_blank',
    'template_meeting_record',
    'template_self_inspection',
    'template_defect_improvement',
    'template_payment_estimate',
    'template_review_control',
)
JINJA = re.compile(r'\{\{.*?\}\}')


def migrate(cr, version):
    if not version:
        return  # 全新安裝：資料檔本來就帶 content_json
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    Mixin = env['doc.render.mixin']
    import json
    done = skipped = 0
    for xmlid in XMLIDS:
        tmpl = env.ref('dobtor_doc_editor.%s' % xmlid, raise_if_not_found=False)
        if not tmpl:
            continue
        if tmpl.content_json:
            skipped += 1
            continue
        html = JINJA.sub('', tmpl.content_html or '')
        if not html.strip():
            _logger.info('[doc.template] %s 沒有 content_html，跳過', xmlid)
            skipped += 1
            continue
        notes = []
        tree = Mixin._html_to_content_json(html, notes=notes)
        if not tree.get('main'):
            _logger.warning('[doc.template] %s 轉出空的 main，保持原狀', xmlid)
            skipped += 1
            continue
        if notes:
            # 不中斷：轉得出東西就比停在舊路徑好，但要留下紀錄
            _logger.warning('[doc.template] %s 轉換時有未支援的標籤：%s',
                            xmlid, notes)
        tmpl.content_json = json.dumps(tree, ensure_ascii=False)
        done += 1
    _logger.info('[doc.template] content_json 補上 %d 張、跳過 %d 張', done, skipped)
