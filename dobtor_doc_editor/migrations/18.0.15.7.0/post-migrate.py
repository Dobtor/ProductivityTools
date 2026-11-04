# -*- coding: utf-8 -*-
"""把內建外框範本頁尾寫死中文的「第 X / Y 頁」換成多語寫法。

修的是什麼：範本內文已經依客戶語言切換，但外框頁尾的頁碼那一行是寫死的中文
「第 」「 頁」，印給英文客戶時整張英文、只有頁尾夾一行中文。新的外框改成
多語文字（繁中「第 1 / 1 頁」、英文「Page 1 / 1」、其他語言照 Odoo 自己的翻譯）。

只換跟舊版一模一樣的那一行（見 doc.template._upgrade_page_line）：使用者改過
那幾個字、或刪掉頁碼的外框不碰。外框其他地方改過沒關係——只動這一行。

用 SQL 直接寫回、不經 ORM：write_date 維持原樣，18.0.15.6.0 那支 migration
「沒被改過才轉」的判斷才不會被這次的寫入弄亂，也不會讓外框看起來像剛被人編輯過。
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
    # 藥丸在編輯器裡顯示的字用管理員的語言（升級時 context 沒有語言，
    # 不指定的話繁中使用者在外框裡看到的是英文的「Page」）
    admin = env.ref('base.user_admin', raise_if_not_found=False)
    Template = env['doc.template'].with_context(lang=(admin and admin.lang) or 'en_US')
    cr.execute("""
        SELECT id, content_json
          FROM doc_template
         WHERE role = 'layout' AND content_json IS NOT NULL
    """)
    for template_id, raw in cr.fetchall():
        try:
            tree = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not Template._upgrade_page_line(tree):
            _logger.info('[doc_editor] 外框範本 %s 的頁碼那一行改過或不存在，不動', template_id)
            continue
        cr.execute(
            'UPDATE doc_template SET content_json = %s WHERE id = %s',
            (json.dumps(tree, ensure_ascii=False), template_id),
        )
        _logger.info('[doc_editor] 外框範本 %s 的頁碼已改成多語', template_id)
