# -*- coding: utf-8 -*-
"""缺失改善通知範本 content_html：插入 {{ defect_categories }}（供 checkbox chip 升級）。

content_html 在 data/doc_template_data.xml 的 <data noupdate="1">，既有 DB 不吃 XML
update。本 migration 對已安裝、升級到本版的 DB，就地在「缺失說明」段前插入一行
缺失類別 token，讓開檔自動升級把它變成 checkbox（多選）chip：

  </table>\\n<h3>缺失說明</h3>  →  </table>\\n<p>缺失類別（可複選）：{{ defect_categories }}</p>\\n<h3>缺失說明</h3>

新裝 DB 由 XML 直接帶 token，不需本 script。idempotent（已含 token 即略過）。
"""
from odoo import api, SUPERUSER_ID

_ANCHOR = "</table>\n<h3>缺失說明</h3>"
_INSERT = "</table>\n<p>缺失類別（可複選）：{{ defect_categories }}</p>\n<h3>缺失說明</h3>"
_TOKEN = "{{ defect_categories }}"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    tmpl = env.ref(
        "dobtor_doc_editor.template_defect_improvement", raise_if_not_found=False
    )
    if not tmpl:
        return
    # content_html 是 markupsafe.Markup；用 str() 取純字串，否則 Markup.replace 會把
    # 插入字串裡的 <p></p> 跳脫成 &lt;p&gt;（_INSERT 含 HTML tag，與 18.0.2.2.0 那支
    # 純 token 替換不同，會踩到這個雷）。
    html = str(tmpl.content_html or "")
    if _TOKEN in html or _ANCHOR not in html:
        return  # 已轉換過，或範本內容被改過（anchor 不在）→ 不動
    tmpl.content_html = html.replace(_ANCHOR, _INSERT, 1)
