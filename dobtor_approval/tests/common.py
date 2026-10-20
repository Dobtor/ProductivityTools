# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""dobtor_approval 測試共用：組織、使用者與流程樣本。

★ 權限相關的測試用**非管理者**使用者執行（用 superuser 跑會把權限問題整個蓋掉）。
"""
from odoo.tests.common import TransactionCase, new_test_user, tagged

USER = 'dobtor_approval.group_bpmn_approval_user'
DESIGNER = 'dobtor_approval.group_bpmn_approval_designer'
MANAGER = 'dobtor_approval.group_bpmn_approval_manager'


def bpmn(body):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d">'
            '<bpmn:process id="P" isExecutable="true">%s</bpmn:process></bpmn:definitions>' % body)


def flow(fid, src, dst):
    return '<bpmn:sequenceFlow id="%s" sourceRef="%s" targetRef="%s"/>' % (fid, src, dst)


#: Start → 簽核 T1 → End
LINEAR_XML = bpmn('<bpmn:startEvent id="S"/><bpmn:userTask id="T1" name="主管"/><bpmn:endEvent id="E"/>'
                  + flow('f1', 'S', 'T1') + flow('f2', 'T1', 'E'))


@tagged('post_install', '-at_install')
class ApprovalTestCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        icp = env['ir.config_parameter'].sudo()
        for key in ('basic_approval', 'conditional', 'cosign', 'delegation'):
            icp.set_param('dobtor_approval.%s' % key, 'True')

        def user(login, group=USER, **vals):
            return new_test_user(env, login=login, groups='base.group_user,' + group, **vals)
        cls.designer = user('ap_designer', DESIGNER)
        cls.manager = user('ap_manager', MANAGER)
        cls.plain = user('ap_plain')
        cls.stranger = user('ap_stranger')
        cls.ceo = user('ap_ceo', name='AP CEO')
        cls.boss = user('ap_boss', name='AP Boss')
        cls.staff = user('ap_staff', name='AP Staff')

        employee = cls.employee
        cls.dept = env['hr.department'].create({'name': 'AP 部門'})
        cls.job = env['hr.job'].create({'name': 'AP 職位'})
        cls.ceo_emp = employee(cls.ceo)
        cls.boss_emp = employee(cls.boss, parent_id=cls.ceo_emp.id, department_id=cls.dept.id)
        cls.dept.manager_id = cls.boss_emp
        cls.staff_emp = employee(cls.staff, parent_id=cls.boss_emp.id, department_id=cls.dept.id,
                                 job_id=cls.job.id)

    @classmethod
    def employee(cls, user, **vals):
        """使用者的員工資料（沒有就建；有就更新）。★ 不重複建立：hr 可能已替使用者建好一筆。"""
        emp = user.employee_ids[:1]
        if emp:
            emp.write(vals)
            return emp
        return cls.env['hr.employee'].create(dict({'name': user.name, 'user_id': user.id}, **vals))

    # ---- 樣本 -------------------------------------------------------
    def make_process(self, xml=LINEAR_XML, name='AP 流程', roles=None, publish=False, **vals):
        proc = self.env['bpmn.executable.process'].create(dict({'name': name, 'xml': xml}, **vals))
        proc._sync_node_configs_from_xml(xml)
        for eid, role_vals in (roles or {}).items():
            role = self.env['bpmn.role'].create(dict({'name': 'R-%s' % eid, 'process_id': proc.id},
                                                     **role_vals))
            proc.node_config_ids.filtered(lambda c: c.bpmn_element_id == eid).role_id = role
        if publish:
            proc.action_publish()
        return proc

    def make_role(self, **vals):
        return self.env['bpmn.role'].create(dict({'name': 'AP 角色'}, **vals))

    def new_instance(self, applicant=None, **vals):
        return self.env['bpmn.process.instance'].new(
            dict({'applicant_user_id': (applicant or self.staff).id}, **vals))
