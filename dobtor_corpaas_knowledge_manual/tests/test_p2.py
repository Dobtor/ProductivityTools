# -*- coding: utf-8 -*-
"""P2：旅程篇與章內依流程排序、起草依能力順序（D1）、成本規劃器的操作說明部分（D3）。"""
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
        self.assertIn('草稿 → 完成', html)
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
