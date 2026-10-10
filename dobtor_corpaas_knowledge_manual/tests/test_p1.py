# -*- coding: utf-8 -*-
"""P1：規則產生截圖腳本（A2）、未變畫面沿用截圖（R4）、截圖未就緒不能核准（D2）。"""
import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from ..services import rule_scripts
from .common import ManualCase
from .test_hooks import FakeSandbox


@tagged('post_install', '-at_install')
class TestRuleScripts(ManualCase):

    def test_list_view_opens_record_and_tabs(self):
        entry = {'view_type': 'list', 'columns': [
            {'name': 'name', 'label': '名稱'}, {'name': 'email', 'label': 'Email'},
            {'name': 'x', 'label': ''}, {'name': 'phone', 'label': '電話'},
            {'name': 'city', 'label': '城市'}]}
        record = {'fields': [{'name': 'name', 'label': '名稱'}], 'tabs': [
            {'name': 'contact', 'text': '聯絡人'}, {'name': 'sales', 'text': '銷售'},
            {'name': 'notes', 'text': '備註'}, {'name': 'more', 'text': '更多'}]}
        steps, ph = rule_scripts.build_steps(
            {'key': 'sale.action:x', 'kind': 'action', 'action_xmlid': 'sale.action_x'},
            entry=entry, record=record, has_record=True)
        self.assertEqual(steps[0], {'goto': {'action': 'sale.action_x'}})
        highlights = [s['highlight']['field'] for s in steps if 'highlight' in s]
        self.assertEqual(highlights[:3], ['name', 'email', 'phone'], '清單標前 3 個有標籤的欄')
        self.assertEqual(ph, ['rec'])
        self.assertIn({'open': '{rec}'}, steps)
        clicks = [s['click']['page'] for s in steps if 'click' in s]
        self.assertEqual(clicks, ['sales', 'notes'], '第一個分頁已在表單裡；最多再拍 2 個')
        self.assertFalse(rule_scripts.mutates(steps), '只看不改：說明庫拍完可沿用')

    def test_report_views_do_not_open_records(self):
        steps, ph = rule_scripts.build_steps(
            {'key': 'k', 'kind': 'action', 'action_xmlid': 'a.b'},
            entry={'view_type': 'graph'}, has_record=True)
        self.assertEqual(ph, [])
        self.assertNotIn({'open': '{rec}'}, steps)

    def test_setting_and_missing_action(self):
        steps, _ph = rule_scripts.build_steps(
            {'key': 'sale.setting:automatic_invoice', 'kind': 'setting',
             'anchor': 'automatic_invoice'})
        self.assertEqual(steps[0]['goto']['action'], rule_scripts.SETTINGS_ACTION)
        self.assertIn({'highlight': {'field': 'automatic_invoice', 'n': 1}}, steps)
        self.assertEqual(rule_scripts.build_steps({'key': 'k', 'kind': 'action'}), (None, []))

    def test_pick_role(self):
        codes = ['sales', 'purchase', 'stock', 'account', 'admin']
        self.assertEqual(rule_scripts.pick_role('setting', 'sale', codes), 'admin')
        self.assertEqual(rule_scripts.pick_role('action', 'stock_landed_costs', codes), 'stock')
        self.assertEqual(rule_scripts.pick_role('action', 'unknown', ['x']), 'x')

    def test_mutates(self):
        self.assertTrue(rule_scripts.mutates([{'click': {'button': 'action_confirm'}}]))
        self.assertTrue(rule_scripts.mutates([{'fill': {'field': 'name', 'value': 'a'}}]))
        self.assertFalse(rule_scripts.mutates([{'click': {'page': 'notes'}}]))

    def test_rule_template_created_from_probe(self):
        Hooks = type(self.hooks)
        self.scenario.seed_json = json.dumps(
            [{'xmlid': 'p1', 'model': 'res.partner', 'values': {'name': 'A'}}])
        self.scenario._do_publish('new')   # 拍照只用核准過的示範資料
        probe = {self.f2.id: {'entry': {'view_type': 'list', 'columns': [
            {'name': 'name', 'label': '名稱'}]}, 'record': {'fields': [], 'tabs': []}}}
        self.f2.action_xmlid = 'base.action_partner_form'
        with patch.object(Hooks, '_manual_probe_many', lambda s, sb, items: probe):
            made = self.hooks._manual_rule_templates(
                self.pkg, FakeSandbox(self.scenario), [(self.f2, {'admin': 'h1'}, None)],
                'tok', {'ai': False})
        self.assertEqual(made, 1)
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().search(
            [('feature_id', '=', self.f2.id)])
        self.assertEqual(tmpl.source, 'rule')
        b = tmpl.binding_for(self.scenario)
        self.assertEqual(json.loads(b.bindings_json), {'rec': '__doc_scenario_kbtest_assoc.p1'})

    def test_rule_mode_replaces_failed_ai_template(self):
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        self.cap_a.feature_ids = [(6, 0, self.f1.ids)]
        self.cap_b.feature_ids = [(5,)]
        self.env['corpaas.knowledge.selection'].sudo().search(
            [('package_id', '=', self.pkg.id)]).unlink()
        ai = Template.create({'feature_id': self.f1.id, 'login_role': 'admin',
                              'fingerprint': 'h1', 'source': 'ai',
                              'steps_json': json.dumps([{'shot': 'main'}])})
        Binding.create({'template_id': ai.id, 'scenario_id': self.scenario.id,
                        'state': 'failed'})
        seen = []
        Hooks = type(self.hooks)
        with patch.object(Hooks, '_manual_rule_templates',
                          lambda s, pkg, sb, items, tok, stop: seen.extend(items) or 1):
            n = self.hooks._manual_prepare_templates(self.pkg, FakeSandbox(self.scenario),
                                                     'tok', {'ai': False})
        self.assertEqual(n, 1)
        self.assertEqual([(f, old) for f, _h, old in seen], [(self.f1, ai)])


@tagged('post_install', '-at_install')
class TestReuseShots(ManualCase):

    def _setup(self):
        self.cap_a.feature_ids = [(6, 0, self.f1.ids)]
        self.cap_b.feature_ids = [(5,)]
        self.env['corpaas.knowledge.selection'].sudo().search(
            [('package_id', '=', self.pkg.id)]).unlink()
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': self.f1.id, 'login_role': 'admin', 'fingerprint': 'h1',
            'steps_json': json.dumps([{'goto': {'action': 'a.b'}}, {'shot': 'main'}])})
        b = self.env['corpaas.knowledge.shot_binding'].sudo().create({
            'template_id': tmpl.id, 'scenario_id': self.scenario.id, 'state': 'ok'})
        self._asset(self.f1, owner=b)
        return tmpl, b

    def test_full_refresh_skips_unchanged_screens(self):
        tmpl, b = self._setup()
        b.shot_inputs = self.hooks._manual_shot_inputs(b)
        sb = FakeSandbox(self.scenario)
        Event = self.env['corpaas.knowledge.event']
        todo = self.hooks._manual_bindings_to_shoot(self.pkg, sb, Event, {'full': True})
        self.assertNotIn(b, todo, '輸入沒變：沿用現有截圖，不重拍')
        tmpl.steps_json = json.dumps([{'goto': {'action': 'a.c'}}, {'shot': 'main'}])
        todo = self.hooks._manual_bindings_to_shoot(self.pkg, sb, Event, {'full': True})
        self.assertIn(b, todo, '腳本改了就要重拍')

    def test_incremental_refresh_reshoots_changed_inputs(self):
        """增量更新：拍攝輸入變了（例如截圖程式改了）也重拍；沒變的沿用。"""
        _tmpl, b = self._setup()
        b.shot_inputs = self.hooks._manual_shot_inputs(b)
        sb = FakeSandbox(self.scenario)
        Event = self.env['corpaas.knowledge.event']
        self.assertNotIn(b, self.hooks._manual_bindings_to_shoot(self.pkg, sb, Event, {}))
        b.shot_inputs = 'old-runner'
        self.assertIn(b, self.hooks._manual_bindings_to_shoot(self.pkg, sb, Event, {}))

    def test_failed_reshot_once_when_inputs_change(self):
        """失敗的：輸入沒變不重拍（避免一直重試），截圖程式或腳本改了才再拍一次。"""
        _tmpl, b = self._setup()
        sb = FakeSandbox(self.scenario)
        Event = self.env['corpaas.knowledge.event']
        self.hooks._manual_fail(b, 'Locator.click: Timeout', repair=False)
        self.assertEqual(b.shot_inputs, self.hooks._manual_shot_inputs(b), '失敗也記下用了哪些輸入')
        self.assertNotIn(b, self.hooks._manual_bindings_to_shoot(self.pkg, sb, Event, {}))
        b.shot_inputs = 'old-runner'
        self.assertIn(b, self.hooks._manual_bindings_to_shoot(self.pkg, sb, Event, {}))

    def test_seed_revision_changes_inputs(self):
        _tmpl, b = self._setup()
        before = self.hooks._manual_shot_inputs(b)
        self.scenario.sudo().published_rev_no = (self.scenario.published_rev_no or 0) + 1
        self.assertNotEqual(before, self.hooks._manual_shot_inputs(b))


@tagged('post_install', '-at_install')
class TestApproveNeedsShots(ManualCase):

    def test_failed_binding_blocks_approval(self):
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': self.f1.id, 'login_role': 'admin', 'fingerprint': 'h1',
            'steps_json': json.dumps([{'shot': 'main'}])})
        b = self.env['corpaas.knowledge.shot_binding'].sudo().create({
            'template_id': tmpl.id, 'scenario_id': self.scenario.id, 'state': 'failed',
            'last_error': '畫面是空白引導頁（示範資料不足或被篩選濾掉）：main'})
        art = self._article(self.f1, cap=self.cap_a, shot_binding_id=b.id)
        art.knowledge_propose('new')
        self.assertFalse(art.manual_shots_ready)
        self.assertIn('空白頁', art.manual_shots_problem)
        with self.assertRaises(UserError):
            art.with_user(self.approver).action_approve()
        art.with_user(self.approver).with_context(knowledge_force_approve=True).action_approve()
        self.assertEqual(art.state, 'published')


@tagged('post_install', '-at_install')
class TestFrontRoutes(ManualCase):
    """網站前台頁（kind=route）：會員／訪客身分拍前台，文章排在章節最前面。"""

    def _route(self, anchor, name='線上商城', menus=None):
        return self.Feature.create({
            'feature_key': 'website_sale.route:%s' % anchor, 'module': 'website_sale',
            'kind': 'route', 'anchor': anchor, 'name': name, 'front_menus': menus,
            'package_ids': [(6, 0, self.pkg.ids)]})

    def test_front_path_steps_and_roles(self):
        self.assertTrue(rule_scripts.is_front_path('/shop'))
        self.assertTrue(rule_scripts.is_front_path('/web/signup'))
        self.assertFalse(rule_scripts.is_front_path('/odoo/contacts'))
        self.assertFalse(rule_scripts.is_front_path('/web#action=1'))
        steps, ph = rule_scripts.build_steps({'key': 'website_sale.route:/shop#public',
                                              'kind': 'route', 'anchor': '/shop#public'})
        self.assertEqual(steps[0], {'goto': {'url': '/shop'}})
        self.assertEqual(ph, [])
        steps, _ph = rule_scripts.build_steps({'key': 'website_sale.route:/shop#internal',
                                               'kind': 'route', 'anchor': '/shop#internal'})
        self.assertIn({'highlight': {'selector': '.o_frontend_to_backend_edit_btn', 'n': 1}},
                      steps, '網站管理：標出前台的「編輯此內容」')
        self.assertIn({'goto': {'url': '/@/shop'}}, steps, '再拍網站編輯器')
        codes = ['sales', 'member', 'web_editor', 'admin']
        self.assertEqual(rule_scripts.pick_role('route', 'portal', codes,
                                                anchor='/my/orders#portal'), 'member')
        self.assertEqual(rule_scripts.pick_role('route', 'website_sale', codes,
                                                anchor='/shop#public'), 'visitor')
        self.assertEqual(rule_scripts.pick_role('route', 'website_sale', codes,
                                                anchor='/shop#internal'), 'web_editor')
        self.assertEqual(rule_scripts.pick_role('route', 'portal', ['admin'],
                                                anchor='/my#portal'),
                         'visitor', '沒有會員角色就用訪客')

    def test_validate_allows_front_url_only(self):
        from ..services import manual_lib
        manual_lib.validate_steps([{'goto': {'url': '/shop'}}, {'shot': 'shop_page'}])
        manual_lib.validate_steps([{'goto': {'url': '/@/shop'}}, {'shot': 'shop_editor'}])
        with self.assertRaises(ValueError):
            manual_lib.validate_steps([{'goto': {'url': '/odoo/contacts'}}, {'shot': 'x'}])

    def test_route_fingerprint_candidate_and_group(self):
        from ..models.placement import GROUP_FRONT, article_group
        shop = self._route('/shop#public', menus='首頁\n好康商城')
        orders = self._route('/my/orders#portal', '我的訂單', menus='首頁\n會員中心')
        editor = self._route('/shop#internal', '線上商城（網站管理）')
        self.pkg._knowledge_route_fingerprints({'website_sale': '1.0'})
        FP = self.env['corpaas.knowledge.fingerprint']
        fp = FP.search([('feature_id', '=', shop.id), ('current', '=', True)])
        self.assertEqual((len(fp), fp.role_code), (1, 'visitor'))
        self.assertEqual(FP.search([('feature_id', '=', orders.id),
                                    ('current', '=', True)]).role_code, 'member')
        self.pkg._knowledge_route_fingerprints({'website_sale': '1.0'})
        self.assertEqual(FP.search_count([('feature_id', '=', shop.id)]), 1, '沒改版不換指紋')
        self.pkg._knowledge_route_fingerprints({'website_sale': '2.0'})
        self.assertEqual(FP.search_count([('feature_id', '=', shop.id)]), 2, '模組改版換指紋')
        self.assertEqual(set(self.hooks._manual_package_hashes(self.pkg, shop)), {'visitor'})
        self.cap_a.feature_ids = [(4, shop.id)]
        self.assertIn(shop, self.hooks._manual_candidates(self.pkg), '前台頁是文章候選')
        self.assertEqual(article_group(shop), GROUP_FRONT)
        prompt = self.hooks._manual_feature_dict(orders, self.pkg)
        self.assertEqual(prompt['audience'], 'member')
        self.assertEqual(prompt['anchor'], '/my/orders')
        from ..services import prompts
        note = prompts._front_note(prompt)
        self.assertIn('會員中心', note)
        self.assertIn('網站入口', note)
        self.assertIn('編輯此內容', prompts._front_note(
            self.hooks._manual_feature_dict(editor, self.pkg)))
        roles = self.scenario.all_roles().mapped('code')
        self.assertIn('member', roles, '有會員頁就補會員角色')
        self.assertIn('web_editor', roles, '有網站管理頁就補網站管理角色')
