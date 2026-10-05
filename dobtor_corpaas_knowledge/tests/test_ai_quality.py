# -*- coding: utf-8 -*-
"""AI 歸類的品質與去重（K4–K12）：能力代碼、提案去重、新能力合併、跨方案沿用、快取。"""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..services import hub_client, search_lib


@tagged('post_install', '-at_install')
class TestSearchLibHelpers(TransactionCase):

    def test_similarity_is_symmetric(self):
        self.assertEqual(search_lib.similarity('訂單管理', '銷售訂單管理'),
                         search_lib.similarity('銷售訂單管理', '訂單管理'))
        self.assertGreater(search_lib.similarity('訂單管理', '銷售訂單管理'), 0.5)
        self.assertEqual(search_lib.similarity('', '訂單'), 0.0)

    def test_merge_lines_dedupes_normalized(self):
        self.assertEqual(search_lib.merge_lines('建立報價\n查詢訂單', ['建立 報價', '取消訂單']),
                         '建立報價\n查詢訂單\n取消訂單')


@tagged('post_install', '-at_install')
class TestAiQuality(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Tmpl = cls.env['product.template']
        Pkg = cls.env['infrastructure.solution.package']
        cls.pkg = Pkg.create({'product_tmpl_id': Tmpl.create(
            {'name': 'AQ 方案A', 'type': 'service'}).id, 'knowledge_enabled': True})
        cls.pkg_b = Pkg.create({'product_tmpl_id': Tmpl.create(
            {'name': 'AQ 方案B', 'type': 'service'}).id, 'knowledge_enabled': True})
        cls.Cap = cls.env['corpaas.knowledge.capability']
        cls.Sel = cls.env['corpaas.knowledge.selection']
        cls.Feature = cls.env['corpaas.knowledge.feature']

    def _feature(self, key, origin='custom', usage=0, **kw):
        module, rest = key.split('.', 1)
        return self.Feature.create(dict({
            'feature_key': self.Feature.make_key(module, 'action', rest),
            'module': module, 'kind': 'action', 'anchor': rest,
            'name': rest, 'module_origin': origin, 'usage_score': usage,
            'package_ids': [(4, self.pkg.id)]}, **kw))

    # K4 ------------------------------------------------------------------
    def test_capability_always_gets_unique_code(self):
        a = self.Cap.create({'name': '訂單管理'})
        b = self.Cap.create({'name': 'Order Management'})
        c = self.Cap.create({'name': 'Order Management'})
        self.assertTrue(a.code)
        self.assertEqual(b.code, 'order_management')
        self.assertNotEqual(b.code, c.code)

    def test_find_by_normalized_name(self):
        cap = self.Cap.create({'name': '訂單 管理'})
        self.assertEqual(self.Cap._knowledge_find_by_name('訂單管理'), cap)

    # K7 ------------------------------------------------------------------
    def test_upsert_updates_instead_of_duplicating(self):
        f = self._feature('x_aq.f1')
        vals = {'package_id': self.pkg.id, 'kind': 'feature', 'feature_id': f.id,
                'reason': 'r1', 'score': 1}
        a = self.Sel._knowledge_upsert(vals)
        b = self.Sel._knowledge_upsert(dict(vals, reason='r2', score=5))
        self.assertEqual(a, b)
        self.assertEqual((a.reason, a.score), ('r2', 5))

    def test_excluded_proposal_is_not_proposed_again(self):
        f = self._feature('x_aq.f2')
        vals = {'package_id': self.pkg.id, 'kind': 'feature', 'feature_id': f.id}
        a = self.Sel._knowledge_upsert(vals)
        a.action_exclude()
        self.assertEqual(self.Sel._knowledge_upsert(vals), a)
        self.assertEqual(self.Sel.search_count([('feature_id', '=', f.id)]), 1)

    def test_new_capability_proposals_merge_features(self):
        mk = lambda feats: {'package_id': self.pkg.id, 'kind': 'capability',
                            'proposal_json': json.dumps({'new_capability': '排班 管理',
                                                         'features': feats})}
        a = self.Sel._knowledge_upsert(mk(['k1']))
        b = self.Sel._knowledge_upsert(dict(mk(['k2']), proposal_json=json.dumps(
            {'new_capability': '排班管理', 'features': ['k2']})))
        self.assertEqual(a, b, '名稱正規化後相同＝同一個提案')
        self.assertEqual(json.loads(a.proposal_json)['features'], ['k1', 'k2'])

    # K8 ------------------------------------------------------------------
    def test_similar_capabilities_shown_and_used(self):
        cap = self.Cap.create({'name': '銷售訂單管理'})
        sel = self.Sel.create({'package_id': self.pkg.id, 'kind': 'capability',
                               'proposal_json': json.dumps({'new_capability': '訂單管理'})})
        self.assertIn(cap, sel.similar_capability_ids)
        sel.action_use_similar()
        self.assertEqual(sel.capability_id, cap)

    # K5 / K6 / K9 ----------------------------------------------------------
    def _classify(self, items):
        Ai = type(self.env['corpaas.knowledge.ai'])
        prompts = []

        def ask(s, purpose, prompt, **kw):
            prompts.append(prompt)
            return {'items': items}

        with patch.object(Ai, 'ask', ask):
            self.pkg._knowledge_ai_catalog(self.Feature, 'tok')
        return prompts

    def test_classify_can_use_global_capability(self):
        glob = self.Cap.create({'name': '庫存盤點', 'code': 'stock_count'})
        f = self._feature('x_aq.f3', classify_pending=True)
        prompts = self._classify([{'key': f.feature_key, 'capability': 'stock_count',
                                   'intents': ['盤點', '盤點', '庫存 盤點']}])
        self.assertIn('stock_count', prompts[0], '全域能力也要給 AI')
        sel = self.Sel.search([('feature_id', '=', f.id)])
        self.assertEqual(sel.capability_id, glob)
        self.assertTrue(f.ai_classified)
        self.assertFalse(f.classify_pending)
        self.assertEqual(f.intents, '盤點\n庫存 盤點', '同義詞去重')

    def test_cold_start_clusters_into_few_capabilities(self):
        """方案沒有能力、一次 20 個功能點：先分群，新能力只能用分出的名稱（實機曾提 71 個）。"""
        feats = [self._feature('x_aq.c%02d' % i, classify_pending=True) for i in range(20)]
        names = ['銷售報價', '庫存作業']
        items = [{'key': f.feature_key, 'new_capability': names[i % 2]} for i, f in
                 enumerate(feats[:18])]
        items.append({'key': feats[18].feature_key, 'new_capability': '銷售報價單設定'})
        items.append({'key': feats[19].feature_key, 'new_capability': '條碼分隔符設定'})
        Ai = type(self.env['corpaas.knowledge.ai'])
        prompts = []

        def ask(s, purpose, prompt, **kw):
            prompts.append(prompt)
            return {'capabilities': [{'name': n, 'outcome': n + '的成果'} for n in names],
                    'items': items}

        with patch.object(Ai, 'ask', ask):
            self.pkg._knowledge_ai_catalog(self.Feature, 'tok')
        self.assertIn('6–10 個業務能力', prompts[0])
        props = self.Sel.search([('package_id', '=', self.pkg.id), ('kind', '=', 'capability')])
        self.assertEqual(sorted(props.mapped('proposal_name')), sorted(names),
                         '只有分出來的兩個能力，不會一個功能點一個')
        sales = props.filtered(lambda p: p.proposal_name == '銷售報價')
        data = json.loads(sales.proposal_json)
        self.assertIn(feats[18].feature_key, data['features'], '清單外的名稱靠到最像的一群')
        self.assertEqual(data['outcome'], '銷售報價的成果')
        orphan = self.Sel.search([('feature_id', '=', feats[19].id)])
        self.assertTrue(orphan and not orphan.capability_id, '都不像的先不歸，不另開能力')

    def test_small_batch_does_not_cluster(self):
        f = self._feature('x_aq.s1', classify_pending=True)
        prompts = self._classify([{'key': f.feature_key, 'new_capability': '排班管理'}])
        self.assertNotIn('6–10 個業務能力', prompts[0])

    def test_similar_new_capabilities_grouped_into_one_proposal(self):
        f1 = self._feature('x_aq.g1', classify_pending=True)
        f2 = self._feature('x_aq.g2', classify_pending=True)
        f3 = self._feature('x_aq.g3', classify_pending=True)
        self._classify([
            {'key': f1.feature_key, 'new_capability': '排班管理'},
            {'key': f2.feature_key, 'new_capability': '排班 管理功能'},
            {'key': f3.feature_key, 'new_capability': '會員點數'},
        ])
        props = self.Sel.search([('package_id', '=', self.pkg.id), ('kind', '=', 'capability')])
        self.assertEqual(len(props), 2)
        shift = props.filtered(lambda p: '排班' in p.proposal_name)
        self.assertEqual(set(json.loads(shift.proposal_json)['features']),
                         {f1.feature_key, f2.feature_key})

    def test_new_capability_matching_existing_name_reuses_it(self):
        cap = self.Cap.create({'name': '排班管理'})
        f = self._feature('x_aq.g4', classify_pending=True)
        self._classify([{'key': f.feature_key, 'new_capability': '排班 管理'}])
        self.assertEqual(self.Sel.search([('feature_id', '=', f.id)]).capability_id, cap)

    # K10 -----------------------------------------------------------------
    def test_select_reserves_official_quota_but_prefers_own(self):
        own = [self._feature('x_own.o%d' % i, usage=1) for i in range(140)]
        off = [self._feature('sale.s%d' % i, origin='odoo', usage=999) for i in range(60)]
        Ai = type(self.env['corpaas.knowledge.ai'])
        prompts = []
        with patch.object(Ai, 'ask', lambda s, p, prompt, **kw: prompts.append(prompt) or {}), \
                patch.object(type(self.pkg), '_knowledge_master',
                             lambda s, raise_if_missing=True: True):
            self.pkg._knowledge_ai_select_run()
        sent_off = sum(1 for f in off if f.feature_key in prompts[0])
        sent_own = sum(1 for f in own if f.feature_key in prompts[0])
        self.assertEqual(sent_off, 30)
        self.assertEqual(sent_own, 120)

    # K11 -----------------------------------------------------------------
    def _inventory_into(self, pkg, feature):
        """模擬盤點把既有功能點加進 pkg。"""
        from ..services import remote
        item = {'module': feature.module, 'kind': feature.kind, 'anchor': feature.anchor,
                'name': feature.name, 'entries': []}
        golden = type('G', (), {'id': 0, 'name': 'g', 'instance_id': None})()
        Pkg = type(pkg)
        with patch.object(remote, 'shell_json', return_value={'features': [item]}), \
                patch.object(Pkg, '_provision_module_names', lambda s: [feature.module]), \
                patch.object(Pkg, '_knowledge_golden_installed',
                             lambda s, g, official_only=False: set()):
            pkg._knowledge_inventory(golden, 'tok')

    def test_classified_feature_reuses_mapping_in_new_package(self):
        cap = self.Cap.create({'name': '共用能力', 'package_ids': [(4, self.pkg_b.id)]})
        f = self._feature('x_aq.r1', ai_classified=True, capability_ids=[(4, cap.id)])
        self._inventory_into(self.pkg_b, f)
        self.assertFalse(f.classify_pending, '歸類過的不再請 AI')
        sel = self.Sel.search([('package_id', '=', self.pkg_b.id), ('feature_id', '=', f.id)])
        self.assertEqual(sel.state, 'approved')
        self.assertTrue(sel.auto_approved)

    def test_reuse_does_not_add_capability_to_package(self):
        cap = self.Cap.create({'name': '別的能力'})
        f = self._feature('x_aq.r2', ai_classified=True, capability_ids=[(4, cap.id)])
        self._inventory_into(self.pkg_b, f)
        sel = self.Sel.search([('package_id', '=', self.pkg_b.id), ('feature_id', '=', f.id)])
        self.assertEqual(sel.state, 'proposed', '能力不在這個方案上：留給人決定')
        self.assertNotIn(self.pkg_b, cap.package_ids)

    def test_unclassified_feature_goes_to_ai(self):
        f = self._feature('x_aq.r3')
        self._inventory_into(self.pkg_b, f)
        self.assertTrue(f.classify_pending)

    # K12 -----------------------------------------------------------------
    def test_stable_purposes_are_cached(self):
        calls = []

        def fake(url, key, purpose, prompt, context=None):
            calls.append(purpose)
            return '```json\n{"items": []}\n```', 0.01, 1

        with patch.object(hub_client, 'call', fake):
            Ai = self.env['corpaas.knowledge.ai']
            Ai.ask('classify_features', 'same prompt')
            Ai.ask('classify_features', 'same prompt')
            Ai.ask('manual_explore', 'same prompt')
            Ai.ask('manual_explore', 'same prompt')
        self.assertEqual(calls.count('classify_features'), 1)
        self.assertEqual(calls.count('manual_explore'), 2, '起草類不快取')
