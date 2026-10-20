# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""發佈守門：結構校驗、能力開關、版本號與狀態轉換。"""
from odoo.exceptions import AccessError, UserError

from .common import ApprovalTestCase, LINEAR_XML, bpmn, flow

ROLE = {'T1': {'resolver_type': 'direct_manager'}}


class TestPublishGuard(ApprovalTestCase):

    def test_publish_bumps_version_and_freezes(self):
        proc = self.make_process(roles=ROLE)
        self.assertEqual((proc.state, proc.definition_version), ('draft', 0))
        proc.action_publish()
        self.assertEqual((proc.state, proc.definition_version), ('published', 1))
        proc.action_publish()
        self.assertEqual(proc.definition_version, 2)

    def test_publish_requires_start_and_end(self):
        no_end = bpmn('<bpmn:startEvent id="S"/><bpmn:userTask id="T1"/>' + flow('f', 'S', 'T1'))
        with self.assertRaisesRegex(UserError, '結束'):
            self.make_process(xml=no_end, roles=ROLE, publish=True)
        no_start = bpmn('<bpmn:userTask id="T1"/><bpmn:endEvent id="E"/>' + flow('f', 'T1', 'E'))
        with self.assertRaisesRegex(UserError, '開始'):
            self.make_process(xml=no_start, roles=ROLE, publish=True)

    def test_user_task_needs_a_role(self):
        with self.assertRaisesRegex(UserError, '尚未綁定簽核角色'):
            self.make_process(publish=True)

    def test_service_task_and_business_rule_need_bindings(self):
        svc = bpmn('<bpmn:startEvent id="S"/><bpmn:serviceTask id="V" name="動作"/><bpmn:endEvent id="E"/>'
                   + flow('f1', 'S', 'V') + flow('f2', 'V', 'E'))
        self.env['ir.config_parameter'].sudo().set_param('dobtor_approval.action_gate', 'True')
        with self.assertRaisesRegex(UserError, '系統動作節點'):
            self.make_process(xml=svc, publish=True)
        br = bpmn('<bpmn:startEvent id="S"/><bpmn:businessRuleTask id="B" name="規則"/><bpmn:endEvent id="E"/>'
                  + flow('f1', 'S', 'B') + flow('f2', 'B', 'E'))
        for key in ('dmn', 'dmn_decision_table', 'dmn_business_rule'):
            self.env['ir.config_parameter'].sudo().set_param('dobtor_approval.%s' % key, 'True')
        with self.assertRaisesRegex(UserError, '商業規則節點'):
            self.make_process(xml=br, publish=True)

    def test_matrix_and_decision_roles_must_be_bound(self):
        self.env['ir.config_parameter'].sudo().set_param('dobtor_approval.authority_matrix', 'True')
        with self.assertRaisesRegex(UserError, '核決權限表'):
            self.make_process(roles={'T1': {'resolver_type': 'authority_matrix'}}, publish=True)
        with self.assertRaisesRegex(UserError, 'DMN'):
            self.make_process(roles={'T1': {'resolver_type': 'dmn_decision'}}, publish=True)

    def test_feature_switches_gate_publishing(self):
        par = bpmn('<bpmn:startEvent id="S"/><bpmn:parallelGateway id="G"/><bpmn:endEvent id="E"/>'
                   + flow('f1', 'S', 'G') + flow('f2', 'G', 'E'))
        with self.assertRaisesRegex(UserError, '平行'):
            self.make_process(xml=par, publish=True)
        self.env['ir.config_parameter'].sudo().set_param('dobtor_approval.parallel_gw', 'True')
        proc = self.make_process(xml=par, publish=True)
        self.assertEqual(proc.state, 'published')

    def test_role_and_node_level_features_are_scanned_too(self):
        # 會簽（cosign）：設在 node_config 上，不在 XML 裡
        self.env['ir.config_parameter'].sudo().set_param('dobtor_approval.cosign', 'False')
        proc = self.make_process(roles=ROLE)
        proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == 'T1').approval_mode = 'all'
        with self.assertRaisesRegex(UserError, '會簽'):
            proc.action_publish()
        # 運算式簽核人（expression_resolver）：設在 role 上
        proc2 = self.make_process(roles={'T1': {'resolver_type': 'expression', 'expression': 'applicant'}})
        with self.assertRaisesRegex(UserError, 'Python 運算式'):
            proc2.action_publish()

    def test_a_failed_publish_changes_nothing(self):
        proc = self.make_process()
        with self.assertRaises(UserError):
            proc.action_publish()
        self.assertEqual((proc.state, proc.definition_version), ('draft', 0))

    def test_only_published_processes_can_start(self):
        proc = self.make_process(roles=ROLE)
        with self.assertRaises(UserError):
            proc.start(applicant=self.staff)
        proc.action_publish()
        self.assertEqual(proc.start(applicant=self.staff).definition_version, 1)

    def test_archive(self):
        proc = self.make_process(roles=ROLE, publish=True)
        proc.action_archive_process()
        self.assertEqual((proc.state, proc.active), ('archived', False))
        with self.assertRaises(UserError):
            proc.start(applicant=self.staff)

    def test_designers_can_publish_plain_users_cannot(self):
        proc = self.make_process(roles=ROLE)
        with self.assertRaises(AccessError):
            proc.with_user(self.plain).action_publish()
        proc.with_user(self.designer).action_publish()
        self.assertEqual(proc.state, 'published')

    def test_instance_records_the_definition_version_only(self):
        """★ 實例只記版本號，沒有流程快照：之後改了定義，執行時用的是「現在」的 XML 與節點設定。"""
        proc = self.make_process(roles=ROLE, publish=True)
        inst = proc.start(applicant=self.staff)
        self.assertEqual(inst.definition_version, 1)
        self.assertFalse([f for f in inst._fields if 'snapshot' in f and f != 'gate_snapshot'])
        nodes, _flows = proc._build_graph()
        self.assertIn('T1', nodes)

    def test_process_with_running_instances_cannot_be_sent_back_to_draft(self):
        """有進行中實例時 action_set_draft 拒絕；實例結束後才可退回草稿。"""
        proc = self.make_process(roles=ROLE, publish=True)
        inst = proc.start(applicant=self.staff)
        with self.assertRaises(UserError):
            proc.with_user(self.designer).action_set_draft()
        self.assertEqual((proc.state, inst.state), ('published', 'running'))
        inst.action_cancel_instance()
        proc.with_user(self.designer).action_set_draft()
        self.assertEqual(proc.state, 'draft')

    def test_running_instance_follows_the_live_definition_not_a_snapshot(self):
        """★ 記錄現況：實例沒有流程快照，推進時用的是「現在」的 XML 與節點設定。

        啟動時只有一關 T1；之後（退回草稿 → 改結構 → 再發佈）多了第二關 T2，
        進行中的實例簽完 T1 就會走進啟動時根本不存在的 T2。第二期若要允許 AI 改定義，
        必須先有發布快照或在途單據政策（見 ai_bridge_approval_design_v1.md）。
        """
        two = bpmn('<bpmn:startEvent id="S"/><bpmn:userTask id="T1" name="主管"/>'
                   '<bpmn:userTask id="T2" name="新增的一關"/><bpmn:endEvent id="E"/>'
                   + flow('f1', 'S', 'T1') + flow('f2', 'T1', 'T2') + flow('f3', 'T2', 'E'))
        proc = self.make_process(roles=ROLE, publish=True)
        inst = proc.start(applicant=self.staff)
        self.assertEqual(inst.token_ids.filtered(lambda t: t.state == 'active').bpmn_element_id, 'T1')
        proc.state = 'draft'      # 繞過 action_set_draft 的在途守衛，才能重現「無快照」
        proc.save_xml(two)
        proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == 'T2').role_id = self.make_role(
            process_id=proc.id, resolver_type='specific_user', user_ids=[(6, 0, [self.ceo.id])])
        proc.action_publish()
        inst.activity_link_ids.filtered(lambda l: l.decision == 'pending')._on_activity_done()
        self.assertEqual(inst.state, 'running')
        self.assertEqual(inst.token_ids.filtered(lambda t: t.state == 'active').bpmn_element_id, 'T2')
        self.assertEqual(inst.definition_version, 1)             # 實例仍然只記著 v1
        self.assertEqual(proc.definition_version, 2)

    def test_capability_level_is_informational_only(self):
        """★ 記錄現況：流程上的 capability_level（T0–T6「能力上限」）發佈時不被檢查。

        它只由精靈在建流程時估算寫入；真正守門的是能力開關（feature_registry）。
        與客戶方案階梯 L1–L4 不是同一個東西。
        """
        self.env['ir.config_parameter'].sudo().set_param('dobtor_approval.cosign', 'True')
        proc = self.make_process(roles=ROLE, capability_level='T0')
        proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == 'T1').approval_mode = 'all'
        proc.action_publish()                                    # 會簽需要 T1 以上，仍然發佈成功
        self.assertEqual((proc.state, proc.capability_level), ('published', 'T0'))
