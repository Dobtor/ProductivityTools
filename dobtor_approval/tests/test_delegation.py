# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""職務代理：區間、範圍、約束與記錄規則。"""
from odoo import fields
from odoo.exceptions import AccessError, ValidationError

from .common import ApprovalTestCase


class TestDelegation(ApprovalTestCase):

    def delegate(self, a=None, b=None, start=-1, end=1, **vals):
        today = fields.Date.today()
        return self.env['bpmn.delegation'].create(dict({
            'delegator_id': (a or self.boss).id, 'delegate_id': (b or self.stranger).id,
            'date_start': fields.Date.add(today, days=start),
            'date_end': fields.Date.add(today, days=end)}, **vals))

    def substitute(self, users, definition=False, env_user=None):
        Delegation = self.env['bpmn.delegation']
        if env_user:
            Delegation = Delegation.with_user(env_user)
        return Delegation._substitute_users(users, definition)

    def test_active_delegation_replaces_the_delegator(self):
        self.delegate()
        self.assertEqual(self.substitute(self.boss | self.ceo), self.stranger | self.ceo)

    def test_window_is_inclusive_and_outside_it_does_nothing(self):
        self.delegate(start=0, end=0)                           # 只有今天
        self.assertEqual(self.substitute(self.boss), self.stranger)
        self.env['bpmn.delegation'].search([]).unlink()
        self.delegate(start=1, end=3)                           # 明天才開始
        self.assertEqual(self.substitute(self.boss), self.boss)
        self.env['bpmn.delegation'].search([]).unlink()
        self.delegate(start=-3, end=-1)                         # 昨天已結束
        self.assertEqual(self.substitute(self.boss), self.boss)

    def test_archived_delegation_is_ignored(self):
        self.delegate().active = False
        self.assertEqual(self.substitute(self.boss), self.boss)

    def test_scope_by_process(self):
        mine = self.make_process(name='AP 適用')
        other = self.make_process(name='AP 不適用')
        self.delegate(definition_ids=[(6, 0, [mine.id])])
        self.assertEqual(self.substitute(self.boss, mine), self.stranger)
        self.assertEqual(self.substitute(self.boss, other), self.boss)

    def test_unscoped_delegation_covers_every_process(self):
        self.delegate()
        self.assertEqual(self.substitute(self.boss, self.make_process()), self.stranger)

    def test_substitution_is_a_single_hop(self):
        """A→B 且 B→C：A 的單停在 B，不會再往下找 C（引擎的實際行為；AI 診斷依此提醒）。"""
        self.delegate(self.boss, self.stranger)
        self.delegate(self.stranger, self.plain)
        self.assertEqual(self.substitute(self.boss), self.stranger)

    def test_constraints(self):
        with self.assertRaises(ValidationError):
            self.delegate(start=3, end=1)
        with self.assertRaises(ValidationError):
            self.delegate(self.boss, self.boss)

    def test_users_see_only_delegations_they_are_part_of(self):
        mine = self.delegate(self.boss, self.stranger)
        theirs = self.delegate(self.staff, self.plain)
        Delegation = self.env['bpmn.delegation']
        self.assertEqual(Delegation.with_user(self.boss).search([]), mine)
        self.assertEqual(Delegation.with_user(self.stranger).search([]), mine)      # 代理人也看得到
        self.assertEqual(Delegation.with_user(self.staff).search([]), theirs)
        self.assertEqual(Delegation.with_user(self.manager).search([]), mine | theirs)

    def test_a_user_cannot_edit_someone_elses_delegation(self):
        theirs = self.delegate(self.staff, self.plain)
        with self.assertRaises(AccessError):
            theirs.with_user(self.boss).write({'date_end': fields.Date.add(fields.Date.today(), days=90)})

    def test_substitution_does_not_depend_on_who_triggers(self):
        """解析簽核人以 sudo 讀代理關係：申請人（非管理者）送簽時，主管的代理照樣生效。"""
        self.delegate(self.boss, self.stranger)
        self.assertEqual(self.substitute(self.boss, env_user=self.manager), self.stranger)
        self.assertEqual(self.substitute(self.boss, env_user=self.staff), self.stranger)
        self.assertEqual(self.substitute(self.boss, env_user=self.plain), self.stranger)

    def test_substitution_by_sudo_does_not_widen_visibility(self):
        """解析端 sudo 不放寬可見範圍：申請人仍看不到主管的代理設定。"""
        deleg = self.delegate(self.boss, self.stranger)
        self.assertEqual(self.substitute(self.boss, env_user=self.staff), self.stranger)
        self.assertFalse(self.env['bpmn.delegation'].with_user(self.staff).search([('id', '=', deleg.id)]))
