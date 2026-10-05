# -*- coding: utf-8 -*-
"""方案屬性層：兩個方案共用同一個功能點／開關／流程時，依黃金庫而異的值互不覆蓋。"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPackageLayer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Pkg = cls.env['infrastructure.solution.package']
        Tmpl = cls.env['product.template']
        cls.a = Pkg.create({'product_tmpl_id': Tmpl.create({'name': 'PL A', 'type': 'service'}).id})
        cls.b = Pkg.create({'product_tmpl_id': Tmpl.create({'name': 'PL B', 'type': 'service'}).id})
        F = cls.env['corpaas.knowledge.feature']
        cls.f = F.create({'feature_key': 'sale.action:pl', 'module': 'sale', 'kind': 'action',
                          'anchor': 'pl', 'name': 'pl', 'model': 'x.pl',
                          'module_origin': 'odoo',
                          'package_ids': [(4, cls.a.id), (4, cls.b.id)]})
        Class = cls.env['corpaas.knowledge.feature.class']
        for pkg in (cls.a, cls.b):
            Class.create({'feature_id': cls.f.id, 'package_id': pkg.id,
                          'classification': 'std_base'})

    def test_usage_is_per_package(self):
        self.f.class_for(self.a).write({'usage_score': 10, 'usage_source': 'measured'})
        self.f.class_for(self.b).write({'usage_score': 3, 'usage_source': 'model'})
        self.f._sync_global_aggregates()
        self.assertEqual(self.f.attr_for(self.a, 'usage_score'), 10)
        self.assertEqual(self.f.attr_for(self.b, 'usage_score'), 3)
        self.assertEqual(self.f.usage_score, 10, '全域只當彙總：取最大')

    def test_customized_is_per_package(self):
        self.f.class_for(self.a).write({'customized': True, 'custom_elements': '["field:x"]'})
        self.assertTrue(self.f.attr_for(self.a, 'customized'))
        self.assertFalse(self.f.attr_for(self.b, 'customized'),
                         'A 的黃金庫改過，不代表 B 也改過')
        # 說明書候選：B 沒改過的官方畫面不寫文章，A 改過的要寫
        if 'corpaas.knowledge.article' in self.env:
            Hooks = self.env['corpaas.knowledge.hooks']
            cap = self.env['corpaas.knowledge.capability'].create(
                {'name': 'PL cap', 'feature_ids': [(4, self.f.id)],
                 'package_ids': [(4, self.a.id), (4, self.b.id)]})
            self.a.knowledge_capability_ids = [(4, cap.id)]
            self.b.knowledge_capability_ids = [(4, cap.id)]
            self.assertIn(self.f, Hooks._manual_candidates(self.a))
            self.assertNotIn(self.f, Hooks._manual_candidates(self.b))
            # 方案勾了「原生畫面也製作操作說明」：沒改過的官方畫面照樣寫（原生功能導覽型方案）
            self.b.knowledge_document_native = True
            self.assertIn(self.f, Hooks._manual_candidates(self.b))
            self.a.knowledge_document_native = False
            self.assertIn(self.f, Hooks._manual_candidates(self.a), 'A 是因為改過才寫，與開關無關')

    def test_toggle_state_is_per_package(self):
        T = self.env['corpaas.knowledge.toggle']
        t = T.create({'name': 'module_x_pl', 'kind': 'module', 'target': 'x_pl',
                      'downstream': 'x_last', 'package_ids': [(4, self.a.id), (4, self.b.id)]})
        S = self.env['corpaas.knowledge.toggle.state']
        S.create({'toggle_id': t.id, 'package_id': self.a.id, 'downstream': 'x_bom_a'})
        S.create({'toggle_id': t.id, 'package_id': self.b.id, 'downstream': ''})
        Pkg = type(self.a)
        with patch.object(Pkg, '_provision_module_names', lambda s: ['x_bom_a', 'x_last']):
            self.assertEqual(t.downstream_bom(self.a), ['x_bom_a'])
            self.assertEqual(t.downstream_bom(self.b), [],
                             '用 B 自己的狀態，不是全域（最近一次）的值')

    def test_sync_toggles_writes_per_package_state(self):
        data = lambda down: [{'name': 'module_x_sync', 'kind': 'module', 'target': 'x_sync',
                              'module': 'x_sync', 'label': 'X', 'path': ['銷售', 'X'],
                              'downstream': down, 'value': 'on'}]
        now = '2026-10-05 00:00:00'
        self.a._knowledge_sync_toggles(data(['m_a']), set(), now, 'tok')
        self.b._knowledge_sync_toggles(data(['m_b']), set(), now, 'tok')
        t = self.env['corpaas.knowledge.toggle'].search([('name', '=', 'module_x_sync')])
        self.assertEqual(len(t), 1)
        self.assertEqual(t.state_for(self.a).downstream, 'm_a')
        self.assertEqual(t.state_for(self.b).downstream, 'm_b')
        self.a._knowledge_sync_toggles([], set(), now, 'tok')
        self.assertFalse(t.state_for(self.a), '方案不再開啟：它的狀態一起移除')
        self.assertTrue(t.state_for(self.b))

    def test_flow_transitions_survive_other_package(self):
        flow = self.env['corpaas.knowledge.flow'].create(
            {'model': 'x.pl', 'state_field': 'state'})
        feats = self.f
        da = {'buttons': [{'name': 'act_a', 'visible': ['draft'], 'targets': ['done']}]}
        db = {'buttons': [{'name': 'act_b', 'visible': ['draft'], 'targets': ['done']}]}
        self.a._knowledge_flow_transitions(flow, da, feats)
        h1 = flow.structure_hash
        self.b._knowledge_flow_transitions(flow, db, feats)
        names = set(flow.transition_ids.mapped('button_name'))
        self.assertEqual(names, {'act_a', 'act_b'}, 'B 推不出 act_a，不能把 A 的轉換刪掉')
        h2 = flow.structure_hash
        self.a._knowledge_flow_transitions(flow, da, feats)
        self.assertEqual(flow.structure_hash, h2, '輪流更新時結構雜湊不再來回跳')
        self.assertNotEqual(h1, h2)
        # A 的程式改了、不再有 act_a：只拿掉 A；沒有任何方案推得出就刪
        self.a._knowledge_flow_transitions(flow, {'buttons': []}, feats)
        self.assertNotIn('act_a', flow.transition_ids.mapped('button_name'))

    def test_transition_usage_is_per_package(self):
        flow = self.env['corpaas.knowledge.flow'].create(
            {'model': 'x.pl2', 'state_field': 'state'})
        t = self.env['corpaas.knowledge.flow.transition'].create(
            {'flow_id': flow.id, 'from_value': 'a', 'to_value': 'b', 'button_name': 'x'})
        t._set_package_usage(self.a, 7)
        t._set_package_usage(self.b, 5)
        self.assertEqual((t.usage_count, t.ev_tenant), (12, True))
        t._set_package_usage(self.a, 0)
        self.assertEqual(t._package_usage(self.b), 5, '重設 A 不影響 B')
        self.assertEqual(t.usage_count, 5)


@tagged('post_install', '-at_install')
class TestCleanup(TransactionCase):

    def test_gc_keeps_accounting_drops_payloads(self):
        Call = self.env['corpaas.knowledge.ai.call']
        old = Call.create({'purpose': 'classify_features', 'ok': True, 'cost_usd': 0.5,
                           'response_text': 'x' * 100})
        hit = Call.create({'purpose': 'classify_features', 'ok': True, 'cached': True})
        fresh = Call.create({'purpose': 'classify_features', 'ok': True, 'response_text': 'y'})
        self.env.cr.execute("UPDATE corpaas_knowledge_ai_call SET create_date = now() - "
                            "interval '120 days' WHERE id IN %s", (tuple((old | hit).ids),))
        self.env.invalidate_all()
        Call._gc_cache()
        self.assertTrue(old.exists() and not old.response_text and old.cost_usd == 0.5,
                        '帳留著，原始回應清掉')
        self.assertFalse(hit.exists(), '命中快取的零成本紀錄過期刪除')
        self.assertEqual(fresh.response_text, 'y')


@tagged('post_install', '-at_install')
class TestFreshCursorBookkeep(TransactionCase):
    """獨立游標簿記真的寫進去（實機在 odoo shell 佇列裡靜默遺失過）。"""

    def test_bookkeep_persists_through_fresh_cursor(self):
        from ..services import txn
        pkg = self.env['infrastructure.solution.package'].create({
            'product_tmpl_id': self.env['product.template'].create(
                {'name': 'BK', 'type': 'service'}).id})
        self.env.flush_all()
        self.registry.enter_test_mode(self.env.cr)
        self.addCleanup(self.registry.leave_test_mode)
        with patch.object(txn, 'in_tests', lambda env: False):
            pkg.with_context(knowledge_fresh_cursor=True)._knowledge_bookkeep(
                {'knowledge_last_token': 'fresh-ok'})
        self.env.cr.execute('SELECT knowledge_last_token FROM infrastructure_solution_package '
                            'WHERE id = %s', (pkg.id,))
        self.assertEqual(self.env.cr.fetchone()[0], 'fresh-ok')


@tagged('post_install', '-at_install')
class TestBookkeepOutsideRefresh(TransactionCase):
    """短交易（按鈕、上架）裡簿記寫在自己的交易，不另開游標（否則撞 40001）。"""

    def test_button_writes_in_own_transaction(self):
        from ..services import txn
        pkg = self.env['infrastructure.solution.package'].create({
            'product_tmpl_id': self.env['product.template'].create(
                {'name': 'BK2', 'type': 'service'}).id})
        opened = []
        orig = type(self.registry).cursor
        with patch.object(txn, 'in_tests', lambda env: False), \
                patch.object(type(self.registry), 'cursor',
                             lambda s, *a, **k: opened.append(1) or orig(s, *a, **k)):
            pkg.write({'knowledge_enabled': True})
            pkg._knowledge_bookkeep({'knowledge_pending_full': True})
        self.assertFalse(opened, '不在知識更新作業裡：不另開游標')
        self.assertTrue(pkg.knowledge_pending_full)
