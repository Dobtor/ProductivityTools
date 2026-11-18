from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProjectLinkConflict(TransactionCase):
    """一個專案只能連一張心智圖：撞到時要給看得懂的 UserError，不是資料庫錯誤。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({'name': '叡揚合作'})
        cls.wb_linked = cls.env['xmind.workbook'].create({'name': '叡揚合作', 'project_id': cls.project.id})
        cls.wb_other = cls.env['xmind.workbook'].create({'name': '沉默是金'})

    def test_write_conflict_names_existing_map(self):
        with self.assertRaises(UserError) as cm:
            self.wb_other.write({'project_id': self.project.id})
        msg = str(cm.exception)
        self.assertIn('叡揚合作', msg)
        self.assertIn('#%d' % self.wb_linked.id, msg)
        self.assertFalse(self.wb_other.project_id)

    def test_create_conflict(self):
        with self.assertRaises(UserError):
            self.env['xmind.workbook'].create({'name': 'X', 'project_id': self.project.id})

    def test_archived_map_still_blocks(self):
        self.wb_linked.active = False
        with self.assertRaises(UserError) as cm:
            self.wb_other.write({'project_id': self.project.id})
        self.assertIn('#%d' % self.wb_linked.id, str(cm.exception))

    def test_relink_after_unlink(self):
        self.wb_linked.write({'project_id': False})
        self.wb_other.write({'project_id': self.project.id})
        self.assertEqual(self.wb_other.project_id, self.project)

    def test_rewrite_same_project_is_fine(self):
        self.wb_linked.write({'project_id': self.project.id})
        self.assertEqual(self.wb_linked.project_id, self.project)
