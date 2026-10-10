# -*- coding: utf-8 -*-
"""P2：旅程篇與章內依流程排序、起草依能力順序（D1）、成本規劃器的操作說明部分（D3）。"""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import ManualCase


@tagged('post_install', '-at_install')
class TestJourney(ManualCase):

    def _three_in_cap_a(self):
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        a1 = self._article(self.f1, self.cap_a, name='甲 建立報名')
        a2 = self._article(self.f2, self.cap_a, name='乙 報名確認')
        a3 = self._article(self.f3, self.cap_a, name='丙 收款')
        return a1, a2, a3

    def _flow(self, features):
        flow = self.env['corpaas.knowledge.flow'].sudo().create({
            'model': 'res.partner', 'model_name': '報名', 'state_field': 'kbt_state',
            'capability_id': self.cap_a.id, 'feature_ids': [(6, 0, features.ids)]})
        for i, (v, label) in enumerate([('draft', '草稿'), ('done', '完成')]):
            self.env['corpaas.knowledge.flow.step'].sudo().create({
                'flow_id': flow.id, 'sequence': i, 'value': v, 'label': label,
                'on_statusbar': True})
        return flow

    def test_journey_first_and_articles_in_flow_order(self):
        a1, a2, a3 = self._three_in_cap_a()
        # 流程：收款（f3）是入口畫面、確認（f2）是按鈕 → 先 f3 再 f2；f1 不在流程上排最後
        self.f2.kind = 'button'
        self._flow(self.f2 | self.f3)
        self.cap_a._do_publish('new')
        self._publish(a1, a2, a3)
        channel = self._channel()
        section = channel.knowledge_section_ids.filtered(lambda s: s.capability_id == self.cap_a)
        journey = section.journey_slide_id
        self.assertTrue(journey.is_published, '三篇以上的章節有旅程篇')
        self.assertEqual(journey.name, '線上報名：整體流程')
        seq = lambda s: (s.invalidate_recordset() or s.sequence)  # noqa: E731
        self.assertEqual(seq(journey), 101, '旅程篇是章節第一篇')
        slides = {a: a.placement_ids.slide_id for a in (a1, a2, a3)}
        self.assertEqual([seq(slides[a3]), seq(slides[a2]), seq(slides[a1])], [102, 103, 104],
                         '章內依流程：入口畫面 → 按鈕 → 不在流程上的')
        html = journey.html_content
        self.assertIn('o_kb_flowpos', html, '流程狀態改成徽章列')
        self.assertLess(html.index('草稿'), html.index('完成'))
        self.assertLess(html.index('丙 收款'), html.index('乙 報名確認'))
        self.assertIn(slides[a3].website_url, html)
        self.assertEqual(journey.category_id, section.slide_id)

    def test_small_chapter_has_no_journey_and_retire_unpublishes(self):
        a1, a2, a3 = self._three_in_cap_a()
        self._publish(a1, a2)
        section = self._channel().knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_a)
        self.assertFalse(section.journey_slide_id, '兩篇不需要導覽')
        self._publish(a3)
        journey = section.journey_slide_id
        self.assertTrue(journey.is_published)
        a3.action_retire()
        self.assertFalse(journey.is_published, '剩兩篇：旅程篇取消發佈（不刪）')
        self.assertTrue(journey.exists())

    def test_journey_not_rewritten_when_unchanged(self):
        arts = self._three_in_cap_a()
        self._publish(*arts)
        channel = self._channel()
        journey = channel.knowledge_section_ids.journey_slide_id
        stamp = journey.date_published
        channel._knowledge_renumber()
        self.assertEqual(journey.date_published, stamp, '內容沒變不重設「新」標記')


@tagged('post_install', '-at_install')
class TestDraftOrderAndCost(ManualCase):

    def test_candidates_in_capability_order(self):
        # 收款（能力 B）使用量最高，仍排在能力 A 之後；共通操作最後
        self.f3.sudo().usage_score = 999
        order = [f for f, _c in self.hooks._manual_sorted_candidates(self.pkg)]
        self.assertEqual(order[-1], self.f4, '共通操作排最後')
        self.assertLess(order.index(self.f1), order.index(self.f3))
        self.assertLess(order.index(self.f2), order.index(self.f3))

    def test_cost_lines_count_drafts(self):
        self._publish(self._article(self.f1, self.cap_a))
        plan = self.pkg._knowledge_cost_plan(full=True)
        lines = {l['key']: l for l in plan['lines']}
        self.assertEqual(lines['draft']['count'], 3, 'f2、f3、f4 還沒有文章')
        self.assertTrue(lines['draft']['deferrable'])
        self.assertEqual(lines['script']['unit'], 0.0, '規則模式產生腳本不花 AI')
        self.pkg.action_knowledge_cost_plan()
        self.assertIn('起草參考篇', self.pkg.knowledge_cost_plan_html)

    def test_archived_templates_not_counted_for_repair(self):
        import json
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        for active in (True, False):
            t = Template.create({'feature_id': self.f1.id, 'login_role': 'admin',
                                 'fingerprint': 'h%s' % active, 'source': 'ai',
                                 'steps_json': json.dumps([{'shot': 'main'}])})
            Binding.create({'template_id': t.id, 'scenario_id': self.scenario.id,
                            'state': 'failed', 'needs_repair': True})
            t.active = active
        lines = {l['key']: l for l in self.pkg._knowledge_cost_lines()}
        self.assertEqual(lines['repair']['count'], 1, '封存的範本不會再修')


@tagged('post_install', '-at_install')
class TestTextLintAndFailures(ManualCase):

    def test_lint_blocks_approval(self):
        blk = self._block(self.f1, html='<p>打開这个畫面，填 partner_id。（系統原文 Customer）</p>'
                                        '<p>[[shot:main_list]]</p>', publish=True)
        art = self._article(self.f1, self.cap_a, block=blk)
        problems = art._manual_text_problems()
        joined = '；'.join(problems)
        self.assertIn('簡體字', joined)
        self.assertIn('partner_id', joined)
        self.assertIn('系統原文', joined)
        self.assertNotIn('main_list', joined, '截圖標記名稱不算技術欄位')
        art.knowledge_propose('new')
        with self.assertRaises(UserError):
            art.with_user(self.approver).action_approve()

    def test_clean_text_passes(self):
        art = self._article(self.f1, self.cap_a)
        self.assertEqual(art._manual_text_problems(), [])

    def test_failure_kinds_feed_scenario_gaps(self):
        import json
        hooks = self.hooks
        self.assertEqual(hooks._manual_failure_kind('畫面是空白引導頁（示範資料不足）'), 'empty')
        self.assertEqual(hooks._manual_failure_kind('畫面出現錯誤對話框：存取錯誤'), 'access')
        self.assertEqual(hooks._manual_failure_kind('Locator.click: Timeout'), 'locator')
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': self.f2.id, 'login_role': 'admin', 'fingerprint': 'h1',
            'steps_json': json.dumps([{'shot': 'main'}])})
        b = self.env['corpaas.knowledge.shot_binding'].sudo().create({
            'template_id': tmpl.id, 'scenario_id': self.scenario.id, 'state': 'failed',
            'last_error': '畫面是空白引導頁（示範資料不足或被篩選濾掉）：main'})
        stats = {}
        hooks._manual_record_failures(self.scenario, b, stats)
        self.assertEqual(stats['shots_failed_empty'], 1)
        self.assertEqual(json.loads(self.scenario.shot_gaps), ['報名確認'])


@tagged('post_install', '-at_install')
class TestIterativeManual(ManualCase):

    def _binding(self, feature, state='failed', error='Locator.click: Timeout', repair=False):
        import json
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': feature.id, 'login_role': 'sales', 'fingerprint': 'h1',
            'steps_json': json.dumps([{'shot': 'main'}])})
        return self.env['corpaas.knowledge.shot_binding'].sudo().create({
            'template_id': tmpl.id, 'scenario_id': self.scenario.id, 'state': state,
            'last_error': error, 'needs_repair': repair})

    def test_clean_title(self):
        from ..services.manual_lib import clean_title
        self.assertEqual(clean_title('【標準進階】外包直運——直送客戶'), '外包直運——直送客戶')
        self.assertEqual(clean_title('協會年會 - 付款服務商', '協會年會'), '付款服務商')
        self.assertEqual(clean_title('建立報價單', '協會年會'), '建立報價單')

    def test_partial_approval(self):
        good = self._article(self.f1, self.cap_a, name='建立報名')
        bad = self._article(self.f2, self.cap_a, name='【標準功能】報名確認')
        (good | bad).knowledge_propose('new')
        res = (good | bad).with_user(self.approver).action_approve()
        self.assertEqual(good.state, 'published')
        self.assertEqual(bad.state, 'review', '不合格的略過，不讓整批失敗')
        self.assertEqual(res['params']['type'], 'warning')
        self.assertIn('標題含內部標籤', res['params']['message'])

    def test_shot_gaps_and_access_fixer(self):
        import json
        from unittest.mock import patch
        from .test_hooks import FakeSandbox
        self.f1.action_xmlid = 'base.action_partner_form'
        b = self._binding(self.f1, error='畫面出現錯誤對話框：存取錯誤 您並無權限')
        self.hooks._manual_sync_shot_gaps(self.pkg, b)
        gap = self.env['corpaas.knowledge.gap_item'].search([('res_id', '=', b.id)])
        self.assertEqual(gap.kind, 'access')
        role = self.env.ref('dobtor_corpaas_knowledge.role_stock')
        self.scenario.role_ids = [(6, 0, (role | self.env.ref(
            'dobtor_corpaas_knowledge.role_admin')).ids)]
        sb = FakeSandbox(self.scenario)
        with patch.object(type(sb), '_shell', lambda s, script: {
                'base.action_partner_form': ['stock', 'admin']}, create=True):
            fixed = self.hooks._manual_fix_shot_gaps(self.pkg, sb, {})
        self.assertEqual(fixed, 1)
        self.assertEqual(json.loads(b.roles_json), {'login_role': 'stock'}, '優先用進得去的一般角色')
        self.assertEqual(b.state, 'pending')
        self.assertEqual(gap.attempts, 1)
        # 換成一般角色後仍是存取錯誤 → 第二次直接用系統管理員
        b.write({'state': 'failed', 'last_error': '畫面出現錯誤對話框：存取錯誤 您並無權限'})
        self.hooks._manual_sync_shot_gaps(self.pkg, b)
        with patch.object(type(sb), '_shell', lambda s, script: {
                'base.action_partner_form': ['stock', 'admin']}, create=True):
            self.hooks._manual_fix_shot_gaps(self.pkg, sb, {})
        self.assertEqual(json.loads(b.roles_json), {'login_role': 'admin'}, '換過還是不行就用管理員')
        b.state = 'ok'
        self.hooks._manual_sync_shot_gaps(self.pkg, b)
        self.assertEqual(gap.state, 'resolved')

    def test_human_access_gap_gets_one_admin_try(self):
        import json
        from unittest.mock import patch
        from .test_hooks import FakeSandbox
        self.f1.action_xmlid = 'base.action_partner_form'
        b = self._binding(self.f1, error='畫面出現錯誤對話框：存取錯誤 您並無權限')
        b.roles_json = json.dumps({'login_role': 'stock'})
        self.hooks._manual_sync_shot_gaps(self.pkg, b)
        gap = self.env['corpaas.knowledge.gap_item'].search([('res_id', '=', b.id)])
        gap.write({'state': 'human', 'attempts': 3})
        self.scenario.role_ids = [(6, 0, (self.env.ref('dobtor_corpaas_knowledge.role_stock') | self.env.ref(
            'dobtor_corpaas_knowledge.role_admin')).ids)]
        sb = FakeSandbox(self.scenario)
        with patch.object(type(sb), '_shell', lambda s, script: {}, create=True):
            self.assertEqual(self.hooks._manual_fix_shot_gaps(self.pkg, sb, {}), 1)
            self.assertEqual(b.login_role(), 'admin', '轉人工前沒試過管理員：再給一次')
            self.assertEqual(self.hooks._manual_fix_shot_gaps(self.pkg, sb, {}), 0, '試過管理員就不再動')

    def test_human_data_gap_retried_once_with_conditions(self):
        from unittest.mock import patch
        b = self._binding(self.f1, error='畫面是空白引導頁（示範資料不足）')
        self.hooks._manual_sync_shot_gaps(self.pkg, b)
        gap = self.env['corpaas.knowledge.gap_item'].search([('res_id', '=', b.id)])
        gap.write({'state': 'human', 'attempts': 3, 'fix_note': 'ai_seed：補了 3 筆示範資料'})
        Scenario = type(self.scenario)
        with patch.object(Scenario, '_ai_fill_gaps', return_value=2) as fill:
            self.hooks._knowledge_fix_gaps_before_sandbox(self.pkg, {})
            self.assertEqual(fill.call_count, 1, '還沒看過畫面條件：再補一次')
            self.assertEqual(b.state, 'pending')
            self.hooks._knowledge_fix_gaps_before_sandbox(self.pkg, {})
            self.assertEqual(fill.call_count, 1, '帶條件補過就不再補')

    def test_fix_gaps_button_collects_existing_failures(self):
        from unittest.mock import patch
        self.cap_a.feature_ids = [(6, 0, self.f1.ids)]
        self.cap_b.feature_ids = [(5,)]
        b = self._binding(self.f1, error='畫面是空白引導頁（示範資料不足）')
        Pkg = type(self.pkg)
        with patch.object(Pkg, 'knowledge_enqueue_refresh', lambda s, **kw: None), \
                patch.object(type(self.hooks), '_manual_relevant_bindings', lambda s, p: b):
            self.pkg.action_knowledge_fix_gaps()
        gap = self.env['corpaas.knowledge.gap_item'].search([('res_id', '=', b.id)])
        self.assertEqual(gap.kind, 'data')

    def test_text_gap_fixed_by_rule(self):
        art = self._article(self.f1, self.cap_a, name='【標準進階】建立報名')
        art.knowledge_propose('new')
        self.hooks._manual_sync_text_gaps(self.pkg)
        gap = self.env['corpaas.knowledge.gap_item'].search([('res_id', '=', art.id),
                                                              ('kind', '=', 'text')])
        self.assertTrue(gap)
        self.hooks._manual_fix_text_gaps(self.pkg)
        self.assertEqual(art.name, '建立報名')
        self.assertEqual(gap.state, 'resolved')

    def test_no_draft_for_failed_shot(self):
        b = self._binding(self.f1, error='畫面是空白引導頁（示範資料不足）')
        art = self.hooks._manual_reconcile_one(
            self.pkg, self.f1, self.cap_a, self.scenario, {'admin': 'h1'}, b.template_id,
            'tok', {}, {'ai': False})
        self.assertFalse(art, '截圖失敗不起草')


@tagged('post_install', '-at_install')
class TestDiagramOutlets(ManualCase):

    def test_journey_shows_mainline_and_registers_embed(self):
        from odoo.addons.dobtor_corpaas_knowledge.services import bpmn_lib
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        model = {'name': '線上報名', 'lanes': [{'id': 'admin', 'name': '管理員'}],
                 'nodes': [{'id': 'Start_1', 'kind': 'start', 'name': '開始', 'lane': 'admin', 'col': 0},
                           {'id': 'End_done', 'kind': 'end', 'name': '完成', 'lane': 'admin', 'col': 1}],
                 'edges': [{'src': 'Start_1', 'dst': 'End_done'}]}
        diagram = self.env['bpmn.diagram'].sudo().create({
            'name': '線上報名：主線', 'code': 'kb_cap_test', 'xml': bpmn_lib.to_xml(model, 'kb_t'),
            'svg': bpmn_lib.to_svg(model), 'knowledge_capability_id': self.cap_a.id,
            'knowledge_package_id': self.pkg.id, 'knowledge_scope': 'capability'})
        arts = [self._article(f, self.cap_a, name=n) for f, n in
                ((self.f1, '甲'), (self.f2, '乙'), (self.f3, '丙'))]
        self._publish(*arts)
        section = self._channel().knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_a)
        journey = section.journey_slide_id
        self.assertIn('/web/content/%s' % diagram.knowledge_attachment_id.id, journey.html_content)
        self.assertTrue(self.env['bpmn.diagram.embed'].search_count([
            ('diagram_id', '=', diagram.id), ('res_model', '=', 'slide.slide'),
            ('res_id', '=', journey.id)]), '設計圖上看得到嵌入在哪篇')

    def test_path_gaps(self):
        from unittest.mock import patch
        from .test_hooks import FakeSandbox
        flow = self.env['corpaas.knowledge.flow'].sudo().create({
            'model': 'res.partner', 'state_field': 'kbp_state', 'field_type': 'selection',
            'model_name': '報名流程', 'package_ids': [(4, self.pkg.id)],
            'feature_ids': [(4, self.f1.id)]})
        for i, v in enumerate(['draft', 'done']):
            self.env['corpaas.knowledge.flow.step'].sudo().create(
                {'flow_id': flow.id, 'sequence': i, 'value': v, 'label': v, 'on_statusbar': True})
        sb = FakeSandbox(self.scenario)
        with patch.object(type(sb), '_shell', lambda s, script: {'res.partner': {'draft': 3}},
                          create=True):
            self.assertEqual(self.hooks._manual_sync_path_gaps(self.pkg, sb), 1)
        gap = self.env['corpaas.knowledge.gap_item'].search([('res_id', '=', flow.id),
                                                              ('res_model', '=', flow._name)])
        self.assertEqual((gap.kind, gap.feature_id), ('data', self.f1))
        self.assertIn('done', gap.evidence)
        # 流程路徑缺口（掛流程、沒有 needs_repair）開著時，判斷要不要準備說明庫不能當掉
        self.assertIn(self.scenario, self.hooks._knowledge_scenarios_needing_shots(
            self.pkg, self.env['corpaas.knowledge.event']))
        with patch.object(type(sb), '_shell',
                          lambda s, script: {'res.partner': {'draft': 3, 'done': 1}}, create=True):
            self.hooks._manual_sync_path_gaps(self.pkg, sb)
        self.assertEqual(gap.state, 'resolved')
