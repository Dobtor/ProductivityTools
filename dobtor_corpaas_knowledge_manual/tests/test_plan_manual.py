# -*- coding: utf-8 -*-
"""說明書出口接上說明書製作計畫：範圍依底稿、指標、內容指示（依指示重寫、共用區塊分岔）。"""
import json
from unittest.mock import patch

from odoo.tests import tagged

from .common import ManualCase


@tagged('post_install', '-at_install')
class TestPlanManual(ManualCase):

    def _plan(self):
        Plan = self.env['corpaas.knowledge.plan'].sudo().with_context(knowledge_plan_system=True)
        plan = Plan.create({'package_id': self.pkg.id, 'state': 'running'})
        Item = self.env['corpaas.knowledge.plan.item'].sudo().with_context(knowledge_plan_system=True)
        ch_a = Item.create({'plan_id': plan.id, 'kind': 'chapter', 'key': 'reg', 'name': '線上報名',
                            'res_model': self.cap_a._name, 'res_id': self.cap_a.id})
        ch_b = Item.create({'plan_id': plan.id, 'kind': 'chapter', 'key': 'pay', 'name': '收費對帳',
                            'res_model': self.cap_b._name, 'res_id': self.cap_b.id})
        Item.create({'plan_id': plan.id, 'kind': 'story', 'key': 'story', 'name': '協會',
                     'content_json': json.dumps({'company': '晨光協會', 'rules': ['用「會員」稱呼客戶']})})
        Line = self.env['corpaas.knowledge.scope_line'].sudo().with_context(knowledge_plan_system=True)
        for f, a, item in ((self.f1, 'chapter', ch_a), (self.f2, 'chapter', ch_a),
                           (self.f3, 'exclude', None), (self.f4, 'chapter', ch_b)):
            Line.create({'plan_id': plan.id, 'feature_id': f.id, 'module': f.module, 'assignment': a,
                         'item_id': item.id if item else False})
        return plan, ch_a, ch_b

    def test_candidates_follow_plan_lines(self):
        plan, ch_a, ch_b = self._plan()
        self.assertEqual(self.pkg.knowledge_plan_id, plan)
        cand = self.hooks._manual_candidates(self.pkg)
        self.assertEqual(set(cand), {self.f1, self.f2, self.f4}, '排除的功能點不寫；範圍只看計畫底稿')
        self.assertEqual(cand[self.f4], self.cap_b, '章節取計畫展開的能力（不是圈選提案）')

    def test_metrics(self):
        plan, ch_a, _ch_b = self._plan()
        Tmpl = self.env['corpaas.knowledge.shot_template'].sudo()
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        for f, state in ((self.f1, 'ok'), (self.f2, 'failed'), (self.f3, 'ok')):
            t = Tmpl.create({'feature_id': f.id, 'login_role': 'admin', 'fingerprint': 'h1',
                             'steps_json': json.dumps([{'shot': 'main'}])})
            Binding.create({'template_id': t.id, 'scenario_id': self.scenario.id, 'state': state})
        a1 = self._article(self.f1, self.cap_a)
        self._publish(a1)
        self._article(self.f2, self.cap_a).knowledge_propose('new')
        m = self.hooks._knowledge_plan_metrics(plan)
        self.assertEqual((m['shots_total'], m['shots_ok']), (2, 1), 'f3 被排除，不算進指標')
        self.assertEqual(m['shot_rate'], 50.0)
        self.assertEqual((m['articles_total'], m['articles_published']), (2, 1))
        self.assertEqual(m['chapters'][str(ch_a.id)], {'features': 2, 'shots_ok': 1, 'published': 1})

    def test_instruction_rewrites_and_forks_shared_block(self):
        plan, _a, _b = self._plan()
        block = self._block(self.f1, publish=True)
        art = self._article(self.f1, self.cap_a, block=block)
        other = self._article(self.f1, self.cap_a, name='另一篇', block=block)
        self._publish(art, other)
        Item = self.env['corpaas.knowledge.plan.item'].sudo().with_context(knowledge_plan_system=True)
        Item.create({'plan_id': plan.id, 'kind': 'instruction', 'key': 'i1', 'name': '先選年會再填人數',
                     'change': 'new', 'content_json': json.dumps({'article_id': art.id,
                                                                  'text': '第 1 步先選年會再填人數'})})
        self.hooks._knowledge_plan_apply_instructions(plan)
        self.assertTrue(art.manual_pending_instruction)
        self.assertIn('先選年會', art.manual_instructions)
        Tmpl = self.env['corpaas.knowledge.shot_template'].sudo()
        t = Tmpl.create({'feature_id': self.f1.id, 'login_role': 'admin', 'fingerprint': 'h1',
                         'steps_json': json.dumps([{'shot': 'main'}])})
        art.shot_binding_id = self.env['corpaas.knowledge.shot_binding'].sudo().create(
            {'template_id': t.id, 'scenario_id': self.scenario.id, 'state': 'ok'})
        Ai = type(self.env['corpaas.knowledge.ai'])
        replies = {'manual_step_block': {'title': '報名步驟', 'steps': [{'title': '選年會', 'html': '<p>先選年會。</p>'}]},
                   'manual_scenario': {'title': '建立報名', 'html': '<p>依指示改寫。</p>'}}
        with patch.object(Ai, 'ask', side_effect=lambda purpose, prompt, **kw: replies[purpose]) as ask:
            self.hooks._manual_apply_pending_instructions(self.pkg, 'tok', {'ai': False})
        self.assertIn('先選年會再填人數', ask.call_args_list[0][0][1], '提示詞帶人工指示')
        self.assertFalse(art.manual_pending_instruction)
        self.assertEqual(art.state, 'review', '已上線的文章依指示改寫後重新送審')
        self.assertIn('依指示改寫', art.scenario_html)
        fork = art.step_block_ids
        self.assertNotEqual(fork, block, '共用且已上線的步驟區塊分岔成這篇專屬')
        self.assertEqual(fork.derived_from_id, block)
        self.assertEqual(other.step_block_ids, block, '其他文章仍用共用版本')

    def test_review_prompt_has_rules_and_instructions(self):
        self._plan()
        art = self._article(self.f1, self.cap_a)
        art.manual_instructions = '・第 1 步先選年會'
        prompt = art._manual_review_prompt(self.pkg)
        self.assertIn('用「會員」稱呼客戶', prompt)
        self.assertIn('第 1 步先選年會', prompt)
