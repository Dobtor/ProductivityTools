# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged('post_install', '-at_install')
class TestContentState(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.editor = new_test_user(cls.env, 'kb_editor',
                                   groups='base.group_user,dobtor_corpaas_knowledge.group_knowledge_editor')
        cls.approver = new_test_user(cls.env, 'kb_approver',
                                     groups='base.group_user,dobtor_corpaas_knowledge.group_knowledge_approver')
        cls.cap = cls.env['corpaas.knowledge.capability'].create(
            {'name': '線上報名收費', 'code': 'reg_pay', 'pain': '報名與收款分兩套'})

    def test_propose_text_goes_to_review_then_publish(self):
        self.cap.knowledge_propose('new')
        self.assertEqual(self.cap.state, 'review')
        with self.assertRaises(AccessError):
            self.cap.with_user(self.editor).action_approve()
        self.cap.with_user(self.approver).action_approve()
        self.assertEqual(self.cap.state, 'published')
        self.assertEqual(self.cap.published_rev_no, self.cap.rev_no)

    def test_shot_only_publishes_automatically(self):
        self.cap.knowledge_propose('new')
        self.cap.with_user(self.approver).action_approve()
        self.cap.knowledge_mark_stale('指紋改變')
        self.assertEqual(self.cap.state, 'stale')
        self.cap.knowledge_reshoot_done()
        self.assertEqual(self.cap.state, 'published')

    def test_reject_requires_reason(self):
        self.cap.knowledge_propose('new')
        with self.assertRaises(UserError):
            self.cap.with_user(self.approver).action_reject()
        self.cap.with_user(self.approver).action_reject(reason='用語不對')
        self.assertEqual(self.cap.state, 'draft')
        self.assertEqual(self.cap.reject_reason, '用語不對')

    def test_review_diff_and_restore(self):
        self.cap.knowledge_propose('new')
        self.cap.with_user(self.approver).action_approve()
        self.cap.outcome = '報名即收款'
        self.cap.knowledge_propose('text')
        self.assertIn('報名即收款', self.cap.review_diff)
        self.cap.with_user(self.approver).action_approve()
        first = self.env['corpaas.knowledge.revision'].search(
            [('res_model', '=', self.cap._name), ('res_id', '=', self.cap.id),
             ('was_published', '=', True)], order='rev_no asc', limit=1)
        self.cap.action_restore_revision(first)
        self.assertEqual(self.cap.state, 'review')
        self.assertFalse(self.cap.outcome)

    def test_scenario_shared_requires_review_and_waiver(self):
        sc = self.env['corpaas.knowledge.scenario'].create(
            {'name': '通用商務', 'code': 'general', 'is_base': True, 'auto_text_after': 2})
        self.assertTrue(sc._knowledge_requires_review('text'))
        self.assertFalse(sc._knowledge_requires_review('shot'))
        # ★ 計的是「這個情境的文章」審核結果，不是情境記錄本身
        sc.note_article_review(True)
        self.assertFalse(sc.text_review_waived())
        sc.note_article_review(True)
        self.assertTrue(sc.text_review_waived())
        sc.note_article_review(False)
        self.assertFalse(sc.text_review_waived(), '退回或核准者改過就歸零')

    def test_live_seed_only_approved(self):
        sc = self.env['corpaas.knowledge.scenario'].create({
            'name': '年會', 'code': 'annual', 'is_base': True,
            'seed_json': '[{"xmlid": "p", "model": "res.partner", "values": {"name": "A"}}]'})
        with self.assertRaises(UserError):
            sc.live_seed()
        sc.knowledge_propose('new')
        sc.with_user(self.approver).action_approve()
        self.assertEqual(sc.live_seed()[0]['values']['name'], 'A')
        # 已發佈後直接改欄位（沒送審）→ 說明庫仍用核准版
        sc.seed_json = '[{"xmlid": "p", "model": "res.partner", "values": {"name": "未核准"}}]'
        self.assertEqual(sc.live_seed()[0]['values']['name'], 'A')
        sc.knowledge_propose('text')
        self.assertEqual(sc.live_seed()[0]['values']['name'], 'A', '待核中仍用上線版')

    def test_scenario_code_validated(self):
        with self.assertRaises(UserError):
            self.env['corpaas.knowledge.scenario'].create({'name': 'x', 'code': '課程'})

    def test_scenario_lineage_and_seed_merge(self):
        base = self.env['corpaas.knowledge.scenario'].create({
            'name': '基底', 'code': 'base1', 'glossary': '客戶=客戶',
            'seed_json': '[{"xmlid": "p", "model": "res.partner", "values": {"name": "A"}}]'})
        child = self.env['corpaas.knowledge.scenario'].create({
            'name': '課程', 'code': 'course', 'parent_id': base.id, 'glossary': '客戶=會員',
            'seed_json': '[{"xmlid": "__doc_scenario_base1.p", "model": "res.partner",'
                         ' "values": {"name": "B"}}, {"xmlid": "q", "model": "res.partner",'
                         ' "values": {"name": "Q"}}]'})
        seed = child.full_seed()
        self.assertEqual([r['xmlid'] for r in seed],
                         ['__doc_scenario_base1.p', '__doc_scenario_course.q'])
        self.assertEqual(seed[0]['values']['name'], 'B', '子情境覆寫祖先同 xmlid')
        self.assertEqual(child.glossary_map()['客戶'], '會員')
        base.parent_id = child
        with self.assertRaises(UserError):
            child.lineage()

    def test_gc_keeps_latest_published(self):
        self.cap.knowledge_propose('new')
        self.cap.with_user(self.approver).action_approve()
        for i in range(7):
            self.cap.outcome = 'v%s' % i
            self.cap.knowledge_propose('text')  # 送審但不核准
        Rev = self.env['corpaas.knowledge.revision']
        Rev._gc_keep_last(3)
        revs = Rev.search([('res_model', '=', self.cap._name), ('res_id', '=', self.cap.id)])
        self.assertTrue(revs.filtered('was_published'), '最新上線版不能被清掉')
        self.assertEqual(len(revs), 4)

    def test_feature_selection_approve_links_capability(self):
        f = self.env['corpaas.knowledge.feature'].create({
            'feature_key': 'x.menu:x.m', 'module': 'x', 'kind': 'menu', 'anchor': 'x.m',
            'name': 'M'})
        tmpl = self.env['product.template'].create({'name': 'P', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        sel = self.env['corpaas.knowledge.selection'].create({
            'package_id': pkg.id, 'kind': 'feature', 'feature_id': f.id,
            'proposal_json': '{"new_capability": "新能力甲"}'})
        with self.assertRaises(AccessError):
            sel.with_user(self.editor).action_approve()
        sel.with_user(self.approver).action_approve()
        self.assertEqual(sel.capability_id.name, '新能力甲')
        self.assertIn(f, sel.capability_id.feature_ids)
        self.assertIn(pkg, sel.capability_id.package_ids)
