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


def _jaccard(ga, gb):
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / float(len(ga | gb))


def similarity(a, b):
    """兩段文字的對稱相似度（二元組 Jaccard），0..1。用於能力名稱查重。

    原文與去空白標點後各比一次取高者：「排班 管理功能」被空白切開時，跨空白的
    二元組（班管）會消失，只比原文會低估。
    """
    return max(_jaccard(grams(a), grams(b)),
               _jaccard(grams(normalize_name(a)), grams(normalize_name(b))))


_NORM = re.compile(r'[\s\-_,，、。．.;；:：/／()（）\[\]「」"\'?？!！]+')


def normalize_name(text):
    """名稱正規化：去空白標點、轉小寫。「訂單 管理」與「訂單管理」視為同名。"""
    return _NORM.sub('', (text or '').lower())


def merge_lines(*texts):
    """多段「一行一個」文字合併去重（正規化比對，保留第一次出現的原文與順序）。"""
    out, seen = [], set()
    for text in texts:
        for line in (text or '').splitlines() if isinstance(text, str) else (text or []):
            line = (line or '').strip()
            key = normalize_name(line)
            if line and key not in seen:
                seen.add(key)
                out.append(line)
    return '\n'.join(out)
