# -*- coding: utf-8 -*-

import base64

from odoo.tests.common import TransactionCase


class TestTranscriptStateRecompute(TransactionCase):
    """驗證 note._recompute_transcript_state — partial / done / error 計算"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.note = cls.env['note.note'].create({
            'name': 'Multi-Segment Meeting',
            'note_type': 'meeting',
        })

    def _make_recording(self, state='uploaded'):
        attachment = self.env['ir.attachment'].create({
            'name': 'seg.webm',
            'type': 'binary',
            'datas': base64.b64encode(b'data'),
            'res_model': 'note.note',
            'res_id': self.note.id,
        })
        return self.env['note.recording'].create({
            'note_id': self.note.id,
            'attachment_id': attachment.id,
            'state': state,
            'duration': 10,
        })

    def test_no_recordings_state_none(self):
        self.note._recompute_transcript_state()
        self.assertEqual(self.note.transcript_state, 'none')

    def test_all_done_state_done(self):
        self._make_recording('done')
        self._make_recording('done')
        self.note._recompute_transcript_state()
        self.assertEqual(self.note.transcript_state, 'done')

    def test_all_error_state_error(self):
        self._make_recording('error')
        self._make_recording('error')
        self.note._recompute_transcript_state()
        self.assertEqual(self.note.transcript_state, 'error')

    def test_mixed_done_and_error_state_partial(self):
        self._make_recording('done')
        self._make_recording('error')
        self.note._recompute_transcript_state()
        self.assertEqual(self.note.transcript_state, 'partial')

    def test_any_processing_state_processing(self):
        self._make_recording('done')
        self._make_recording('processing')
        self._make_recording('error')
        self.note._recompute_transcript_state()
        self.assertEqual(self.note.transcript_state, 'processing')

    def test_only_uploaded_state_none(self):
        self._make_recording('uploaded')
        self.note._recompute_transcript_state()
        self.assertEqual(self.note.transcript_state, 'none')

    def test_last_transcript_error_reads_latest(self):
        """驗證 last_transcript_error 取最新 error 錄音的訊息"""
        old = self._make_recording('error')
        old.error_message = 'Old failure'
        new = self._make_recording('error')
        new.error_message = 'Newest failure'
        self.note.invalidate_recordset(['last_transcript_error'])
        # 再讀一次
        _ = self.note.last_transcript_error
        self.assertEqual(self.note.last_transcript_error, 'Newest failure')
