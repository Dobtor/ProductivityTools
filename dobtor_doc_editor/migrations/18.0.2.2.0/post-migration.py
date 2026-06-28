# -*- coding: utf-8 -*-
"""自主檢查表範本 content_html：死文字 → {{ token }}（供 radio chip 升級）。

content_html 存在 data/doc_template_data.xml 的 <data noupdate="1"> 區塊，既有 DB
不會被 XML 更新覆蓋（noupdate 只擋 update、不擋新裝時的 create）。本 migration 對
「已安裝、升級到本版」的 DB 就地把自主檢查表的兩處死文字改成 token，讓開檔自動升級
能把它們變成 radio chip：

  整體結果   □合格　□條件式合格　□不合格  → {{ overall_result }}（odoo radio）
  清單 3 列  □合格 □不合格 ×3            → {{ result_1/2/3 }}（custom radio）

新裝的 DB 由 XML 直接 create 帶 token 的 content_html，不需本 script；本 script
idempotent（已含 {{ overall_result }} 即略過），重跑安全。
"""
from odoo import api, SUPERUSER_ID

# 全形空白 U+3000（整體結果三選項之間的分隔），用顯式 escape 避免與半形空白混淆
_OVERALL_LITERAL = "□合格　□條件式合格　□不合格"
_OVERALL_TOKEN = "{{ overall_result }}"
# 清單列「□合格 □不合格」用半形空白
_RESULT_LITERAL = "□合格 □不合格"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    tmpl = env.ref(
        "dobtor_doc_editor.template_self_inspection", raise_if_not_found=False
    )
    if not tmpl:
        return
    html = tmpl.content_html or ""
    if _OVERALL_TOKEN in html:
        return  # 已轉換過
    html = html.replace(_OVERALL_LITERAL, _OVERALL_TOKEN)
    # 依出現順序把 3 個相同的「□合格 □不合格」換成 result_1/2/3
    for i in (1, 2, 3):
        html = html.replace(_RESULT_LITERAL, "{{ result_%d }}" % i, 1)
    tmpl.content_html = html
