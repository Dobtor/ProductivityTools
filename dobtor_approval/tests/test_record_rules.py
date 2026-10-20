# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""實例的記錄規則：申請人與簽核人看得到；其他人（含設計者）看不到；管理者全可見。"""
from odoo.exceptions import AccessError

from .common import ApprovalTestCase


class TestInstanceRecordRules(ApprovalTestCase):

    def setUp(self):
        super().setUp()
        self.proc = self.make_process(roles={'T1': {'resolver_type': 'direct_manager'}}, publish=True)
        self.inst = self.proc.start(applicant=self.staff)

    def visible_to(self, user):
        return self.env['bpmn.process.instance'].with_user(user).search([('id', '=', self.inst.id)])

    def test_applicant_and_approver_can_see_it(self):
        self.assertEqual(self.visible_to(self.staff), self.inst)
        self.assertEqual(self.visible_to(self.boss), self.inst)          # 待簽人

    def test_unrelated_users_including_designers_cannot(self):
        for user in (self.stranger, self.plain, self.ceo, self.designer):
            self.assertFalse(self.visible_to(user), user.login)

    def test_manager_sees_everything(self):
        self.assertEqual(self.visible_to(self.manager), self.inst)

    def test_reading_by_id_is_refused_for_unrelated_users(self):
        with self.assertRaises(AccessError):
            self.inst.with_user(self.stranger).read(['state'])

    def test_list_counts_follow_the_rule(self):
        Instance = self.env['bpmn.process.instance']
        other = self.proc.start(applicant=self.ceo)
        self.assertEqual(Instance.with_user(self.staff).search([('process_id', '=', self.proc.id)]), self.inst)
        self.assertEqual(Instance.with_user(self.manager).search([('process_id', '=', self.proc.id)]),
                         self.inst | other)

    def test_unrelated_user_cannot_write_or_unlink_an_instance(self):
        self.assertFalse(self.visible_to(self.stranger))
        with self.assertRaises(AccessError):
            self.inst.with_user(self.stranger).write({'state': 'cancelled'})
        with self.assertRaises(AccessError):
            self.inst.with_user(self.designer).write({'state': 'cancelled'})
        self.assertEqual(self.inst.state, 'running')

    def test_applicant_and_approver_can_still_write_their_instance(self):
        self.inst.with_user(self.staff).check_access('write')
        self.inst.with_user(self.boss).check_access('write')
        self.inst.with_user(self.manager).check_access('write')

    def test_engine_flow_by_non_admin_users_still_works(self):
        """非管理者起單、待簽人簽核推進皆不受新規則影響。"""
        inst = self.proc.with_user(self.staff).start(applicant=self.staff)
        self.assertEqual(inst.state, 'running')
        link = inst.activity_link_ids.filtered(lambda l: l.decision == 'pending')
        self.assertEqual(link.approver_user_id, self.boss)
        link.with_user(self.boss)._on_activity_done()
        self.assertEqual(inst.state, 'approved')
