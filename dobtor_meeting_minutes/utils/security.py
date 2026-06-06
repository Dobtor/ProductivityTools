# -*- coding: utf-8 -*-
"""安全相關工具：敏感資料遮蔽"""

import re


# API key / Bearer token / authorization header 遮蔽規則
# (pattern, replacement) — 保留 prefix 便於辨識，token 部份全部替換為 ***
_SECRET_PATTERNS = [
    (re.compile(r'(Bearer\s+)[A-Za-z0-9_\-\.=]+', re.IGNORECASE), r'\1***'),
    (re.compile(r'(authorization["\']?\s*[:=]\s*["\']?)[A-Za-z0-9_\-\.=]+', re.IGNORECASE), r'\1***'),
    (re.compile(r'sk-[A-Za-z0-9_\-]{10,}'), '***'),
    # AssemblyAI api key 常見格式：32-char hex
    (re.compile(r'\b[a-f0-9]{32}\b'), '***'),
]


def mask_secrets(text):
    """遮蔽 API key 與 authorization header

    用於寫入 log / traceback / response snippet 之前。
    即使 regex 未完全覆蓋，也不會壞事（只是多/少遮幾個字元）。
    """
    if not text:
        return text
    masked = text
    for pat, repl in _SECRET_PATTERNS:
        masked = pat.sub(repl, masked)
    return masked


def redact_display_key(value, visible_tail=4):
    """用於 UI 顯示 API key：只顯示最後 N 個字元 + 前面星號

    >>> redact_display_key('sk-1234567890abcdef')
    '●●●●●●●●●●●●●cdef'
    >>> redact_display_key('', 4)
    ''
    """
    if not value:
        return ''
    if len(value) <= visible_tail:
        return '●' * len(value)
    return '●' * (len(value) - visible_tail) + value[-visible_tail:]
