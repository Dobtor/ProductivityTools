# -*- coding: utf-8 -*-
"""任務流程推導（K13–K14）：在測試庫內執行同一份 flow_script。"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..services import remote
from . import test_refresh as base


@tagged('post_install', '-at_install')
class TestFlows(base._RefreshBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'sale.order' not in cls.env:
            return
        F = cls.env['corpaas.knowledge.feature']
        cls.f_order = F.create({
            'feature_key': 'sale.action:sale.action_orders', 'module': 'sale',
            'kind': 'action', 'anchor': 'sale.action_orders', 'name': '訂單',
            'model': 'sale.order', 'package_ids': [(4, cls.pkg.id)]})
        cls.f_confirm = F.create({
            'feature_key': 'sale.button:sale.view_order_form/button[action_confirm]',
            'module': 'sale', 'kind': 'button',
            'anchor': 'sale.view_order_form/button[action_confirm]', 'name': '確認',
            'model': 'sale.order', 'button_name': 'action_confirm', 'view_mode': 'form',
            'package_ids': [(4, cls.pkg.id)]})

    def setUp(self):
        super().setUp()
        if 'sale.order' not in self.env:
            self.skipTest('沒有安裝 sale')

    def _flows(self):
        with patch.object(remote, 'shell_json', side_effect=self._exec_shell):
            return self.pkg._knowledge_flows(self.master.golden, 'tok')

    def test_sale_order_flow_derived_statically(self):
        flows = self._flows()
        flow = flows.filtered(lambda f: f.model == 'sale.order')
        self.assertEqual(len(flow), 1)
        self.assertEqual(flow.state_field, 'state')
        self.assertIn('sale', flow.step_ids.mapped('value'))
        confirm = flow.transition_ids.filtered(lambda t: t.button_name == 'action_confirm')
        self.assertTrue(confirm, '確認按鈕要成為轉換')
        self.assertIn('sale', confirm.mapped('to_value'),
                      'AST 要追到 helper 寫入的 state=sale')
        self.assertTrue(all(t.ev_static for t in confirm))
        self.assertEqual(confirm[:1].button_feature_id, self.f_confirm)
        self.assertIn(self.f_order, flow.feature_ids)
        self.assertIn(self.pkg, flow.package_ids)

    def test_rerun_is_idempotent(self):
        first = self._flows().filtered(lambda f: f.model == 'sale.order')
        n = len(first.transition_ids)
        second = self._flows().filtered(lambda f: f.model == 'sale.order')
        self.assertEqual(first, second)
        self.assertEqual(len(second.transition_ids), n)

    def test_tenant_evidence_survives_static_loss(self):
        flow = self._flows().filtered(lambda f: f.model == 'sale.order')
        t = flow.transition_ids.create({'flow_id': flow.id, 'from_value': 'x',
                                        'to_value': 'y', 'button_name': '',
                                        'ev_tenant': True, 'usage_count': 3})
        self._flows()
        self.assertTrue(t.exists(), '租戶觀察到的轉換不因靜態推不出來而刪除')

    def test_flow_removed_from_package_when_model_leaves(self):
        flow = self._flows().filtered(lambda f: f.model == 'sale.order')
        (self.f_order | self.f_confirm).write({'package_ids': [(3, self.pkg.id)]})
        self._flows()
        self.assertNotIn(self.pkg, flow.package_ids)



@tagged('post_install', '-at_install')
class TestFlowObservations(TransactionCase):
    """截圖時觀察到的轉換（K15）。"""

    def test_observation_confirms_or_adds_transition(self):
        flow = self.env['corpaas.knowledge.flow'].create(
            {'model': 'x.obs', 'state_field': 'state'})
        T = self.env['corpaas.knowledge.flow.transition']
        known = T.create({'flow_id': flow.id, 'from_value': 'draft', 'to_value': 'done',
                          'button_name': 'action_done', 'ev_static': True})
        self.env['corpaas.knowledge.flow']._knowledge_record_observations('x.obs', [
            {'button': 'action_done', 'from': 'draft', 'to': 'done'},
            {'button': 'action_reopen', 'from': 'done', 'to': 'draft'},
            {'button': 'noop', 'from': 'draft', 'to': 'draft'},
        ])
        self.assertTrue(known.ev_shot)
        new = flow.transition_ids.filtered(lambda t: t.button_name == 'action_reopen')
        self.assertTrue(new.ev_shot and not new.ev_static)
        self.assertFalse(flow.transition_ids.filtered(lambda t: t.button_name == 'noop'))
