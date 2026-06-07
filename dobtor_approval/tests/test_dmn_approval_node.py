# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""DMN 簽核節點端到端：user_task 以 DMN 決策（approver 輸出）解析簽核人鏈。"""
from odoo.tests.common import TransactionCase, tagged

# 單關 approver 決策：金額>=0 → 直屬主管。輸入用 number(amount) 容忍常數綁定的字串。
APPROVER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="da" name="da" namespace="http://dobtor/dmn">
  <decision id="Dec" name="核決鏈">
    <decisionTable id="DT" hitPolicy="COLLECT">
      <input id="i"><inputExpression typeRef="number"><text>number(amount)</text></inputExpression></input>
      <output id="ores" name="resolver" typeRef="string"/>
      <output id="olvl" name="level" typeRef="number"/>
      <rule><inputEntry><text>&gt;= 0</text></inputEntry>
            <outputEntry><text>"direct_manager"</text></outputEntry><outputEntry><text>1</text></outputEntry></rule>
    </decisionTable>
  </decision>
  <inputData id="ID" name="amount"/>
</definitions>"""

PROC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d">
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="Start"/>
    <bpmn:userTask id="T1" name="核決"/>
    <bpmn:endEvent id="End"/>
    <bpmn:sequenceFlow id="f0" sourceRef="Start" targetRef="T1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="T1" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""


@tagged('post_install', '-at_install')
class TestDmnApprovalNode(TransactionCase):

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        for f in ('basic_approval', 'dmn', 'dmn_decision_table'):
            ICP.set_param('dobtor_approval.%s' % f, 'True')
        self.mgr = self.env['res.users'].create({'name': 'Mgr', 'login': 'mgr_dmnnode_t'})
        self.app = self.env['res.users'].create({'name': 'App', 'login': 'app_dmnnode_t'})
        mgr_emp = self.env['hr.employee'].create({'name': 'Mgr', 'user_id': self.mgr.id})
        self.env['hr.employee'].create(
            {'name': 'App', 'user_id': self.app.id, 'parent_id': mgr_emp.id})

        self.defn = self.env['dmn.definitions'].create({'name': 'da', 'dmn_xml': APPROVER_XML})
        self.env['dmn.input.binding'].create({
            'definitions_id': self.defn.id, 'variable': 'amount',
            'source_kind': 'constant', 'constant_value': '100000'})
        self.decision = self.defn.decision_ids[:1]

        self.proc = self.env['bpmn.executable.process'].create({'name': 'p', 'xml': PROC_XML})
        cfg = self.proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == 'T1')
        role = self.env['bpmn.role'].create({
            'process_id': self.proc.id, 'name': 'r',
            'resolver_type': 'dmn_decision', 'decision_id': self.decision.id})
        cfg.write({'role_id': role.id, 'approval_mode': 'any'})

    def test_dmn_node_resolves_direct_manager(self):
        self.proc.action_publish()
        self.assertEqual(self.proc.state, 'published')
        inst = self.proc.start(applicant=self.app)
        self.assertNotEqual(inst.state, 'incident', inst.incident_message or '')
        links = inst.activity_link_ids.filtered(lambda l: l.bpmn_element_id == 'T1')
        self.assertIn(self.mgr, links.mapped('approver_user_id'),
                      'DMN approver 鏈 direct_manager 應解析為申請人主管')
