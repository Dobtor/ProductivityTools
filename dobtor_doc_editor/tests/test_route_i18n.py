# -*- coding: utf-8 -*-
r"""i18n 那 5 條路由的行為測試——優化 3 第三批（2026-10-09）。

☠️ 這 5 條是 `make audit` 量到「完全沒有任何驗證」裡最整齊的一組：
tour 走不到（它只有 78 步，打到 5 條路由），Python 測試也沒有。而其中
`i18n/convert` 與 `i18n/import` **會改 content_json**——也就是使用者的文件內容。

一樣用一條流程（列語系 → 抽靜態文字 → 轉藥丸 → 匯出 CSV → 匯入回填），
因為 i18n 的錯誤幾乎都在接縫上：抽出來的 key 要能對上匯出的 CSV，
匯入的 CSV 要能對上文件裡的藥丸。分開測會讓那一類錯誤溜掉。

☠️ 這一支**不碰** `docs/a11y_i18n_design.md` 的決定（「預設語系 zh_TW、
hardcode 中文是刻意的」）。它驗的是 i18n **功能**能不能用，
不是模組該不該被翻譯。
"""
from odoo.tests.common import HttpCase, tagged

from .session_probe import SessionAliveMixin


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestI18nRoutes(SessionAliveMixin, HttpCase):
    """五條 i18n 路由，一條流程走完。"""

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self.template = self.env['doc.template'].sudo().create({
            'name': 'i18n 路由測試範本',
            'role': 'content',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'content_html': '<p>合約編號</p><p>簽約日期</p>',
        })

    def _call(self, route, **params):
        return self._jsonrpc_with_evidence(route, params, where=route)

    def test_languages_returns_installed_languages(self):
        """`i18n/languages` 要回得出已安裝的語系（它連參數都沒有）。"""
        result = self._call('/dobtor_doc/i18n/languages')
        self.assertIsInstance(result, list,
                              'i18n/languages 回的不是 list：%r' % result)
        self.assertTrue(result, '一個語系都沒回——至少該有預設的那個')
        for row in result:
            self.assertIn('code', row, '語系項目缺 code：%r' % row)
            self.assertIn('name', row, '語系項目缺 name：%r' % row)

    def test_i18n_lifecycle_end_to_end(self):
        """抽靜態文字 → 轉藥丸 → 匯出 CSV → 匯入回填。"""
        # 1. 抽靜態文字
        extracted = self._call('/dobtor_doc/i18n/extract',
                               template_id=self.template.id)
        texts = extracted.get('texts')
        self.assertIsInstance(
            texts, list, 'i18n/extract 沒回 texts list：%r' % extracted)

        # 2. 轉成 i18n 藥丸（會改 content_json——這是這組裡會動資料的那條）
        converted = self._call('/dobtor_doc/i18n/convert',
                               template_id=self.template.id,
                               texts=texts[:1] if texts else [],
                               lang='zh_TW')
        self.assertIn(
            'content_json', converted,
            'i18n/convert 沒回 content_json——前端會用舊內容把轉換覆蓋掉：%r'
            % {k: str(v)[:60] for k, v in converted.items()})

        # 3. 匯出 CSV
        exported = self._call('/dobtor_doc/i18n/export',
                              template_id=self.template.id)
        self.assertIn('csv', exported, 'i18n/export 沒回 csv：%r' % exported)
        self.assertIn('entries', exported,
                      'i18n/export 沒回 entries 計數：%r' % exported)
        self.assertIsInstance(exported['csv'], str)

        # 4. 把剛匯出的 CSV 原封不動匯回去——應該是 no-op，不可以炸
        imported = self._call('/dobtor_doc/i18n/import',
                              template_id=self.template.id,
                              csv_content=exported['csv'])
        self.assertIsInstance(
            imported, dict, 'i18n/import 回的不是 dict：%r' % imported)
        self.assertIn(
            'content_json', imported,
            'i18n/import 沒回 content_json（同 convert 的理由）：%r'
            % {k: str(v)[:60] for k, v in imported.items()})

    def test_import_has_the_size_guard_wired(self):
        """`assert_text_size` 要**真的接在這條路由上**（稽核尺 2 補的守衛）。

        ☠️ 刻意不送 50MB 的 payload：那會讓測試變慢又脆（第一版就是這樣，
        直接 error）。改成把上限 patch 成很小，再送一個小 payload
        ——驗的是「呼叫點存在」，而那正是這一則的目的。
        `test_input_bounds.py` 驗 helper 本身的行為；這裡驗接線。
        """
        from unittest.mock import patch
        from ..controllers import doc_controller_i18n

        real = doc_controller_i18n.assert_text_size

        def tiny(text, label, max_bytes=None):
            return real(text, label, max_bytes=16)

        # ☠️ `assertRaises` **不能傳 exception tuple**：Odoo 覆寫了它
        #    （odoo/tests/common.py:490）並對參數做 `issubclass(exception,
        #    AccessError)`，傳 tuple 會得到
        #    `TypeError: issubclass() arg 1 must be a class`
        #    ——那是「測試本身壞了」而不是斷言失敗，很容易誤讀。
        #    這條路由把 UserError 包成 JSON-RPC error，而
        #    `_jsonrpc_with_evidence` 看到 error 就 self.fail() → AssertionError。
        with patch.object(doc_controller_i18n, 'assert_text_size', tiny):
            with self.assertRaises(AssertionError):
                self._call('/dobtor_doc/i18n/import',
                           template_id=self.template.id,
                           csv_content='a' * 64)

    def test_import_with_garbage_csv_gives_a_readable_error(self):
        """亂七八糟的 CSV 不可以 500、不可以噴 traceback。"""
        result = None
        from odoo.tests.common import JsonRpcException
        try:
            result = self._call('/dobtor_doc/i18n/import',
                                template_id=self.template.id,
                                csv_content='這不是 CSV\x00\x01亂碼')
        except (AssertionError, JsonRpcException):
            return      # 被擋下來、而且是 JSON 形式的錯誤
        self.assertIsInstance(result, dict)
        blob = str(result)
        self.assertNotIn(
            'Traceback', blob,
            '亂碼 CSV 讓路由把 traceback 回給使用者：%r' % blob[:200])
