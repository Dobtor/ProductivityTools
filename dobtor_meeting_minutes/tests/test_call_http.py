# -*- coding: utf-8 -*-

import base64
from unittest.mock import MagicMock, patch

import requests

from odoo.tests.common import TransactionCase

from odoo.addons.dobtor_meeting_minutes.models.note_recording import TranscribeError


def _make_response(status_code, text='', json_data=None):
    """Build a mock requests.Response"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    resp.text = text
    resp.json.return_value = json_data or {}
    return resp


class TestCallHttp(TransactionCase):
    """Mock requests 驗證 _call_http 分類邏輯

    重要：這些測試確保 API 異常一律被歸類為 TranscribeError，
    而非 raw requests exception 洩漏給 worker 造成分類錯亂。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        note = cls.env['note.note'].create({'name': 'T', 'note_type': 'meeting'})
        attachment = cls.env['ir.attachment'].create({
            'name': 'test.webm',
            'type': 'binary',
            'datas': base64.b64encode(b'x'),
            'res_model': 'note.note',
            'res_id': note.id,
        })
        cls.recording = cls.env['note.recording'].create({
            'note_id': note.id,
            'attachment_id': attachment.id,
            'file_format': 'webm',
        })

    def test_timeout_raises_timeout_code(self):
        with patch('requests.request', side_effect=requests.exceptions.Timeout('slow')):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('POST', 'http://x', error_prefix='test')
        self.assertEqual(cm.exception.code, 'timeout')
        self.assertIn('test', cm.exception.message)

    def test_connection_error_raises_network_code(self):
        with patch('requests.request', side_effect=requests.exceptions.ConnectionError('dns fail')):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('GET', 'http://x', error_prefix='p')
        self.assertEqual(cm.exception.code, 'network_error')

    def test_401_raises_config_error(self):
        resp = _make_response(401, text='{"error":"bad key"}')
        with patch('requests.request', return_value=resp):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('POST', 'http://x', error_prefix='p')
        self.assertEqual(cm.exception.code, 'config_error')
        self.assertEqual(cm.exception.http_status, 401)

    def test_403_raises_config_error(self):
        resp = _make_response(403, text='forbidden')
        with patch('requests.request', return_value=resp):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('POST', 'http://x', error_prefix='p')
        self.assertEqual(cm.exception.code, 'config_error')

    def test_429_raises_quota_exceeded(self):
        resp = _make_response(429, text='rate limit hit')
        with patch('requests.request', return_value=resp):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('POST', 'http://x', error_prefix='p')
        self.assertEqual(cm.exception.code, 'quota_exceeded')

    def test_500_raises_http_error(self):
        resp = _make_response(500, text='Internal Server Error')
        with patch('requests.request', return_value=resp):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('POST', 'http://x', error_prefix='p')
        self.assertEqual(cm.exception.code, 'http_error')
        self.assertEqual(cm.exception.http_status, 500)

    def test_400_raises_http_error(self):
        resp = _make_response(400, text='bad request')
        with patch('requests.request', return_value=resp):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('POST', 'http://x', error_prefix='p')
        self.assertEqual(cm.exception.code, 'http_error')

    def test_ok_response_returned(self):
        resp = _make_response(200, text='ok', json_data={'ok': True})
        with patch('requests.request', return_value=resp):
            result = self.recording._call_http('POST', 'http://x')
        self.assertEqual(result.status_code, 200)

    def test_response_body_captured_in_snippet(self):
        body = 'detailed error message with context'
        resp = _make_response(500, text=body)
        with patch('requests.request', return_value=resp):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('POST', 'http://x')
        self.assertIn(body, cm.exception.response_snippet or '')

    def test_http_url_populated(self):
        url = 'https://api.example.com/v1/endpoint'
        with patch('requests.request', side_effect=requests.exceptions.Timeout('t')):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('POST', url, error_prefix='p')
        self.assertEqual(cm.exception.http_url, url)

    def test_sensitive_data_masked_in_snippet(self):
        """回應 body 若含 API key，寫入 snippet 前應被遮蔽"""
        body = 'Invalid Bearer sk-leaked1234567890key in request'
        resp = _make_response(400, text=body)
        with patch('requests.request', return_value=resp):
            with self.assertRaises(TranscribeError) as cm:
                self.recording._call_http('POST', 'http://x')
        self.assertNotIn('sk-leaked1234567890key', cm.exception.response_snippet or '')
