# -*- coding: utf-8 -*-

from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestActivityNoteLink(TransactionCase):
    """待辦 ↔ 筆記（自 dobtor_mail_activity 搬入）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')
        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': '筆記關聯測試類型',
            'category': 'default',
        })
        cls.note = cls.env['note.note'].create({
            'memo': '<p>測試筆記內容</p>',
            'user_id': cls.user.id,
        })

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


@tagged('post_install', '-at_install')
class TestNoteReviewFixes(TransactionCase):
    """審查後補的回歸測試。"""

    def test_default_note_id_in_context_joins_note_ids(self):
        note = self.env['note.note'].create({'memo': '<p>ctx</p>'})
        act = self.env['mail.activity'].with_context(default_note_id=note.id).create({
            'summary': 'ctx default', 'date_deadline': date.today(),
        })
        self.assertEqual(act.note_id, note)
        self.assertIn(note, act.note_ids)

    def test_wizard_cleared_note_is_respected(self):
        note = self.env['note.note'].create({'memo': '<p>wiz</p>'})
        wiz = self.env['mail.activity.create.wizard'].with_context(default_note_id=note.id).create({
            'summary': 'cleared', 'date_deadline': date.today(),
        })
        self.assertEqual(wiz.note_id, note)
        wiz.note_id = False
        act_id = wiz.action_create_todo()['infos']['activity_id']
        act = self.env['mail.activity'].browse(act_id)
        self.assertFalse(act.note_id)
        self.assertFalse(act.note_ids)

    def test_calendar_note_count_follows_archive(self):
        from datetime import datetime, timedelta
        from odoo import Command
        start = datetime.now() + timedelta(days=1)
        ev = self.env['calendar.event'].create({'name': 'Arch', 'start': start, 'stop': start + timedelta(hours=1)})
        note = self.env['note.note'].create({'memo': '<p>m</p>', 'calendar_event_ids': [Command.link(ev.id)]})
        self.assertEqual(ev.note_count, 1)
        note.active = False
        self.assertEqual(ev.note_count, 0)

    def test_core_does_not_seed_note_transfer_config(self):
        Config = self.env['mail.activity.transfer.config'].with_context(active_test=False)
        Config.search([('model', '=', 'note.note')]).unlink()
        Config.create_default_configs()
        self.assertFalse(Config.search([('model', '=', 'note.note')]),
                         'note.note 的設定只由 dobtor_meeting_minutes 資料檔建立')
