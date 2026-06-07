# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""互斥閘道條件路由端到端：依 conditionExpression 選分支。"""
from odoo.tests.common import TransactionCase, tagged

# Start → XOR →（cond 1>0 → T_yes）/（default → T_no）。第一條條件成立 → 走 T_yes。
XOR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d">
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="Start"/>
    <bpmn:exclusiveGateway id="G1" name="判斷"/>
    <bpmn:userTask id="T_yes" name="是"/>
    <bpmn:userTask id="T_no" name="否"/>
    <bpmn:endEvent id="End"/>
    <bpmn:sequenceFlow id="f0" sourceRef="Start" targetRef="G1"/>
    <bpmn:sequenceFlow id="fy" sourceRef="G1" targetRef="T_yes">
      <bpmn:conditionExpression>1 &gt; 0</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="fn" sourceRef="G1" targetRef="T_no"/>
    <bpmn:sequenceFlow id="fy2" sourceRef="T_yes" targetRef="End"/>
    <bpmn:sequenceFlow id="fn2" sourceRef="T_no" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""

XOR_FALSE_XML = XOR_XML.replace('1 &gt; 0', '1 &lt; 0')  # 條件不成立 → 走預設 T_no


@tagged('post_install', '-at_install')
class TestExclusiveRouting(TransactionCase):

    def _build(self, xml):
        ICP = self.env['ir.config_parameter'].sudo()
        for f in ('basic_approval', 'conditional'):
            ICP.set_param('dobtor_approval.%s' % f, 'True')
        proc = self.env['bpmn.executable.process'].create({'name': 'p', 'xml': xml})
        for eid in ('T_yes', 'T_no'):
            cfg = proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == eid)
            role = self.env['bpmn.role'].create({
                'process_id': proc.id, 'name': eid,
                'resolver_type': 'specific_user',
                'user_ids': [(6, 0, [self.env.user.id])]})
            cfg.write({'role_id': role.id, 'approval_mode': 'any'})
        proc.action_publish()
        return proc

    def _pending_at(self, inst, eid):
        return inst.activity_link_ids.filtered(
            lambda l: l.bpmn_element_id == eid and l.decision == 'pending')

    def test_condition_true_routes_yes(self):
        inst = self._build(XOR_XML).start()
        self.assertTrue(self._pending_at(inst, 'T_yes'), '條件成立應走 T_yes')
        self.assertFalse(self._pending_at(inst, 'T_no'), '不應走 T_no')

    def test_condition_false_routes_default(self):
        inst = self._build(XOR_FALSE_XML).start()
        self.assertTrue(self._pending_at(inst, 'T_no'), '條件不成立應走預設 T_no')
        self.assertFalse(self._pending_at(inst, 'T_yes'))
