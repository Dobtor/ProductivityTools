# -*- coding: utf-8 -*-
"""Sprint 66 — Backend tests for `/dobtor/fonts/*` endpoints（Sprint 64b infrastructure）。

驗證：
    - `/dobtor/fonts/list`（JSON-RPC）回傳 available fonts
    - `/dobtor/fonts/<family>`（HTTP）對已知 family 回 TTF bytes
    - 對未知 family 回 404
    - URL-decoded CJK family 處理正確
    - file missing 時 graceful（map 有但檔案不存在）

執行方式（Odoo HttpCase 需 Odoo runtime）：
    docker exec odoo18 odoo -c /etc/odoo/odoo.conf -d odoo18_dev \\
        --test-tags dobtor_doc_editor.font_serve --stop-after-init

也可單獨用 ORM 層測 controller 邏輯（不啟 HTTP），見 `TestFontServeLogic`。
"""

from unittest.mock import patch

from odoo.tests.common import HttpCase, TransactionCase, tagged

from ..controllers.font_serve import FONT_PATH_MAP, resolve_font_path


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'font_serve')
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


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'font_serve')
class TestFontServeHttp(HttpCase):
    """HTTP 層測試：實際呼叫 `/dobtor/fonts/*` 路由。"""

    def test_list_fonts_json_rpc(self):
        """`/dobtor/fonts/list` JSON-RPC 回 available fonts + 大小."""
        resp = self.url_open(
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
        resp = self.url_open(f'/dobtor/fonts/{quote(existing_family)}')
        self.assertEqual(resp.status_code, 200)
        # Sprint 69: Content-Type 可能是 font/ttf 或 font/collection（.ttc）
        content_type = resp.headers.get('Content-Type', '')
        self.assertIn(content_type, ('font/ttf', 'font/collection', 'font/otf'))
        # 1 年 immutable cache
        cache_control = resp.headers.get('Cache-Control', '')
        self.assertIn('max-age=', cache_control)
        self.assertIn('immutable', cache_control)
        # ACAO: *（fonts 不機密）
        self.assertEqual(resp.headers.get('Access-Control-Allow-Origin'), '*')
        # 真有 bytes
        self.assertGreater(len(resp.content), 0)

    def test_serve_unknown_family_returns_404(self):
        """未知 family 回 404。"""
        resp = self.url_open('/dobtor/fonts/NoSuchFontFamily12345')
        self.assertEqual(resp.status_code, 404)

    def test_serve_known_family_missing_file_returns_404(self):
        """family 在 map 但所有 candidate 都不存在 → 404（graceful、Sprint 69 schema）。"""
        # patch FONT_PATH_MAP，加一個 family 指向 candidate tuple 全 missing
        bogus_map = dict(FONT_PATH_MAP)
        bogus_map['BOGUS_FAMILY'] = ('/nonexistent/path.ttf', '/also/missing.ttf')
        with patch.dict('odoo.addons.dobtor_doc_editor.controllers.font_serve.FONT_PATH_MAP', bogus_map, clear=True):
            resp = self.url_open('/dobtor/fonts/BOGUS_FAMILY')
            self.assertEqual(resp.status_code, 404)


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'font_serve')
class TestFontServeSecurity(HttpCase):
    """Sprint 68 — 邊界與安全測試：FONT_PATH_MAP dict.get() 已防 path traversal、
    但仍應 explicit 驗證（紀律 #5 應用：production path 與 test path 可能不同）。

    這層測試補完 Sprint 66 漏掉的：
        - Path traversal（`../../etc/passwd` 與 percent-encoded 變體）
        - URL-encoded CJK 自動 decode（標楷體 → %E6%A8%99%E6%A5%B7%E9%AB%94）
        - Null byte injection（CVE-2023-style）
    """

    def test_path_traversal_literal_returns_404(self):
        """字面 path traversal `../../etc/passwd` 不應命中 dict、回 404。"""
        # Odoo router 對 string converter 是否吃 `/` 取決於 werkzeug；
        # 若 router 把 `..` 視為非法路徑、可能 400 / 404 由 Odoo 處理
        resp = self.url_open('/dobtor/fonts/..%2F..%2Fetc%2Fpasswd')
        self.assertEqual(resp.status_code, 404)

    def test_path_traversal_double_encoded_returns_404(self):
        """雙層 percent-encode 也不應繞過（dict 鍵嚴格相等）。"""
        # %252E%252E → `..` 解兩次；但 Werkzeug 只 decode 一次 → 字面 `%2E%2E`
        # 任何方式都不會匹配 FONT_PATH_MAP，故必 404
        resp = self.url_open('/dobtor/fonts/%252E%252E%252Fpasswd')
        self.assertEqual(resp.status_code, 404)

    def test_null_byte_in_family_returns_404(self):
        """family 含 null byte（CVE 風格、企圖截斷檔名）不應命中 → 404。"""
        # %00 是 null byte
        resp = self.url_open('/dobtor/fonts/%E6%A8%99%E6%A5%B7%E9%AB%94%00.ttf')
        self.assertEqual(resp.status_code, 404)

    def test_url_encoded_cjk_decodes_correctly(self):
        """URL-encoded 「標楷體」應正確 decode、走 resolve_font_path candidate chain（Sprint 69）。"""
        # 「標楷體」UTF-8 percent-encoded = %E6%A8%99%E6%A5%B7%E9%AB%94
        if not resolve_font_path('標楷體'):
            self.skipTest('「標楷體」candidate chain 全 missing（CJK font 未安裝）')

        resp = self.url_open('/dobtor/fonts/%E6%A8%99%E6%A5%B7%E9%AB%94')
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
        patch_target = 'odoo.addons.dobtor_doc_editor.controllers.font_serve.FONT_PATH_MAP'
        with patch.dict(patch_target, empty_map, clear=True):
            resp = self.url_open(
                '/dobtor/fonts/list',
                data='{}',
                headers={'Content-Type': 'application/json'},
            )
            self.assertEqual(resp.status_code, 200)
            result = resp.json().get('result', resp.json())
            self.assertEqual(result.get('fonts'), [])
            # note 仍要在（caller 須能識別 endpoint 沒掛掉、只是無 font）
            self.assertIn('note', result)
