"""Unit tests for doc_zip_guard (W9-10 P2-1)。

跑：
    docker exec odoo18 odoo -c /etc/odoo/odoo.conf -d odoo18_dev \
        --test-tags dobtor_doc_editor --stop-after-init
"""

import io
import zipfile

from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError

from ..models import doc_zip_guard


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'zip_guard')
class TestZipGuard(TransactionCase):

    def _make_zip(self, entries):
        """產一個 in-memory zip，entries = list of (name, content)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            for name, content in entries:
                zf.writestr(name, content)
        return buf.getvalue()

    def test_small_valid_zip_passes(self):
        """正常的小 zip 應該通過。"""
        data = self._make_zip([
            ('word/document.xml', '<root/>'),
            ('[Content_Types].xml', '<types/>'),
        ])
        info = doc_zip_guard.inspect_zip_safe(data)
        self.assertEqual(info['entry_count'], 2)
        self.assertGreater(info['total_uncompressed'], 0)

    def test_oversized_input_rejected(self):
        """原檔超過 50MB 應被擋。"""
        big = b'X' * (60 * 1024 * 1024)
        with self.assertRaises(UserError) as cm:
            doc_zip_guard.assert_input_size(big)
        self.assertIn('過大', str(cm.exception))

    def test_too_many_entries_rejected(self):
        """超過 1000 個 entry 應被擋。"""
        # 1001 個小檔
        entries = [(f'f{i}', 'x') for i in range(1001)]
        data = self._make_zip(entries)
        with self.assertRaises(UserError) as cm:
            doc_zip_guard.inspect_zip_safe(data)
        self.assertIn('entry', str(cm.exception).lower())

    def test_total_uncompressed_overflow_rejected(self):
        """解壓後總和超過 200MB 應被擋。

        故意產 5 個各 50MB 的 entry → 解壓後 250MB > 200MB 上限
        （壓縮率高 → 原檔小，不會被 input size 擋）
        """
        entries = []
        for i in range(5):
            # 高度可壓縮的內容（重複 'X'）
            entries.append((f'big{i}.bin', b'X' * (50 * 1024 * 1024)))
        data = self._make_zip(entries)
        with self.assertRaises(UserError) as cm:
            doc_zip_guard.inspect_zip_safe(
                data,
                max_total_uncompressed=200 * 1024 * 1024,
            )
        self.assertIn('解壓', str(cm.exception))

    def test_malformed_zip_rejected(self):
        """非合法 zip 應拋 UserError 而非 zipfile.BadZipFile。"""
        with self.assertRaises(UserError):
            doc_zip_guard.inspect_zip_safe(b'not a zip')

    def test_safe_open_returns_zipfile(self):
        """safe_open_docx_zip 通過後回傳 ZipFile 可讀。"""
        data = self._make_zip([('word/document.xml', '<root/>')])
        zf = doc_zip_guard.safe_open_docx_zip(data)
        try:
            self.assertIn('word/document.xml', zf.namelist())
        finally:
            zf.close()

    # ── Sprint 71 補測缺口 ────────────────────────────────────────────

    def test_single_file_high_ratio_bomb_detected(self):
        """單檔壓縮比 >100x 且 >1MB → ZipBombError（doc_zip_guard.py line 115-121 cover）。"""
        # 2MB 全 X、用 DEFLATE 高度壓縮（ratio 應 >> 100x）
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('bomb.bin', b'X' * (2 * 1024 * 1024))
        data = buf.getvalue()
        with self.assertRaises(UserError) as cm:
            doc_zip_guard.inspect_zip_safe(data, max_ratio=100)
        # 訊息應提到 ratio 或 bomb
        msg = str(cm.exception).lower()
        self.assertTrue(
            '壓縮比' in str(cm.exception) or 'ratio' in msg or 'bomb' in msg,
            f'訊息應提示壓縮比異常：{cm.exception}',
        )

    def test_small_high_ratio_file_not_flagged(self):
        """<1MB 的高壓縮率小檔不誤判（小檔高比例正常、純文字 docx 常見）。"""
        # 500KB 全 X、會高壓縮 ratio 但 file_size < 1MB threshold
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('small.txt', b'X' * (500 * 1024))
        data = buf.getvalue()
        # 不該 raise — small files allowed
        info = doc_zip_guard.inspect_zip_safe(data)
        self.assertEqual(info['entry_count'], 1)

    def test_default_constants_match_docstring_claims(self):
        """預設常數與 docstring 宣告的 50MB / 200MB / 1000 entries 一致。"""
        self.assertEqual(doc_zip_guard.DEFAULT_INPUT_MAX_BYTES, 50 * 1024 * 1024)
        self.assertEqual(doc_zip_guard.DEFAULT_OUTPUT_MAX_BYTES, 200 * 1024 * 1024)
        self.assertEqual(doc_zip_guard.DEFAULT_MAX_ENTRIES, 1000)
