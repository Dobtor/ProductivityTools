# -*- coding: utf-8 -*-
"""P2：示範資料包＋送審前重播檢查（A3）、範本資料來源分級（A4）、示範資料只新增就疊加（R2）。"""
import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.catalog import qualify_seed_record
from ..services import scripts
from .test_refresh import _RefreshBase
from .test_usage_flow import make_database


def _seed(*recs):
    return json.dumps(list(recs))


@tagged('post_install', '-at_install')
class TestSeedPacks(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Pack = self.env['corpaas.knowledge.seed_pack'].sudo()
        self.contacts = self.Pack.create({
            'name': '聯絡人', 'code': 'kbt_contacts', 'sequence': 20,
            'seed_json': _seed({'xmlid': 'c1', 'model': 'res.partner',
                                'values': {'name': '客戶甲'}})})
        self.sales = self.Pack.create({
            'name': '銷售流程', 'code': 'kbt_sales', 'sequence': 10,
            'depend_ids': [(6, 0, self.contacts.ids)],
            'seed_json': _seed({'xmlid': 's1', 'model': 'res.partner',
                                'values': {'name': '聯絡人乙',
                                           'parent_id': '__ref__:__doc_pack_kbt_contacts.c1',
                                           'user_id': '__ref__:user_sales'}})})
        self.role = self.env['corpaas.knowledge.role'].sudo().create(
            {'name': '業務', 'code': 'sales', 'group_xmlids': 'base.group_user'})
        self.sc = self.env['corpaas.knowledge.scenario'].sudo().create({
            'name': '資料包情境', 'code': 'kbt_pack_sc', 'narrative': 'n',
            'role_ids': [(6, 0, self.role.ids)],
            'pack_ids': [(6, 0, self.sales.ids)],
            'seed_json': _seed({'xmlid': 'x1', 'model': 'res.partner',
                                'values': {'name': '情境自己的', 'parent_id': '__ref__:x0'}})})

    def test_qualify_refs(self):
        rec = qualify_seed_record(
            {'xmlid': 'a', 'model': 'm', 'values': {'p': '__ref__:b', 'q': '__ref__:base.x',
                                                    'u': '__ref__:user_sales',
                                                    'm': ['__ref__:b', '__ref__:c.d']}},
            '__doc_pack_p', '__doc_scenario_s', {'user_sales'})
        self.assertEqual(rec['xmlid'], '__doc_pack_p.a')
        self.assertEqual(rec['values']['p'], '__ref__:__doc_pack_p.b')
        self.assertEqual(rec['values']['q'], '__ref__:base.x')
        self.assertEqual(rec['values']['u'], '__ref__:__doc_scenario_s.user_sales',
                         '角色帳號建在情境的命名空間')
        self.assertEqual(rec['values']['m'], ['__ref__:__doc_pack_p.b', '__ref__:c.d'])
        call = qualify_seed_record({'xmlid': 'k', 'model': 'm', 'call': 'action_x', 'ref': 'b'},
                                   '__doc_pack_p', '__doc_scenario_s')
        self.assertEqual(call['ref'], '__doc_pack_p.b')

    def test_draft_order_dependencies_first(self):
        keys = [r['xmlid'] for r in self.sc.live_seed(draft=True)]
        self.assertEqual(keys, ['__doc_pack_kbt_contacts.c1', '__doc_pack_kbt_sales.s1',
                                '__doc_scenario_kbt_pack_sc.x1'],
                         '依賴的資料包先重播，即使 sequence 比較大')
        own = self.sc.live_seed(draft=True)[-1]
        self.assertEqual(own['values']['parent_id'], '__ref__:__doc_scenario_kbt_pack_sc.x0')

    def test_live_seed_needs_approved_packs_and_published_selection(self):
        with patch.object(type(self.sc), '_enqueue_seed_check', lambda s, **kw: False):
            self.sc._do_publish('new')
        with self.assertRaises(UserError, msg='資料包沒核准不能拿來拍'):
            self.sc.live_seed()
        self.contacts._do_publish('new')
        self.sales._do_publish('new')
        self.assertEqual(len(self.sc.live_seed()), 3)
        # 情境改選資料包、還沒核准：上線版仍用舊的組合
        other = self.Pack.create({'name': '庫存', 'code': 'kbt_stock',
                                  'seed_json': _seed({'xmlid': 'w', 'model': 'res.partner',
                                                      'values': {'name': 'w'}})})
        other._do_publish('new')
        self.sc.sudo().pack_ids = [(4, other.id)]
        self.assertEqual(len(self.sc.live_seed()), 3)
        self.assertEqual(len(self.sc.live_seed(draft=True)), 4)

    def test_seed_revisions_include_packs(self):
        with patch.object(type(self.sc), '_enqueue_seed_check', lambda s, **kw: False):
            self.sc._do_publish('new')
        self.sales._do_publish('new')   # 依賴關係也用上線版：銷售包上線才帶出聯絡人包
        revs = self.sc.seed_revisions()
        self.assertEqual([r[0] for r in revs], ['corpaas.knowledge.seed_pack'] * 2
                         + ['corpaas.knowledge.scenario'])

    def test_pack_cycle_detected(self):
        self.contacts.depend_ids = [(6, 0, self.sales.ids)]
        with self.assertRaises(UserError):
            self.sc.live_seed(draft=True)

    def test_bad_pack_json_rejected(self):
        with self.assertRaises(UserError):
            self.Pack.create({'name': 'x', 'code': 'kbt_bad', 'seed_json': '{"a": 1}'})


@tagged('post_install', '-at_install')
class TestSeedCheck(_RefreshBase):

    def setUp(self):
        super().setUp()
        self.sc = self.env['corpaas.knowledge.scenario'].sudo().create({
            'name': '重播檢查', 'code': 'kbt_check', 'narrative': 'n',
            'package_ids': [(6, 0, self.pkg.ids)],
            'seed_json': _seed({'xmlid': 'p', 'model': 'res.partner', 'values': {'name': 'A'}})})

    def test_submit_with_seed_change_enqueues_check(self):
        self.sc._do_publish('new')
        self.sc.seed_json = _seed(
            {'xmlid': 'p', 'model': 'res.partner', 'values': {'name': 'B'}})
        self.sc.state = 'draft'
        self.sc.action_submit()
        q = self.env['corpaas.queue'].sudo().search(
            [('operate', '=', 'knowledge_sandbox')], order='id desc', limit=1)
        self.assertTrue(q, '改了示範資料送審：排一張重播檢查')
        self.assertIn("'op': 'check'", q.params)
        self.assertEqual(self.sc.seed_check_state, 'queued')

    def test_text_only_change_does_not_check(self):
        self.sc._do_publish('new')
        self.sc.narrative = '只改敘事'
        self.sc.state = 'draft'
        self.sc.action_submit()
        self.assertFalse(self.sc.seed_check_state)

    def test_run_seed_check_reports_empty_screens(self):
        Sandbox = self.env['corpaas.knowledge.sandbox'].sudo()
        Pkg = type(self.pkg)
        dropped = []
        master = make_database(self.env, 9471).instance_id
        items = [['k.partners', 'base.action_partner_form'],
                 ['k.none', 'base.action_res_users'], ['k.gone', 'nope.not_there']]
        with patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: master), \
                patch.object(type(Sandbox), 'rebuild',
                             lambda s, seed=None: {'errors': [{'xmlid': 'p', 'model': 'res.partner',
                                                               'error': 'boom'}]}), \
                patch.object(type(Sandbox), 'drop', lambda s: dropped.append(s.db_name)), \
                patch.object(type(Sandbox), '_shell',
                             lambda s, script: self._exec_shell(None, None, None, script)), \
                patch.object(Pkg, '_knowledge_probe_items',
                             lambda s: (items, {'k.partners': '聯絡人', 'k.none': '使用者',
                                                'k.gone': '不存在'})), \
                patch.object(type(self.env['res.users']), 'search_count',
                             lambda s, dom, **kw: 0):
            state = Sandbox.run_seed_check(self.pkg, self.sc)
        self.assertEqual(state, 'issues')
        self.assertEqual(dropped, [Sandbox.make_name(self.pkg, self.sc) + '-chk'],
                         '檢查完一定刪掉臨時庫')
        report = json.loads(self.sc.seed_check_report)
        self.assertNotIn('k.gone', report['counts'], '動作不存在的略過')
        self.assertGreater(report['counts']['k.partners'], 0)
        self.assertEqual(report['counts']['k.none'], 0)
        html = self.sc.seed_check_html
        self.assertIn('使用者', html)
        self.assertIn('boom', html)
        chk = Sandbox.search([('db_name', 'like', '-chk')])
        self.assertTrue(chk.is_check)
        self.assertNotIn(chk, self.pkg.knowledge_sandbox_ids, '方案的說明庫清單不列臨時庫')

    def test_probe_script_compiles(self):
        compile(scripts.data_probe_script([['a', 'b.c']]), '<probe>', 'exec')


@tagged('post_install', '-at_install')
class TestOverlay(TransactionCase):

    def _sb(self, applied):
        Sandbox = self.env['corpaas.knowledge.sandbox']
        return Sandbox.new({'state': 'ready', 'ready_at': '2026-10-05 00:00:00',
                            'base_sig': 'B', 'dirty': False,
                            'seed_applied': json.dumps(Sandbox._seed_hashes(applied))})

    def _delta(self, sb, seed, base='B'):
        S = type(sb)
        with patch.object(S, '_base_signature', lambda s: base), \
                patch.object(type(self.env['corpaas.knowledge.scenario']), 'live_seed',
                             lambda s, draft=False: seed):
            return sb._overlay_delta()

    def test_additions_only_overlay(self):
        a = {'xmlid': 'm.a', 'model': 'res.partner', 'values': {'name': 'A'}}
        b = {'xmlid': 'm.b', 'model': 'res.partner', 'values': {'name': 'B'}}
        confirm = {'xmlid': 'm.c', 'model': 'sale.order', 'call': 'action_confirm', 'ref': 'm.b'}
        sb = self._sb([a])
        self.assertEqual(self._delta(sb, [a, b, confirm]), [b, confirm],
                         '新增記錄與新的動作只做一次')
        self.assertEqual(self._delta(sb, [a]), [], '沒有新增：空的疊加')

    def test_change_or_delete_rebuilds(self):
        a = {'xmlid': 'm.a', 'model': 'res.partner', 'values': {'name': 'A'}}
        sb = self._sb([a])
        self.assertIsNone(self._delta(sb, [dict(a, values={'name': 'A2'})]), '改既有記錄要重建')
        self.assertIsNone(self._delta(sb, []), '刪記錄要重建')
        self.assertIsNone(self._delta(sb, [a], base='X'), '黃金庫／程式／角色變了要重建')
        sb.dirty = True
        self.assertIsNone(self._delta(sb, [a]), '被拍攝改過一定重建')


@tagged('post_install', '-at_install')
class TestDataSource(TransactionCase):

    def test_default_and_purge_rule(self):
        tmpl = self.env['product.template'].create({'name': 'DS', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].sudo().create(
            {'product_tmpl_id': tmpl.id})
        Version = self.env['infrastructure.template.version'].sudo()
        blank = Version.create({'package_id': pkg.id, 'version_no': 91, 'include_db': False})
        full = Version.create({'package_id': pkg.id, 'version_no': 92, 'include_db': True})
        self.assertEqual(blank.knowledge_data_source, 'blank')
        self.assertEqual(full.knowledge_data_source, 'customer', '推不出來一律當客戶庫')
        Db = self.env['infrastructure.database']
        self.assertTrue(Db.new({'template_version_id': full.id})._knowledge_needs_purge())
        self.assertFalse(Db.new({'template_version_id': blank.id})._knowledge_needs_purge())
        full.knowledge_data_source = 'demo'
        self.assertFalse(Db.new({'template_version_id': full.id})._knowledge_needs_purge())
        self.assertTrue(Db.new({})._knowledge_needs_purge(), '沒有範本版本：嚴格清除')

    def test_skipped_purge_skips_gate(self):
        sb = self.env['corpaas.knowledge.sandbox'].new({'purge_skipped': True})
        self.assertEqual(sb.gate_bad_records({'res.partner': [1]}), [])


@tagged('post_install', '-at_install')
class TestCostPlanner(TransactionCase):

    def setUp(self):
        super().setUp()
        tmpl = self.env['product.template'].create({'name': 'COST', 'type': 'service'})
        self.pkg = self.env['infrastructure.solution.package'].sudo().create(
            {'product_tmpl_id': tmpl.id})
        self.Ai = self.env['corpaas.knowledge.ai']
        self.env['ir.config_parameter'].sudo().set_param(
            'corpaas_knowledge.budget_usd_per_refresh', '1.0')

    def _lines(self, s, full=False):
        return [{'key': 'fixed', 'label': 'f', 'count': 1, 'purposes': ['classify_features'],
                 'deferrable': False},
                {'key': 'draft', 'label': 'd', 'count': 10,
                 'purposes': ['manual_step_block', 'manual_scenario'], 'deferrable': True}]

    def test_plan_uses_smaller_of_budget_and_hub_left(self):
        from ..services import hub_client
        Pkg = type(self.pkg)
        with patch.object(Pkg, '_knowledge_cost_lines', self._lines):
            plan = self.pkg._knowledge_cost_plan()
            # 單價：歸類 0.25；起草 0.05+0.06=0.11 → 預算 1.0 扣 0.25 剩 0.75 → 6 篇
            draft = plan['lines'][1]
            self.assertEqual(draft['fit'], 6)
            self.assertEqual(plan['deferred'], 4)
            self.assertIsNone(plan['hub_left'])
            hub_client.LAST_QUOTA.clear()
            hub_client.LAST_QUOTA.update(cost_left=0.5)
            self.env['corpaas.knowledge.ai.call'].sudo().create(
                dict(self.Ai._quota_vals(), purpose='select', ok=True))
            self.assertFalse(hub_client.LAST_QUOTA, '取走即清')
            plan = self.pkg._knowledge_cost_plan()
            self.assertEqual(plan['allowed'], 0.5, 'Hub 今日剩餘比單次預算小：以它為準')
            self.assertEqual(plan['lines'][1]['fit'], 2)
            self.pkg.action_knowledge_cost_plan()
            self.assertIn('留到隔天', self.pkg.knowledge_cost_plan_html)

    def test_hub_left_expires_next_day(self):
        call = self.env['corpaas.knowledge.ai.call'].sudo().create(
            {'purpose': 'select', 'ok': True, 'hub_cost_known': True, 'hub_cost_left': 0})
        self.env.cr.execute("UPDATE corpaas_knowledge_ai_call SET create_date = '2000-01-01' "
                            "WHERE id = %s", (call.id,))
        call.invalidate_recordset()
        self.assertIsNone(self.Ai.hub_cost_left(), '昨天的剩餘額度不算數')

    def test_hub_exhausted_stops_before_calling(self):
        from ..services import hub_client
        self.env['corpaas.knowledge.ai.call'].sudo().create(
            {'purpose': 'select', 'ok': True, 'hub_cost_known': True, 'hub_cost_left': 0})
        with patch.object(hub_client, 'call', side_effect=AssertionError('不該呼叫')):
            with self.assertRaises(hub_client.BudgetExceeded):
                self.Ai.ask('select', 'x', package=self.pkg)

    def test_hub_quota_refusal_is_budget_not_failure(self):
        from ..services import hub_client
        with patch.object(hub_client, '_rpc', lambda url, key, params, timeout=60: {
                'ok': False, 'error': 'cost_exceeded', 'detail': '今日用量已達上限'}):
            with self.assertRaises(hub_client.BudgetExceeded):
                hub_client.call('https://hub', 'k', 'p', 'x')

    def test_unit_cost_from_history(self):
        Call = self.env['corpaas.knowledge.ai.call'].sudo()
        for c in (0.2, 0.4):
            Call.create({'purpose': 'select', 'ok': True, 'cost_usd': c})
        Call.create({'purpose': 'select', 'ok': True, 'cost_usd': 0, 'cached': True})
        self.assertAlmostEqual(self.Ai.unit_cost('select'), 0.3)
        self.assertEqual(self.Ai.unit_cost('never_used'), 0.1)

    def test_minutes_until_tomorrow_2am_taipei(self):
        from datetime import datetime
        Pkg = type(self.pkg)
        # 台北 10/5 23:00（UTC 15:00）→ 明天 02:00 還有 180 分鐘
        self.assertEqual(Pkg._knowledge_minutes_until_tomorrow(datetime(2026, 10, 5, 15, 0)), 180)
        # 台北 10/6 01:00（UTC 10/5 17:00）→ 隔天（10/7）02:00
        self.assertEqual(Pkg._knowledge_minutes_until_tomorrow(datetime(2026, 10, 5, 17, 0)),
                         25 * 60)

    def test_carry_over_enqueues_tomorrow(self):
        Pkg = type(self.pkg)
        run = self.env['corpaas.knowledge.run'].sudo().create(
            {'package_id': self.pkg.id, 'token': 'tok-carry'})
        calls = []
        with patch.object(Pkg, '_knowledge_cost_lines', self._lines), \
                patch.object(Pkg, '_knowledge_budget_exhausted', lambda s, t: True), \
                patch.object(Pkg, 'knowledge_enqueue_refresh',
                             lambda s, **kw: calls.append(kw)):
            self.assertTrue(self.pkg._knowledge_carry_over(run))
        self.assertEqual(calls[0]['reason'], 'budget_carryover')
        self.assertFalse(calls[0]['full'])
        self.assertGreater(calls[0]['delay_minutes'], 0)
        self.assertEqual(run.stats()['carried_over'], 10)
        with patch.object(Pkg, '_knowledge_budget_exhausted', lambda s, t: False):
            self.assertFalse(self.pkg._knowledge_carry_over(run), '預算沒用完不排')
