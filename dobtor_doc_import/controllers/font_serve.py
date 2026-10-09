# -*- coding: utf-8 -*-
"""Sprint 64b — Font Serve Controller

提供 portal / canvas-editor 端 lazy load LO 系統字型 bytes 的 HTTP endpoint。
未來自家 pipeline 取代 canvas-editor production rendering 時，配合 FontLoader
（[`static/src/core/font_loader.ts`](../static/src/core/font_loader.ts)）對齊 goldens metric source。

**重要定位**（Sprint 64b 誠實註記）：
    - 目前 production 走 canvas-editor，本 endpoint 是「未來 migrate 準備 infrastructure」
    - VR pipeline 自己有 LO 系統 font bytes（`scripts/visual_regression_v14.mjs` 直接 readFileSync）
    - 本 endpoint 提供 *browser* 端取得 font bytes 的方式（fs 不可用）→ 將來
      canvas-editor 端或自家 pipeline 端要用 FontMetricsAdapter 時 fetch + IDB cache

設計（Strategy B from Sprint 64 audit）：
    - 路由：`GET /dobtor/fonts/<family>`（auth='user' — 見下方「為什麼從 public 收緊」）
    - URL-decode family name（支援 CJK 全形字 e.g. /dobtor/fonts/%E6%A8%99%E6%A5%B7%E9%AB%94）
    - server-side 從 fixed mapping 找對應 TTF（與 visual_regression_v14.mjs 一致）
    - 回傳 `font/ttf` + 長 Cache-Control（fonts 不變 = immutable）
    - 配 `font_loader.ts` 的 IDB cache → 第一次 fetch 後跨 session 共用

為什麼從 `auth='public'` 收緊成 `auth='user'`（2026-10-09）：
    這兩條路由**沒有活的消費者**——唯一的客戶是 `static/src/core/font_loader.ts`
    與 `ShapingFontChain.ts`，而它們目前不可達（ADR-034 的 `import` 軸宣告，
    附啟動條件）。在那個前提下，`auth='public'` 讓**任何未登入的人**都能
    讓伺服器讀磁碟並回傳一份字型（CJK 的 .ttc 可達數十 MB），沒有速率限制，
    而當下沒有任何對應的好處。

    字型本身不是機密，所以這不是資料外洩；收緊的理由是**去掉一個沒有用途的
    未驗證入口**。`auth='user'` 涵蓋 portal 使用者，所以檔頭原本寫的
    「portal / canvas-editor 端 lazy load」情境完全不受影響
    ——portal 使用者是登入狀態。

    ☠️ 連帶移除 `Access-Control-Allow-Origin: *`：CORS 規格**禁止**用 `*`
    搭配帶憑證（cookie）的請求，而 `auth='user'` 之後跨 origin 取字型必須
    帶 session cookie。也就是說那個 header 已經不可能發揮它原本宣稱的作用
    （「跨 origin 安全」），留著只會讓人以為這個端點是開放的。
    真正的消費者 `font_loader.ts` 是同源 fetch，不需要 CORS header。

    守衛：`tests/test_font_serve.py::TestFontServeRequiresLogin`
    ——未登入時兩條路由都不可以給出字型。沒有那道測試，這次收緊哪天被改回去
    不會有任何人知道。
"""

import logging
import os

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Sprint 64b → Sprint 69：font family → candidate 系統字型路徑（tuple, 第一個存在的 wins）
# 與 scripts/visual_regression_v14.mjs --font-metrics 模式同步
# 對齊 LibreOffice headless 渲染 goldens 時的 fallback font source
#
# **Sprint 69 揭示**：odoo18 container 為 minimal Debian/Ubuntu、無 droid/liberation 套件、
# 只有 fonts-noto-cjk + dejavu。WSL host（VR 跑）有 droid。改用 candidate fallback list、
# 跨 WSL host + odoo18 container 都 work。
#
# 順序原則（重要）：
# 1. 第一個（如 droid/liberation）= WSL host 環境 / VR pipeline 對齊 goldens 用
# 2. 第二個（如 Noto CJK / DejaVu）= odoo18 container 實際存在的字型
# → resolve_font_path() 依序試、回第一個存在的；都不存在則 None
CJK_CANDIDATES = (
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",      # WSL host（VR pipeline）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",         # odoo18 container
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",        # fallback CJK
)
SERIF_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",  # WSL host
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",                  # odoo18 container
)
SANS_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",   # WSL host
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",                   # odoo18 container
)

FONT_PATH_MAP = {
    # Latin：Times New Roman → Serif（LiberationSerif → DejaVuSerif fallback）
    "Times New Roman": SERIF_CANDIDATES,
    "Arial": SANS_CANDIDATES,
    # CJK：所有常見繁中字型 fallback chain（DroidSansFallback → NotoCJK）
    "標楷體": CJK_CANDIDATES,
    "微軟正黑體": CJK_CANDIDATES,
    "新細明體": CJK_CANDIDATES,
    "細明體": CJK_CANDIDATES,
    "DFKai-SB": CJK_CANDIDATES,
    "PMingLiU": CJK_CANDIDATES,
    "MingLiU": CJK_CANDIDATES,
}


def resolve_font_path(family):
    """回傳 family 對應第一個存在的字型路徑、無對應或全 missing 時回 None。

    Sprint 69：candidate fallback resolver 跨 WSL host / odoo18 container 兼容。
    """
    candidates = FONT_PATH_MAP.get(family)
    if not candidates:
        return None
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _content_type_for(path):
    """根據副檔名回 Content-Type。Sprint 69：TTC 是 OpenType Collection、用 font/collection。"""
    if path.endswith(".ttc"):
        return "font/collection"
    if path.endswith(".otf"):
        return "font/otf"
    return "font/ttf"


# 1 年 cache（fonts 不會變、新 family 才會新 URL）
_CACHE_CONTROL = "public, max-age=31536000, immutable"


class DobtorFontController(http.Controller):
    """Sprint 64b font serve endpoint（Strategy B: portal lazy load + IDB cache）。"""

    @http.route("/dobtor/fonts/list", type="json", auth="user", csrf=False)
    def list_fonts(self):
        """回傳可載入的 font family 清單 + 對應 endpoint URL。

        前端 FontLoader 用此 endpoint discover 可用字型、再選擇 fetch 哪些。
        """
        available = []
        for family in FONT_PATH_MAP:
            resolved = resolve_font_path(family)
            if resolved:
                available.append({
                    "family": family,
                    "url": "/dobtor/fonts/%s" % family,
                    "size_bytes": os.path.getsize(resolved),
                })
        return {
            "fonts": available,
            "note": "Sprint 64b infra（auth=user）— 目前 production 走 canvas-editor、未直接使用此 endpoint；"
                    "未來 migrate 自家 pipeline 時配 FontLoader (static/src/core/font_loader.ts) 使用",
        }

    @http.route(
        "/dobtor/fonts/<string:family>",
        type="http",
        auth="user",
        csrf=False,
        readonly=True,
    )
    def serve_font(self, family, **kwargs):
        """Serve font bytes for a family.

        - family 是 URL-decoded（Werkzeug 自動處理 percent-encoding）
        - 透過 resolve_font_path() 依序試 candidate paths（Sprint 69 修正）
        - 全部 candidates 都不存在 → 404
        - 找到 → 回 bytes + Content-Type（依副檔名）+ Cache-Control immutable / 1 年
        """
        font_path = resolve_font_path(family)
        if not font_path:
            _logger.info("font family not resolvable: %s", family)
            return request.not_found()

        try:
            with open(font_path, "rb") as fh:
                content = fh.read()
        except (IOError, OSError) as e:
            _logger.error("font read failed: %s — %s", font_path, e)
            return request.not_found()

        headers = [
            ("Content-Type", _content_type_for(font_path)),
            ("Content-Length", str(len(content))),
            ("Cache-Control", _CACHE_CONTROL),
            # ☠️ 原本有 ("Access-Control-Allow-Origin", "*")。改成 auth='user'
            #    之後它不可能發揮作用：CORS 規格禁止 `*` 搭配帶憑證的請求，
            #    而跨 origin 取字型現在必須帶 session cookie。真正的消費者
            #    （font_loader.ts）是同源 fetch，不需要這個 header。
        ]
        return request.make_response(content, headers=headers)
