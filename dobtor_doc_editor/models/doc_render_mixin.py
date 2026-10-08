"""doc.render.mixin — 藥丸渲染管線的組合點。

實作分成六層（見 models/render/）：

    tree      元素樹的詞彙與走訪
    sandbox   Jinja 沙箱與求值（兩條求值路徑的差別在那裡說明）
    fields    欄位清單與別名（alias 退場中）
    i18n      多語文字工具
    snapshot  快照管線——**pass 鏈的順序約束在那裡**
    output    HTML / DOCX 輸出

為什麼用純 Python mixin 而不是六個 AbstractModel 再 _inherit 組合：
那樣會在 registry 裡多出六個模型，而它們單獨存在時是壞的
（snapshot 的方法會呼叫 sandbox 的方法）。純類別組合只有一個模型
`doc.render.mixin`，誰都不可能只拿到半套。
Odoo 的 _build_model 以 `type(name, (cls,), …)` 建類別，宣告類別自己的
Python 基底會保留在 MRO 裡——這是支援的做法。
"""
from odoo import models

from .render.fields import RenderFields
from .render.i18n import RenderI18n
from .render.output import RenderOutput
from .render.sandbox import RenderSandbox
from .render.snapshot import RenderSnapshot
from .render.tree import RenderTree


class DocRenderMixin(
    RenderTree,
    RenderSandbox,
    RenderFields,
    RenderI18n,
    RenderSnapshot,
    RenderOutput,
    models.AbstractModel,
):
    _name = 'doc.render.mixin'
    _description = '文件渲染 Mixin'
