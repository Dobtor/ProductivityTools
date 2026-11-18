# -*- coding: utf-8 -*-
"""筆記標題（明確給定不覆寫、只取第一個區塊）、錄音名稱時區、
後台簽名也產生最終簽署 PDF、轉錄改 postcommit 啟動 thread。"""
import base64
from datetime import datetime
from unittest.mock import patch

from odoo import Command
from odoo.tests import Form
from odoo.tests.common import TransactionCase, tagged

# 1x1 PNG
PNG = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


@tagged('post_install', '-at_install')
class TestNoteTitle(TransactionCase):

    def test_explicit_name_kept_on_create_and_memo_change(self):
        note = self.env['note.note'].create({
            'name': '第 45 週例會', 'memo': '<p>完全不同的第一行</p>'})
        self.assertEqual(note.name, '第 45 週例會')
        self.assertTrue(note.name_manual)
        note.memo = '<p>又改了內容</p>'
        self.assertEqual(note.name, '第 45 週例會')

    def test_explicit_name_on_write(self):
        note = self.env['note.note'].create({'memo': '<p>原標題</p>'})
        self.assertEqual(note.name, '原標題')
        note.write({'name': '手動標題'})
        note.memo = '<p>新內容</p>'
        self.assertEqual(note.name, '手動標題')
        # 清空 → 回到自動推導
        note.write({'name': ''})
        self.assertEqual(note.name, '新內容')

    def test_derived_title_first_block_only(self):
        note = self.env['note.note'].create({
            'memo': '<h2>第 45 週例會</h2><p>出席：A、B</p>'})
        self.assertEqual(note.name, '第 45 週例會')
        note.memo = '<div><h1>標題</h1><p>內文</p></div>'
        self.assertEqual(note.name, '標題')

    def test_form_typed_title_survives_memo_edit(self):
        with Form(self.env['note.note']) as form:
            form.memo = '<p>內容第一行</p>'
            self.assertEqual(form.name, '內容第一行')
            form.name = '我的標題'
            form.memo = '<p>改過的內容</p>'
            self.assertEqual(form.name, '我的標題')
        note = form.record
        self.assertEqual(note.name, '我的標題')
        self.assertTrue(note.name_manual)

    def test_name_equal_to_derived_is_not_manual(self):
        # 表單 onchange 會把推導出的 name 一起送回
        note = self.env['note.note'].create({'name': '第一行', 'memo': '<p>第一行</p>'})
        self.assertFalse(note.name_manual)
        note.memo = '<p>第二版</p>'
        self.assertEqual(note.name, '第二版')


@tagged('post_install', '-at_install')
class TestRecordingNameTz(TransactionCase):

    def test_recording_name_in_user_tz(self):
        self.env.user.tz = 'Asia/Taipei'
        note = self.env['note.note'].create({'memo': '<p>rec</p>', 'note_type': 'meeting'})
        res = self.env['note.recording'].create_from_browser({
            'note_id': note.id,
            'audio_base64': base64.b64encode(b'abc').decode(),
            'duration': 10,
            'record_start': '2026-11-16T06:00:00Z',
            'record_end': '2026-11-16T06:00:10Z',
            'file_format': 'webm',
        })
        recording = note.recording_ids[:1]
        self.assertTrue(recording)
        self.assertIn('2026-11-16 14:00', recording.name)
        self.assertEqual(recording.record_start, datetime(2026, 11, 16, 6, 0))

    def test_transcribe_starts_thread_postcommit(self):
        note = self.env['note.note'].create({'memo': '<p>rec</p>', 'note_type': 'meeting'})
        attachment = self.env['ir.attachment'].create({
            'name': 'r.webm', 'datas': base64.b64encode(b'abc'),
            'res_model': 'note.note', 'res_id': note.id})
        recording = self.env['note.recording'].create({
            'note_id': note.id, 'attachment_id': attachment.id})
        with patch('odoo.addons.dobtor_meeting_minutes.models.note_recording.threading.Thread') as Thread, \
                patch.object(type(self.env.cr), 'commit', side_effect=AssertionError('no mid-request commit')):
            recording.action_transcribe()
            Thread.assert_not_called()
            self.env.cr.postcommit.run()
            Thread.assert_called_once()
        self.assertEqual(recording.state, 'processing')


@tagged('post_install', '-at_install')
class TestBackendSignPdf(TransactionCase):

    def test_backend_sign_attaches_final_pdf(self):
        signer = self.env['res.partner'].create({'name': 'Signer A', 'email': 'a@example.com'})
        event = self.env['calendar.event'].create({
            'name': 'Weekly', 'start': '2026-11-16 06:00:00', 'stop': '2026-11-16 07:00:00',
            'partner_ids': [Command.link(signer.id)],
        })
        note = self.env['note.note'].create({
            'memo': '<p>Minutes</p>', 'note_type': 'meeting',
            'calendar_event_ids': [Command.link(event.id)],
            'signer_ids': [Command.link(signer.id)],
        })
        note.action_send_for_signature()
        sig = note.signature_ids
        self.assertEqual(len(sig), 1)
        sig.action_sign('Signer A', PNG)
        self.assertEqual(note.state, 'signed')
        pdf_msgs = note.message_ids.filtered(
            lambda m: any(a.name.endswith('Signed.pdf') for a in m.attachment_ids))
        self.assertEqual(len(pdf_msgs), 1, '後台簽名路徑也要附最終簽署文件')
