# -*- coding: utf-8 -*-

import base64

from odoo.tests.common import TransactionCase


class TestTranscribeLog(TransactionCase):
    """驗證 note.transcribe.log 模型的 retriable 計算與生命週期"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.note = cls.env['note.note'].create({
            'name': 'Test Meeting',
            'note_type': 'meeting',
        })
        cls.attachment = cls.env['ir.attachment'].create({
            'name': 'test.webm',
            'type': 'binary',
            'datas': base64.b64encode(b'fake audio data'),
            'res_model': 'note.note',
            'res_id': cls.note.id,
            'mimetype': 'audio/webm',
        })
        cls.recording = cls.env['note.recording'].create({
            'note_id': cls.note.id,
            'attachment_id': cls.attachment.id,
            'duration': 60.0,
            'file_format': 'webm',
            'file_size': 15,
        })

    def _make_log(self, state, **kwargs):
        vals = {
            'recording_id': self.recording.id,
            'provider': 'assemblyai',
            'attempt_no': 1,
            'state': state,
        }
        vals.update(kwargs)
        return self.env['note.transcribe.log'].create(vals)

    # ===== retriable 計算 =====
    def test_network_error_is_retriable(self):
        log = self._make_log('network_error')
        self.assertTrue(log.retriable)

    def test_timeout_is_retriable(self):
        log = self._make_log('timeout')
        self.assertTrue(log.retriable)

    def test_stale_worker_is_retriable(self):
        log = self._make_log('stale_worker')
        self.assertTrue(log.retriable)

    def test_upload_failed_is_retriable(self):
        log = self._make_log('upload_failed')
        self.assertTrue(log.retriable)

    def test_http_500_is_retriable(self):
        log = self._make_log('http_error', http_status=502)
        self.assertTrue(log.retriable)

    def test_http_400_not_retriable(self):
        log = self._make_log('http_error', http_status=400)
        self.assertFalse(log.retriable)

    def test_config_error_not_retriable(self):
        log = self._make_log('config_error')
        self.assertFalse(log.retriable)

    def test_quota_exceeded_not_retriable(self):
        log = self._make_log('quota_exceeded')
        self.assertFalse(log.retriable)

    def test_parse_error_not_retriable(self):
        log = self._make_log('parse_error')
        self.assertFalse(log.retriable)

    def test_internal_error_not_retriable(self):
        log = self._make_log('internal_error')
        self.assertFalse(log.retriable)

    def test_success_not_retriable(self):
        log = self._make_log('success')
        self.assertFalse(log.retriable)

    # ===== 關聯與 next_attempt_no =====
    def test_note_id_populated_from_recording(self):
        log = self._make_log('success')
        self.assertEqual(log.note_id, self.note)

    def test_next_attempt_no_increments(self):
        self._make_log('success', attempt_no=1)
        self._make_log('http_error', attempt_no=2)
        self.assertEqual(self.recording._next_attempt_no(), 3)

    def test_next_attempt_no_starts_at_one(self):
        self.assertEqual(self.recording._next_attempt_no(), 1)

    # ===== latest_log_id / can_retry =====
    def test_can_retry_when_latest_retriable(self):
        self.recording.write({'state': 'error'})
        self._make_log('timeout')
        self.recording._compute_latest_log()
        self.assertTrue(self.recording.can_retry)

    def test_cannot_retry_when_not_error(self):
        self._make_log('success')
        self.recording._compute_latest_log()
        self.assertFalse(self.recording.can_retry)

    def test_cannot_retry_after_max_attempts(self):
        self.recording.write({'state': 'error'})
        self._make_log('timeout', attempt_no=3)
        self.recording._compute_latest_log()
        self.assertFalse(self.recording.can_retry)

    # ===== display_name =====
    def test_display_name_includes_state_and_attempt(self):
        log = self._make_log('timeout', attempt_no=2)
        self.assertIn('2', log.display_name)
        self.assertTrue(
            'Timeout' in log.display_name or 'timeout' in log.display_name
        )
