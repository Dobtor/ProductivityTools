# -*- coding: utf-8 -*-
"""把內建外框範本的頁首頁尾轉成編輯器的段落寫法。

修的是什麼：canvas-editor 的換行是**下一段的開頭**，一段的對齊看開頭的換行；
以前的程式卻把對齊寫在段落**結尾**的換行上。這一版 PDF 改成跟編輯器同一套
讀法之後，舊外框的頁尾「第 X / Y 頁」會從置中變成靠左（編輯器裡本來就是
靠左，只是以前 PDF 讀錯一行剛好讀對）。頁首每個格子結尾的換行也會變成
多一行空白。

只動「建立之後沒有被改過」的外框（write_date 等於 create_date）：那一定是
find_or_create_layout 產生的原樣，轉換規則是確定的。有人在編輯器裡改過的
外框不碰——對齊可能已經是使用者自己調的，猜錯會蓋掉他的設定。

用 SQL 直接寫回、不經 ORM：write_date 維持原樣，「沒被改過」的判斷才會一直
成立，也不會讓這筆外框看起來像是剛被人編輯過。
"""
import json
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # 全新安裝：程式產生的外框已經是新寫法
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    mixin = env['doc.render.mixin']
    cr.execute("""
        SELECT id, content_json, write_date <> create_date AS edited
          FROM doc_template
         WHERE role = 'layout' AND content_json IS NOT NULL
    """)
    for template_id, raw, edited in cr.fetchall():
        if edited:
            _logger.info(
                '[doc_editor] 外框範本 %s 改過，不自動轉換段落寫法；'
                '頁尾頁碼若變成靠左，請在編輯器裡重新設定置中。', template_id)
            continue
        try:
            tree = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(tree, dict):
            continue
        mixin._paragraph_ends_to_starts(tree)
        cr.execute(
            'UPDATE doc_template SET content_json = %s WHERE id = %s',
            (json.dumps(tree, ensure_ascii=False), template_id),
        )
        _logger.info('[doc_editor] 外框範本 %s 已轉成新的段落寫法', template_id)
