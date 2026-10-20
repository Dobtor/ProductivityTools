from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDiagramBasic(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.designer = new_test_user(
            cls.env, login='bpmn_designer2', groups='base.group_user,dobtor_approval.group_bpmn_diagram_manager')
        cls.viewer = new_test_user(
            cls.env, login='bpmn_viewer', groups='base.group_user,dobtor_approval.group_bpmn_diagram_user')

    def test_create_gets_blank_bpmn_and_defaults(self):
        rec = self.env['bpmn.diagram'].with_user(self.designer).create({'name': 'A'})
        self.assertIn('startEvent', rec.xml)
        self.assertEqual((rec.state, rec.version, rec.diagram_type), ('draft', 1, 'bpmn'))

    def test_preview_svg_from_di(self):
        rec = self.env['bpmn.diagram'].with_user(self.designer).create({'name': 'A'})
        self.assertEqual(rec._ensure_preview_svg(force=True), 1)
        self.assertIn('<svg', rec.svg)

    def test_viewer_cannot_write_and_sees_only_customer_or_own(self):
        rec = self.env['bpmn.diagram'].with_user(self.designer).create({'name': 'A'})
        self.assertFalse(rec.with_user(self.viewer).has_access('read'))     # 無客戶且非本人建立
        rec.partner_id = self.env.ref('base.partner_admin')
        mine = rec.with_user(self.viewer)
        self.assertTrue(mine.has_access('read'))
        self.assertFalse(mine.has_access('write'))

    def test_open_editor_action(self):
        rec = self.env['bpmn.diagram'].with_user(self.designer).create({'name': 'A'})
        action = rec.action_open_editor()
        self.assertEqual(action['tag'], 'dobtor_bpmn.bpmn_editor')
        self.assertEqual(action['params']['diagram_id'], rec.id)
