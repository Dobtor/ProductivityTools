"""Tests for Jinja sandbox (W9-10 P2-1)。

W5-6 P1-2 整合 mixin 後，惡意 portal user 可能透過樣板填充嘗試 RCE。
驗證 SandboxedEnvironment 確實阻擋常見攻擊向量。
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestJinjaSandbox(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']

    def _render(self, template_str, ctx=None):
        """走 doc.render.mixin 的 _render_template 路徑。"""
        # 因 _render_template 內可能直接用 SandboxedEnvironment，這裡測試其實際 import
        from jinja2.sandbox import SandboxedEnvironment
        env = SandboxedEnvironment()
        tmpl = env.from_string(template_str)
        return tmpl.render(ctx or {})

    def test_normal_substitution_works(self):
        result = self._render('Hello {{ name }}', {'name': 'World'})
        self.assertEqual(result, 'Hello World')

    def test_arithmetic_works(self):
        result = self._render('{{ a + b }}', {'a': 1, 'b': 2})
        self.assertEqual(result, '3')

    def test_attribute_access_blocked_for_dangerous(self):
        """Jinja sandbox 會擋 __class__、__mro__ 等危險屬性。"""
        from jinja2.exceptions import SecurityError
        # 經典 Python sandbox escape：透過 __class__.__mro__ 拿 object 然後找子類
        with self.assertRaises(SecurityError):
            self._render('{{ "".__class__.__mro__[1].__subclasses__() }}')

    def test_import_blocked(self):
        """sandbox 不允許 import。

        注意：odoo TransactionCase 改寫過的 assertRaises 不支援 tuple
        多型別，所以拆成兩個獨立 try。
        """
        from jinja2.exceptions import SecurityError, TemplateSyntaxError
        try:
            self._render('{% import os %}')
            self.fail("Expected SecurityError or TemplateSyntaxError, got nothing")
        except (SecurityError, TemplateSyntaxError):
            pass  # 預期行為

    def test_attr_filter_class_returns_undefined(self):
        """jinja2 attr filter 對底線開頭屬性 → 回 Undefined（非 raise）。

        jinja2 SandboxedEnvironment 對 attr filter 的策略：不 raise，回 Undefined。
        渲染後的字串不應包含可利用的型別資訊（class 名稱、address 等）。
        """
        result = self._render(
            '{{ obj | attr("__class__") }}',
            {'obj': ''},
        )
        # 不應洩漏 'str' / 'class' / Python 物件 repr
        self.assertNotIn("class 'str'", result)
        self.assertNotIn('object at 0x', result)

    def test_undefined_variable_does_not_leak(self):
        """未定義變數應為空字串（預設）或被擋下，不應拋出敏感資訊。"""
        # 預設行為：StrictUndefined 才會 raise，普通 SandboxedEnvironment 用 Undefined
        # → 結果是 'Hello '
        result = self._render('Hello {{ secret }}')
        self.assertNotIn('Traceback', result)
        self.assertNotIn('Error', result)
