# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""閘道 join 並發測試：並行 split → 兩關 → join。

驗證上輪重寫的 join 同步（可達性分析 + _resume_joins）：
- 兩分支匯流後僅推進一次（無雙重觸發）、實例正常完成（無死結）。
本機無法實跑此並發核心，故以此測試於使用者實例把關。
"""
from odoo.tests.common import TransactionCase, tagged

PAR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:startEvent id="Start" name="開始"/>
    <bpmn:parallelGateway id="Split" name="分岔"/>
    <bpmn:userTask id="T1" name="關1"/>
    <bpmn:userTask id="T2" name="關2"/>
    <bpmn:parallelGateway id="Join" name="匯流"/>
    <bpmn:endEvent id="End" name="結束"/>
    <bpmn:sequenceFlow id="f0" sourceRef="Start" targetRef="Split"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Split" targetRef="T1"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Split" targetRef="T2"/>
    <bpmn:sequenceFlow id="f3" sourceRef="T1" targetRef="Join"/>
    <bpmn:sequenceFlow id="f4" sourceRef="T2" targetRef="Join"/>
    <bpmn:sequenceFlow id="f5" sourceRef="Join" targetRef="End"/>
  </bpmn:process>
</bpmn:definitions>"""


@tagged('post_install', '-at_install')
class TestGatewayJoin(TransactionCase):

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('dobtor_approval.parallel_gw', 'True')
        ICP.set_param('dobtor_approval.basic_approval', 'True')
        self.user = self.env.user
        self.proc = self.env['bpmn.executable.process'].create({
            'name': '並行測試', 'xml': PAR_XML})
        # 兩關綁簽核人＝測試使用者（specific_user）
        for eid in ('T1', 'T2'):
            cfg = self.proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == eid)
            role = self.env['bpmn.role'].create({
                'process_id': self.proc.id, 'name': eid,
                'resolver_type': 'specific_user',
                'user_ids': [(6, 0, [self.user.id])]})
            cfg.write({'role_id': role.id, 'approval_mode': 'any'})

    def _approve(self, element_id):
        link = self.inst.activity_link_ids.filtered(
            lambda l: l.bpmn_element_id == element_id and l.decision == 'pending')[:1]
        self.assertTrue(link, '應有 %s 的待簽 link' % element_id)
        link._on_activity_done()

    def test_parallel_split_join_completes(self):
        self.proc.action_publish()
        self.assertEqual(self.proc.state, 'published')
        self.inst = self.proc.start(applicant=self.user)

        # split 後兩分支各有待簽
        self.assertTrue(self.inst.activity_link_ids.filtered(
            lambda l: l.bpmn_element_id == 'T1' and l.decision == 'pending'))
        self.assertTrue(self.inst.activity_link_ids.filtered(
            lambda l: l.bpmn_element_id == 'T2' and l.decision == 'pending'))

        # 簽完第一關 → join 仍等第二關（不應完成、不應死結）
        self._approve('T1')
        self.assertEqual(self.inst.state, 'running', '第一關簽完不應完成')

        # 簽完第二關 → join 匯流推進 → 實例完成
        self._approve('T2')
        self.assertEqual(self.inst.state, 'approved', 'join 匯流後實例應完成（無死結）')
        # 無殘留 active token（無雙重觸發殘留）
        self.assertFalse(self.inst.token_ids.filtered(lambda t: t.state == 'active'))
        self.assertNotEqual(self.inst.state, 'incident')
