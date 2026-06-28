"""Tests for doc.linked.mixin (W9-10 P2-1, W5-6 P1-2)."""

from odoo import models, fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestDocLinkedMixin(TransactionCase):
    """因 mixin 是 abstract，需用一個既有 model 動態繼承來測。

    取巧法：用 res.partner 動態繼承（不真的 _register hook）。
    實作上：在 Python 層 mock setup_models 不可行，這裡改用 mixin
    的內部 method 直接呼叫的方式驗邏輯。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.linked.mixin']

    def test_mixin_is_abstract(self):
        """mixin 不能被實例化。"""
        self.assertEqual(self.Mixin._abstract, True)

    def test_mixin_has_required_fields(self):
        """mixin 提供 linked_doc_id 與 linked_doc_count 欄位。"""
        self.assertIn('linked_doc_id', self.Mixin._fields)
        self.assertIn('linked_doc_count', self.Mixin._fields)

    def test_mixin_provides_hook_methods(self):
        """繼承的 model 必有以下 hook：_doc_default_template_xml_id /
        _doc_collaborators / _doc_render_context / _doc_initial_name。"""
        for hook in (
            '_doc_default_template_xml_id',
            '_doc_collaborators',
            '_doc_render_context',
            '_doc_initial_name',
        ):
            self.assertTrue(hasattr(self.Mixin, hook),
                            f"mixin 缺少 hook method: {hook}")

    def test_doc_document_has_res_id_field(self):
        """W5-6 加的 res_id 欄位應存在於 doc.document。"""
        Doc = self.env['doc.document']
        self.assertIn('res_id', Doc._fields)
        self.assertIn('model_id', Doc._fields)

    def test_default_templates_loaded(self):
        """W5-6 預設樣板應已載入。"""
        ids = (
            'dobtor_doc_editor.template_meeting_record',
            'dobtor_doc_editor.template_self_inspection',
            'dobtor_doc_editor.template_defect_improvement',
            'dobtor_doc_editor.template_payment_estimate',
        )
        for xml_id in ids:
            template = self.env.ref(xml_id, raise_if_not_found=False)
            self.assertTrue(
                template,
                f"預設樣板未載入：{xml_id}",
            )
            # 樣板必有 content_html
            self.assertTrue(template.content_html)
