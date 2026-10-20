from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestFrozenGuard(TransactionCase):
    """定版（frozen）的圖不能改設計 XML；其他欄位與狀態轉換照舊。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.designer = new_test_user(
            cls.env, login='bpmn_designer', groups='base.group_user,dobtor_approval.group_bpmn_diagram_manager')
        cls.Diagram = cls.env['bpmn.diagram'].with_user(cls.designer)
        cls.diagram = cls.Diagram.create({'name': '請購'})

    def test_draft_diagram_xml_is_writable(self):
        self.diagram.write({'xml': self.diagram.xml + '\n'})
        self.assertTrue(self.diagram.xml.endswith('\n'))

    def test_frozen_blocks_xml_write(self):
        self.diagram.action_freeze()
        self.assertEqual(self.diagram.state, 'frozen')
        old = self.diagram.xml
        with self.assertRaisesRegex(UserError, '已定版'):
            self.diagram.write({'xml': old + ' '})
        self.assertEqual(self.diagram.xml, old)

    def test_frozen_still_allows_other_fields_and_svg(self):
        self.diagram.action_freeze()
        self.diagram.write({'name': '請購（定版）', 'svg': '<svg/>'})
        self.assertEqual(self.diagram.name, '請購（定版）')
        self.assertEqual(self.diagram._ensure_preview_svg(force=True), 1)

    def test_set_draft_then_edit(self):
        self.diagram.action_freeze()
        self.diagram.action_set_draft()
        self.diagram.write({'xml': self.diagram.xml + ' '})

    def test_leaving_frozen_in_the_same_write_is_allowed(self):
        self.diagram.action_freeze()
        self.diagram.write({'state': 'draft', 'xml': self.diagram.xml + ' '})
        self.assertEqual(self.diagram.state, 'draft')

    def test_multi_record_write_blocks_if_any_is_frozen(self):
        other = self.Diagram.create({'name': '另一張'})
        self.diagram.action_freeze()
        with self.assertRaises(UserError):
            (self.diagram | other).write({'xml': '<x/>'})

    def test_create_with_xml_unaffected(self):
        rec = self.Diagram.create({'name': 'n', 'xml': '<x/>', 'state': 'frozen'})
        self.assertEqual(rec.state, 'frozen')
