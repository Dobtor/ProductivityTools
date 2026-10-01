# -*- coding: utf-8 -*-
from odoo.tests import BaseCase, tagged

from odoo.addons.dobtor_corpaas_knowledge_marketing.models import html_guard


@tagged('post_install', '-at_install')
class TestHtmlGuard(BaseCase):

    def test_strips_forbidden(self):
        out = html_guard.clean(
            '<p style="color:red" onclick="x()">好<a href="https://evil">用</a></p>'
            '<style>p{}</style><script>alert(1)</script><svg><circle/></svg>'
            '<img src="/x.png"/><div class="s_alert alert alert-info">提示</div>')
        self.assertIn('<p>好用</p>', out)
        self.assertIn('s_alert alert alert-info', out)
        for bad in ('<style', '<script', '<svg', '<img', '<a', 'href', 'style=', 'onclick'):
            self.assertNotIn(bad, out)

    def test_empty(self):
        self.assertEqual(html_guard.clean(None), '')
        self.assertEqual(html_guard.clean('   '), '')

    def test_class_whitelist_and_attrs(self):
        out = html_guard.clean(
            '<div class="s_alert alert alert-info o_snippet_x" id="main" data-snippet="s_x">'
            '<table class="table table-striped my-table" data-foo="1"><thead class="table-light">'
            '<tr><th scope="col" colspan="2">欄</th></tr></thead></table>'
            '<span class="badge text-bg-primary fw-bold">新</span><section>留字</section>'
            '<!-- 註解 --></div>')
        self.assertIn('class="s_alert alert alert-info"', out)
        self.assertIn('class="table table-striped"', out)
        self.assertIn('class="badge text-bg-primary"', out)
        self.assertIn('colspan="2"', out)
        self.assertIn('留字', out)
        for bad in ('o_snippet_x', 'my-table', 'fw-bold', 'id=', 'data-', '<section', '註解'):
            self.assertNotIn(bad, out)
