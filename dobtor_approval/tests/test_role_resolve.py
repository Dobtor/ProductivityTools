# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""bpmn.role.resolve() 的每一種解析方式，以及 resolve_preview() 與空結果的原因診斷。"""
from odoo.exceptions import UserError, ValidationError

from .common import ApprovalTestCase


class TestRoleResolve(ApprovalTestCase):

    def resolve(self, role, applicant=None, **inst_vals):
        return role.resolve(self.new_instance(applicant, **inst_vals))

    # ---- 組織關係 ---------------------------------------------------
    def test_direct_manager(self):
        role = self.make_role(resolver_type='direct_manager')
        self.assertEqual(self.resolve(role), self.boss)
        self.assertEqual(self.resolve(role, self.boss), self.ceo)
        self.assertFalse(self.resolve(role, self.ceo))             # 最高層沒有主管

    def test_no_applicant_resolves_nothing(self):
        role = self.make_role(resolver_type='direct_manager')
        inst = self.env['bpmn.process.instance'].new({})
        self.assertFalse(role.resolve(inst))

    def test_manager_level(self):
        self.assertEqual(self.resolve(self.make_role(resolver_type='manager_level', level=1)), self.boss)
        self.assertEqual(self.resolve(self.make_role(resolver_type='manager_level', level=2)), self.ceo)
        self.assertFalse(self.resolve(self.make_role(resolver_type='manager_level', level=3)))

    def test_manager_level_is_constrained(self):
        for bad in (0, 21):
            with self.assertRaises(ValidationError):
                self.make_role(resolver_type='manager_level', level=bad)

    def test_department_manager(self):
        self.assertEqual(self.resolve(self.make_role(resolver_type='department_manager')), self.boss)

    def test_department_specific(self):
        role = self.make_role(resolver_type='department_specific', specific_department_id=self.dept.id)
        self.assertEqual(self.resolve(role, self.stranger), self.boss)    # 與申請人無關

    def test_job_position(self):
        role = self.make_role(resolver_type='job_position', job_id=self.job.id)
        self.assertEqual(self.resolve(role), self.staff)                  # 擔任該職位的員工

    def test_specific_user_drops_inactive_users(self):
        role = self.make_role(resolver_type='specific_user',
                              user_ids=[(6, 0, [self.boss.id, self.ceo.id])])
        self.assertEqual(self.resolve(role), self.boss | self.ceo)
        self.ceo.active = False
        self.assertEqual(self.resolve(role), self.boss)

    def test_group(self):
        group = self.env['res.groups'].create({'name': 'AP 群組'})
        group.users = [(6, 0, [self.boss.id, self.ceo.id])]
        role = self.make_role(resolver_type='group', group_id=group.id)
        self.assertEqual(self.resolve(role), self.boss | self.ceo)

    # ---- 單據欄位 ---------------------------------------------------
    def test_field_on_record_user_employee_and_partner(self):
        partner = self.env['res.partner'].create({'name': 'AP 單據', 'user_id': self.boss.id})
        inst = dict(res_model='res.partner', res_id=partner.id)
        role = self.make_role(resolver_type='field_on_record', record_field='user_id')
        self.assertEqual(self.resolve(role, **inst), self.boss)
        # hr.employee 欄位 → 取其 user
        emp_role = self.make_role(resolver_type='field_on_record', record_field='parent_id')
        self.assertEqual(self.resolve(emp_role, res_model='hr.employee', res_id=self.staff_emp.id), self.boss)
        # res.partner 欄位 → 取對應 user
        partner_role = self.make_role(resolver_type='field_on_record', record_field='partner_id')
        self.assertEqual(self.resolve(partner_role, res_model='res.users', res_id=self.staff.id), self.staff)

    def test_field_on_record_degrades_to_empty(self):
        partner = self.env['res.partner'].create({'name': 'AP 單據'})
        role = self.make_role(resolver_type='field_on_record', record_field='user_id')
        self.assertFalse(self.resolve(role, res_model='res.partner', res_id=partner.id))   # 欄位空
        self.assertFalse(self.resolve(role))                                               # 沒有單據
        bad = self.make_role(resolver_type='field_on_record', record_field='nope')
        self.assertFalse(self.resolve(bad, res_model='res.partner', res_id=partner.id))    # 欄位不存在
        unsupported = self.make_role(resolver_type='field_on_record', record_field='country_id')
        partner.country_id = self.env.ref('base.tw')
        self.assertFalse(self.resolve(unsupported, res_model='res.partner', res_id=partner.id))

    # ---- 運算式 -----------------------------------------------------
    def test_expression(self):
        role = self.make_role(resolver_type='expression', expression='applicant')
        self.assertEqual(self.resolve(role), self.staff)
        role.expression = "env['res.users'].search([('login', '=', 'ap_ceo')])"
        self.assertEqual(self.resolve(role), self.ceo)

    def test_expression_empty_and_wrong_type(self):
        role = self.make_role(resolver_type='expression', expression='None')
        self.assertFalse(self.resolve(role))
        role.expression = "'not users'"
        with self.assertRaises(UserError):
            self.resolve(role)
        role.expression = '1/0'
        with self.assertRaises(UserError):
            self.resolve(role)

    # ---- 核決權限表 -------------------------------------------------
    def test_authority_matrix_chain(self):
        matrix = self.env['bpmn.authority.matrix'].create({
            'name': 'AP 矩陣', 'hit_policy': 'collect',
            'line_ids': [(0, 0, {'sequence': 1, 'resolver_type': 'direct_manager'}),
                         (0, 0, {'sequence': 2, 'resolver_type': 'manager_level', 'level': 2})]})
        role = self.make_role(resolver_type='authority_matrix', matrix_id=matrix.id)
        self.assertEqual(self.resolve(role), self.boss | self.ceo)

    # ---- 職務代理與過濾 ---------------------------------------------
    def test_substitute_can_be_switched_off(self):
        from odoo import fields
        today = fields.Date.today()
        self.env['bpmn.delegation'].create({
            'delegator_id': self.boss.id, 'delegate_id': self.stranger.id,
            'date_start': fields.Date.subtract(today, days=1), 'date_end': fields.Date.add(today, days=1)})
        on = self.make_role(resolver_type='direct_manager')
        off = self.make_role(resolver_type='direct_manager', apply_substitute=False)
        self.assertEqual(self.resolve(on), self.stranger)
        self.assertEqual(self.resolve(off), self.boss)

    def test_substitute_needs_the_delegation_feature(self):
        from odoo import fields
        today = fields.Date.today()
        self.env['bpmn.delegation'].create({
            'delegator_id': self.boss.id, 'delegate_id': self.stranger.id,
            'date_start': fields.Date.subtract(today, days=1), 'date_end': fields.Date.add(today, days=1)})
        self.env['ir.config_parameter'].sudo().set_param('dobtor_approval.delegation', 'False')
        self.assertEqual(self.resolve(self.make_role(resolver_type='direct_manager')), self.boss)

    def test_inactive_users_are_filtered_from_every_resolver(self):
        self.boss.active = False
        self.assertFalse(self.resolve(self.make_role(resolver_type='direct_manager')))


class TestResolvePreview(ApprovalTestCase):

    def test_default_return_type_is_unchanged(self):
        role = self.make_role(resolver_type='direct_manager')
        users = role.resolve_preview(self.staff.id)
        self.assertEqual(users._name, 'res.users')
        self.assertEqual(users, self.boss)

    def test_with_reason_returns_a_tuple(self):
        role = self.make_role(resolver_type='direct_manager')
        users, reason = role.resolve_preview(self.staff.id, with_reason=True)
        self.assertEqual((users, reason), (self.boss, {}))

    def test_preview_matches_resolve_on_a_real_instance(self):
        proc = self.make_process(roles={'T1': {'resolver_type': 'direct_manager'}}, publish=True)
        role = proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == 'T1').role_id
        preview = role.resolve_preview(self.staff.id)
        inst = proc.start(applicant=self.staff)
        self.assertEqual(preview, inst.activity_link_ids.approver_user_id)

    def test_preview_does_not_create_anything(self):
        Instance = self.env['bpmn.process.instance']
        before = Instance.search_count([])
        self.make_role(resolver_type='direct_manager').resolve_preview(self.staff.id)
        self.assertEqual(Instance.search_count([]), before)

    def test_a_broken_role_does_not_break_the_preview(self):
        role = self.make_role(resolver_type='expression', expression='1/0')
        self.assertFalse(role.resolve_preview(self.staff.id))
        users, reason = role.resolve_preview(self.staff.id, with_reason=True)
        self.assertFalse(users)
        self.assertEqual(reason['code'], 'expression_error')
        self.assertTrue(reason['message'])
        self.assertLessEqual(len(reason['message']), 200)

    def test_every_empty_result_has_a_specific_reason(self):
        no_user = self.env['res.users'].create({'name': 'AP 無員工', 'login': 'ap_noemp'})
        no_user.employee_ids.unlink()
        # 有員工但沒有主管、沒有部門
        solo = self.env['res.users'].create({'name': 'AP 孤', 'login': 'ap_solo'})
        self.employee(solo)
        # 主管沒有使用者帳號
        ghost_boss = self.env['hr.employee'].create({'name': 'AP 無帳號主管'})
        lonely = self.env['res.users'].create({'name': 'AP 下屬', 'login': 'ap_sub'})
        self.employee(lonely, parent_id=ghost_boss.id,
                      department_id=self.env['hr.department'].create({'name': 'AP 無經理部門'}).id)
        empty_group = self.env['res.groups'].create({'name': 'AP 空群組'})
        other_job = self.env['hr.job'].create({'name': 'AP 無人職位'})
        staffed_job = self.env['hr.job'].create({'name': 'AP 有員工無帳號'})
        self.env['hr.employee'].create({'name': 'AP 無帳號員工', 'job_id': staffed_job.id})
        dept_no_mgr = self.env['hr.department'].create({'name': 'AP 沒經理'})
        partner = self.env['res.partner'].create({'name': 'AP 單據'})
        matrix = self.env['bpmn.authority.matrix'].create({
            'name': 'AP 空矩陣', 'line_ids': [(0, 0, {'amount_min': 1000, 'resolver_type': 'direct_manager'})]})
        defn = self.env['dmn.definitions'].create({'name': 'ap', 'dmn_xml': (
            '<?xml version="1.0"?><definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" '
            'id="x" name="x" namespace="http://x"><decision id="D" name="D"><literalExpression>'
            '<text>"x"</text></literalExpression></decision></definitions>')})
        cases = [
            # (角色欄位, 申請人, 單據, 期望原因碼)
            ({'resolver_type': 'direct_manager'}, False, None, 'no_applicant'),
            ({'resolver_type': 'direct_manager'}, no_user, None, 'no_employee'),
            ({'resolver_type': 'direct_manager'}, solo, None, 'no_manager'),
            ({'resolver_type': 'direct_manager'}, lonely, None, 'manager_no_user'),
            ({'resolver_type': 'manager_level', 'level': 3}, self.staff, None, 'no_manager_at_level'),
            ({'resolver_type': 'manager_level', 'level': 1}, lonely, None, 'manager_no_user'),
            ({'resolver_type': 'department_manager'}, solo, None, 'no_department'),
            ({'resolver_type': 'department_manager'}, lonely, None, 'department_no_manager'),
            ({'resolver_type': 'department_specific'}, self.staff, None, 'department_not_set'),
            ({'resolver_type': 'department_specific', 'specific_department_id': dept_no_mgr.id},
             self.staff, None, 'department_no_manager'),
            ({'resolver_type': 'job_position', 'job_id': other_job.id}, self.staff, None, 'job_no_employee'),
            ({'resolver_type': 'job_position', 'job_id': staffed_job.id}, self.staff, None, 'job_no_user'),
            ({'resolver_type': 'specific_user'}, self.staff, None, 'no_user_selected'),
            ({'resolver_type': 'group'}, self.staff, None, 'group_not_set'),
            ({'resolver_type': 'group', 'group_id': empty_group.id}, self.staff, None, 'group_no_users'),
            ({'resolver_type': 'field_on_record'}, self.staff, None, 'field_not_set'),
            ({'resolver_type': 'field_on_record', 'record_field': 'user_id'}, self.staff, None, 'no_record'),
            ({'resolver_type': 'field_on_record', 'record_field': 'nope'}, self.staff, partner,
             'field_missing_on_record'),
            ({'resolver_type': 'field_on_record', 'record_field': 'user_id'}, self.staff, partner, 'field_empty'),
            ({'resolver_type': 'field_on_record', 'record_field': 'country_id'}, self.staff, None, 'no_record'),
            ({'resolver_type': 'expression'}, self.staff, None, 'expression_empty'),
            ({'resolver_type': 'expression', 'expression': 'None'}, self.staff, None, 'expression_returned_empty'),
            ({'resolver_type': 'authority_matrix'}, self.staff, None, 'matrix_not_set'),
            ({'resolver_type': 'authority_matrix', 'matrix_id': matrix.id}, self.staff, None, 'matrix_no_match'),
            ({'resolver_type': 'dmn_decision'}, self.staff, None, 'decision_not_set'),
            ({'resolver_type': 'dmn_decision', 'decision_id': defn.decision_ids[:1].id}, self.staff, None,
             'decision_no_approver'),
        ]
        for vals, applicant, record, expected in cases:
            with self.subTest(code=expected, resolver=vals['resolver_type']):
                role = self.make_role(**vals)
                users, reason = role.resolve_preview(
                    applicant.id if applicant else False,
                    record._name if record else False, record.id if record else False, with_reason=True)
                self.assertFalse(users)
                self.assertEqual(reason['code'], expected, reason)
                self.assertTrue(reason['message'])

    def test_job_position_without_a_job_resolves_to_nobody(self):
        """角色選了「指定職位」卻沒填職位：解析回空（不可撈出所有沒職位的員工），發佈時被擋。"""
        role = self.make_role(resolver_type='job_position')
        users, reason = role.with_user(self.designer).resolve_preview(self.staff.id, with_reason=True)
        self.assertFalse(users)
        self.assertEqual(reason['code'], 'job_not_set')
        proc = self.make_process(roles={'T1': {'resolver_type': 'job_position'}})
        with self.assertRaises(UserError) as cm:
            proc.with_user(self.designer).action_publish()
        self.assertIn('職位', str(cm.exception))
        self.assertEqual(proc.state, 'draft')

    def test_inactive_specific_users_are_explained(self):
        role = self.make_role(resolver_type='specific_user', user_ids=[(6, 0, [self.ceo.id])])
        self.ceo.active = False
        users, reason = role.resolve_preview(self.staff.id, with_reason=True)
        self.assertFalse(users)
        self.assertEqual(reason['code'], 'users_inactive')

    def test_matrix_lines_without_users(self):
        matrix = self.env['bpmn.authority.matrix'].create({
            'name': 'AP 命中但無人', 'line_ids': [(0, 0, {'resolver_type': 'direct_manager'})]})
        role = self.make_role(resolver_type='authority_matrix', matrix_id=matrix.id)
        users, reason = role.resolve_preview(self.ceo.id, with_reason=True)     # ceo 沒有主管
        self.assertFalse(users)
        self.assertEqual(reason['code'], 'matrix_lines_no_users')
