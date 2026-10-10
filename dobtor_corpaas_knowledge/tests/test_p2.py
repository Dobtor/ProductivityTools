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
        self.role = self.env.ref('dobtor_corpaas_knowledge.role_sales')   # 角色範本
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
        self.assertIn("'rev': %s" % self.sc.rev_no, q.params, '帶修訂號：修正後的再檢查不會被去重吃掉')
        self.assertEqual(self.sc.seed_check_state, 'queued')

    def test_prune_failed_records_with_dependents(self):
        self.sc.seed_json = _seed(
            {'xmlid': 'p', 'model': 'res.partner', 'values': {'name': 'A'}},
            {'xmlid': 'bad', 'model': 'stock.picking', 'values': {'partner_id': '__ref__:p'}},
            {'xmlid': 'bad_line', 'model': 'stock.move', 'values': {'picking_id': '__ref__:bad'}},
            {'xmlid': 'bad_confirm', 'model': 'stock.picking', 'call': 'action_confirm',
             'target': 'bad'})
        self.sc._do_publish('new')
        n = self.sc._prune_failed_seed({'errors': [
            {'xmlid': '%s.bad' % self.sc.xml_module, 'error': 'x'},
            {'xmlid': 'doc_pack_x.other', 'error': '資料包的錯不歸我'}]})
        self.assertEqual(n, 3, '出錯的記錄連同參照它、對它動作的記錄一起拿掉')
        self.assertEqual([r['xmlid'] for r in json.loads(self.sc.seed_json)], ['p'])

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

    def test_check_errors_trigger_one_ai_repair(self):
        Sandbox = self.env['corpaas.knowledge.sandbox'].sudo()
        Sc = type(self.sc)
        Pkg = type(self.pkg)
        master = make_database(self.env, 9472).instance_id
        repairs, prompts = [], []
        Ai = type(self.env['corpaas.knowledge.ai'])

        def ask(s, purpose, prompt, **kw):
            prompts.append((purpose, prompt))
            return {'seed': [{'xmlid': 'p', 'model': 'res.partner', 'values': {'name': '修好'}}]}

        with patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: master), \
                patch.object(type(Sandbox), 'rebuild', lambda s, seed=None: {'errors': [
                    {'xmlid': '__doc_scenario_kbt_check.p', 'model': 'res.partner',
                     'error': 'duplicate key'}]}), \
                patch.object(type(Sandbox), 'drop', lambda s: None), \
                patch.object(type(Sandbox), '_shell', lambda s, script: {}), \
                patch.object(Pkg, '_knowledge_probe_items', lambda s: ([], {})), \
                patch.object(Ai, 'ask', ask), \
                patch.object(Sc, '_enqueue_seed_check', lambda s, **kw: repairs.append(s.id)):
            Sandbox.run_seed_check(self.pkg, self.sc)
            self.assertEqual(self.sc.seed_auto_repairs, 1)
            self.assertIn('修好', self.sc.seed_json)
            self.assertEqual(prompts[0][0], 'seed_repair')
            self.assertIn('duplicate key', prompts[0][1])
            self.assertIn('不要同一個產品再建 product.template', prompts[0][1])
            self.assertEqual(repairs, [self.sc.id], '修完送審會再檢查一次')
            Sandbox.run_seed_check(self.pkg, self.sc)
            self.assertEqual(self.sc.seed_auto_repairs, 2)
            Sandbox.run_seed_check(self.pkg, self.sc)
            self.assertEqual(len(prompts), 2, '最多自動修兩次')

    def test_role_groups_read_from_golden(self):
        """角色可用群組讀黃金庫的應用群組（實機功能點都沒記群組，AI 只拿到 base.group_user）。"""
        from ..services import remote
        Pkg = type(self.pkg)
        with patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: self.master), \
                patch.object(remote, 'shell_json', side_effect=self._exec_shell):
            groups = self.pkg._knowledge_role_groups([('id', '=', 0)])
        self.assertTrue(any(g.startswith('base.group_system｜') for g in groups))
        self.assertTrue(all('｜' in g for g in groups))

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


@tagged('post_install', '-at_install')
class TestProposalReview(TransactionCase):

    def test_capability_proposal_lists_its_features(self):
        tmpl = self.env['product.template'].create({'name': 'REV', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].sudo().create(
            {'product_tmpl_id': tmpl.id})
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        feats = Feature.browse([Feature.create({
            'feature_key': 'kbrev.action:x%s' % i, 'module': 'kbrev', 'kind': 'action',
            'anchor': 'x%s' % i, 'name': '畫面 %s' % i}).id for i in range(3)])
        sel = self.env['corpaas.knowledge.selection'].sudo().create({
            'package_id': pkg.id, 'kind': 'capability',
            'proposal_json': json.dumps({'new_capability': '銷售', 'outcome': '賣得更快',
                                         'features': feats.mapped('feature_key') + ['gone']})})
        self.assertEqual(sel.proposal_feature_ids, feats, '已不存在的鍵略過')
        self.assertEqual(sel.proposal_feature_count, 3)
        self.assertEqual(sel.proposal_outcome, '賣得更快')
        action = self.env.ref('dobtor_corpaas_knowledge.action_kb_selection')
        self.assertIn('search_default_kind_capability', action.context)


@tagged('post_install', '-at_install')
class TestAutoChain(TransactionCase):
    """核准後自動接續：情境提案 → AI 起草示範資料；示範資料核准 → 全量更新。"""

    def setUp(self):
        super().setUp()
        tmpl = self.env['product.template'].create({'name': 'CHAIN', 'type': 'service'})
        self.pkg = self.env['infrastructure.solution.package'].sudo().create(
            {'product_tmpl_id': tmpl.id, 'knowledge_enabled': True})
        self.approver = self.env['res.users'].create({
            'name': 'kb chain approver', 'login': 'kb_chain_approver',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('dobtor_corpaas_knowledge.group_knowledge_approver').id])]})

    def test_scenario_proposal_approval_drafts_seed(self):
        Sc = type(self.env['corpaas.knowledge.scenario'])
        drafted = []
        sel = self.env['corpaas.knowledge.selection'].sudo().create({
            'package_id': self.pkg.id, 'kind': 'scenario',
            'proposal_json': json.dumps({'name': '晨光', 'code': 'kbt_chain',
                                         'roles': [{'code': 'sales', 'name': '業務',
                                                    'groups': ['sales_team.group_sale_salesman']}]})})
        with patch.object(Sc, 'action_ai_draft_seed', lambda s: drafted.append(s.code)):
            sel._knowledge_approve()
        self.assertEqual(drafted, ['kbt_chain'])

    def test_failed_auto_draft_does_not_block_approval(self):
        Sc = type(self.env['corpaas.knowledge.scenario'])
        sel = self.env['corpaas.knowledge.selection'].sudo().create({
            'package_id': self.pkg.id, 'kind': 'scenario',
            'proposal_json': json.dumps({'name': '晨光2', 'code': 'kbt_chain2'})})

        def boom(s):
            raise UserError('母體沒有黃金庫')
        with patch.object(Sc, 'action_ai_draft_seed', boom):
            sel._knowledge_approve()
        self.assertEqual(sel.state, 'approved')
        self.assertTrue(sel.scenario_id)

    def test_seed_approval_enqueues_full_refresh_once(self):
        Pkg = type(self.pkg)
        Sc = type(self.env['corpaas.knowledge.scenario'])
        calls = []
        sc = self.env['corpaas.knowledge.scenario'].sudo().create({
            'name': '晨光3', 'code': 'kbt_chain3', 'narrative': 'n',
            'package_ids': [(6, 0, self.pkg.ids)],
            'seed_json': _seed({'xmlid': 'p', 'model': 'res.partner', 'values': {'name': 'A'}})})
        with patch.object(Sc, '_enqueue_seed_check', lambda s, **kw: False), \
                patch.object(Pkg, 'knowledge_enqueue_refresh',
                             lambda s, **kw: calls.append((s.ids, kw))):
            sc.knowledge_propose('new')
            self.assertEqual(sc.state, 'review')
            sc.with_user(self.approver).action_approve()
            self.assertEqual(calls, [([self.pkg.id], {'full': True, 'reason': 'seed_approved'})])
            # 只改敘事再核准：不排更新
            sc.narrative = '改敘事'
            sc.knowledge_propose('new')
            sc.with_user(self.approver).action_approve()
            self.assertEqual(len(calls), 1)


@tagged('post_install', '-at_install')
class TestGeneralization(TransactionCase):
    """通用化：結構化契約＋重問、資料包組裝示範資料、方案設定檔驅動的上限。"""

    def setUp(self):
        super().setUp()
        tmpl = self.env['product.template'].create({'name': 'GEN', 'type': 'service'})
        self.pkg = self.env['infrastructure.solution.package'].sudo().create(
            {'product_tmpl_id': tmpl.id})
        self.Ai = type(self.env['corpaas.knowledge.ai'])

    def test_seed_contract(self):
        from ..models.catalog import seed_contract_errors
        self.assertEqual(seed_contract_errors([
            {'xmlid': 'a', 'model': 'res.partner', 'values': {'name': 'x'}},
            {'xmlid': 'c', 'model': 'sale.order', 'call': 'action_confirm', 'ref': 'so'}]), [])
        errs = seed_contract_errors([
            {'xmlid': 'p', 'model': 'product.template', 'values': {}},
            {'xmlid': 's', 'model': 'sale.order', 'values': {'state': 'sale'}},
            {'xmlid': 'k', 'call': 'unlink', 'ref': 'x'}, {'model': 'res.partner'}])
        self.assertEqual(len(errs), 4)

    def test_ask_checked_retries_once_with_errors(self):
        prompts = []
        with patch.object(self.Ai, 'ask', lambda s, p, prompt, **kw: prompts.append(prompt) or {'n': 1}):
            data, errs = self.env['corpaas.knowledge.ai'].ask_checked(
                'x', 'Q', lambda d: ['n 要是 2'] if d.get('n') != 2 else [])
        self.assertEqual(len(prompts), 2)
        self.assertIn('n 要是 2', prompts[1])
        self.assertEqual(errs, ['n 要是 2'])

    def test_compose_seed_from_packs(self):
        Pack = self.env['corpaas.knowledge.seed_pack'].sudo()
        contacts = Pack.create({'name': '聯絡人', 'code': 'kbg_contacts', 'seed_json': _seed(
            {'xmlid': 'c1', 'model': 'res.partner', 'values': {'name': '客戶甲'}})})
        contacts._do_publish('new')
        Pack.create({'name': '未核准', 'code': 'kbg_draft', 'seed_json': '[]'})
        sc = self.env['corpaas.knowledge.scenario'].sudo().create({
            'name': '晴天', 'code': 'kbg_sc', 'package_ids': [(6, 0, self.pkg.ids)]})
        reply = {'packs': ['kbg_contacts', 'nope'], 'company': '晴天貿易', 'warehouse': '主倉',
                 'narrative': '晴天貿易是一家小型批發商，主要客戶是客戶甲，從報價、出貨到收款都在同一套系統完成。',
                 'seed': [{'xmlid': 'x1', 'model': 'res.partner',
                           'values': {'parent_id': '__ref__:__doc_pack_kbg_contacts.c1'}},
                          {'xmlid': 'bad', 'model': 'product.template', 'values': {}}]}
        prompts = []
        Sc = type(sc)
        with patch.object(self.Ai, 'ask', lambda s, p, prompt, **kw: prompts.append(prompt) or reply), \
                patch.object(type(self.pkg), '_knowledge_probe_items', lambda s: ([], {})), \
                patch.object(Sc, '_enqueue_seed_check', lambda s, **kw: False):
            sc._ai_draft_seed_run()
        self.assertIn('kbg_contacts', prompts[0])
        self.assertNotIn('kbg_draft', prompts[0], '只給已核准的資料包')
        self.assertEqual(len(prompts), 2, '契約不符重問一次')
        self.assertEqual(sc.pack_ids.mapped('code'), ['kbg_contacts'])
        seed = json.loads(sc.seed_json)
        self.assertEqual([r['xmlid'] for r in seed], ['base.main_company', 'stock.warehouse0', 'x1'],
                         '公司與倉庫改名＋補缺口；不合契約的記錄丟掉')
        self.assertEqual(seed[0]['values']['name'], '晴天貿易')
        self.assertIn('客戶甲', prompts[0], '資料包裡的客戶與產品名稱給 AI 寫敘事')
        self.assertIn('客戶甲', sc.narrative, '敘事依實際資料重寫')
        self.assertEqual(sc.state, 'review')

    def test_select_respects_profile_limits(self):
        self.pkg.knowledge_max_scenarios = 1
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        Feature.create({'feature_key': 'kbg.action:a', 'module': 'kbg', 'kind': 'action',
                        'anchor': 'a', 'name': 'a', 'package_ids': [(4, self.pkg.id)],
                        'group_xmlids': 'sales_team.group_sale_manager'})
        reply = {'scenarios': [
            {'new': {'name': '甲公司', 'code': 'kbg_a', 'roles': [
                {'code': 'sales', 'name': '業務', 'groups': ['sales_team.group_sale_manager']}]},
             'score': 1},
            {'new': {'name': '乙公司', 'code': 'kbg_b'}, 'score': 9}]}
        prompts = []
        with patch.object(self.Ai, 'ask', lambda s, p, prompt, **kw: prompts.append(prompt) or reply), \
                patch.object(type(self.pkg), '_knowledge_master',
                             lambda s, raise_if_missing=True: True):
            self.pkg._knowledge_ai_select_run()
        self.assertEqual(len(prompts), 2)
        self.assertIn('情境最多 1 個', prompts[1])
        self.assertIn('不可用管理員等級群組', prompts[1])
        self.assertIn('既有角色範本', prompts[0])
        self.assertIn('不要寫具體的公司名、人名、產品名', prompts[0])
        props = self.env['corpaas.knowledge.selection'].search(
            [('package_id', '=', self.pkg.id), ('kind', '=', 'scenario')])
        self.assertEqual(props.mapped('proposal_name'), ['乙公司'], '超過上限照分數留')

    def test_import_bundled_packs(self):
        Pack = self.env['corpaas.knowledge.seed_pack']
        out = Pack.import_bundle()
        self.assertEqual(set(out.values()), {'新建'})
        packs = Pack.search([('code', 'in', list(out))])
        self.assertEqual(len(packs), 6)
        self.assertEqual(set(packs.mapped('state')), {'published'}, '資料包自動核准上線')
        sales = packs.filtered(lambda p: p.code == 'sales_flow')
        self.assertEqual(sorted(sales.depend_ids.mapped('code')), ['contacts', 'products'])
        self.assertEqual(set(Pack.import_bundle().values()), {'相同'}, '再載一次不重複')
        with self.assertRaises(UserError):
            Pack.import_bundle('../etc')

    def test_profile_validation(self):
        with self.assertRaises(Exception):
            self.pkg.write({'knowledge_cap_min': 8, 'knowledge_cap_max': 4})
        self.assertEqual(self.pkg._knowledge_profile()['max_scenarios'], 1)


@tagged('post_install', '-at_install')
class TestIterativeCore(_RefreshBase):
    """迭代式架構：缺口、收斂迴圈、可取消、重啟續跑、平行預取、只補缺口的示範資料。"""

    def test_gap_lifecycle(self):
        Gap = self.env['corpaas.knowledge.gap_item']
        g = Gap.note(self.pkg, 'access', '進不去')
        self.assertEqual(Gap.note(self.pkg, 'access', '還是進不去'), g, '同對象同類型不重複')
        g.attempted('rule_role', 'x')
        g.attempted('rule_role', 'y')
        self.assertEqual(g.state, 'open')
        g.attempted('rule_role', 'z')
        self.assertEqual(g.state, 'human', '修到上限轉人工')
        g.action_reopen()
        self.assertEqual((g.state, g.attempts), ('open', 0))
        g.resolve('好了')
        self.assertEqual(g.state, 'resolved')

    def test_iterate_enqueues_until_daily_cap(self):
        Pkg = type(self.pkg)
        run = self.env['corpaas.knowledge.run'].sudo().create(
            {'package_id': self.pkg.id, 'token': 'tok-it'})
        calls = []
        with patch.object(Pkg, 'knowledge_enqueue_refresh', lambda s, **kw: calls.append(kw)):
            self.assertFalse(self.pkg._knowledge_iterate(run), '沒有缺口不排')
            self.env['corpaas.knowledge.gap_item'].note(self.pkg, 'data', '空白')
            self.assertTrue(self.pkg._knowledge_iterate(run))
            self.assertEqual(calls[-1], {'full': False, 'reason': 'gap_fix'})
            self.pkg.knowledge_max_iterations = 1
            self.assertFalse(self.pkg._knowledge_iterate(run), '今天已達輪數上限')

    def test_cancel_and_resume(self):
        from odoo.exceptions import UserError
        Pkg = type(self.pkg)
        run = self.env['corpaas.knowledge.run'].sudo().create(
            {'package_id': self.pkg.id, 'token': 'tok-cr'})
        run.begin_stage('shoot')
        run.check_cancel()
        run.action_cancel()
        with self.assertRaises(UserError):
            run.check_cancel()
        run2 = self.env['corpaas.knowledge.run'].sudo().create(
            {'package_id': self.pkg.id, 'token': 'tok-cr2'})
        run2.begin_stage('outlets')
        self.env.flush_all()
        self.env.cr.execute("UPDATE corpaas_knowledge_run SET write_date = (now() at time zone 'UTC') - interval '1 hour' "
                            "WHERE id = %s", (run2.id,))
        run2.invalidate_recordset()
        staged = []
        with patch.object(Pkg, '_knowledge_enqueue_stage', lambda s, r, stage: staged.append(stage)):
            self.env['corpaas.knowledge.run']._cron_resume_orphans()
        self.assertIn('outlets', staged, '重啟後從中斷的階段續跑')
        self.assertEqual(run2.resumes, 1)

    def test_prefetch_parallel_then_ask_uses_it(self):
        from ..services import hub_client
        Ai = self.env['corpaas.knowledge.ai'].with_context(kb_prefetch_in_tests=True)
        sent = []

        def call(url, key, purpose, prompt, context=None, **kw):
            sent.append(purpose)
            return '{"ok": "%s"}' % purpose, 0.01, 1

        with patch.object(hub_client, 'call', call):
            n = Ai.prefetch([('p1', 'A'), ('p2', 'B')], package=self.pkg)
            self.assertEqual(n, 2)
            self.assertEqual(Ai.ask('p1', 'A', package=self.pkg), {'ok': 'p1'})
        self.assertEqual(sorted(sent), ['p1', 'p2'], 'ask 用預取結果，不再呼叫')

    def test_prefetch_key_matches_ask_with_profile(self):
        """方案檔案前綴的用途：預先問的鍵要跟 ask 一致，不能同一題付兩次。"""
        from ..services import hub_client
        Ai = self.env['corpaas.knowledge.ai'].with_context(kb_prefetch_in_tests=True)
        Pkg = type(self.pkg)
        sent = []

        def call(url, key, purpose, prompt, context=None, **kw):
            sent.append(prompt)
            return '{"ok": 1}', 0.01, 1

        with patch.object(hub_client, 'call', call), \
                patch.object(Pkg, '_knowledge_profile_text', lambda s: '方案檔案：有網站'):
            Ai.prefetch([('manual_repair', 'A')], package=self.pkg)
            self.assertEqual(Ai.ask('manual_repair', 'A', package=self.pkg), {'ok': 1})
        self.assertEqual(len(sent), 1, 'ask 拿到預先問的結果')
        self.assertIn('方案檔案：有網站', sent[0])

    def test_static_part_sent_as_system_when_enabled(self):
        from ..services import hub_client
        Ai = self.env['corpaas.knowledge.ai']
        seen = []

        def call(url, key, purpose, prompt, context=None, system=None, **kw):
            seen.append((prompt, system))
            return '{"ok": 1}', 0.01, 1

        icp = self.env['ir.config_parameter'].sudo()
        with patch.object(hub_client, 'call', call):
            Ai.ask('manual_bind', '變動', static='固定清單')
            icp.set_param('corpaas_knowledge.hub_system_prompt', '1')
            Ai.ask('manual_bind', '變動', static='固定清單')
        (p0, s0), (p1, s1) = seen
        self.assertIsNone(s0)
        self.assertTrue(p0.endswith('固定清單\n\n變動'), '沒開：固定內容併在前面，內容一樣')
        self.assertEqual(p1, '變動', '開了：只送變動的部分')
        self.assertIn('固定清單', s1)

    def test_hub_without_system_support_is_refused(self):
        from ..services import hub_client
        with patch.object(hub_client, '_rpc', return_value={'ok': True, 'run_id': 1}):
            with self.assertRaises(hub_client.HubError):
                hub_client.call('http://hub', 'k', 'p', 'x', system='固定')

    def test_fill_gaps_only_adds(self):
        sc = self.env['corpaas.knowledge.scenario'].sudo().create({
            'name': '補缺口', 'code': 'kbt_fill', 'narrative': 'n',
            'package_ids': [(6, 0, self.pkg.ids)],
            'seed_json': _seed({'xmlid': 'p', 'model': 'res.partner', 'values': {'name': 'A'}})})
        Sc = type(sc)
        with patch.object(Sc, '_enqueue_seed_check', lambda s, **kw: False):
            sc._do_publish('new')
        feature = self.env['corpaas.knowledge.feature'].sudo().create({
            'feature_key': 'kbt.action:fill', 'module': 'kbt', 'kind': 'action',
            'anchor': 'fill', 'name': '追加銷售', 'model': 'res.partner'})
        reply = {'seed': [{'xmlid': 'p', 'model': 'res.partner', 'values': {'name': '改'}},
                          {'xmlid': 'q', 'model': 'res.partner', 'values': {'name': 'B'}}]}
        prompts = []
        with patch.object(type(self.env['corpaas.knowledge.ai']), 'ask',
                          lambda s, p, prompt, **kw: prompts.append(prompt) or reply), \
                patch.object(Sc, '_enqueue_seed_check', lambda s, **kw: False):
            added = sc._ai_fill_gaps(self.pkg, feature)
        self.assertEqual(added, 1, '已存在的 xmlid 丟掉，只新增')
        self.assertIn('只能新增不能改', prompts[1])
        keys = [r['xmlid'] for r in json.loads(sc.seed_json)]
        self.assertEqual(keys, ['p', 'q'])
        self.assertEqual(json.loads(sc.seed_json)[0]['values']['name'], 'A')
        self.assertEqual(sc.state, 'published', '單一方案的情境：補資料自動上線')

    def test_screen_access_script(self):
        res = self._exec_shell(None, None, None, scripts.screen_access_script(
            ['base.action_res_users', 'nope.x'],
            {'admin': ['base.group_system'], 'plain': ['base.group_user']}))
        self.assertIn('admin', res['base.action_res_users'])
        self.assertNotIn('plain', res['base.action_res_users'], '使用者清單要設定權限')
        self.assertNotIn('nope.x', res)
