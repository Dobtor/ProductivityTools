"""doc.qweb.converter — QWeb 報表轉範本的組合點。

實作分成五層（見 models/qweb/）：

    entry      對外入口與轉換後試算
    locate     找出要轉哪一段 arch（combined arch、外殼範本）
    expr       表達式對應與 t-set 符號表展開
    structure  走訪與 t-if/t-elif/t-else 兄弟鏈
    blocks     圖片、稅額彙總、重複、表格、條件

組合方式與 doc.render.mixin 相同（純 Python mixin，見 ADR-026）：
拆成五個 AbstractModel 會在 registry 多出五個「單獨存在時是壞的」模型。
"""
import json
import logging
import re
from odoo import models
from .qweb.entry import ConvEntry
from .qweb.locate import ConvLocate
from .qweb.expr import ConvExpr
from .qweb.structure import ConvStructure
from .qweb.blocks import ConvBlocks

# ☠️ 組合點在 models/，常數在 models/qweb/——相對 import 要多一層。
# 少這一層的症狀是模組整個載不進去（ModuleNotFoundError），
# 和 models/render/ 那次拆分踩到的是同一個坑（ADR-026）。
from .qweb.constants import (
    _logger,
    _ROOT_VARS,
    _WRAPPER_TEMPLATES,
    _LAYOUT_TEMPLATES,
    _TAX_TOTALS_TEMPLATES,
    _TAX_TOTALS_COMPANY_TEMPLATES,
    _WIDGET_WRAPPERS,
    _BLOCK_TAGS,
    _SKIP_TAGS,
    _SIMPLE_PATH_RE,
    _LIT,
    _ROOT_TOKEN_RE,
    _LINE_TOKEN_RE,
)


class DocQwebConverter(
        ConvEntry,
        ConvLocate,
        ConvExpr,
        ConvStructure,
        ConvBlocks,
        models.AbstractModel,
):
    """把原生 QWeb 報表範本轉成本模組的 content_json。

    這支**只轉版面與結構**，而且會把每一個沒把握的地方列進 notes。
    設計原則只有一條：**寧可標成待辦，也不要猜**。轉錯的版面使用者看得見，
    轉錯的綁定（印出別的欄位的值）看不見。

    與「從渲染結果反推綁定」完全不同：那條路不安全（數量的 "2" 在一份輸出
    裡出現 243 次；qty=1 時 price_unit 與 price_subtotal 數學上不可區分）。
    但從 arch 轉換時 `t-field="doc.partner_id"` 寫得清清楚楚——路徑是讀出來的，
    不是猜的。所以簡單路徑會直接綁好，複雜表達式才標 unbound。
    """
    _name = 'doc.qweb.converter'
    _description = 'QWeb 報表 → 文件範本轉換器'

