# -*- coding: utf-8 -*-

from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDoneWizardTimesheet(TransactionCase):
    """完成時登錄工時到專案工時表。"""

    def test_done_logs_timesheet_to_default_project(self):
        user = self.env.ref('base.user_demo')  # demo 有員工紀錄
        self.env.company.dobtor_activity_timesheet_enabled = True
        project = self.env['project.project'].create({
            'name': 'Default TS', 'allow_timesheets': True,
        })
        self.env.company.default_timesheet_project_id = project
        activity = self.env['mail.activity'].create({
            'summary': '待完成2',
            'date_deadline': date.today(),
            'user_id': user.id,
        })
        # 登錄工時需員工紀錄；TransactionCase 預設身分 OdooBot 沒有 → 以被指派者執行
        wizard = self.env['mail.activity.done.wizard'].with_user(user).create({
            'activity_id': activity.id,
            'actual_hours': 1.0,
        })
        wizard.action_done()
        activity.invalidate_recordset()
        self.assertFalse(activity.active)
        self.assertEqual(activity.timesheet_ids.project_id, project)
        self.assertEqual(activity.actual_hours, 1.0)


@tagged('post_install', '-at_install')
class TestDoneWizardWithoutProject(TransactionCase):
    """A 方案：找不到工時專案 → 完成時跳過工時；之後掛上專案可補登（含已完成待辦）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')  # demo 有員工紀錄
        cls.env.company.dobtor_activity_timesheet_enabled = True
        cls.env.company.default_timesheet_project_id = False
        cls.project = cls.env['project.project'].create({
            'name': 'Later Project', 'allow_timesheets': True,
        })

    def _activity(self):
        return self.env['mail.activity'].create({
            'summary': '無專案待辦',
            'date_deadline': date.today(),
            'user_id': self.user.id,
            'estimated_hours': 2.0,
        })

    def _wizard(self, activity, **ctx):
        return self.env['mail.activity.done.wizard'].with_user(self.user).with_context(
            default_activity_id=activity.id, **ctx).create({})

    def test_01_done_skips_hours_without_project(self):
        activity = self._activity()
        self.assertFalse(activity.can_log_timesheet)
        wizard = self._wizard(activity)
        self.assertTrue(wizard.timesheet_skipped)
        self.assertEqual(wizard.actual_hours, 2.0)
        wizard.action_done()
        self.assertFalse(activity.active, '沒有專案也要能完成')
        self.assertFalse(activity.timesheet_ids)
        self.assertEqual(activity.actual_hours, 0)
        self.assertTrue(any('Hours not logged' in (m.body or '')
                            for m in activity.message_ids),
                        '應留痕未登錄的工時，供日後補登')

    def test_02_log_and_continue_without_project_raises(self):
        activity = self._activity()
        wizard = self._wizard(activity)
        wizard.actual_hours = 1.0
        with self.assertRaises(UserError):
            wizard.action_log_and_continue()
        with self.assertRaises(UserError):
            activity.action_log_timesheet()

    def test_03_backfill_after_project_linked(self):
        activity = self._activity()
        self._wizard(activity).action_done()
        self.assertFalse(activity.active)

        # 之後掛上專案 → 可於已完成待辦補登
        activity.sudo().with_context(skip_schedule_check=True).project_id = self.project
        activity.invalidate_recordset(['can_log_timesheet'])
        self.assertTrue(activity.can_log_timesheet)
        action = activity.with_user(self.user).action_log_timesheet()
        self.assertTrue(action['context']['default_log_only'])

        wizard = self._wizard(activity, **{
            k: v for k, v in action['context'].items() if k != 'default_activity_id'})
        self.assertTrue(wizard.log_only)
        self.assertFalse(wizard.timesheet_skipped)
        self.assertEqual(wizard.actual_hours, 2.0, '預填「預估 − 已登錄」')
        wizard.action_log_and_continue()

        self.assertEqual(len(activity.timesheet_ids), 1)
        self.assertEqual(activity.timesheet_ids.project_id, self.project)
        self.assertEqual(activity.actual_hours, 2.0)
        self.assertFalse(activity.active, '補登不改變完成狀態')

    def test_04_default_project_is_used(self):
        self.env.company.default_timesheet_project_id = self.project
        activity = self._activity()
        self.assertTrue(activity.can_log_timesheet)
        wizard = self._wizard(activity)
        self.assertFalse(wizard.timesheet_skipped)
        wizard.action_done()
        self.assertEqual(activity.timesheet_ids.project_id, self.project)


