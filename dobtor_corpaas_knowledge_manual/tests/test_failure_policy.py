# -*- coding: utf-8 -*-
"""失敗分類、整批提前終止、重試政策（計畫第 29、31 項）。"""
from unittest.mock import patch

from odoo.tests.common import tagged

from ..services import failure_policy as fp
from .common import ManualCase
from .test_hooks import FakeSandbox


@tagged('post_install', '-at_install')
class TestFailurePolicy(ManualCase):

    def test_classify_and_fingerprint(self):
        self.assertEqual(fp.classify('APIRequestContext.post: getaddrinfo ENOTFOUND docsbx'), fp.TRANSIENT)
        self.assertEqual(fp.classify("畫面出現錯誤對話框：存取錯誤 您並無權限存取 '結算單'"), fp.ENVIRONMENT)
        self.assertEqual(fp.classify('後台沒有載入（Timeout 30000ms）'), fp.ENVIRONMENT)
        self.assertEqual(fp.classify('畫面是空白引導頁：x_entry'), fp.DATA)
        self.assertEqual(fp.classify('Locator.click: Timeout 10000ms exceeded.'), fp.SCRIPT)
        self.assertEqual(fp.classify('說明庫找不到示範資料：rec'), fp.SCRIPT, '改繫結修得好')
        a = fp.fingerprint("存取錯誤 您並無權限存取 '結算單' (dobtor.commission.settlement) 記錄 16")
        b = fp.fingerprint("存取錯誤 您並無權限存取 '結算單' (dobtor.commission.settlement) 記錄 9")
        self.assertEqual(a, b, '只差記錄編號＝同一種錯')
        c = fp.fingerprint("存取錯誤 您並無權限存取 '付款交易' (payment.transaction) 記錄 9")
        self.assertNotEqual(a, c, '不同模型是不同的錯')

    def test_halt_reason(self):
        down = ['後台沒有載入（Timeout）：{"url": "/"}'] * 4
        self.assertIsNone(fp.halt_reason(down[:2], 2, 5), '前哨批還沒拍完不判斷')
        self.assertTrue(fp.halt_reason(down + ['ok?'], 5, 5), '前哨批同一環境錯誤 4 次 → 停')
        scripts = ['Locator.click: Timeout 10000ms exceeded.'] * 5
        self.assertIsNone(fp.halt_reason(scripts, 5, 5), '腳本錯誤各自修，不整批停')
        self.assertIsNone(fp.halt_reason(down[:3], 20, 5), '失敗率不到一半不停')

    def test_canary_first_covers_roles(self):
        class B:
            def __init__(self, role):
                self.role = role

            def login_role(self):
                return self.role
        bs = [B('sales')] * 4 + [B('admin'), B('member')]
        first = self.hooks._manual_canary_first(bs, 3)[:3]
        self.assertEqual({b.role for b in first}, {'sales', 'admin', 'member'})

    def test_repair_skips_environment_and_repeated_errors(self):
        import json
        Ai = type(self.env['corpaas.knowledge.ai'])
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': self.f1.id, 'login_role': 'admin', 'fingerprint': 'hx',
            'steps_json': json.dumps([{'goto': {'action': 'a.b'}}, {'shot': 'main'}])})
        b = self.env['corpaas.knowledge.shot_binding'].sudo().create(
            {'template_id': tmpl.id, 'scenario_id': self.scenario.id})
        b.write({'state': 'failed', 'needs_repair': True, 'repair_attempts': 0,
                 'last_error': "畫面出現錯誤對話框：存取錯誤 您並無權限存取 '結算單' 記錄."})
        with patch.object(Ai, 'ask') as ask:
            self.hooks._manual_repair_bindings(self.pkg, b, 'tok', {'ai': False})
        ask.assert_not_called()
        self.assertFalse(b.needs_repair, '環境錯誤不叫 AI 修')
        err = 'Locator.click: Timeout 10000ms exceeded.'
        b.write({'state': 'failed', 'needs_repair': True, 'last_error': err,
                 'repair_fp': fp.fingerprint(err)})
        with patch.object(Ai, 'ask') as ask:
            self.hooks._manual_repair_bindings(self.pkg, b, 'tok', {'ai': False})
        ask.assert_not_called()
        self.assertFalse(b.needs_repair, '修過仍是同一錯誤，不再修')
