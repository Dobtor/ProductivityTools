# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""編輯器後端 API：save_xml（只限草稿）與 set_node_config（只收白名單鍵）。"""
from odoo.exceptions import AccessError, UserError

from .common import ApprovalTestCase, LINEAR_XML, bpmn, flow

TWO_TASKS = bpmn('<bpmn:startEvent id="S"/><bpmn:userTask id="T1" name="主管"/>'
                 '<bpmn:userTask id="T2" name="財務"/><bpmn:endEvent id="E"/>'
                 + flow('f1', 'S', 'T1') + flow('f2', 'T1', 'T2') + flow('f3', 'T2', 'E'))


class TestSaveXml(ApprovalTestCase):

    def test_draft_saves_and_syncs_node_configs(self):
        proc = self.make_process()
        self.assertEqual(sorted(proc.node_config_ids.mapped('bpmn_element_id')), ['E', 'S', 'T1'])
        proc.with_user(self.designer).save_xml(TWO_TASKS)
        self.assertEqual(proc.xml, TWO_TASKS)
        self.assertEqual(sorted(proc.node_config_ids.mapped('bpmn_element_id')), ['E', 'S', 'T1', 'T2'])
        self.assertEqual(proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == 'T2').name, '財務')

    def test_removed_nodes_lose_their_config_but_keep_the_rest(self):
        proc = self.make_process(xml=TWO_TASKS, roles={'T1': {'resolver_type': 'direct_manager'}})
        proc.with_user(self.designer).save_xml(LINEAR_XML)
        self.assertEqual(sorted(proc.node_config_ids.mapped('bpmn_element_id')), ['E', 'S', 'T1'])
        self.assertEqual(proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == 'T1').role_id.resolver_type,
                         'direct_manager')                     # 既有節點的人工設定不被覆蓋

    def test_published_process_structure_is_frozen(self):
        proc = self.make_process(roles={'T1': {'resolver_type': 'direct_manager'}}, publish=True)
        with self.assertRaises(UserError):
            proc.with_user(self.designer).save_xml(TWO_TASKS)
        self.assertEqual(proc.xml, LINEAR_XML)

    def test_archived_and_malformed_are_refused(self):
        proc = self.make_process()
        with self.assertRaises(UserError):
            proc.with_user(self.designer).save_xml('<bpmn:definitions')
        self.assertEqual(proc.xml, LINEAR_XML)                 # 壞 XML 不會先寫進去
        proc.action_archive_process()
        with self.assertRaises(UserError):
            proc.with_user(self.designer).save_xml(TWO_TASKS)

    def test_needs_designer_rights(self):
        proc = self.make_process()
        with self.assertRaises(AccessError):
            proc.with_user(self.plain).save_xml(TWO_TASKS)
        self.assertEqual(proc.xml, LINEAR_XML)


class TestSetNodeConfig(ApprovalTestCase):

    def cfg(self, proc, eid='T1'):
        return proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == eid)

    def test_allowed_config_keys_are_applied(self):
        proc = self.make_process()
        proc.with_user(self.designer).set_node_config('T1', {
            'approval_mode': 'all', 'allow_escalation': True, 'sla_hours': 8.0, 'sla_action': 'remind',
            'flow_conditions': '{}'})
        cfg = self.cfg(proc)
        self.assertEqual((cfg.approval_mode, cfg.allow_escalation, cfg.sla_hours, cfg.sla_action),
                         ('all', True, 8.0, 'remind'))

    def test_keys_outside_the_whitelist_are_ignored(self):
        proc = self.make_process()
        other = self.make_process(name='AP 另一個')
        stray_role = self.make_role(process_id=other.id, resolver_type='direct_manager')
        cfg = self.cfg(proc)
        proc.with_user(self.designer).set_node_config('T1', {
            'approval_mode': 'all',
            'process_id': other.id, 'role_id': stray_role.id, 'bpmn_element_id': 'HACK',
            'sequence': 99, 'node_type': 'end', 'name': '被改名'})
        self.assertEqual(cfg.approval_mode, 'all')             # 白名單內的鍵照常寫入
        self.assertEqual(cfg.process_id, proc)
        self.assertFalse(cfg.role_id)
        self.assertEqual(cfg.bpmn_element_id, 'T1')
        self.assertEqual(cfg.node_type, 'user_task')
        self.assertEqual(cfg.name, '主管')

    def test_role_is_created_from_role_keys_only(self):
        proc = self.make_process()
        other = self.make_process(name='AP 另一個')
        proc.with_user(self.designer).set_node_config('T1', {
            'resolver_type': 'specific_user', 'user_ids': [self.boss.id, self.ceo.id],
            'name': '被塞進來的名字', 'process_id': other.id, 'apply_substitute': False})
        role = self.cfg(proc).role_id
        self.assertEqual(role.resolver_type, 'specific_user')
        self.assertEqual(role.user_ids, self.boss | self.ceo)
        self.assertEqual(role.process_id, proc)                # 不能被導去別的流程
        self.assertEqual(role.name, '主管')                    # 名稱取節點名稱，不吃外來值
        self.assertTrue(role.apply_substitute)

    def test_existing_role_is_updated_not_replaced(self):
        proc = self.make_process(roles={'T1': {'resolver_type': 'direct_manager'}})
        role = self.cfg(proc).role_id
        proc.with_user(self.designer).set_node_config('T1', {'resolver_type': 'manager_level', 'level': 2})
        self.assertEqual(self.cfg(proc).role_id, role)
        self.assertEqual((role.resolver_type, role.level), ('manager_level', 2))

    def test_role_keys_without_resolver_type_change_nothing(self):
        proc = self.make_process(roles={'T1': {'resolver_type': 'direct_manager'}})
        proc.with_user(self.designer).set_node_config('T1', {'level': 5})
        self.assertEqual(self.cfg(proc).role_id.level, 1)

    def test_unknown_element_gets_a_config_row(self):
        proc = self.make_process()
        proc.with_user(self.designer).set_node_config('NEW', {'approval_mode': 'all', 'name': '新節點'})
        self.assertEqual(self.cfg(proc, 'NEW').name, '新節點')

    def test_needs_designer_rights(self):
        proc = self.make_process()
        with self.assertRaises(AccessError):
            proc.with_user(self.plain).set_node_config('T1', {'approval_mode': 'all'})

    def test_published_process_node_config_is_refused(self):
        """set_node_config 僅 draft 允許；已發佈的流程拒絕（設定不變）。"""
        proc = self.make_process(roles={'T1': {'resolver_type': 'direct_manager'}}, publish=True)
        with self.assertRaises(UserError):
            proc.with_user(self.designer).set_node_config('T1', {'approval_mode': 'all'})
        self.assertNotEqual(self.cfg(proc).approval_mode, 'all')
        proc.with_user(self.designer).action_set_draft()
        proc.with_user(self.designer).set_node_config('T1', {'approval_mode': 'all'})
        self.assertEqual(self.cfg(proc).approval_mode, 'all')
