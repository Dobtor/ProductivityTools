# -*- coding: utf-8 -*-
"""條款庫的純函式：套用條件與置換變數（不 import odoo，可獨立測試）。"""
import re

_VAR = re.compile(r'\{(\w+)\}')

#: 條款適用條件。`always` 以外的都要版本「具備該特徵」才會載入。
CONDITIONS = [
    ('always', '一律'),
    ('subscription', '訂閱＋一次性導入'),
    ('time_budget', '工時制固定預算'),
    ('custom_dev', '含客製開發'),
    ('data_migration', '含資料移轉'),
    ('integration', '含系統串接'),
    ('multi_company', '多公司'),
]


def applies(condition, flags):
    """條款的條件是否成立。`flags` 是這個版本具備的特徵集合。"""
    return not condition or condition == 'always' or condition in flags


def render(text, values):
    """把 `{name}` 換成值；**不認得的變數原樣留著**，不丟例外。

    ★ 不用 `str.format`：條款裡常有別的大括號（例如 `{A}`、金額範例），
      format 遇到會 KeyError／ValueError，一條壞條款就讓整份文件出不來。
    ★ 原樣留著而不是換成空字串：缺值要被看見（文件裡留著 `{validity_days}`），
      而不是悄悄少一句話。
    """
    def repl(match):
        key = match.group(1)
        value = values.get(key)
        # ☠️ 不能寫 `value not in (None, False)`：Python 裡 0 == False，保固 0 個月會被當成缺值
        return match.group(0) if value is None or value is False else str(value)
    return _VAR.sub(repl, text or '')


def unresolved(text):
    """條款裡還沒被換掉的變數名（給檢查用）。"""
    return sorted(set(_VAR.findall(text or '')))
