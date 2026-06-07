# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""businessRuleTask 端到端：求值 DMN 決策 → 寫入實例 ctx（dmn_outputs）。"""
import json

from odoo.tests.common import TransactionCase, tagged

# literal 決策：輸出固定字串（無需輸入），驗證寫入 dmn_outputs。
LIT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="db" name="db" namespace="http://dobtor/dmn">
  <decision id="DecBR" name="評等">
    <literalExpression><text>"PASS"</text></literalExpression>
  </decision>
</definitions>"""

PROC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d">
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="Start"/>
    <bpmn:businessRuleTask id="BR1" name="評等"/>
    <bpmn:endEvent id="End"/>
    <bpmn:sequenceFlow id="f0" sourceRef="Start" targetRef="BR1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="BR1" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""


@tagged('post_install', '-at_install')
class TestBusinessRule(TransactionCase):

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        for f in ('basic_approval', 'dmn', 'dmn_decision_table', 'dmn_business_rule',
                  'action_gate'):
            ICP.set_param('dobtor_approval.%s' % f, 'True')
        self.defn = self.env['dmn.definitions'].create({'name': 'db', 'dmn_xml': LIT_XML})
        self.decision = self.defn.decision_ids[:1]
        self.proc = self.env['bpmn.executable.process'].create({'name': 'p', 'xml': PROC_XML})
        cfg = self.proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == 'BR1')
        cfg.write({'dmn_decision_id': self.decision.id})

    def test_business_rule_writes_ctx(self):
        self.proc.action_publish()
        inst = self.proc.start()
        self.assertNotEqual(inst.state, 'incident', inst.incident_message or '')
        # 商業規則為 pass-through，實例應一路走到完成
        self.assertEqual(inst.state, 'approved')
        outputs = json.loads(inst.dmn_outputs or '{}')
        self.assertEqual(outputs.get('評等'), 'PASS',
                         'businessRuleTask 求值結果應寫入實例 dmn_outputs')

    def test_get_ctx_value(self):
        self.proc.action_publish()
        inst = self.proc.start()
        self.assertEqual(inst.get_ctx_value('評等'), 'PASS')
