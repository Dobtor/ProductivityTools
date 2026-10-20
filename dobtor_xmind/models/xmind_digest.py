# -*- coding: utf-8 -*-
"""分頁內容摘要（digest）與樂觀鎖用的衝突例外。

為什麼需要：``save_mindmap_data`` 是「整張分頁覆寫」，後存者蓋掉先存者。
編輯器載入畫面後，若這張分頁在伺服器端被別人（另一個分頁、專案同步、匯入、
外部程式）改過，舊畫面再存檔就會把那些變更悄悄洗掉。摘要就是「我載入時看到的
那一版」的指紋：存檔時帶回來，與目前資料庫的指紋不同就拒絕，而不是覆蓋。

★ 純函式（本檔不 import odoo ORM）：``digest_payload()`` 只吃一個可 JSON 化的
  結構，方便獨立測試；怎麼從資料庫組出這個結構在 ``xmind.sheet._content_digest()``。
★ 範圍刻意比「標題＋結構」寬：涵蓋主題的文字、樣式、標記、專案連結，以及五種
  特徵層（關聯線／外框／總結／標註／浮動主題）—— 因為存檔會把這些全部覆寫，
  樂觀鎖要保護的就是這一整組。**不含** ``expanded``（使用者只是收合／展開）
  與浮動主題座標：那些是檢視狀態，讓它們造成衝突只會製造雜訊。
"""
import hashlib
import json

from odoo.exceptions import UserError

#: 摘要版本。演算法改了就要換，舊版本的摘要一律當成不符（不會誤放行）。
DIGEST_VERSION = 'v1'


class XmindConflict(UserError):
    """存檔時發現分頁在載入之後被改過（樂觀鎖不符）。

    ``current_digest`` 是目前資料庫的摘要，讓呼叫端可以決定要重新載入。
    """

    def __init__(self, message, current_digest=None):
        super().__init__(message)
        self.current_digest = current_digest


def digest_payload(payload):
    """把可 JSON 化的結構正規化後取 sha256（十六進位字串）。"""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                     separators=(',', ':'), default=str)
    return hashlib.sha256((DIGEST_VERSION + '\n' + raw).encode('utf-8')).hexdigest()
