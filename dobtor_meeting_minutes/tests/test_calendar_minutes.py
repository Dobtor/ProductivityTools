# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCalendarMeetingMinutes(TransactionCase):
    """日曆事件 ↔ 會議記錄。

    前端（calendar popover）依賴 note_count（stored，日曆 rawRecord 讀取）、
    action_create_note、action_view_notes。
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

    def _note(self, event):
        return self.env['note.note'].create({
            'memo': '<p>minutes</p>',
            'note_type': 'meeting',
            'calendar_event_ids': [Command.link(event.id)],
        })

    def test_01_no_notes_initially(self):
        self.assertEqual(self.event.note_count, 0)
        self.assertFalse(self.event.note_ids)

    def test_02_create_action_prefills_meeting(self):
        action = self.event.action_create_note()
        self.assertEqual(action['res_model'], 'note.note')
        ctx = action['context']
        self.assertEqual(ctx['default_note_type'], 'meeting')
        self.assertIn('Sprint Planning', ctx['default_memo'])
        note = self.env['note.note'].with_context(**ctx).create({})
        self.assertIn(self.event, note.calendar_event_ids)
        self.assertIn('Sprint Planning', note.name)

    def test_03_note_count_is_stored_and_follows(self):
        self.assertTrue(self.env['calendar.event']._fields['note_count'].store)
        self._note(self.event)
        self.assertEqual(self.event.note_count, 1)
        self._note(self.event)
        self.assertEqual(self.event.note_count, 2)

    def test_04_view_notes_single_opens_form(self):
        self._note(self.event)
        action = self.event.action_view_notes()
        self.assertEqual(action['view_mode'], 'form')
        self.assertIn('res_id', action)

    def test_05_view_notes_many_opens_list(self):
        notes = self._note(self.event) | self._note(self.event)
        action = self.event.action_view_notes()
        self.assertNotEqual(action['view_mode'], 'form')
        (fname, op, ids), = action['domain']
        self.assertEqual((fname, op, set(ids)), ('id', 'in', set(notes.ids)))

    def test_06_note_survives_event_deletion(self):
        """會議刪掉，記錄仍在（內容有保存價值）。"""
        note = self._note(self.event)
        self.event.unlink()
        self.assertTrue(note.exists())
        self.assertFalse(note.calendar_event_ids)

    def test_07_note_count_correct_for_multiple_events(self):
        start = datetime.now() + timedelta(days=2)
        events = self.env['calendar.event'].create([{
            'name': 'Meeting %d' % i,
            'start': start,
            'stop': start + timedelta(hours=1),
        } for i in range(3)])
        self._note(events[0])
        self._note(events[1])
        self._note(events[1])
        self.assertEqual(events.mapped('note_count'), [1, 2, 0])
