# -*- coding: utf-8 -*-
"""截圖失敗的分類與指紋：決定要不要重試、要不要叫 AI 修、整批要不要提前停。

★ 只有「腳本可修」值得叫 AI：環境（登入、權限、記錄規則、客戶資料）與資料（空白、找不到示範記錄）
  改腳本修不好，暫時性（網路、導向被打斷）原樣再試一次就好。
☠️ 實機（社群電商方案）：說明庫連不上時 87 張逐一請 AI「修」，花了約 $34；42 張修滿三次仍是同一個錯誤；
  第 45 輪拍了 2 小時 20 分、87 張全失敗才停。
"""
import re

TRANSIENT, ENVIRONMENT, DATA, SCRIPT, UNKNOWN = (
    'transient', 'environment', 'data', 'script', 'unknown')

_RULES = (
    (TRANSIENT, ('net::ERR', 'ENOTFOUND', 'Target closed', 'Connection refused',
                 'interrupted by another navigation', '沒有結果', '平行拍攝的子程序')),
    (ENVIRONMENT, ('後台沒有載入', '存取錯誤', '權限', 'Access', '登入失敗',
                   '非示範資料', '有東西出錯了', 'Odoo Server Error')),
    (DATA, ('空白引導頁',)),
    # 佔位符對不到示範記錄、角色沒帳號：AI 改繫結／改角色修得好，歸腳本類
    (SCRIPT, ('Locator.', '找不到要標註', 'wait_for_selector', 'Timeout', '未知步驟', '無法定位',
              '找不到示範資料', '說明庫沒有角色', '用網址打開精靈')),
)
_HINT = re.compile(r'^畫面（.*$', re.M)
_LOCATOR_TIMEOUT = re.compile(r'^(Locator|Page)\.\w+: Timeout')
_ACCESS = ('存取錯誤', '權限', 'Access')


def is_access(error):
    """環境錯誤裡屬於「權限」的（換角色修得好）；只看錯誤本身，不看 Call log。"""
    text = _HINT.sub('', error or '').split('Call log:')[0]
    return any(n in text for n in _ACCESS)
#: 可以叫 AI 修腳本的分類
REPAIRABLE = (SCRIPT, UNKNOWN)


def classify(error):
    """錯誤訊息 → 分類（依序比對，先中先贏）。"""
    # 截圖程式附的「畫面看得到的按鈕」那一行與 Playwright 的 Call log 不算：
    # 裡面是按鈕文字與選擇器（可能剛好含 Access、權限），不是錯誤本身
    text = _HINT.sub('', error or '').split('Call log:')[0]
    if _LOCATOR_TIMEOUT.match(text.strip()):
        return SCRIPT
    for kind, needles in _RULES:
        if any(n in text for n in needles):
            return kind
    return UNKNOWN


_WAITING = re.compile(r'waiting for (.{1,160})')


def fingerprint(error):
    """同一種錯誤的指紋：分類＋第一行去掉數字、引號內容、網址、編號。

    ★ 定位逾時另外帶上「等的是哪個元素」：不同按鈕點不到是不同的錯，不能算「同一錯誤不再修」。
    ☠️ 實機（社群電商方案）：23 張不同按鈕的逾時指紋都是「Locator.click: Timeout」。"""
    first = (error or '').strip().splitlines()[0] if (error or '').strip() else ''
    first = re.sub(r'https?://\S+', 'URL', first)
    first = re.sub(r"'[^']*'|\"[^\"]*\"|「[^」]*」|\{[^}]*\}|\[[^\]]*\]", 'Q', first)
    first = re.sub(r'\d+', 'N', first)
    target = _WAITING.search(error or '') if 'Timeout' in first else None
    if target:
        first += ' @' + re.sub(r'\d+', 'N', target.group(1).strip())[:100]
    return '%s:%s' % (classify(error), first[:220])


def halt_reason(errors, shot, canary, threshold=3, rate=0.5):
    """整批要不要停：已拍 ≥ 前哨數、失敗率 ≥ rate、且同一個「全面性」指紋出現 ≥ threshold 次。

    ★ 只有全面性的錯（後台打不開、登入失敗、系統錯誤、網路）才停：腳本錯各自修；資料（空白引導頁）
      與權限（換角色修得好）只影響那幾個畫面，停了反而讓其他畫面都沒拍。
    ☠️ 實機（2026-10-11 社群電商從零）：統一發票 4 個畫面示範資料不足都是空白引導頁，畫面名稱截斷後同一指紋
      → 整批停、29 張沒拍。
    errors：這一輪已拍的失敗訊息清單；shot：這一輪已拍張數。回傳 (指紋, 次數) 或 None。"""
    if shot < canary or not errors or len(errors) < shot * rate:
        return None
    counts = {}
    for e in errors:
        fp = fingerprint(e)
        if not fp.startswith((SCRIPT, DATA)) and not is_access(e):
            counts[fp] = counts.get(fp, 0) + 1
    if not counts:
        return None
    fp, n = max(counts.items(), key=lambda kv: kv[1])
    return (fp, n) if n >= threshold else None
