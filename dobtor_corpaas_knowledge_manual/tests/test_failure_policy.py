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


@tagged('post_install', '-at_install')
class TestPackageProfile(ManualCase):
    """方案檔案（計畫第 32 項）：探測結果合併、轉成給 AI 的一段話、登入方式判斷。"""

    def test_profile_merge_text_and_login_mode(self):
        from ..models.hooks import login_mode
        self.assertEqual(login_mode('http://sb:8069/?popup=login&redirect=%2F'), 'popup')
        self.assertEqual(login_mode('http://sb:8069/web/login'), 'standard')
        self.assertEqual(login_mode('http://sb:8069/my'), 'redirect')
        self.pkg._knowledge_update_profile({'companies': 1, 'website': True, 'websites': 1,
                                            'custom_groups': [{'xmlid': 'x.g', 'name': '佣金管理員'}]})
        self.pkg._knowledge_update_profile({'login_mode': 'popup'})
        prof = self.pkg.knowledge_profile()
        self.assertEqual((prof['companies'], prof['login_mode']), (1, 'popup'), '兩次探測合併')
        text = self.pkg._knowledge_profile_text()
        self.assertIn('彈出視窗', text)
        self.assertIn('佣金管理員', text)

    def test_profile_prefixed_to_environment_prompts(self):
        Ai = type(self.env['corpaas.knowledge.ai'])
        self.pkg._knowledge_update_profile({'companies': 2})
        seen = []

        def fake_call(url, key, purpose, prompt, *a, **kw):
            seen.append((purpose, prompt))
            return '{}', 0.0, 1
        from odoo.addons.dobtor_corpaas_knowledge.services import hub_client
        with patch.object(hub_client, 'call', fake_call), \
                patch.object(Ai, '_conf', lambda s: {'hub_url': 'x', 'hub_key': 'k', 'budget': 99,
                                                     'timeout': 5}), \
                patch.object(Ai, 'hub_cost_left', lambda s: None):
            self.env['corpaas.knowledge.ai'].ask('seed_repair', 'PROMPT', package=self.pkg)
            self.env['corpaas.knowledge.ai'].ask('manual_step_block', 'PROMPT2', package=self.pkg)
        self.assertIn('公司 2 家', seen[0][1])
        self.assertNotIn('方案檔案', seen[1][1], '跨方案共用的步驟說明不帶方案環境')
