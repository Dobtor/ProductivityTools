# -*- coding: utf-8 -*-

from datetime import date
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestActivityDoneWizard(TransactionCase):
    """測試完成待辦 Wizard"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')

        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': 'Wizard 測試類型',
            'category': 'default',
        })

        cls.note = cls.env['note.note'].create({
            'memo': '<p>Wizard 測試筆記</p>',
            'user_id': cls.user.id,
        })

    def test_01_done_wizard_create(self):
        """測試建立完成 Wizard"""
        activity = self.env['mail.activity'].create({
            'summary': '待完成',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'user_id': self.user.id,
            'estimated_hours': 2.0,
        })

        wizard = self.env['mail.activity.done.wizard'].create({
            'activity_id': activity.id,
            'actual_hours': 1.5,
            'feedback': '已完成測試',
        })

        self.assertTrue(wizard.id)
        self.assertEqual(wizard.activity_id.id, activity.id)

    def test_02_done_wizard_action(self):
        """測試執行完成動作"""
        activity = self.env['mail.activity'].create({
            'summary': '待完成2',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'user_id': self.user.id,
        })

        wizard = self.env['mail.activity.done.wizard'].create({
            'activity_id': activity.id,
            'actual_hours': 1.0,
        })

        wizard.action_done()

        # 重新載入 activity
        activity.invalidate_recordset()
        self.assertFalse(activity.active)


@tagged('post_install', '-at_install')
class TestActivityPostponeWizard(TransactionCase):
    """測試延期 Wizard"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')

        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': '延期測試類型',
            'category': 'default',
        })

        cls.note = cls.env['note.note'].create({
            'memo': '<p>延期測試筆記</p>',
            'user_id': cls.user.id,
        })

    def test_01_postpone_wizard(self):
        """測試延期 Wizard"""
        activity = self.env['mail.activity'].create({
            'summary': '待延期',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'user_id': self.user.id,
            'planned_date': date.today(),
            'schedule_status': 'monday',
        })

        wizard = self.env['mail.activity.postpone.wizard'].create({
            'activity_id': activity.id,
            'reason': '測試延期原因',
        })

        wizard.action_postpone()

        # 重新載入 activity
        activity.invalidate_recordset()
        self.assertEqual(activity.schedule_status, 'waiting')
        self.assertFalse(activity.planned_date)

    def test_02_batch_postpone_wizard(self):
        """測試批次延期 Wizard（多選）"""
        def _make(summary):
            return self.env['mail.activity'].create({
                'summary': summary,
                'activity_type_id': self.activity_type.id,
                'res_model_id': self.env['ir.model']._get('note.note').id,
                'res_id': self.note.id,
                'date_deadline': date.today(),
                'user_id': self.user.id,
                'planned_date': date.today(),
                'schedule_status': 'monday',
            })

        a1 = _make('批次延期1')
        a2 = _make('批次延期2')

        # 模擬清單多選入口：以 default_activity_ids 帶入
        wizard = self.env['mail.activity.postpone.wizard'].with_context(
            default_activity_ids=[a1.id, a2.id],
        ).create({'reason': '批次延期原因'})

        self.assertTrue(wizard.is_batch)
        self.assertEqual(wizard.activity_count, 2)

        wizard.action_postpone()

        for activity in (a1, a2):
            activity.invalidate_recordset()
            self.assertEqual(activity.schedule_status, 'waiting')
            self.assertFalse(activity.planned_date)


@tagged('post_install', '-at_install')
class TestActivityTransferWizard(TransactionCase):
    """測試轉移 Wizard"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')

        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': '轉移測試類型',
            'category': 'default',
        })

        cls.note1 = cls.env['note.note'].create({
            'memo': '<p>來源筆記</p>',
            'user_id': cls.user.id,
        })

        cls.note2 = cls.env['note.note'].create({
            'memo': '<p>目標筆記</p>',
            'user_id': cls.user.id,
        })

    def test_01_transfer_wizard(self):
        """測試轉移 Wizard"""
        activity = self.env['mail.activity'].create({
            'summary': '待轉移',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note1.id,
            'date_deadline': date.today(),
            'user_id': self.user.id,
        })

        wizard = self.env['mail.activity.transfer.wizard'].create({
            'activity_id': activity.id,
            'target_ref': f'note.note,{self.note2.id}',
        })

        wizard.action_transfer()
        activity.invalidate_recordset()
        self.assertEqual(activity.res_id, self.note2.id)


@tagged('post_install', '-at_install')
class TestActivityReassignWizard(TransactionCase):
    """測試重新指派 Wizard"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user1 = cls.env.ref('base.user_demo')
        cls.user2 = cls.env['res.users'].create({
            'name': '指派目標用戶',
            'login': 'reassign_target',
        })

        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': '指派測試類型',
            'category': 'default',
        })

        cls.note = cls.env['note.note'].create({
            'memo': '<p>指派測試筆記</p>',
            'user_id': cls.user1.id,
        })

    def test_01_reassign_wizard(self):
        """測試重新指派 Wizard"""
        activity = self.env['mail.activity'].create({
            'summary': '待重新指派',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'user_id': self.user1.id,
        })

        wizard = self.env['mail.activity.reassign.wizard'].create({
            'activity_id': activity.id,
            'new_user_id': self.user2.id,
        })

        wizard.action_confirm()
        activity.invalidate_recordset()

        # 改派會取消原待辦並為新負責人建立一筆新待辦
        self.assertFalse(activity.active)
        new_activity = self.env['mail.activity'].search([
            ('res_model', '=', 'note.note'),
            ('res_id', '=', self.note.id),
            ('user_id', '=', self.user2.id),
            ('active', '=', True),
        ])
        self.assertEqual(len(new_activity), 1)
        self.assertEqual(new_activity.transferred_from_id, activity.id)
