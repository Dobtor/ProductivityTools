# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase

from odoo.addons.dobtor_meeting_minutes.models.note_recording import TranscribeError


class TestTranscribeError(TransactionCase):
    """驗證 TranscribeError 分類邏輯"""

    def test_valid_code_preserved(self):
        err = TranscribeError('config_error', 'API key missing')
        self.assertEqual(err.code, 'config_error')

    def test_invalid_code_normalized_to_internal(self):
        err = TranscribeError('nonexistent_code', 'x')
        self.assertEqual(err.code, 'internal_error')

    def test_http_status_stored(self):
        err = TranscribeError('http_error', 'fail', http_status=500)
        self.assertEqual(err.http_status, 500)

    def test_http_status_defaults_to_zero(self):
        err = TranscribeError('timeout', 'slow')
        self.assertEqual(err.http_status, 0)

    def test_response_snippet_stored(self):
        err = TranscribeError(
            'http_error', 'bad',
            response_snippet='{"error":"foo"}',
        )
        self.assertEqual(err.response_snippet, '{"error":"foo"}')

    def test_message_passed_to_exception(self):
        err = TranscribeError('timeout', 'ran too long')
        self.assertEqual(str(err), 'ran too long')
