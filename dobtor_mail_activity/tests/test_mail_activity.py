# -*- coding: utf-8 -*-

from datetime import date, timedelta
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMailActivity(TransactionCase):
    """測試 mail.activity 擴展功能"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')
        cls.partner = cls.env.ref('base.partner_demo')

        # 建立測試用待辦類型
        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': '測試待辦類型',
            'category': 'default',
        })

        # 建立測試用筆記（作為待辦目標）
        cls.note = cls.env['note.note'].create({
            'memo': '<p>測試筆記內容</p>',
            'user_id': cls.user.id,
        })

    def test_01_create_activity(self):
        """測試建立待辦"""
        activity = self.env['mail.activity'].create({
            'summary': '測試待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
        })

        self.assertTrue(activity.id)
        self.assertEqual(activity.summary, '測試待辦')
        self.assertTrue(activity.active)
        self.assertEqual(activity.activity_status, 'active')

    def test_02_activity_without_user(self):
        """測試建立無指派人的待辦"""
        activity = self.env['mail.activity'].create({
            'summary': '無指派人待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'user_id': False,
        })

        self.assertTrue(activity.id)
        self.assertFalse(activity.user_id)

    def test_03_activity_priority(self):
        """測試待辦優先級欄位"""
        activity = self.env['mail.activity'].create({
            'summary': '緊急重要待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'urgency': 'urgent',
            'importance': 'important',
        })

        self.assertEqual(activity.urgency, 'urgent')
        self.assertEqual(activity.importance, 'important')

    def test_04_activity_schedule(self):
        """測試待辦排程功能"""
        activity = self.env['mail.activity'].create({
            'summary': '排程測試',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'schedule_status': 'monday',
            'planned_date': date.today(),
        })

        self.assertEqual(activity.schedule_status, 'monday')
        self.assertTrue(activity.planned_date)

    def test_05_activity_done(self):
        """測試完成待辦（封存）"""
        activity = self.env['mail.activity'].create({
            'summary': '待完成待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'user_id': self.user.id,
        })

        # 執行完成（透過內部方法）
        activity._action_done(feedback='測試完成')

        self.assertFalse(activity.active)
        self.assertTrue(activity.done_date)
        self.assertEqual(activity.activity_status, 'done')

    def test_06_activity_cancel(self):
        """測試取消待辦"""
        activity = self.env['mail.activity'].create({
            'summary': '待取消待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
        })

        # action_cancel 現導向取消原因精靈；封存/記錄邏輯在 _action_cancel
        activity._action_cancel(feedback='測試取消原因')

        self.assertFalse(activity.active)
        self.assertTrue(activity.cancel_date)
        self.assertEqual(activity.activity_status, 'cancelled')
        self.assertEqual(activity.feedback, '測試取消原因')

    def test_07_activity_restore(self):
        """測試恢復已封存待辦"""
        activity = self.env['mail.activity'].create({
            'summary': '待恢復待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
        })

        # 先取消
        activity._action_cancel(feedback='原因')
        self.assertFalse(activity.active)

        # 再恢復
        activity.action_restore()
        self.assertTrue(activity.active)
        self.assertFalse(activity.cancel_date)

    def test_08_schedule_week_compute(self):
        """測試週次計算"""
        today = date.today()
        current_week_start = today - timedelta(days=today.weekday())

        # 本週待辦
        activity_this_week = self.env['mail.activity'].create({
            'summary': '本週待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': today,
            'planned_date': current_week_start,
        })
        self.assertEqual(activity_this_week.schedule_week, 'week0')
        self.assertEqual(activity_this_week.schedule_week_number, 0)

        # 下週待辦
        activity_next_week = self.env['mail.activity'].create({
            'summary': '下週待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': today + timedelta(days=7),
            'planned_date': current_week_start + timedelta(days=7),
        })
        self.assertEqual(activity_next_week.schedule_week, 'week1')
        self.assertEqual(activity_next_week.schedule_week_number, 1)

    def test_09_assignment_history(self):
        """測試指派歷史"""
        user2 = self.env['res.users'].create({
            'name': '測試用戶2',
            'login': 'test_user_2',
        })

        activity = self.env['mail.activity'].create({
            'summary': '指派測試',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'user_id': self.user.id,
        })

        # 變更指派（需要 allow_user_change context 繞過建立後唯讀限制）
        activity.with_context(allow_user_change=True).write({'user_id': user2.id})

        # 檢查歷史記錄
        self.assertEqual(len(activity.assignment_history_ids), 1)
        history = activity.assignment_history_ids[0]
        self.assertEqual(history.previous_user_id.id, self.user.id)
        self.assertEqual(history.new_user_id.id, user2.id)

    def test_10_note_relation(self):
        """測試筆記關聯"""
        activity = self.env['mail.activity'].create({
            'summary': '關聯筆記測試',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'note_id': self.note.id,
        })

        self.assertEqual(activity.note_id.id, self.note.id)

        # 檢查筆記的待辦計數（透過 note_id 關聯）
        self.assertGreaterEqual(self.note.note_activity_count, 1)

    def test_11_estimated_hours(self):
        """測試工時相關欄位"""
        activity = self.env['mail.activity'].create({
            'summary': '工時測試',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'estimated_hours': 2.5,
        })

        self.assertEqual(activity.estimated_hours, 2.5)

    def test_12_standalone_activity_allowed(self):
        """需求七：允許建立無關聯文件（res_model_id/res_id 皆空）的獨立待辦。"""
        activity = self.env['mail.activity'].create({
            'summary': '獨立待辦（無目標文件）',
            'activity_type_id': self.activity_type.id,
            'date_deadline': date.today(),
            # 刻意不帶 res_model_id / res_id
        })
        self.assertTrue(activity.id)
        self.assertFalse(activity.res_model_id)
        self.assertFalse(activity.res_id)

    def test_13_transfer_activity(self):
        """測試轉移待辦功能"""
        # 建立另一個目標文件 (res.partner)
        partner = self.env['res.partner'].create({
            'name': '轉移目標客戶',
        })

        # 建立待辦
        activity = self.env['mail.activity'].create({
            'summary': '待轉移待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'note_id': self.note.id,
        })

        # 確認初始狀態
        self.assertFalse(activity.is_transferred)
        self.assertEqual(activity.res_model, 'note.note')
        self.assertEqual(activity.res_id, self.note.id)

        # 使用 wizard 轉移
        wizard = self.env['mail.activity.transfer.wizard'].create({
            'activity_id': activity.id,
            'source_model': 'note.note',
            'source_id': self.note.id,
            'target_ref': f'res.partner,{partner.id}',
        })
        wizard.action_transfer()

        # 驗證轉移結果
        self.assertTrue(activity.is_transferred)
        self.assertEqual(activity.res_model, 'res.partner')
        self.assertEqual(activity.res_id, partner.id)
        self.assertEqual(activity.transferred_from_model, 'note.note')
        self.assertEqual(activity.transferred_from_id, self.note.id)
        self.assertEqual(activity.note_id.id, self.note.id)  # note_id 應保留
        self.assertEqual(activity.schedule_origin, 'transferred')

    def test_14_get_related_notes(self):
        """測試取得關聯筆記 API"""
        # 建立目標文件
        partner = self.env['res.partner'].create({
            'name': '測試客戶',
        })

        # 建立筆記待辦並轉移
        activity = self.env['mail.activity'].create({
            'summary': '筆記關聯待辦',
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.env['ir.model']._get('res.partner').id,
            'res_id': partner.id,
            'date_deadline': date.today(),
            'note_id': self.note.id,
        })

        # 取得關聯筆記
        notes = self.env['mail.activity'].get_related_notes('res.partner', partner.id)

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['id'], self.note.id)
        self.assertEqual(notes[0]['total_count'], 1)
        self.assertEqual(notes[0]['active_count'], 1)
