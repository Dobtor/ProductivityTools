# -*- coding: utf-8 -*-
r"""使用者輸入的大小上限——稽核尺 2（2026-10-09）。

☠️ 盤點 41 條路由的輸入邊界時抓到的**不一致**：

  upload_template   有 assert_input_size()（50MB）
  telemetry_error   明確截斷 message / stack_trace
  /dobtor_doc/save  **四個內容欄位完全沒有上限** ← 文件內容的主要寫入路徑
  i18n/import       **csv_content 沒有上限**

守衛的零件（`assert_input_size`）早就存在，漏的是最大的那一條。這支守住
補上的 `assert_text_size()` 真的會擋，而且**不會誤擋正常大小**
——後者同樣重要：訂太緊會打斷合理用例（content_html 可能內嵌 base64 圖片），
那比沒有上限更糟。
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..models.doc_zip_guard import DEFAULT_INPUT_MAX_BYTES, assert_text_size


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'security')
class TestAssertTextSize(TransactionCase):
    """`assert_text_size()` 的兩個方向。"""

    def test_normal_size_passes(self):
        """正常大小不可以被誤擋。"""
        assert_text_size('<p>' + 'x' * 10000 + '</p>', 'content_html')
        assert_text_size(None, 'content_html')   # None 不該炸
        assert_text_size('', 'content_html')     # 空字串不該炸

    def test_oversized_raises_user_error(self):
        """超過上限要丟 UserError（不是 500），訊息要指出是哪一欄。"""
        with self.assertRaises(UserError) as caught:
            assert_text_size('x' * (DEFAULT_INPUT_MAX_BYTES + 1), 'content_json')
        msg = str(caught.exception)
        self.assertIn('content_json', msg, '錯誤訊息要寫出欄位名稱')
        self.assertIn('MB', msg, '錯誤訊息要寫出大小，使用者才知道要縮多少')

    def test_size_is_measured_in_utf8_bytes_not_characters(self):
        """用 UTF-8 位元組數算，不是字元數。

        ☠️ 中文一個字 3 bytes。用字元數算的話，實際記憶體用量會是估計值的
        三倍——這一則把「用位元組」釘成事實。
        """
        # 剛好超過上限的中文：位元組數超、字元數只有三分之一
        chars = DEFAULT_INPUT_MAX_BYTES // 3 + 10
        with self.assertRaises(UserError):
            assert_text_size('中' * chars, 'content_html')
        # 同樣的**字元數**但是 ASCII → 位元組數只有三分之一，應該過
        assert_text_size('a' * chars, 'content_html')
