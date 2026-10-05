# -*- coding: utf-8 -*-
"""K19–K26：官方畫面改動偵測、官方文件對照、覆蓋率、缺口主題、流程命名。"""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from . import test_refresh as base


@tagged('post_install', '-at_install')
class TestCustomizedOfficial(base._RefreshBase):

    def test_official_screen_extended_by_other_module_is_customized(self):
        Pkg = type(self.pkg)
        # 測試庫只把 base／web 當官方：其他模組（auth_*、mail、dobtor_*）繼承 base 畫面＝改過
        with patch.object(Pkg, '_knowledge_golden_installed',
                          lambda s, g, official_only=False: {'base', 'web'}):
            self.master.golden.id = 1
            self.addCleanup(setattr, self.master.golden, 'id', 0)
            self._refresh()
        feats = self.env['corpaas.knowledge.feature'].search(
            [('package_ids', 'in', self.pkg.id), ('module_origin', '=', 'odoo')])
        custom = feats.filtered(lambda f: f.attr_for(self.pkg, 'customized'))
        self.assertTrue(custom, '有被非官方模組繼承的官方畫面')
        row = custom[0].class_for(self.pkg)
        self.assertTrue(row, '「改過」記在方案屬性層')
        elements = json.loads(row.custom_elements)
        self.assertTrue(elements and all(':' in e for e in elements))
        self.assertTrue(row.custom_modules)
        self.assertNotIn('base', row.custom_modules.split(','))


@tagged('post_install', '-at_install')
class TestOfficialDocsAndCoverage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pkg = cls.env['infrastructure.solution.package'].create({
            'product_tmpl_id': cls.env['product.template'].create(
                {'name': 'OC 方案', 'type': 'service'}).id, 'knowledge_enabled': True})
        F = cls.env['corpaas.knowledge.feature']
        mk = lambda key, **kw: F.create(dict({
            'feature_key': 'sale.action:%s' % key, 'module': 'sale', 'kind': 'action',
            'anchor': key, 'name': key, 'model': 'sale.order',
            'package_ids': [(4, cls.pkg.id)]}, **kw))
        cls.f_plain = mk('plain', module_origin='odoo', usage_score=50)
        cls.f_custom = mk('custom', module_origin='odoo', customized=True)
        cls.f_own = F.create({'feature_key': 'x_own.action:own', 'module': 'x_own',
                              'kind': 'action', 'anchor': 'own', 'name': 'own',
                              'model': 'x.own', 'package_ids': [(4, cls.pkg.id)]})

    def _ask(self, items):
        Ai = type(self.env['corpaas.knowledge.ai'])
        return patch.object(Ai, 'ask', lambda s, purpose, prompt, **kw: {'items': items})

    def test_verified_url_auto_approved_unverified_waits(self):
        Doc = type(self.env['corpaas.knowledge.official_doc'])
        base_url = 'https://www.odoo.com/documentation/18.0/'
        with self._ask([{'key': self.f_plain.feature_key, 'url': base_url + 'sales.html',
                         'title': '銷售'}]), \
                patch.object(Doc, '_verify_url', lambda s, url: True):
            docs = self.pkg._knowledge_official_docs('tok')
        self.assertEqual(docs.feature_id, self.f_plain, '改過的官方畫面不找官方文件')
        self.assertEqual((docs.state, docs.verified, docs.auto_approved),
                         ('approved', True, True))
        # 已有對照就不再問
        with self._ask([]) as _p:
            self.assertFalse(self.pkg._knowledge_official_docs('tok'))

    def test_unverified_url_stays_proposed(self):
        Doc = type(self.env['corpaas.knowledge.official_doc'])
        with self._ask([{'key': self.f_plain.feature_key, 'url': 'https://evil.example/x'}]), \
                patch.object(Doc, '_verify_url', lambda s, url: False):
            docs = self.pkg._knowledge_official_docs('tok')
        self.assertEqual(docs.state, 'proposed')
        self.assertFalse(self.env['corpaas.knowledge.official_doc']._verify_url(
            'https://evil.example/x'), '不在官方文件網址底下的一律不過')

    def test_help_links_include_official_doc(self):
        self.env['corpaas.knowledge.official_doc'].create({
            'feature_id': self.f_plain.id, 'url': 'https://www.odoo.com/documentation/18.0/s',
            'state': 'approved'})
        links = self.env['corpaas.knowledge.hooks']._knowledge_help_links(
            self.pkg, [(self.f_plain, 1.0)], 'q', {})
        self.assertIn('official', [l['kind'] for l in links])

    def test_coverage_statuses_and_rate(self):
        self.env['corpaas.knowledge.official_doc'].create({
            'feature_id': self.f_plain.id, 'url': 'https://www.odoo.com/documentation/18.0/s',
            'state': 'approved'})
        self.pkg._knowledge_rebuild_coverage()
        rows = self.env['corpaas.knowledge.coverage'].search([('package_id', '=', self.pkg.id)])
        status = {r.feature_id: r.status for r in rows}
        self.assertEqual(status[self.f_plain], 'official')
        self.assertEqual(status[self.f_custom], 'missing', '改過的官方畫面要自己寫說明')
        self.assertEqual(status[self.f_own], 'missing')
        self.assertEqual(rows[0].status, 'missing', '缺說明的排前面')
        self.assertAlmostEqual(self.pkg.knowledge_coverage_rate, 33.3, places=1)

    def test_pending_metrics(self):
        self.env['corpaas.knowledge.selection'].create(
            {'package_id': self.pkg.id, 'kind': 'feature', 'feature_id': self.f_own.id})
        self.assertEqual(self.pkg.knowledge_pending_count, 1)
        self.assertGreaterEqual(self.pkg.knowledge_pending_days, 0.0)

    def test_unmatched_queries_clustered_into_gaps(self):
        Log = self.env['corpaas.knowledge.help.log']
        logs = Log.create([{'package_id': self.pkg.id, 'query': q, 'hits': 0}
                           for q in ('怎麼做會員點數', '點數怎麼兌換', '可以排班嗎')])
        Ai = type(self.env['corpaas.knowledge.ai'])
        with patch.object(Ai, 'ask', lambda s, purpose, prompt, **kw: {'items': [
                {'query': q, 'key': None} for q in logs.mapped('query')]}):
            Log._cron_feed_misses()
        self.assertTrue(all(logs.mapped('unmatched')))
        with patch.object(Ai, 'ask', lambda s, purpose, prompt, **kw: {'topics': [
                {'topic': '會員點數', 'queries': ['怎麼做會員點數', '點數怎麼兌換']},
                {'topic': '排班', 'queries': ['可以排班嗎']}]}):
            Log._cron_cluster_gaps()
        gaps = self.env['corpaas.knowledge.gap'].search([('package_id', '=', self.pkg.id)])
        self.assertEqual(sorted(gaps.mapped('query_count')), [1, 2])
        self.assertTrue(all(logs.mapped('clustered')))


@tagged('post_install', '-at_install')
class TestFlowNaming(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pkg = cls.env['infrastructure.solution.package'].create({
            'product_tmpl_id': cls.env['product.template'].create(
                {'name': 'FN 方案', 'type': 'service'}).id})
        cls.f = cls.env['corpaas.knowledge.feature'].create({
            'feature_key': 'x.action:o', 'module': 'x', 'kind': 'action', 'anchor': 'o',
            'name': 'o', 'model': 'x.order', 'package_ids': [(4, cls.pkg.id)]})
        cls.flow = cls.env['corpaas.knowledge.flow'].create({
            'model': 'x.order', 'state_field': 'state', 'structure_hash': 'h1',
            'package_ids': [(4, cls.pkg.id)], 'feature_ids': [(4, cls.f.id)]})

    def _name(self, item):
        Ai = type(self.env['corpaas.knowledge.ai'])
        with patch.object(Ai, 'ask', lambda s, purpose, prompt, **kw: {'items': [item]}):
            return self.pkg._knowledge_flow_names('tok')

    def test_flow_proposal_approval_names_and_attaches_capability(self):
        cap = self.env['corpaas.knowledge.capability'].create({'name': '接單', 'code': 'take'})
        sel = self._name({'model': 'x.order', 'name': '訂單處理', 'summary': '從報價到成交',
                          'capability': 'take'})
        self.assertEqual((sel.kind, sel.flow_id, sel.capability_id), ('flow', self.flow, cap))
        self.assertFalse(self.pkg._knowledge_flow_names('tok'), '已有待審提案：先不再問')
        sel._knowledge_approve()
        self.assertEqual(self.flow.ai_name, '訂單處理')
        self.assertEqual(self.flow.name, '訂單處理')
        self.assertEqual(self.flow.named_hash, 'h1')
        self.assertIn(self.f, cap.feature_ids, '整個流程的功能點一次掛進能力')
        self.assertIn(self.pkg, cap.package_ids)
        outlines = cap._knowledge_flow_outlines(self.pkg)
        self.assertEqual(outlines[0]['name'], '訂單處理')

    def test_flow_name_never_becomes_capability(self):
        sel = self._name({'model': 'x.order', 'name': '訂單處理', 'capability': None})
        before = self.env['corpaas.knowledge.capability'].search_count([])
        sel._knowledge_approve()
        self.assertEqual(self.env['corpaas.knowledge.capability'].search_count([]), before,
                         '流程名稱不是能力名稱：沒提 new_capability 就不建能力')
        self.assertFalse(self.flow.capability_id)

    def test_flow_batch_approval(self):
        sel = self.env['corpaas.knowledge.selection'].create(
            {'package_id': self.pkg.id, 'kind': 'feature', 'feature_id': self.f.id})
        self.flow.action_approve_proposals()
        self.assertEqual(sel.state, 'approved')

    def test_flow_joins_capability_owning_most_features_in_batch(self):
        """實機：能力提案與流程提案一起核准，流程另建了「銷售管理」等 6 個重複能力。"""
        Sel = self.env['corpaas.knowledge.selection']
        flow_sel = self._name({'model': 'x.order', 'name': '訂單處理',
                               'new_capability': '銷售管理'})
        cap_sel = Sel.create({'package_id': self.pkg.id, 'kind': 'capability',
                              'proposal_json': json.dumps({'new_capability': '銷售',
                                                           'features': [self.f.feature_key]})})
        before = self.env['corpaas.knowledge.capability'].search_count([])
        (flow_sel | cap_sel)._knowledge_approve()   # 流程排在前面也一樣：能力先核准
        self.assertEqual(self.env['corpaas.knowledge.capability'].search_count([]), before + 1,
                         '只建「銷售」，流程掛上它，不另建「銷售管理」')
        self.assertEqual(self.flow.capability_id, cap_sel.capability_id)

    def test_flow_naming_reuses_waiting_capability_names(self):
        Sel = self.env['corpaas.knowledge.selection']
        Sel.create({'package_id': self.pkg.id, 'kind': 'capability',
                    'proposal_json': json.dumps({'new_capability': '銷售'})})
        prompts = []
        Ai = type(self.env['corpaas.knowledge.ai'])

        def ask(s, purpose, prompt, **kw):
            prompts.append(prompt)
            return {'items': [{'model': 'x.order', 'name': '訂單處理', 'capability': '銷售'}]}

        with patch.object(Ai, 'ask', ask):
            sel = self.pkg._knowledge_flow_names('tok')
        self.assertIn('待審的能力提案：銷售', prompts[0])
        self.assertEqual(json.loads(sel.proposal_json)['new_capability'], '銷售',
                         '名稱填在 code 欄也照收')
