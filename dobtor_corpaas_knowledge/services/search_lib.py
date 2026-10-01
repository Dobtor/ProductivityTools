# -*- coding: utf-8 -*-
"""help_search 的評分——純函式。

中文沒有空白分詞，PG 全文檢索對它幾乎無用。候選集合很小（一個方案幾百個
功能點），所以直接在 Python 以「字元二元組」重疊度評分，簡單且可預測。
"""
import re

_SPLIT = re.compile(r'[\s,，、。．.;；:：/／()（）\[\]「」"\'?？!！]+')


def grams(text):
    """英數取整詞、中文取二元組。"""
    out = set()
    for token in _SPLIT.split((text or '').lower()):
        if not token:
            continue
        if token.isascii():
            out.add(token)
            continue
        if len(token) == 1:
            out.add(token)
        for i in range(len(token) - 1):
            out.add(token[i:i + 2])
    return out


def score(query, fields):
    """fields: [(text, weight)]；回傳 0..1。"""
    q = grams(query)
    if not q:
        return 0.0
    total = 0.0
    weight_sum = 0.0
    for text, weight in fields:
        weight_sum += weight
        g = grams(text)
        if g:
            total += weight * (len(q & g) / float(len(q)))
    return total / weight_sum if weight_sum else 0.0
