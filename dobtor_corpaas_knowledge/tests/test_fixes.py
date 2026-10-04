# -*- coding: utf-8 -*-
"""審查第一輪修正的回歸測試。"""
import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..services import scripts
from .test_refresh import TestRefresh


@tagged('post_install', '-at_install')
class TestPresenceAndRebaseline(TestRefresh):

    def test_per_package_presence(self):
        tmpl = self.env['product.template'].create({'name': '方案B', 'type': 'service'})
        pkg_b = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        self._refresh()
        f = self.env['corpaas.knowledge.feature'].search([('package_ids', 'in', self.pkg.id)], limit=1)
        f.package_ids = [(4, pkg_b.id)]
        # 在 A 方案「消失」：盤點結果少了這一個功能點。
        # ★ 不能用「整個盤點是空的」模擬：空結果多半是腳本那端出事，核心刻意不據此下架。
        Pkg = type(self.pkg)
        Feature = self.env['corpaas.knowledge.feature']

        def shell(env, inst, db, script, **kw):
            res = self._exec_shell(env, inst, db, script)
            if 'MODS' in script:
                res['features'] = [i for i in res['features'] if Feature.make_key(
                    i['module'], i['kind'], i['anchor']) != f.feature_key]
            return res

        with patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: self.master), \
                patch.object(Pkg, '_provision_module_names', lambda s: ['base']), \
                patch('odoo.addons.dobtor_corpaas_knowledge.services.remote.shell_json',
                      side_effect=shell):
            self.pkg.solution_package_knowledge_refresh()
        self.assertNotIn(self.pkg, f.package_ids)
        self.assertIn(self.pkg, f.missing_package_ids)
        self.assertFalse(f.missing, 'B 方案還有，不算全域消失')
        self.assertTrue(f.is_present_in(pkg_b))

    def test_elements_change_rebaselines_silently(self):
        self._refresh()
        feature = self.env['corpaas.knowledge.feature'].search(
            [('package_ids', 'in', self.pkg.id), ('model', '=', 'res.partner'),
             ('kind', '=', 'action')], limit=1)
        Hooks = type(self.env['corpaas.knowledge.hooks'])
        calls = []
        with patch.object(Hooks, '_knowledge_elements_for',
                          lambda s, f, p: [{'field': 'name'}] if f == feature else []), \
                patch.object(Hooks, '_knowledge_fingerprint_rebaselined',
                             lambda s, *a: calls.append(a)):
            events = self._refresh()
        self.assertFalse(events.filtered(lambda e: e.feature_id == feature
                                         and e.type == 'scope_changed'),
                         '第一次有了截圖範本元素不是畫面改變')
        self.assertTrue([c for c in calls if c[0] == feature])

    def test_queue_merges_and_channel(self):
        Pkg = type(self.pkg)
        with patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: self.master):
            q1 = self.pkg.knowledge_enqueue_refresh(full=False, reason='code')
            q2 = self.pkg.knowledge_enqueue_refresh(full=True, reason='monthly')
        self.assertEqual(q1, q2, '同方案只有一張待執行的更新')
        self.assertEqual(q1.channel, 'knowledge')
        self.assertTrue(self.pkg.knowledge_pending_full)


@tagged('post_install', '-at_install')
class TestSandboxAndGate(TransactionCase):

    def test_sandbox_name_and_drop_guard(self):
        tmpl = self.env['product.template'].create({'name': 'P', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        sc = self.env['corpaas.knowledge.scenario'].create({'name': '課程', 'code': 'course'})
        Sandbox = self.env['corpaas.knowledge.sandbox']
        self.assertEqual(Sandbox.make_name(pkg, sc), 'docsbx-p%s-s%s' % (pkg.id, sc.id))
        inst = self.env['infrastructure.instance'].search([], limit=1)
        if not inst:
            return
        sb = Sandbox.create({'package_id': pkg.id, 'scenario_id': sc.id,
                             'master_instance_id': inst.id, 'db_name': 'customer_prod'})
        with self.assertRaises(UserError):
            sb.drop()

    def test_gate_checks_relational_values(self):
        customer = self.env['res.partner'].create({'name': '真實客戶公司'})
        src = scripts.gate_script({}, '2999-01-01 00:00:00',
                                  {'res.partner|parent_id': [customer.id]})
        printed = []
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<gate>', 'exec'),
             {'env': self.env, 'print': printed.append})
        bad = json.loads(printed[-1][len(scripts.MARK):])['bad']
        self.assertIn(['res.partner', customer.id], bad)

    def test_purge_anonymizes_customer_users(self):
        user = self.env['res.users'].create({'name': '客戶員工王小明', 'login': 'wang_x'})
        customer = self.env['res.partner'].create({'name': '真實客戶'})
        term = self.env.ref('account.account_payment_term_30days', raise_if_not_found=False)
        term_lines = term.line_ids if term else self.env['account.payment.term.line']
        src = scripts.purge_script(['res.partner', 'account.payment.term',
                                    'account.payment.term.line']).replace('env.cr.commit()', 'pass')
        printed = []
        exec(compile(src, '<purge>', 'exec'), {'env': self.env, 'print': printed.append})
        self.env.invalidate_all()
        self.assertNotIn('王小明', user.with_context(active_test=False).name)
        self.assertFalse(user.with_context(active_test=False).active)
        self.assertFalse(customer.exists(), '客戶的業務記錄要清掉')
        self.assertTrue(all(line.exists() for line in term_lines),
                        '模組資料的明細（沒有自己的 xmlid）不能被刪')


@tagged('post_install', '-at_install')
class TestAiJob(TransactionCase):

    def test_enqueue_and_run(self):
        tmpl = self.env['product.template'].create({'name': 'P', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        cap = self.env['corpaas.knowledge.capability'].create({'name': '能力', 'code': 'c'})
        Cap = type(cap)
        with patch.object(Cap, '_kb_test_run', create=True,
                          new=lambda self: self.write({'outcome': 'AI 寫的'})):
            action = self.env['corpaas.knowledge.ai'].enqueue(cap, '_kb_test_run', pkg, note='t')
            self.assertEqual(action['tag'], 'display_notification')
            job = self.env['corpaas.knowledge.ai.job'].search([('res_id', '=', cap.id)])
            self.assertEqual(job.queue_id.operate, 'knowledge_ai_job')
            pkg.solution_package_knowledge_ai_job(job_id=job.id)
        self.assertEqual(job.state, 'done')
        self.assertEqual(cap.outcome, 'AI 寫的')
        bad = self.env['corpaas.knowledge.ai.job'].create(
            {'res_model': cap._name, 'res_id': cap.id, 'method': 'unlink', 'package_id': pkg.id})
        with self.assertRaises(UserError):
            bad._run()


@tagged('post_install', '-at_install')
class TestSeedDraft(TransactionCase):

    def test_fields_script_runs(self):
        src = scripts.fields_script(['res.partner'])
        printed = []
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<f>', 'exec'),
             {'env': self.env, 'print': printed.append})
        info = json.loads(printed[-1][len(scripts.MARK):])['res.partner']
        self.assertEqual(info['name']['type'], 'char')
        self.assertEqual(info['parent_id']['relation'], 'res.partner')

    def test_ai_draft_seed_writes_and_proposes(self):
        tmpl = self.env['product.template'].create({'name': 'P', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        sc = self.env['corpaas.knowledge.scenario'].create(
            {'name': '年會', 'code': 'annual2', 'package_ids': [(4, pkg.id)]})
        Pkg, Ai = type(pkg), type(self.env['corpaas.knowledge.ai'])
        from ..services import remote
        golden = type('G', (), {'instance_id': None, 'name': 'g'})()
        master = type('M', (), {'_corpaas_golden_db': lambda s: golden})()
        with patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: master), \
                patch.object(remote, 'shell_json', return_value={'res.partner': {}}), \
                patch.object(Ai, 'ask', return_value={'seed': [
                    {'xmlid': 'm1', 'model': 'res.partner', 'values': {'name': '虛構會員'}}]}):
            sc._ai_draft_seed_run()
        self.assertIn('虛構會員', sc.seed_json)
        self.assertEqual(sc.state, 'review', '新情境的示範資料一定要核准')
        with self.assertRaises(UserError):
            sc.live_seed()


@tagged('post_install', '-at_install')
class TestHelpSignature(TransactionCase):

    DBNAME = 'tenant_a'
    KEY = 'k-test-123'

    def _sign(self, key, body, ts=None, db=None):
        import hashlib
        import hmac
        import time
        ts = str(int(ts if ts is not None else time.time()))
        sig = hmac.new(key.encode(), ts.encode() + b'.' + body, hashlib.sha256).hexdigest()
        return {'X-KB-Database': db or self.DBNAME, 'X-KB-Timestamp': ts, 'X-KB-Signature': sig}

    def test_verify(self):
        DB = self.env['infrastructure.database']
        Cls = type(DB)
        body = b'{"params": {"database": "tenant_a"}}'
        with patch.object(Cls, '_knowledge_help_key_for',
                          lambda s, db: self.KEY if db == self.DBNAME else False):
            v = DB._knowledge_verify_help_request
            self.assertIsNone(v(self.DBNAME, self._sign(self.KEY, body), body))
            self.assertEqual(v(self.DBNAME, self._sign(self.KEY, body), body + b' '),
                             'bad_signature', '內容被改')
            self.assertEqual(v(self.DBNAME, self._sign(self.KEY, body, ts=1), body),
                             'bad_signature', '過期（重送攻擊）')
            self.assertEqual(v(self.DBNAME, self._sign('wrong', body), body), 'bad_signature')
            self.assertEqual(v(self.DBNAME, self._sign(self.KEY, body, db='other'), body),
                             'bad_signature', '標頭庫名與參數不符')
            self.assertEqual(v('other', self._sign(self.KEY, body, db='other'), body),
                             'bad_signature', '沒有金鑰的庫')
            self.assertEqual(v(self.DBNAME, {}, body), 'unsigned')
            self.env['ir.config_parameter'].sudo().set_param(
                'corpaas_knowledge.help_require_signature', 'False')
            self.assertIsNone(v(self.DBNAME, {}, body), '過渡期可關閉強制簽章')

    def test_push_writes_tenant_before_console(self):
        """先寫進租戶、成功才存在主控台：下發失敗不能讓主控台換掉租戶正在用的金鑰。"""
        db = self.env['infrastructure.database'].search([], limit=1)
        if not db:
            self.skipTest('測試庫沒有 infrastructure.database 記錄')
        Cls = type(db)
        pushed = []

        def fail(s, k, v):
            raise RuntimeError('ssh down')
        old = db.sudo().knowledge_help_key
        with patch.object(Cls, '_knowledge_set_tenant_params', lambda s, p: fail(s, 0, 0)):
            with self.assertRaises(UserError):
                db._knowledge_push_help_key()
        self.assertEqual(db.sudo().knowledge_help_key, old)
        with patch.object(Cls, '_knowledge_set_tenant_params', lambda s, p: pushed.extend(p)):
            db._knowledge_push_help_key()
        self.assertIn('dobtor_ai_help.console_key', pushed)
        self.assertTrue(db.sudo().knowledge_help_key)

    def test_groups_filter(self):
        tmpl = self.env['product.template'].create({'name': 'P', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        F = self.env['corpaas.knowledge.feature']
        f_acc = F.create({'feature_key': 'account.menu:x', 'module': 'account', 'kind': 'menu',
                          'anchor': 'x', 'name': '會計報表', 'group_xmlids': 'account.group_account_manager',
                          'package_ids': [(4, pkg.id)]})
        f_all = F.create({'feature_key': 'sale.menu:y', 'module': 'sale', 'kind': 'menu',
                          'anchor': 'y', 'name': '會計報表說明', 'package_ids': [(4, pkg.id)]})
        Help = self.env['corpaas.knowledge.help']
        res = [f for f, _s in Help._match(pkg, query='會計報表', groups=['base.group_user'])]
        self.assertNotIn(f_acc, res, '使用者沒有群組就看不到那個選單，不給連結')
        self.assertIn(f_all, res)
        res = [f for f, _s in Help._match(pkg, query='會計報表',
                                          groups=['account.group_account_manager'])]
        self.assertIn(f_acc, res)
        res = [f for f, _s in Help._match(pkg, query='會計報表')]
        self.assertIn(f_acc, res, '沒傳群組（舊版租戶）不過濾')


@tagged('post_install', '-at_install')
class TestRound3(TransactionCase):

    def setUp(self):
        super().setUp()
        from odoo.tests import new_test_user
        self.editor = new_test_user(self.env, 'r3_editor',
                                    groups='base.group_user,dobtor_corpaas_knowledge.group_knowledge_editor')
        tmpl = self.env['product.template'].create({'name': 'P3', 'type': 'service'})
        self.pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})

    def test_never_published_submit_requires_review(self):
        sc = self.env['corpaas.knowledge.scenario'].create(
            {'name': '單方案情境', 'code': 'solo', 'package_ids': [(4, self.pkg.id)]})
        sc.with_user(self.editor).action_submit()
        self.assertEqual(sc.state, 'review', '從沒上線過的情境不能不經核准就上線')

    def test_editor_cannot_retire(self):
        from odoo.exceptions import AccessError
        cap = self.env['corpaas.knowledge.capability'].create({'name': 'c', 'code': 'c3'})
        with self.assertRaises(AccessError):
            cap.with_user(self.editor).action_retire()

    def test_network_error_becomes_hub_error(self):
        import requests
        from ..services import hub_client
        with patch.object(hub_client.requests, 'post',
                          side_effect=requests.exceptions.ConnectionError('down')):
            with self.assertRaises(hub_client.HubError):
                hub_client.call('http://hub', 'k', 'p', 'x', timeout=1)

    def test_trigger_during_running_refresh_queues_followup(self):
        self.pkg.knowledge_enabled = True
        Pkg = type(self.pkg)
        master = type('M', (), {})()
        with patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: master):
            q1 = self.pkg.knowledge_enqueue_refresh()
            q1.state = 'processing'
            q2 = self.pkg.knowledge_enqueue_refresh(reason='code')
            q3 = self.pkg.knowledge_enqueue_refresh(reason='monthly', full=True)
        self.assertNotEqual(q1, q2, '進行中的那張不能吃掉新的觸發')
        self.assertEqual(q2, q3, '後續觸發合併到同一張待執行的')
        self.assertEqual(q2.state, 'pending')

    def test_sandbox_guards(self):
        sc = self.env['corpaas.knowledge.scenario'].create({'name': 's', 'code': 'sg'})
        inst = self.env['infrastructure.instance'].search([], limit=1)
        if not inst:
            self.skipTest('沒有實例記錄')
        sb = self.env['corpaas.knowledge.sandbox'].create({
            'package_id': self.pkg.id, 'scenario_id': sc.id, 'master_instance_id': inst.id,
            'db_name': 'docsbx-p1-s1', 'state': 'shooting'})
        with self.assertRaises(UserError):
            sb.rebuild()
        with self.assertRaises(UserError):
            sb.drop()

    def test_gate_resolves_nested_line_refs(self):
        customer = self.env['res.partner'].create({'name': '真實客戶'})
        # res.partner 的 child_ids 明細上的 parent_id → res.partner
        src = scripts.gate_script({}, '2999-01-01 00:00:00',
                                  {'res.partner|child_ids>parent_id': [customer.id]})
        printed = []
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<gate>', 'exec'),
             {'env': self.env, 'print': printed.append})
        bad = json.loads(printed[-1][len(scripts.MARK):])['bad']
        self.assertIn(['res.partner', customer.id], bad)

    def test_recorder_groups_and_lines(self):
        import os
        import sys
        import types
        fake = types.ModuleType('playwright.sync_api')
        fake.sync_playwright = None
        sys.modules.setdefault('playwright', types.ModuleType('playwright'))
        sys.modules['playwright.sync_api'] = fake
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'shot_runner', 'run.py')
        ns = {'__name__': 'kb_run'}
        exec(compile(open(path, encoding='utf-8').read(), path, 'exec'), ns)
        rec = ns['Recorder']()

        class Resp:
            status = 200

            def __init__(self, url, result):
                self.url, self._r = url, result

            def json(self):
                return {'result': self._r}
        rec.on_response(Resp('/web/dataset/call_kw/sale.order/web_read_group',
                             {'groups': [{'user_id': [42, '業務甲'], '__count': 3}]}))
        rec.on_response(Resp('/web/dataset/call_kw/sale.order/web_read', [
            {'id': 5, 'partner_id': {'id': 9, 'display_name': 'x'},
             'order_line': [{'id': 1, 'product_id': {'id': 99, 'display_name': 'p'}}]}]))
        pairs, refs = rec.dump()
        self.assertEqual(pairs, {'sale.order': [5]})
        self.assertEqual(refs['sale.order|user_id'], [42])
        self.assertEqual(refs['sale.order|partner_id'], [9])
        self.assertEqual(refs['sale.order|order_line>product_id'], [99])
