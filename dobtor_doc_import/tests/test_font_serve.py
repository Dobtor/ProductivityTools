# -*- coding: utf-8 -*-
"""Sprint 66 — Backend tests for `/dobtor/fonts/*` endpoints（Sprint 64b infrastructure）。

驗證：
    - `/dobtor/fonts/list`（JSON-RPC）回傳 available fonts
    - `/dobtor/fonts/<family>`（HTTP）對已知 family 回 TTF bytes
    - 對未知 family 回 404
    - URL-decoded CJK family 處理正確
    - file missing 時 graceful（map 有但檔案不存在）
    - **未登入不可以拿到字型**（2026-10-09 從 auth='public' 收緊成 auth='user'，
      見 controllers/font_serve.py 檔頭的理由）

執行方式（Odoo HttpCase 需 Odoo runtime）：
    docker exec odoo18 odoo -c /etc/odoo/odoo.conf -d odoo18_dev \\
        --test-tags dobtor_doc_import.font_serve --stop-after-init

也可單獨用 ORM 層測 controller 邏輯（不啟 HTTP），見 `TestFontServeLogic`。
"""

import os
from unittest.mock import patch

from odoo.addons.dobtor_doc_editor.tests.session_probe import SessionAliveMixin
from odoo.tests.common import HttpCase, TransactionCase, tagged

from ..controllers.font_serve import FONT_PATH_MAP, resolve_font_path


@tagged('post_install', '-at_install', 'dobtor_doc_import', 'font_serve')
class TestFontServeLogic(TransactionCase):
    """純邏輯測試：FONT_PATH_MAP 結構 + 已知 family 對應的檔案邏輯。

    Sprint 69 schema 更新：FONT_PATH_MAP[fam] 從 str 改 tuple of candidate paths。
    """

    def test_font_path_map_structure(self):
        """FONT_PATH_MAP 必含基本 family、值是 candidate path tuple、且至少有一個合法字型路徑。"""
        # 至少要有的 family（Sprint 62-64 對齊 LO render 的關鍵 fallback）
        required_families = ['Times New Roman', '標楷體', 'Arial']
        valid_extensions = ('.ttf', '.ttc', '.otf')
        for fam in required_families:
            self.assertIn(fam, FONT_PATH_MAP, f'缺少 family: {fam}')
            candidates = FONT_PATH_MAP[fam]
            self.assertIsInstance(
                candidates, tuple,
                f'{fam} schema 應為 tuple of candidate paths（Sprint 69）',
            )
            self.assertGreater(len(candidates), 0, f'{fam} candidates 不可為空')
            for path in candidates:
                self.assertTrue(
                    path.startswith('/usr/share/fonts/'),
                    f'{fam} candidate 應為 /usr/share/fonts/ 下：{path}',
                )
                self.assertTrue(
                    path.endswith(valid_extensions),
                    f'{fam} candidate 應為 .ttf/.ttc/.otf：{path}',
                )

    def test_cjk_families_share_same_candidate_chain(self):
        """所有 CJK 繁中 family 共用同一個 candidate chain（Sprint 69 schema）。

        Sprint 64b 原本所有 CJK 都對齊單一 DroidSansFallback；Sprint 69 改 tuple、
        所有 CJK family 仍指向同一個 candidate chain（含 DroidSansFallback + Noto CJK fallback）。
        """
        cjk_families = [
            '標楷體', '微軟正黑體', '新細明體', '細明體',
            'DFKai-SB', 'PMingLiU', 'MingLiU',
        ]
        chains = {fam: FONT_PATH_MAP[fam] for fam in cjk_families}
        # 所有 CJK family 的 candidate chain 應該完全相同（同一個 tuple object）
        reference = chains['標楷體']
        for fam, chain in chains.items():
            self.assertEqual(
                chain, reference,
                f'{fam} candidate chain 應與標楷體相同、實際 {chain}',
            )
        # 而且 chain 中至少要有 DroidSansFallback 或 NotoCJK
        has_cjk_font = any(
            'Droid' in p or 'NotoSansCJK' in p or 'NotoSerifCJK' in p
            for p in reference
        )
        self.assertTrue(has_cjk_font, f'CJK chain 應含 Droid 或 Noto CJK：{reference}')

    def test_resolve_font_path_handles_unknown_family(self):
        """resolve_font_path() 對未知 family 應回 None（不 crash）。"""
        self.assertIsNone(resolve_font_path('NoSuchFontFamily12345'))
        self.assertIsNone(resolve_font_path(''))


@tagged('post_install', '-at_install', 'dobtor_doc_import', 'font_serve')
class TestFontServeHttp(SessionAliveMixin, HttpCase):
    """HTTP 層測試：實際呼叫 `/dobtor/fonts/*` 路由。

    ☠️ 2026-10-09 起這兩條路由是 `auth='user'`（從 public 收緊），所以這裡
    必須先登入。掛 SessionAliveMixin 並改用 `_url_open_live()` 的理由跟其他
    打 auth='user' 路由的測試一樣：HttpCase 的 session 會在測試中途偶發失效
    （ormcache 不隨交易回滾），見 dobtor_doc_editor/tests/session_probe.py 檔頭。
    """

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')

    def test_list_fonts_json_rpc(self):
        """`/dobtor/fonts/list` JSON-RPC 回 available fonts + 大小."""
        resp = self._url_open_live(
            '/dobtor/fonts/list',
            data='{}',
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # JSON-RPC 包在 result key
        result = data.get('result', data)
        self.assertIn('fonts', result)
        # 至少有些 font 可用（依環境）
        if result['fonts']:
            sample = result['fonts'][0]
            self.assertIn('family', sample)
            self.assertIn('url', sample)
            self.assertIn('size_bytes', sample)
            self.assertTrue(sample['url'].startswith('/dobtor/fonts/'))

    def test_serve_known_family_returns_font_bytes(self):
        """已知 family 經 resolve_font_path 找到 candidate 後回 font bytes + 正確 headers。

        Sprint 69 schema 更新：用 resolve_font_path() 判斷 family 是否可服務、
        不再要求單一 hardcoded path 存在。
        """
        # 找第一個可 resolve 的 family
        existing_family = None
        for family in FONT_PATH_MAP:
            if resolve_font_path(family):
                existing_family = family
                break
        if not existing_family:
            self.skipTest('所有 family 的 candidate paths 都不存在 — minimal container')

        from urllib.parse import quote
        resp = self._url_open_live(f'/dobtor/fonts/{quote(existing_family)}')
        self.assertEqual(resp.status_code, 200)
        # Sprint 69: Content-Type 可能是 font/ttf 或 font/collection（.ttc）
        content_type = resp.headers.get('Content-Type', '')
        self.assertIn(content_type, ('font/ttf', 'font/collection', 'font/otf'))
        # 1 年 immutable cache
        cache_control = resp.headers.get('Cache-Control', '')
        self.assertIn('max-age=', cache_control)
        self.assertIn('immutable', cache_control)
        # ☠️ 原本斷言 ACAO == '*'。改成 auth='user' 之後那個 header 被移除了
        #    ——CORS 規格禁止 `*` 搭配帶憑證的請求，留著只會讓人以為端點是
        #    開放的。這裡反向斷言它不再出現，免得哪天被加回來。
        self.assertNotEqual(
            resp.headers.get('Access-Control-Allow-Origin'), '*',
            "auth='user' 的端點不該回 Access-Control-Allow-Origin: *"
            "（CORS 規格禁止 `*` 配帶憑證的請求，等於宣告了一個不能用的開放）")
        # 真有 bytes
        self.assertGreater(len(resp.content), 0)

    def test_serve_unknown_family_returns_404(self):
        """未知 family 回 404。"""
        resp = self._url_open_live('/dobtor/fonts/NoSuchFontFamily12345')
        self.assertEqual(resp.status_code, 404)

    def test_serve_known_family_missing_file_returns_404(self):
        """family 在 map 但所有 candidate 都不存在 → 404（graceful、Sprint 69 schema）。"""
        # patch FONT_PATH_MAP，加一個 family 指向 candidate tuple 全 missing
        bogus_map = dict(FONT_PATH_MAP)
        bogus_map['BOGUS_FAMILY'] = ('/nonexistent/path.ttf', '/also/missing.ttf')
        with patch.dict('odoo.addons.dobtor_doc_import.controllers.font_serve.FONT_PATH_MAP', bogus_map, clear=True):
            resp = self._url_open_live('/dobtor/fonts/BOGUS_FAMILY')
            self.assertEqual(resp.status_code, 404)


@tagged('post_install', '-at_install', 'dobtor_doc_import', 'font_serve')
class TestFontServeSecurity(SessionAliveMixin, HttpCase):
    """Sprint 68 — 邊界與安全測試：FONT_PATH_MAP dict.get() 已防 path traversal、
    但仍應 explicit 驗證（紀律 #5 應用：production path 與 test path 可能不同）。

    這層測試補完 Sprint 66 漏掉的：
        - Path traversal（`../../etc/passwd` 與 percent-encoded 變體）
        - URL-encoded CJK 自動 decode（標楷體 → %E6%A8%99%E6%A5%B7%E9%AB%94）
        - Null byte injection（CVE-2023-style）

    ☠️ 這些邊界要在**已登入**的前提下驗——auth 層擋掉的 404 與 dict 鍵不命中
    的 404 長得一樣，未登入跑這批測試會變成「驗到 auth 層、沒驗到 dict 鍵」。
    """

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')

    def test_path_traversal_literal_returns_404(self):
        """字面 path traversal `../../etc/passwd` 不應命中 dict、回 404。"""
        # Odoo router 對 string converter 是否吃 `/` 取決於 werkzeug；
        # 若 router 把 `..` 視為非法路徑、可能 400 / 404 由 Odoo 處理
        resp = self._url_open_live('/dobtor/fonts/..%2F..%2Fetc%2Fpasswd')
        self.assertEqual(resp.status_code, 404)

    def test_path_traversal_double_encoded_returns_404(self):
        """雙層 percent-encode 也不應繞過（dict 鍵嚴格相等）。"""
        # %252E%252E → `..` 解兩次；但 Werkzeug 只 decode 一次 → 字面 `%2E%2E`
        # 任何方式都不會匹配 FONT_PATH_MAP，故必 404
        resp = self._url_open_live('/dobtor/fonts/%252E%252E%252Fpasswd')
        self.assertEqual(resp.status_code, 404)

    def test_null_byte_in_family_returns_404(self):
        """family 含 null byte（CVE 風格、企圖截斷檔名）不應命中 → 404。"""
        # %00 是 null byte
        resp = self._url_open_live('/dobtor/fonts/%E6%A8%99%E6%A5%B7%E9%AB%94%00.ttf')
        self.assertEqual(resp.status_code, 404)

    def test_url_encoded_cjk_decodes_correctly(self):
        """URL-encoded 「標楷體」應正確 decode、走 resolve_font_path candidate chain（Sprint 69）。"""
        # 「標楷體」UTF-8 percent-encoded = %E6%A8%99%E6%A5%B7%E9%AB%94
        if not resolve_font_path('標楷體'):
            self.skipTest('「標楷體」candidate chain 全 missing（CJK font 未安裝）')

        resp = self._url_open_live('/dobtor/fonts/%E6%A8%99%E6%A5%B7%E9%AB%94')
        self.assertEqual(resp.status_code, 200)
        # Sprint 69: 可能是 ttc 或 ttf 端看 container 環境
        content_type = resp.headers.get('Content-Type', '')
        self.assertIn(content_type, ('font/ttf', 'font/collection', 'font/otf'))
        self.assertGreater(len(resp.content), 0)

    def test_list_empty_when_all_paths_missing(self):
        """所有 FONT_PATH_MAP 路徑都不存在時，list 應回空 list（不 crash、Sprint 69 schema）。"""
        empty_map = {
            k: ('/nonexistent/' + k.replace(' ', '_') + '.ttf', '/also/missing/' + k.replace(' ', '_') + '.ttc')
            for k in FONT_PATH_MAP
        }
        patch_target = 'odoo.addons.dobtor_doc_import.controllers.font_serve.FONT_PATH_MAP'
        with patch.dict(patch_target, empty_map, clear=True):
            resp = self._url_open_live(
                '/dobtor/fonts/list',
                data='{}',
                headers={'Content-Type': 'application/json'},
            )
            self.assertEqual(resp.status_code, 200)
            result = resp.json().get('result', resp.json())
            self.assertEqual(result.get('fonts'), [])
            # note 仍要在（caller 須能識別 endpoint 沒掛掉、只是無 font）
            self.assertIn('note', result)


@tagged('post_install', '-at_install', 'dobtor_doc_import', 'font_serve')
class TestFontServeRequiresLogin(HttpCase):
    r"""未登入不可以拿到字型——2026-10-09 從 `auth='public'` 收緊的守衛。

    ☠️ 為什麼一定要有這一支：收緊 auth 是一行字的改動，而「改回去」也是一行。
    沒有會紅的測試盯著，這次收緊的壽命就取決於下一個人有沒有讀過
    controllers/font_serve.py 的檔頭。本模組一整天抓到的失效模式就是
    「寫好了但沒有東西證明它還成立」。

    ☠️ 這個類別**刻意不登入、也不掛 SessionAliveMixin**：它要驗的就是未登入
    的行為，自救機制會把它要驗的東西救掉。

    未登入時 Odoo 的回應形狀**依路由型別而不同**（2026-10-09 實測）：
      - `type='http'` → 303 轉址到 /web/login，跟著轉完拿到登入頁 HTML
      - `type='json'` → **不轉址**，回 HTTP 200 ＋ JSON-RPC error，
        `error.data.name` 是 `odoo.http.SessionExpiredException`
    只驗其中一種會讓另一條路由的回歸溜過去。
    """

    def test_serve_font_requires_login(self):
        """`GET /dobtor/fonts/<family>`（type='http'）未登入 → 導去登入頁，不給 bytes。"""
        existing_family = None
        for family in FONT_PATH_MAP:
            if resolve_font_path(family):
                existing_family = family
                break
        if not existing_family:
            self.skipTest('所有 family 的 candidate paths 都不存在 — minimal container')

        from urllib.parse import quote
        resp = self.url_open(f'/dobtor/fonts/{quote(existing_family)}')
        # 關鍵斷言：不可以是字型
        content_type = (resp.headers.get('Content-Type') or '').split(';')[0]
        self.assertNotIn(
            content_type, ('font/ttf', 'font/collection', 'font/otf'),
            '未登入竟然拿到了字型（Content-Type=%s, %d bytes）——'
            'auth 被改回 public 了嗎？見 controllers/font_serve.py 檔頭。'
            % (content_type, len(resp.content)))
        # 而且要看得出是 auth 層擋的（不是別的 404）
        self.assertIn(
            '/web/login', resp.url,
            '未登入的回應沒有落在登入頁（最終 URL=%s、狀態碼=%s）——'
            '那就不是 auth 層擋下來的，請確認路由的 auth 設定。'
            % (resp.url, resp.status_code))

    def test_list_fonts_requires_login(self):
        """`/dobtor/fonts/list`（type='json'）未登入 → JSON-RPC 的 session 過期錯誤。"""
        resp = self.url_open(
            '/dobtor/fonts/list',
            data='{}',
            headers={'Content-Type': 'application/json'},
        )
        body = resp.json()
        self.assertIsInstance(
            body, dict, 'JSON-RPC 的回應一定是物件，實際 %r' % (body,))
        self.assertIn(
            'error', body,
            '未登入竟然拿到了字型清單：%r——auth 被改回 public 了嗎？'
            % (body.get('result'),))
        name = ((body.get('error') or {}).get('data') or {}).get('name') or ''
        self.assertIn(
            'SessionExpired', name,
            '未登入被擋下來了，但不是 auth 層擋的（error.data.name=%r）。'
            '那代表擋它的是別的東西，這一則就沒有驗到 auth 設定。' % name)


@tagged('post_install', '-at_install', 'dobtor_doc_import')
class TestThirdPartyLicenseRegistry(TransactionCase):
    r"""出貨產物內嵌的第三方，都要有授權登記——階段 5 稽核（2026-10-09）。

    ☠️ 本模組原本**完全沒有** `LICENSE` 與 `LICENSES/`，卻宣告
    `'license': 'OPL-1'` 並出貨兩個內嵌 fflate / @xmldom/xmldom 的產物。

    成因是拆模組（ADR-033）：OOXML 建置鏈與它的 npm 相依整批搬到本模組，
    而授權登記留在核心（`dobtor_doc_editor/LICENSES/`）。核心把這件事做對了，
    本模組是那個把第三方程式碼接過來卻沒接登記的。

    這一支守的是「登記不可以又漂走」。判定依據是**在產物裡實際找到那個函式庫
    的實作符號**，不是 package.json 寫了什麼——package.json 的 dependencies
    有四個，其中兩個並沒有被打進出貨產物（見 LICENSES/README.md）。
    """

    #: 產物 → 必須登記的第三方（判定符號取自該函式庫的內部實作）
    BUNDLED = {
        'static/src/lib/canvas_editor/canvas-editor-custom.umd.js': {
            'fflate': ('strFromU8', 'inflateSync'),
        },
        'tools/dist/parse_docx_cli.cjs': {
            'fflate': ('strFromU8', 'inflateSync'),
            'xmldom': ('__DOMHandler', 'DOMImplementation', 'ParseError'),
        },
    }

    def _root(self):
        # 從測試檔推模組根（tests/ 的上一層）——不必 import controller。
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_module_has_a_license_file(self):
        """模組根目錄要有 LICENSE（manifest 宣告 OPL-1，就要附全文）。"""
        path = os.path.join(self._root(), 'LICENSE')
        self.assertTrue(os.path.exists(path), '模組根目錄缺 LICENSE')
        with open(path, encoding='utf-8') as fh:
            head = fh.read(200)
        self.assertIn(
            'Odoo Proprietary License', head,
            'LICENSE 不是 OPL-1 的全文，但 __manifest__ 宣告 OPL-1')

    def test_every_bundled_third_party_has_its_licence_text(self):
        """產物裡**實際找得到實作符號**的第三方，都要有授權全文。"""
        root = self._root()
        missing = []
        for artifact, libs in self.BUNDLED.items():
            apath = os.path.join(root, artifact)
            if not os.path.exists(apath):
                missing.append('%s 不存在（產物沒建？）' % artifact)
                continue
            with open(apath, 'rb') as fh:
                blob = fh.read()
            for lib, symbols in libs.items():
                found = [s for s in symbols if s.encode() in blob]
                if not found:
                    # 函式庫不再被內嵌了 → 登記可以移除，但要有人決定
                    missing.append(
                        '%s 裡找不到 %s 的任何實作符號 %s——'
                        '它可能已經不再被內嵌了，請更新 LICENSES/README.md 的對應表'
                        % (artifact, lib, symbols))
                    continue
                lic = os.path.join(root, 'LICENSES', '%s.LICENSE' % lib)
                if not os.path.exists(lic):
                    missing.append(
                        '%s 內嵌了 %s（符號 %s）但 LICENSES/%s.LICENSE 不存在'
                        % (artifact, lib, found, lib))
        self.assertFalse(missing, '授權登記有缺口：\n  %s' % '\n  '.join(missing))

    def test_licence_registry_has_a_readme_mapping(self):
        """`LICENSES/README.md` 要列出每個被登記的第三方。

        光放授權全文不夠——沒有對應表的話，下一個人不知道哪個檔案內嵌了什麼。
        """
        root = self._root()
        readme = os.path.join(root, 'LICENSES', 'README.md')
        self.assertTrue(os.path.exists(readme), '缺 LICENSES/README.md 對應表')
        with open(readme, encoding='utf-8') as fh:
            text = fh.read()
        for libs in self.BUNDLED.values():
            for lib in libs:
                self.assertIn(
                    lib, text,
                    'LICENSES/README.md 沒有提到 %s，而產物裡有它' % lib)
