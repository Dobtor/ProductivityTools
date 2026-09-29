# -*- coding: utf-8 -*-

from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestActivityProjectLink(TransactionCase):
    """專案欄位與其推導（原核心行為，搬到橋接後須維持）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Proj Customer'})
        cls.project = cls.env['project.project'].create({
            'name': 'Linked Project', 'partner_id': cls.customer.id,
        })
        cls.task = cls.env['project.task'].create({
            'name': 'Linked Task', 'project_id': cls.project.id,
        })

    def test_partner_fallback_from_project(self):
        """res 推不出客戶時，以專案客戶帶入。"""
        act = self.env['mail.activity'].create({
            'summary': 'p', 'date_deadline': date.today(),
            'project_id': self.project.id,
        })
        self.assertEqual(act.partner_id, self.customer)

    def test_project_from_task_res(self):
        Act = self.env['mail.activity']
        self.assertEqual(Act._project_from_res('project.task', self.task.id), self.project)

    def test_relation_tree_rooted_at_project(self):
        tree = self.env['mail.activity'].get_relation_tree(project_id=self.project.id)
        self.assertEqual(tree['data']['id'], 'project_%s' % self.project.id)

    def test_timesheet_project_from_task(self):
        act = self.env['mail.activity'].create({
            'summary': 't', 'date_deadline': date.today(),
            'res_model_id': self.env['ir.model']._get_id('project.task'),
            'res_id': self.task.id,
        })
        self.assertEqual(act._get_timesheet_project(), self.project)

    def test_create_wizard_writes_project(self):
        wiz = self.env['mail.activity.create.wizard'].create({
            'summary': 'w', 'date_deadline': date.today(),
            'project_id': self.project.id,
        })
        act_id = wiz.action_create_todo()['infos']['activity_id']
        self.assertEqual(self.env['mail.activity'].browse(act_id).project_id, self.project)

    def test_continue_action_carries_project(self):
        act = self.env['mail.activity'].create({
            'summary': 'c', 'date_deadline': date.today(),
            'project_id': self.project.id,
        })
        ctx = act._continue_todo_action()['context']
        self.assertEqual(ctx['default_project_id'], self.project.id)

    def test_project_todo_app_hidden(self):
        menu = self.env.ref('project_todo.menu_todo_todos')
        self.assertIn(
            self.env.ref('dobtor_mail_activity_project.group_hide_project_todo_app'),
            menu.groups_id)
