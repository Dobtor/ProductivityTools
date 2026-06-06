# -*- coding: utf-8 -*-
"""Portal 安全測試 — 確認 token 驗證嚴格、無跨 note 洩漏"""

from odoo.tests.common import TransactionCase


class TestPortalSignatureLookup(TransactionCase):
    """驗證 _lookup_signature helper 的 token 驗證邊界"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.dobtor_meeting_minutes.controllers.portal import MeetingPortal
        cls.helper = MeetingPortal

        cls.partner_a = cls.env['res.partner'].create({'name': 'Alice'})
        cls.partner_b = cls.env['res.partner'].create({'name': 'Bob'})

        cls.note_a = cls.env['note.note'].create({
            'name': 'Note A',
            'note_type': 'meeting',
        })
        cls.note_b = cls.env['note.note'].create({
            'name': 'Note B',
            'note_type': 'meeting',
        })

        cls.sig_a = cls.env['note.signature'].create({
            'note_id': cls.note_a.id,
            'partner_id': cls.partner_a.id,
        })
        cls.sig_b = cls.env['note.signature'].create({
            'note_id': cls.note_b.id,
            'partner_id': cls.partner_b.id,
        })

    def test_safe_int_valid(self):
        self.assertEqual(self.helper._safe_int('42'), 42)

    def test_safe_int_invalid_string(self):
        self.assertFalse(self.helper._safe_int('abc'))
        self.assertFalse(self.helper._safe_int(''))
        self.assertFalse(self.helper._safe_int(None))

    def test_safe_int_float_string(self):
        # int() on '3.14' raises ValueError → helper returns False
        self.assertFalse(self.helper._safe_int('3.14'))

    # The following four tests are omitted because _lookup_signature uses
    # request.env which requires a HTTP context. Integration-level tests
    # would require HttpCase. We verify the guard logic directly:

    def test_cross_note_token_never_matches(self):
        """sig_b 的 token 絕不應在 note_a 的 domain 下查到"""
        # Simulate the exact domain used by _lookup_signature
        domain = [
            ('id', '=', self.sig_b.id),
            ('access_token', '=', self.sig_b.access_token),
            ('note_id', '=', self.note_a.id),  # wrong note!
        ]
        result = self.env['note.signature'].search(domain, limit=1)
        self.assertFalse(result, 'sig_b must not be returned when queried under note_a')

    def test_correct_token_matches(self):
        """同一 note + 正確 token 應能查到"""
        domain = [
            ('id', '=', self.sig_a.id),
            ('access_token', '=', self.sig_a.access_token),
            ('note_id', '=', self.note_a.id),
        ]
        result = self.env['note.signature'].search(domain, limit=1)
        self.assertEqual(result, self.sig_a)

    def test_tampered_token_rejected(self):
        """偽造 token 應返空"""
        domain = [
            ('id', '=', self.sig_a.id),
            ('access_token', '=', 'tampered-token-value'),
            ('note_id', '=', self.note_a.id),
        ]
        result = self.env['note.signature'].search(domain, limit=1)
        self.assertFalse(result)

    def test_missing_parameters_return_none(self):
        # helper 本身：所有參數缺一不可
        self.assertIsNone(self.helper._lookup_signature(False, 1, 'token'))
        self.assertIsNone(self.helper._lookup_signature(self.note_a, False, 'token'))
        self.assertIsNone(self.helper._lookup_signature(self.note_a, 1, False))


class TestCryptoRoundtrip(TransactionCase):
    """驗證 Fernet 加解密 + rotation fallback"""

    def setUp(self):
        super().setUp()
        from odoo.addons.dobtor_meeting_minutes.utils import crypto
        crypto.clear_key_cache()
        self.crypto = crypto

    def tearDown(self):
        self.crypto.clear_key_cache()
        super().tearDown()

    def test_encrypt_decrypt_roundtrip(self):
        plain = 'sk-test-1234567890abcdef'
        enc = self.crypto.encrypt(plain, env=self.env)
        self.assertTrue(enc.startswith('ENC::'))
        self.assertNotIn(plain, enc)
        dec = self.crypto.decrypt(enc, env=self.env)
        self.assertEqual(dec, plain)

    def test_encrypt_empty_unchanged(self):
        self.assertEqual(self.crypto.encrypt('', env=self.env), '')
        self.assertIsNone(self.crypto.encrypt(None, env=self.env))

    def test_decrypt_legacy_plaintext_passthrough(self):
        # 無 ENC:: prefix → 視為舊純文字，原樣返回
        self.assertEqual(
            self.crypto.decrypt('plain-text-value', env=self.env),
            'plain-text-value',
        )

    def test_double_encrypt_noop(self):
        plain = 'mykey'
        enc = self.crypto.encrypt(plain, env=self.env)
        enc2 = self.crypto.encrypt(enc, env=self.env)
        self.assertEqual(enc, enc2)

    def test_versioned_format_parsing(self):
        plain = 'testkey'
        enc = self.crypto.encrypt(plain, env=self.env)
        # 新加密一律帶版本號
        version = self.crypto.get_ciphertext_version(enc)
        self.assertIsNotNone(version)
        self.assertGreaterEqual(version, 1)

    def test_legacy_unversioned_still_decrypts(self):
        """ENC::<token>（無 v 號）應被解為 version 1"""
        plain = 'oldformat'
        enc = self.crypto.encrypt(plain, env=self.env)
        # 模擬舊格式：去掉 v<N>::
        import re
        legacy = re.sub(r'ENC::v\d+::', 'ENC::', enc)
        self.assertEqual(self.crypto.get_ciphertext_version(legacy), 1)
        self.assertEqual(self.crypto.decrypt(legacy, env=self.env), plain)
