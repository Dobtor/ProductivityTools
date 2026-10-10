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
        x = fp.fingerprint('Locator.click: Timeout 10000ms exceeded.\nCall log:\n'
                           '  - waiting for locator("button[name=\\"作廢\\"]:visible").first')
        y = fp.fingerprint('Locator.click: Timeout 10000ms exceeded.\nCall log:\n'
                           '  - waiting for locator("button[name=\\"確認\\"]:visible").first')
        self.assertNotEqual(x, y, '不同按鈕點不到是不同的錯')
        hinted = ('Locator.click: Timeout 10000ms exceeded.\n'
                  '畫面（form /odoo/account.move/3）看得到的按鈕：權限設定(action_x)；分頁：（無）\nCall log:')
        self.assertEqual(fp.classify(hinted), fp.SCRIPT, '畫面提示那一行不影響分類')

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
        self.assertEqual(login_mode('http://sb:8069/', ['/web/login', '/?popup=login&redirect=%2F', '/']),
                         'popup', '中途經過彈窗網址也算')
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


@tagged('post_install', '-at_install')
class TestPreflightHealth(ManualCase):
    """拍攝前健檢（計畫第 27 項）：每個角色先登入一次，登不進去的角色這輪跳過。"""

    def test_down_role_skipped_and_recorded(self):
        import json
        from .test_hooks import _RUN_SHOTS
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': self.f1.id, 'login_role': 'sales', 'fingerprint': 'hz',
            'steps_json': json.dumps([{'goto': {'action': 'a.b'}}, {'shot': 'main'}])})
        b = self.env['corpaas.knowledge.shot_binding'].sudo().create(
            {'template_id': tmpl.id, 'scenario_id': self.scenario.id})
        sb = FakeSandbox(self.scenario)
        sb.role_logins = json.dumps({'admin': 'doc_admin', 'sales': 'doc_sales'})
        sb.package_id = self.pkg
        result = {'shots': {'preflight': {'ok': True}, 'role_sales': {'ok': False, 'error': '登入失敗：x'}}}
        ctx = {}
        with patch(_RUN_SHOTS, return_value=(result, {})) as run:
            ok = self.hooks.with_context(kb_test_preflight=True)._manual_backend_preflight(sb, ctx)
        self.assertTrue(ok, '只有一個角色登不進去不擋整輪')
        self.assertIn('role_sales', [s['id'] for s in run.call_args[0][2]])
        self.assertIn('sales', ctx['manual_role_down'])
        self.assertIn('sales', self.pkg.knowledge_profile()['health']['roles_down'])
        with patch(_RUN_SHOTS) as run:
            self.hooks._manual_run_batch(self.pkg, sb, b, 'tok', ctx)
        run.assert_not_called()
        self.assertEqual(b.state, 'pending')
        self.assertIn('健檢', b.last_error)


@tagged('post_install', '-at_install')
class TestSelfReview(ManualCase):
    """產出自審與單一核准關卡（計畫第 22、23 項）。"""

    def _review_article(self):
        art = self._article(self.f1, self.cap_a)
        art.knowledge_propose('new')
        self.assertEqual(art.state, 'review')
        return art

    def test_pass_auto_publishes_fail_goes_to_exceptions(self):
        Ai = type(self.env['corpaas.knowledge.ai'])
        self.pkg.knowledge_scenario_ids = [(4, self.scenario.id)]
        good = self._review_article()
        with patch.object(Ai, 'ask', return_value={'ok': True, 'problems': []}) as ask:
            pub, bad = self.hooks._manual_auto_publish(self.pkg, 'tok', {'ai': False})
        self.assertEqual((pub, bad), (1, 0))
        self.assertEqual(good.state, 'published', '自審通過就由系統核准上線')
        self.assertEqual(good.manual_review_state, 'pass')
        self.assertEqual(ask.call_args[0][0], 'manual_review')
        bad_art = self._review_article()
        with patch.object(Ai, 'ask', return_value={'ok': False, 'problems': ['步驟提到的按鈕截圖裡沒有']}):
            pub, bad = self.hooks._manual_auto_publish(self.pkg, 'tok', {'ai': False})
        self.assertEqual(bad_art.state, 'review', '不過就留在待審（例外清單）')
        self.assertEqual(bad_art.manual_review_state, 'fail')
        self.assertIn('按鈕', bad_art.manual_review_note)

    def test_conservative_level_never_auto_approves(self):
        Ai = type(self.env['corpaas.knowledge.ai'])
        self.pkg.knowledge_scenario_ids = [(4, self.scenario.id)]
        self.pkg.knowledge_automation = 'conservative'
        art = self._review_article()
        with patch.object(Ai, 'ask') as ask:
            self.assertEqual(self.hooks._manual_auto_publish(self.pkg, 'tok', {'ai': False}), (0, 0))
        ask.assert_not_called()
        self.assertEqual(art.state, 'review')

    def test_rpc_cannot_use_system_approve(self):
        """外部呼叫帶 context 也不能略過核准者檢查（沒有 su）。"""
        from odoo.exceptions import AccessError
        from odoo.tests.common import new_test_user
        self.pkg.knowledge_scenario_ids = [(4, self.scenario.id)]
        art = self._review_article()
        plain = new_test_user(self.env, 'kb_plain_review', groups='base.group_user')
        with self.assertRaises(AccessError):
            art.with_user(plain).with_context(knowledge_system_approve=True).action_approve()


@tagged('post_install', '-at_install')
class TestRunFunnel(ManualCase):

    def test_funnel_rows(self):
        run = self.env['corpaas.knowledge.run'].sudo().create({'package_id': self.pkg.id, 'token': 'tok-f'})
        art = self._article(self.f1, self.cap_a, name='建立報名')
        art.write({'state': 'review', 'manual_review_state': 'fail'})
        rows = dict((r[0], r[1]) for r in run._knowledge_dashboard_funnel())
        self.assertEqual(rows['例外清單'], 1)
        self.assertGreaterEqual(rows['文章'], 1)
        self.assertIn('漏斗', run.dashboard_html)
