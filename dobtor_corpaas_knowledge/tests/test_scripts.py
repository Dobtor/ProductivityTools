# -*- coding: utf-8 -*-
"""送進 odoo shell 的腳本：至少要能編譯，而且唯讀的那幾支必須 rollback。"""
from odoo.tests import TransactionCase, tagged

from ..services import hub_client, scripts


@tagged('post_install', '-at_install')
class TestScripts(TransactionCase):

    def _compiles(self, src):
        compile(src, '<shell>', 'exec')

    def test_all_scripts_compile(self):
        self._compiles(scripts.inventory_script(['sale', 'crm']))
        self._compiles(scripts.fingerprint_script(
            [{'key': 'k', 'model': 'res.partner', 'views': [[False, 'form']],
              'elements': [{'field': 'name'}]}],
            [{'code': 'admin', 'groups': ['base.group_system']}]))
        self._compiles(scripts.purge_script(['res.partner', 'sale.order']))
        self._compiles(scripts.seed_script('__doc_scenario_x',
                                           [{'xmlid': 'p1', 'model': 'res.partner',
                                             'values': {'name': "O'Brien %s"}}],
                                           [{'code': 'sales', 'name': '業務',
                                             'groups': ['base.group_user']}], 'pw%s'))
        self._compiles(scripts.gate_script({'res.partner': [1, 2]}, '2026-01-01 00:00:00'))

    def test_readonly_scripts_rollback(self):
        for src in (scripts.inventory_script(['sale']),
                    scripts.fingerprint_script([], []),
                    scripts.gate_script({}, '2026-01-01')):
            self.assertIn('env.cr.rollback()', src)
            self.assertNotIn('env.cr.commit()', src)

    def test_inventory_finds_front_routes(self):
        """網站前台頁：手動建的網站選單（沒有 xmlid）與已安裝模組的標準頁都盤得到。"""
        if 'website.menu' not in self.env:
            self.skipTest('沒有 website')
        Menu = self.env['website.menu']
        site = self.env['website'].search([], limit=1)
        Menu.create({'name': '分享金規則', 'url': '/kbt-share-rules', 'website_id': site.id,
                     'parent_id': site.menu_id.id})
        Menu.create({'name': '會員專區', 'url': '/kbt-members', 'website_id': site.id,
                     'parent_id': site.menu_id.id,
                     'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        src = scripts.inventory_script(['base'], official=['website']).replace(
            'env.cr.rollback()', 'pass')
        printed = []
        exec(compile(src, '<inv>', 'exec'), {'env': self.env, 'print': printed.append})
        import json
        routes = {f['anchor']: f for f in json.loads(printed[-1][len(scripts.MARK):])['features']
                  if f['kind'] == 'route'}
        self.assertEqual(routes['/kbt-share-rules#public']['module'], 'website')
        self.assertIn('/kbt-share-rules#internal', routes, '公開的內容頁另寫網站管理')
        self.assertIn('/kbt-members#portal', routes, sorted(routes))
        self.assertFalse([k for k in routes if k.startswith('/default-main-menu')], '根選單不是頁面')
        self.assertNotIn('/kbt-members#public', routes)
        self.assertIn('會員專區', routes['/kbt-members#portal']['front_menus'])
        self.assertNotIn('會員專區', routes['/kbt-share-rules#public'].get('front_menus') or '',
                         '訪客看不到會員選單')
        self.assertIn('/#public', routes, '網站首頁（標準頁）')

    def test_fingerprint_script_runs_in_process(self):
        """在測試庫直接 exec 指紋腳本：驗證它真的能跑 get_views 並回傳雜湊。"""
        src = scripts.fingerprint_script(
            [{'key': 'base.action:base.action_partner_form', 'model': 'res.partner',
              'views': [[False, 'form']], 'elements': [{'field': 'name'}],
              'menu_path': 'x', 'view_mode': 'form'}],
            [{'code': 'admin', 'groups': ['base.group_system']}])
        src = src.replace('env.cr.rollback()', 'pass')  # 測試交易本身會回滾
        printed = []
        ns = {'env': self.env, 'print': printed.append}
        exec(compile(src, '<fp>', 'exec'), ns)
        import json
        payload = json.loads(printed[-1][len(scripts.MARK):])
        per = payload['items']['base.action:base.action_partner_form']['admin']
        self.assertIn('scope', per, per)
        self.assertIn('field=name', per['found'])

    def test_seed_script_runs_in_process(self):
        src = scripts.seed_script(
            '__doc_scenario_t',
            [{'xmlid': 'partner_a', 'model': 'res.partner', 'values': {'name': '示範客戶 A'}},
             {'xmlid': 'partner_b', 'model': 'res.partner',
              'values': {'name': 'B', 'parent_id': '__ref__:partner_a'}}],
            [{'code': 'sales', 'name': '業務', 'groups': ['base.group_user']}], 'secret-pw')
        src = src.replace('env.cr.commit()', 'pass')
        printed = []
        exec(compile(src, '<seed>', 'exec'), {'env': self.env, 'print': printed.append})
        import json
        res = json.loads(printed[-1][len(scripts.MARK):])
        self.assertEqual(res['errors'], [])
        b = self.env.ref('__doc_scenario_t.partner_b')
        self.assertEqual(b.parent_id, self.env.ref('__doc_scenario_t.partner_a'))
        self.assertEqual(res['users']['sales'], 'doc_sales')

    def test_seed_script_users_first_and_calls(self):
        """角色帳號先建（單據可指定給它）；動作依序呼叫；不允許的方法擋下。"""
        src = scripts.seed_script(
            '__doc_scenario_t2',
            [{'xmlid': 'p1', 'model': 'res.partner',
              'values': {'name': '示範', 'user_id': '__ref__:user_sales'}},
             {'xmlid': 'p1_archive', 'model': 'res.partner', 'call': 'action_archive',
              'ref': 'p1'},
             {'xmlid': 'bad', 'model': 'res.partner', 'call': 'unlink', 'ref': 'p1'}],
            [{'code': 'sales', 'name': '業務', 'groups': ['base.group_user']}], 'pw-123456')
        src = src.replace('env.cr.commit()', 'pass')
        printed = []
        exec(compile(src, '<seed>', 'exec'), {'env': self.env, 'print': printed.append})
        import json
        res = json.loads(printed[-1][len(scripts.MARK):])
        p1 = self.env.ref('__doc_scenario_t2.p1').with_context(active_test=False)
        self.assertEqual(p1.user_id, self.env.ref('__doc_scenario_t2.user_sales'))
        self.assertFalse(p1.active, '動作有執行')
        self.assertEqual([e['xmlid'] for e in res['errors']], ['bad'], '只允許 action_／button_')

    def test_seed_script_admin_gets_all_internal_groups(self):
        """說明庫的系統管理員拿到所有內部群組（自訂模組的權限群組也要），不含會改變畫面的群組。"""
        custom = self.env['res.groups'].create({'name': 'KB 自訂模組管理員'})
        src = scripts.seed_script('__doc_scenario_t5', [],
                                  [{'code': 'admin', 'name': '管理', 'groups': ['base.group_system']}],
                                  'pw-123456').replace('env.cr.commit()', 'pass')
        exec(compile(src, '<seed>', 'exec'), {'env': self.env, 'print': lambda *a: None})
        admin = self.env.ref('__doc_scenario_t5.user_admin')
        self.assertIn(custom, admin.groups_id)
        mgr = self.env.ref('sales_team.group_sale_manager', raise_if_not_found=False)
        if mgr:
            self.assertIn(mgr, admin.groups_id, '官方 app 的管理員群組也要有（佣金結算單的權限掛在這）')
        self.assertNotIn(self.env.ref('base.group_multi_company'), admin.groups_id)
        self.assertNotIn(self.env.ref('base.group_portal'), admin.groups_id)

    def test_seed_script_role_partner_xmlid_and_publishes_products(self):
        """角色帳號的聯絡人有 xmlid（示範訂單可開給會員）；網路商店的示範商品自動上架。"""
        recs = [{'xmlid': 'p_shop', 'model': 'product.product',
                 'values': {'name': '示範商品', 'sale_ok': True}},
                {'xmlid': 'c1', 'model': 'res.partner',
                 'values': {'name': '會員的朋友', 'parent_id': '__ref__:user_member_partner'}}]
        src = scripts.seed_script('__doc_scenario_t4', recs,
                                  [{'code': 'member', 'name': '會員', 'groups': ['base.group_portal']}],
                                  'pw-123456').replace('env.cr.commit()', 'pass')
        printed = []
        exec(compile(src, '<seed>', 'exec'), {'env': self.env, 'print': printed.append})
        import json
        res = json.loads(printed[-1][len(scripts.MARK):])
        self.assertEqual(res['errors'], [])
        member = self.env.ref('__doc_scenario_t4.user_member')
        self.assertEqual(self.env.ref('__doc_scenario_t4.c1').parent_id, member.partner_id)
        tmpl = self.env.ref('__doc_scenario_t4.p_shop').product_tmpl_id
        if 'is_published' in tmpl._fields:
            self.assertTrue(tmpl.is_published, '網路商店的示範商品要上架')

    def test_seed_script_skips_uninstalled_models(self):
        """方案沒裝的模型連同參照它的記錄略過，不算錯誤（資料包跨方案共用）。"""
        src = scripts.seed_script(
            '__doc_scenario_t3',
            [{'xmlid': 'prog', 'model': 'no.such.model', 'values': {'name': 'x'}},
             {'xmlid': 'child', 'model': 'res.partner',
              'values': {'name': '依賴', 'comment': '__ref__:prog'}},
             {'xmlid': 'child_archive', 'model': 'res.partner', 'call': 'action_archive',
              'ref': 'child'},
             {'xmlid': 'ok', 'model': 'res.partner', 'values': {'name': '正常'}}],
            [], 'pw-123456')
        src = src.replace('env.cr.commit()', 'pass')
        printed = []
        exec(compile(src, '<seed>', 'exec'), {'env': self.env, 'print': printed.append})
        import json
        res = json.loads(printed[-1][len(scripts.MARK):])
        self.assertEqual(res['errors'], [])
        self.assertEqual([s['xmlid'] for s in res['skipped']], ['prog', 'child', 'child_archive'])
        self.assertTrue(self.env.ref('__doc_scenario_t3.ok'))

    def test_seed_script_never_creates_second_company(self):
        n = self.env['res.company'].search_count([])
        src = scripts.seed_script('__doc_scenario_t6', [
            {'xmlid': 'company_rename', 'model': 'res.company', 'values': {'name': '另一家'}}],
            [], 'pw-123456').replace('env.cr.commit()', 'pass')
        exec(compile(src, '<seed>', 'exec'), {'env': self.env, 'print': lambda *a: None})
        self.assertEqual(self.env['res.company'].search_count([]), n, '不建第二家公司')
        from ..models.catalog import seed_contract_errors
        self.assertTrue(seed_contract_errors([{'xmlid': 'c2', 'model': 'res.company', 'values': {}}]))

    def test_seed_errors_fatal_only_when_many(self):
        from ..models.sandbox import seed_errors_fatal
        self.assertFalse(seed_errors_fatal({'done': 154, 'errors': [{}] * 7}), '少數幾筆照常用')
        self.assertTrue(seed_errors_fatal({'done': 10, 'errors': [{}] * 5}))
        self.assertFalse(seed_errors_fatal({'done': 3, 'errors': []}))

    def _diag(self, login, model, rid=None):
        src = scripts.access_diag_script(login, model, rid).replace('env.cr.rollback()', 'pass')
        printed = []
        exec(compile(src, '<diag>', 'exec'), {'env': self.env, 'print': printed.append})
        import json
        return json.loads(printed[-1][len(scripts.MARK):])

    def test_access_diag_acl_and_company(self):
        """唯讀診斷（計畫第 26 項）：沒有讀取權限、記錄屬於別家公司，都講得出原因。"""
        user = self.env['res.users'].create({'name': '診斷員工', 'login': 'kb_diag_user',
                                             'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        d = self._diag('kb_diag_user', 'ir.config_parameter')
        self.assertFalse(d['acl_read'])
        self.assertIn('讀取權限', scripts.access_diag_text(d))
        self.assertIn('base.group_system', scripts.access_diag_text(d), '列出開放給哪些群組')
        other = self.env['res.company'].create({'name': 'KB 另一家公司'})
        p = self.env['res.partner'].create({'name': '別家客戶', 'company_id': other.id})
        d = self._diag(user.login, 'res.partner', p.id)
        self.assertFalse(d['visible_as_user'])
        self.assertIn('KB 另一家公司', scripts.access_diag_text(d))

    def test_runner_signature_follows_file_changes(self):
        """截圖程式單獨換檔（不重啟）時簽章跟著變，舊截圖才會重拍。"""
        import os
        import tempfile
        import time
        from unittest.mock import patch
        from ..services import shooter
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fh:
            fh.write('a = 1\n')
        try:
            with patch.object(shooter, '_RUNNER', fh.name), patch.dict(shooter._RUNNER_SIG, clear=True):
                first = shooter.runner_signature()
                with open(fh.name, 'w') as w:
                    w.write('a = 2\n')
                os.utime(fh.name, (time.time() + 5, time.time() + 5))
                self.assertNotEqual(shooter.runner_signature(), first)
        finally:
            os.unlink(fh.name)

    def test_glossary_text_only_accepts_mappings(self):
        from ..models.catalog import glossary_text
        self.assertEqual(glossary_text({'客戶': '會員'}), '客戶=會員')
        self.assertEqual(glossary_text([{'from': '銷售訂單', 'to': '訂單'}]), '銷售訂單=訂單')
        self.assertFalse(glossary_text([{'term': '會員中心', 'definition': '會員登入後的專屬頁面'}]))
        self.assertEqual(glossary_text('客戶=會員'), '客戶=會員')

    def test_gate_script_flags_customer_records(self):
        customer = self.env['res.partner'].create({'name': '真實客戶'})
        src = scripts.gate_script({'res.partner': [customer.id,
                                                   self.env.ref('base.main_partner').id]},
                                  '2999-01-01 00:00:00')
        printed = []
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<gate>', 'exec'),
             {'env': self.env, 'print': printed.append})
        import json
        bad = json.loads(printed[-1][len(scripts.MARK):])['bad']
        self.assertIn(['res.partner', customer.id], bad)
        self.assertNotIn(['res.partner', self.env.ref('base.main_partner').id], bad)

    def test_extract_json(self):
        self.assertEqual(hub_client.extract_json('前言\n```json\n{"a": 1}\n```'), {'a': 1})
        self.assertEqual(hub_client.extract_json('{"a": [1]}'), {'a': [1]})
        with self.assertRaises(hub_client.HubError):
            hub_client.extract_json('沒有 JSON')


@tagged('post_install', '-at_install')
class TestHubClientPolling(TransactionCase):

    def test_stops_on_terminal_state_without_done_key(self):
        """Hub 的 run_status 少了 `done` 也要能停：看 state。"""
        from unittest.mock import patch
        replies = [{'ok': True, 'run_id': 7},
                   {'ok': True, 'state': 'running'},
                   {'ok': True, 'state': 'done', 'text': '{"a": 1}', 'cost_usd': 0.02}]
        with patch.object(hub_client, '_rpc', side_effect=replies), \
                patch.object(hub_client.time, 'sleep', lambda s: None):
            text, cost, run_id = hub_client.call('http://hub', 'k', 'p', 'prompt', timeout=60)
        self.assertEqual((text, cost, run_id), ('{"a": 1}', 0.02, 7))
        with patch.object(hub_client, '_rpc', side_effect=[{'ok': True, 'run_id': 8},
                                                           {'ok': True, 'state': 'failed'}]), \
                patch.object(hub_client.time, 'sleep', lambda s: None):
            with self.assertRaises(hub_client.HubError):
                hub_client.call('http://hub', 'k', 'p', 'prompt', timeout=60)


@tagged('post_install', '-at_install')
class TestConfigModels(TransactionCase):

    def test_gate_allows_config_models(self):
        """設定類模型（程式建立、沒有 xmlid）不算非示範資料。"""
        tax = self.env['account.tax'].search([], limit=1) if 'account.tax' in self.env else None
        partner = self.env['res.partner'].create({'name': '真實客戶 2'})
        pairs = {'res.partner': [partner.id]}
        if tax:
            pairs['account.tax'] = [tax.id]
        src = scripts.gate_script(pairs, '2999-01-01 00:00:00')
        printed = []
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<gate>', 'exec'),
             {'env': self.env, 'print': printed.append})
        import json
        bad = json.loads(printed[-1][len(scripts.MARK):])['bad']
        self.assertIn(['res.partner', partner.id], bad)
        self.assertFalse([b for b in bad if b[0] == 'account.tax'])
        self.assertIn('stock.rule', scripts.CONFIG_MODELS)


@tagged('post_install', '-at_install')
class TestScreenFilterScript(TransactionCase):

    def test_default_filter_and_rules(self):
        import json
        printed = []
        src = scripts.screen_filter_script(['base.action_res_users', 'base.nope'])
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<screen>', 'exec'),
             {'env': self.env, 'print': printed.append})
        out = json.loads(printed[-1][len(scripts.MARK):])
        self.assertNotIn('base.nope', out)
        d = out['base.action_res_users']
        self.assertEqual(d['model'], 'res.users')
        self.assertTrue(any("share" in f.get('domain', '') for f in d['default_filters']),
                        '預設篩選「內部使用者」的 domain 要讀得出來')
        self.assertIsInstance(d['rules'], list)


@tagged('post_install', '-at_install')
class TestGateBatchScript(TransactionCase):

    def test_batch_matches_single(self):
        import json
        admin = self.env.ref('base.partner_admin').id
        mine = self.env['res.partner'].create({'name': 'old customer'})
        self.env.cr.execute("UPDATE res_partner SET create_date = '2000-01-01' WHERE id = %s", [mine.id])
        items = [{'k': 'a', 'pairs': {'res.partner': [admin]}, 'refs': {}},
                 {'k': 'b', 'pairs': {}, 'refs': {'res.users|partner_id': [mine.id]}}]
        printed = []
        src = scripts.gate_batch_script(items, '2020-01-01 00:00:00', allow=())
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<gate>', 'exec'),
             {'env': self.env, 'print': printed.append})
        bad = json.loads(printed[-1][len(scripts.MARK):])['bad']
        self.assertEqual(bad['a'], [], '模組 xmlid 的記錄允許')
        self.assertEqual(bad['b'], [['res.partner', mine.id]], '關聯欄位指到的舊記錄要擋')


@tagged('post_install', '-at_install')
class TestDemoStateScript(TransactionCase):

    def test_names_states_transient(self):
        import json
        printed = []
        src = scripts.demo_state_script(['base.user_admin', 'base.nope_x'], {})
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<demo>', 'exec'),
             {'env': self.env, 'print': printed.append})
        res = json.loads(printed[-1][len(scripts.MARK):])
        self.assertTrue(res['records']['base.user_admin']['name'])
        self.assertTrue(res['records']['base.nope_x']['missing'])
        self.assertIn('base.language.install', res['transient'])


@tagged('post_install', '-at_install')
class TestReviewFixes(TransactionCase):

    def test_access_diag_text_or_semantics(self):
        base = {'login': 'u', 'model': 'x.y', 'acl_read': True}
        own = {'name': '只看自己', 'global': False, 'matches': False}
        all_ = {'name': '看全部', 'global': False, 'matches': True}
        glob = {'name': '公司規則', 'global': True, 'matches': False}
        self.assertEqual(scripts.access_diag_text(dict(base, rules=[own, all_])), '', '群組規則有一條成立就看得到')
        self.assertIn('只看自己', scripts.access_diag_text(dict(base, rules=[own])))
        self.assertIn('公司規則', scripts.access_diag_text(dict(base, rules=[glob, all_])), '全域規則不成立就擋')

    def test_seed_contract_forbid_rule(self):
        from ..models.catalog import seed_contract_errors
        forbid = [{'model': 'loyalty.program'}]
        errs = seed_contract_errors([{'xmlid': 'p1', 'model': 'loyalty.program', 'values': {}}], forbid=forbid)
        self.assertTrue(errs and 'loyalty.program' in errs[0])

    def test_gate_whitelist_refuses_customer_models(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env['corpaas.knowledge.rule'].create(
                {'name': 'x', 'kind': 'gate_allow_model', 'value': 'res.partner'})


@tagged('post_install', '-at_install')
class TestCodeStructure(TransactionCase):

    def _run(self, src):
        import json
        printed = []
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<code>', 'exec'),
             {'env': self.env, 'print': printed.append})
        return json.loads(printed[-1][len(scripts.MARK):])

    def test_method_chain_and_module_hash(self):
        out = self._run(scripts.code_def_script([['res.partner', 'write'], ['no.model', 'x']]))
        chain = out['res.partner.write']
        self.assertGreaterEqual(len(chain), 2, 'BaseModel 加上各模組的覆寫')
        self.assertEqual(chain[0]['module'], '', '第一段是 Odoo 核心 BaseModel')
        self.assertTrue(all(len(d['hash']) == 16 and d['line'] > 0 for d in chain))
        again = self._run(scripts.code_def_script([['res.partner', 'write']]))
        self.assertEqual(again, {'res.partner.write': chain}, '同樣的程式算出同樣的雜湊')
        mods = self._run(scripts.module_hash_script(core=False))
        self.assertIn('dobtor_corpaas_knowledge', mods)
        self.assertFalse(any(d['core'] for d in mods.values()), '只算官方原碼以外的')

    def test_identity_order_and_chains(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from ..services import remote
        pkg = self.env['infrastructure.solution.package'].sudo().create({
            'product_tmpl_id': self.env['product.template'].create({'name': 'CODE', 'type': 'service'}).id})
        inst = SimpleNamespace(server_id=None, odoo_container='c1', sources_path='/opt/x/sources', name='tpl 14', id=228)
        state = {'digest': 'sha256:aaa', 'build': '18.0.20260901', 'core_calls': 0}

        def run(server, cmd, dont_raise=False):
            if 'Mounts' in cmd:
                return SimpleNamespace(stdout='/usr/lib/python3/dist-packages/odoo\n'
                                              '[{"Source": "/opt/x/sources", "Destination": "/mnt/src"}]')
            if 'docker create' in cmd:
                state['extract'] = state.get('extract', 0) + 1
                assert 'docker cp "$T:$P" - | tar -xf -' in cmd, '串流 tar（不直接 cp 到目錄）'
                return SimpleNamespace(stdout='/srv/ai-src/odoo/' + state['digest'][7:19])
            return SimpleNamespace(stdout=state['digest'] if 'inspect' in cmd else state['build'])

        def shell_json(env, instance, db, src):
            if 'WANT_CORE = True' in src:
                state['core_calls'] += 1
                return {'sale': {'version': '1', 'hash': 'h1', 'core': True}}
            if 'WANT_CORE = False' in src:
                return {'x_mod': {'version': '1.0', 'hash': 'x1', 'core': False}}
            return {'res.partner.write': [{'module': '', 'file': 'f', 'line': 1, 'end': 2, 'hash': 'd1'},
                                          {'module': 'x_mod', 'file': 'g', 'line': 3, 'end': 4, 'hash': state.get('d2', 'd2')}]}

        with patch.object(remote, 'run', run), patch.object(remote, 'shell_json', shell_json):
            first = pkg._knowledge_code_identity(inst, 'db')
            self.assertEqual((first['match'], state['core_calls']), ('hashed', 1), '沒見過：算一次官方原碼')
            self.assertEqual(pkg._knowledge_code_identity(inst, 'db')['match'], 'image', '同映像：不再算')
            self.assertEqual(state['extract'], 1, '同一個映像只抽一次原碼')
            self.assertEqual(self.env['corpaas.knowledge.code_tree'].search(
                [('image_digest', '=', 'sha256:aaa')]).core_path, '/srv/ai-src/odoo/aaa')
            state['digest'] = 'sha256:bbb'
            self.assertEqual(pkg._knowledge_code_identity(inst, 'db')['match'], 'version', '新映像但同一建置版號：沿用')
            self.assertEqual(state['core_calls'], 1)
            state.update(digest='sha256:ccc', build='18.0')
            self.assertEqual(pkg._knowledge_code_identity(inst, 'db')['match'], 'hashed', '版號沒有建置日期：不當同一份')
            facts = pkg._knowledge_code_chains(inst, 'db', [('res.partner', 'write')])
            fact = facts['res.partner.write']
            self.assertEqual(len(fact.def_ids), 2)
            fact.write({'state': 'current', 'fact_json': '{}'})
            again = pkg._knowledge_code_chains(inst, 'db', [('res.partner', 'write')])['res.partner.write']
            self.assertEqual(again, fact, '鏈沒變：同一筆')
            state['d2'] = 'd2b'
            new = pkg._knowledge_code_chains(inst, 'db', [('res.partner', 'write')])['res.partner.write']
            self.assertNotEqual(new, fact)
            self.assertEqual(fact.state, 'stale', '覆寫改了：舊結論過期')
            self.assertEqual(len(self.env['corpaas.knowledge.code_def'].search([('def_hash', '=', 'd1')])), 1,
                             '沒變的那段共用')


@tagged('post_install', '-at_install')
class TestCodeSemantic(TransactionCase):

    def test_runner_paths_semantic_and_gc(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from ..services import remote
        pkg = self.env['infrastructure.solution.package'].sudo().create({
            'product_tmpl_id': self.env['product.template'].create({'name': 'SEM', 'type': 'service'}).id})
        Tree = self.env['corpaas.knowledge.code_tree'].sudo()
        tree = Tree.create({'image_digest': 'sha256:abcdef1234567890', 'odoo_version': '18.0.20260901',
                            'core_path': '/srv/ai-src/odoo/abcdef123456',
                            'core_container_path': '/usr/lib/python3/dist-packages/odoo'})
        pkg._knowledge_update_profile({'code': {'digest': tree.image_digest, 'container_sources': '/mnt/src'}})
        inst = SimpleNamespace(name='tpl 14', id=228)
        self.assertEqual(pkg._knowledge_runner_path('/usr/lib/python3/dist-packages/odoo/addons/sale/models/s.py', inst),
                         '/odoo-core/abcdef123456/odoo/addons/sale/models/s.py')
        if 'infrastructure.ai_runner' in self.env:
            self.assertEqual(pkg._knowledge_runner_path('/mnt/src/Dobtor/x/m.py', inst), '/instances/tpl-14/Dobtor/x/m.py')
        Def = self.env['corpaas.knowledge.code_def'].sudo()
        d1 = Def.create({'def_hash': 'h1', 'method': 'action_ok', 'module': '(core)', 'line_start': 1, 'line_end': 9,
                         'path': '/usr/lib/python3/dist-packages/odoo/addons/sale/models/s.py'})
        d2 = Def.create({'def_hash': 'h2', 'method': 'action_ok', 'module': 'x', 'summary_json': json.dumps('檢查服務商'),
                         'path': '/mnt/src/x.py', 'line_start': 3, 'line_end': 5})
        fact = self.env['corpaas.knowledge.code_fact'].sudo().create(
            {'subject': 'sale.order.action_ok', 'chain_hash': 'c1', 'def_ids': [(6, 0, (d1 | d2).ids)]})
        prompts = []

        def ask(s, purpose, prompt, **kw):
            prompts.append((prompt, kw.get('instance_ref')))
            return {'defs': {'h1': '確認訂單'}, 'fact': {'preconditions': ['要有明細'], 'opens': ''}}

        with patch.object(type(self.env['corpaas.knowledge.ai']), 'ask', ask):
            self.assertEqual(pkg._knowledge_code_semantic(inst, fact), 1)
        prompt, ref = prompts[0]
        self.assertEqual(ref, 228, '指定讀這個實例')
        self.assertIn('/odoo-core/abcdef123456/odoo/addons/sale/models/s.py 第 1–9 行', prompt)
        self.assertIn('檢查服務商', prompt, '已有摘要的那段不再讀，摘要直接給')
        self.assertEqual(json.loads(d1.summary_json), '確認訂單')
        self.assertEqual(fact.state, 'current')
        self.assertEqual(pkg._knowledge_code_facts_for({'sale.order.action_ok'})['sale.order.action_ok']['preconditions'],
                         ['要有明細'])
        # 清理：舊映像沒人用就刪目錄，最近還有人用的不刪
        server = self.env['infrastructure.server'].search([], limit=1)
        tree.write({'server_id': server.id, 'last_seen': '2020-01-01 00:00:00'})
        recent = Tree.create({'image_digest': 'sha256:zzz', 'core_path': '/srv/ai-src/odoo/other', 'server_id': server.id})
        ran = []
        with patch.object(remote, 'run', lambda srv, cmd, dont_raise=False: ran.append(cmd)):
            self.assertEqual(Tree._cron_gc_core(), 1 if server else 0)
        if server:
            self.assertEqual(ran, ['rm -rf /srv/ai-src/odoo/abcdef123456'])
            self.assertFalse(tree.core_path)
        self.assertEqual(recent.core_path, '/srv/ai-src/odoo/other')


@tagged('post_install', '-at_install')
class TestModuleSummary(TransactionCase):

    def test_facts_script(self):
        import json
        printed = []
        src = scripts.module_facts_script(['dobtor_corpaas_knowledge', 'no_such_mod'])
        exec(compile(src.replace('env.cr.rollback()', 'pass'), '<mf>', 'exec'), {'env': self.env, 'print': printed.append})
        out = json.loads(printed[-1][len(scripts.MARK):])
        self.assertNotIn('no_such_mod', out)
        f = out['dobtor_corpaas_knowledge']
        self.assertIn('corpaas.knowledge.feature', f['new_models'])
        self.assertIn('infrastructure.solution.package', f['inherits'])
        self.assertTrue(f['path'])

    def test_summaries_reuse_by_hash_and_feed_prompts(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from ..services import remote
        pkg = self.env['infrastructure.solution.package'].sudo().create({
            'product_tmpl_id': self.env['product.template'].create({'name': 'MS', 'type': 'service'}).id})
        Pkg = type(pkg)
        golden = SimpleNamespace(instance_id=SimpleNamespace(id=228, name='tpl 14'), name='gold')
        pkg._knowledge_update_profile({'code': {'digest': 'sha256:x', 'container_sources': '/mnt/src',
                                                'addons': {'x_ref': {'version': '1', 'hash': 'h1'},
                                                           'x_wallet': {'version': '1', 'hash': 'w1'}}}})
        facts = {'x_ref': {'name': '推薦', 'summary': '推薦碼', 'path': '/mnt/src/x_ref', 'new_models': ['x.ref']},
                 'x_wallet': {'name': '錢包', 'summary': '儲值', 'path': '/elsewhere/x_wallet', 'new_models': []}}
        asked = []

        def ask(s, purpose, prompt, **kw):
            asked.append((purpose, kw.get('instance_ref')))
            return {'purpose': '推薦碼與分享金', 'rules': ['推薦人要是會員'], 'setup': ['先設佣金規則']}

        master = SimpleNamespace(_corpaas_golden_db=lambda: golden)
        with patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: master), \
                patch.object(Pkg, '_knowledge_runner_path',
                             lambda s, path, inst: path.replace('/mnt/src', '/instances/tpl-14') if path.startswith('/mnt/src') else ''), \
                patch.object(remote, 'shell_json', lambda env, inst, db, src: facts), \
                patch.object(type(self.env['corpaas.knowledge.ai']), 'ask', ask):
            self.assertEqual(pkg._knowledge_module_summaries(), 1, '讀得到程式的寫 AI 摘要')
            self.assertEqual(pkg._knowledge_module_summaries(), 0, '模組沒改就不重讀')
        self.assertEqual(asked, [('module_summary', 228)], '指定讀方案主實例；讀不到的只存結構事實')
        brief = {b['module']: b for b in pkg._knowledge_module_brief()}
        self.assertEqual(brief['x_ref']['purpose'], '推薦碼與分享金')
        self.assertEqual(brief['x_wallet']['purpose'], '儲值', '沒有 AI 摘要時用說明檔')
        sc = self.env['corpaas.knowledge.scenario'].sudo().create(
            {'name': 'S', 'code': 'kbt_ms', 'narrative': 'n', 'package_ids': [(6, 0, pkg.ids)]})
        text = sc._seed_rules_text([])
        self.assertIn('先設佣金規則', text, '示範資料提示帶上模組規則')
        pkg._knowledge_update_profile({'code': {'addons': {'x_ref': {'version': '2', 'hash': 'h2'}}}})
        self.assertFalse(pkg._knowledge_module_brief(), '模組改了：舊摘要不再用（等重讀）')

    def test_flow_naming_waits_for_capabilities(self):
        from unittest.mock import patch
        pkg = self.env['infrastructure.solution.package'].sudo().create({
            'product_tmpl_id': self.env['product.template'].create({'name': 'FW', 'type': 'service'}).id})
        flow = self.env['corpaas.knowledge.flow'].sudo().create(
            {'model': 'res.partner', 'state_field': 'kbx', 'structure_hash': 'a', 'package_ids': [(6, 0, pkg.ids)]})
        with patch.object(type(self.env['corpaas.knowledge.ai']), 'ask') as ask:
            self.assertFalse(pkg._knowledge_flow_names(None))
        ask.assert_not_called()
        self.assertTrue(flow)
