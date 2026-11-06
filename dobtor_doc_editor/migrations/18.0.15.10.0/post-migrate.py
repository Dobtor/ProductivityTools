# -*- coding: utf-8 -*-
"""「Odoo 標準」外框的上邊距照官方本文起點，地址區塊上方的留白搬到範本裡。

修的是什麼：官方報表地址區塊的上方有 42px 留白（信封窗格對位用）。舊版外框
把這段算進上邊距（212px），用外框地址區塊的單據（訂單、發票、出貨單、採購單）
因此對得上，但沒有地址區塊的單據（揀貨作業）整頁比官方低約 27pt。

調整方式：
  * 外框上邊距 212 → 170px（官方本文起點）。上邊距被改過的外框不碰——那是
    使用者自己調的，連同掛在它底下的範本都維持原樣。
  * 掛在這些外框底下、一開頭就是外框地址區塊的範本，在最前面補 42px 的空白列，
    地址以下的位置不變；開頭不是地址區塊的（揀貨作業）不補，自然往上對齊官方。
    已經補過的（開頭已經是空白列）不重補。

用 SQL 直接寫回、不經 ORM：write_date 維持原樣，範本不會看起來像剛被人編輯過，
也不會觸發版本快照。
"""
import json
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# 舊版「Odoo 標準」外框的上邊距
_OLD_MARGIN_TOP = 212


def migrate(cr, version):
    if not version:
        # 全新安裝：程式產生的外框與範本已經是新寫法
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Template = env['doc.template']
    name = '外框：%s' % Template._LAYOUT_VARIANTS['odoo']
    new_top = Template._LAYOUT_VARIANT_VALS['odoo']['margin_top']
    cr.execute("""
        SELECT id FROM doc_template
         WHERE role = 'layout' AND name = %s AND margin_top = %s
    """, (name, _OLD_MARGIN_TOP))
    frames = tuple(row[0] for row in cr.fetchall())
    if not frames:
        return
    cr.execute('UPDATE doc_template SET margin_top = %s WHERE id IN %s',
               (new_top, frames))
    _logger.info('[doc_editor] 外框 %s 的上邊距改成 %spx', list(frames), new_top)

    cr.execute("""
        SELECT id, content_json FROM doc_template
         WHERE layout_id IN %s AND content_json IS NOT NULL
    """, (frames,))
    for template_id, raw in cr.fetchall():
        try:
            tree = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not Template._starts_with_address_block(tree):
            continue
        tree['main'][:0] = Template._address_top_rows()
        cr.execute(
            'UPDATE doc_template SET content_json = %s WHERE id = %s',
            (json.dumps(tree, ensure_ascii=False), template_id),
        )
        _logger.info('[doc_editor] 範本 %s 的地址區塊上方補上 %spx',
                     template_id, Template._ADDRESS_TOP_PX)
