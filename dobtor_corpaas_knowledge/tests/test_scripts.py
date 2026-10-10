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
