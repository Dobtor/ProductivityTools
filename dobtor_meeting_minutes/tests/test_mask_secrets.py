# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase

from odoo.addons.dobtor_meeting_minutes.utils.security import (
    mask_secrets,
    redact_display_key,
)


class TestMaskSecrets(TransactionCase):
    """驗證敏感資料遮蔽 — 避免 API key 洩漏至 log / error message"""

    def test_bearer_token_masked(self):
        text = 'Authorization: Bearer sk-ABCD1234567890defghij'
        result = mask_secrets(text)
        self.assertNotIn('sk-ABCD1234567890defghij', result)
        self.assertIn('***', result)
        self.assertIn('Bearer', result)

    def test_authorization_header_masked(self):
        text = 'authorization: abcdef1234567890abcdef1234567890'
        result = mask_secrets(text)
        self.assertNotIn('abcdef1234567890abcdef1234567890', result)
        self.assertIn('***', result)

    def test_openai_key_masked(self):
        text = 'Using key sk-proj-1234567890abcdefXYZ for request'
        result = mask_secrets(text)
        self.assertNotIn('sk-proj-1234567890abcdefXYZ', result)
        self.assertIn('***', result)

    def test_hex_api_key_masked(self):
        text = 'AssemblyAI key: abcdef1234567890abcdef1234567890'
        result = mask_secrets(text)
        self.assertNotIn('abcdef1234567890abcdef1234567890', result)

    def test_empty_input(self):
        self.assertEqual(mask_secrets(None), None)
        self.assertEqual(mask_secrets(''), '')

    def test_no_secrets_unchanged(self):
        text = 'User 123 uploaded file 456 to endpoint /api/foo'
        self.assertEqual(mask_secrets(text), text)

    def test_multiple_secrets(self):
        text = (
            'Bearer sk-first1234567890abcdef '
            'and another sk-second1234567890XYZ'
        )
        result = mask_secrets(text)
        self.assertNotIn('sk-first1234567890abcdef', result)
        self.assertNotIn('sk-second1234567890XYZ', result)

    def test_redact_display_key_shows_last_4(self):
        self.assertEqual(redact_display_key('sk-1234abcdefghij'), '●●●●●●●●●●●●ghij')

    def test_redact_display_key_empty(self):
        self.assertEqual(redact_display_key(''), '')
        self.assertEqual(redact_display_key(None), '')

    def test_redact_display_key_short(self):
        self.assertEqual(redact_display_key('abc'), '●●●')
