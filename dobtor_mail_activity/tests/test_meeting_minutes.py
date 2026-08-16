# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMeetingMinutes(TransactionCase):
    """日曆事件 ↔ 會議記錄。

    前端（calendar popover）依賴三樣東西：note_count 欄位、action_create_note、
    action_view_notes。這組測試釘死它們都存在且語意正確 —— 先前這三者只有前端、
    後端從未實作，按鈕點下去必然 AttributeError。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        start = datetime.now() + timedelta(days=1)
        cls.event = cls.env['calendar.event'].create({
            'name': 'Sprint Planning',
            'start': start,
            'stop': start + timedelta(hours=1),
        })

    def test_01_no_notes_initially(self):
        self.assertEqual(self.event.note_count, 0)
        self.assertFalse(self.event.note_ids)

    def test_02_create_note_links_and_titles(self):
        action = self.event.action_create_note()
        self.assertEqual(action['res_model'], 'note.note')
        note = self.env['note.note'].browse(action['res_id'])

        self.assertEqual(note.calendar_event_id, self.event)
        self.assertIn(self.event, self.env['calendar.event'].browse(self.event.id))
        self.assertEqual(note.user_id, self.env.user)
        # note.name 是由 memo 首行計算而來，不能直接寫入
        self.assertIn('Sprint Planning', note.name)

    def test_03_note_count_follows(self):
        self.event.action_create_note()
        self.event.invalidate_recordset(['note_count', 'note_ids'])
        self.assertEqual(self.event.note_count, 1)
        self.event.action_create_note()
        self.event.invalidate_recordset(['note_count', 'note_ids'])
        self.assertEqual(self.event.note_count, 2)

    def test_04_view_notes_single_opens_form(self):
        self.event.action_create_note()
        action = self.event.action_view_notes()
        self.assertEqual(action['view_mode'], 'form')
        self.assertIn('res_id', action)

    def test_05_view_notes_many_opens_list(self):
        self.event.action_create_note()
        self.event.action_create_note()
        action = self.event.action_view_notes()
        self.assertEqual(action['view_mode'], 'list,form')
        self.assertEqual(action['domain'], [('calendar_event_id', '=', self.event.id)])

    def test_06_note_survives_event_deletion(self):
        """ondelete='set null'：會議刪掉，記錄仍在（內容有保存價值）。"""
        action = self.event.action_create_note()
        note = self.env['note.note'].browse(action['res_id'])
        self.event.unlink()
        self.assertTrue(note.exists())
        self.assertFalse(note.calendar_event_id)

    def test_07_note_count_correct_for_multiple_events(self):
        """多筆事件一起算（日曆一次載入整個月）—— _compute_note_count 以單次
        _read_group 批次統計，這裡驗證批次路徑的結果正確。"""
        start = datetime.now() + timedelta(days=2)
        events = self.env['calendar.event'].create([{
            'name': 'Meeting %d' % i,
            'start': start,
            'stop': start + timedelta(hours=1),
        } for i in range(3)])
        # 只給前兩個事件建記錄，第三個應為 0（驗證分組對映沒有錯位）
        events[0].action_create_note()
        events[1].action_create_note()
        events[1].action_create_note()
        events.invalidate_recordset(['note_count'])
        self.assertEqual(events.mapped('note_count'), [1, 2, 0])
