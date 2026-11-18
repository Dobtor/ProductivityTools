# -*- coding: utf-8 -*-
"""建立時帶 planned_date → schedule_status 由星期幾反推（週看板才看得到）；
管理員自動具備待辦管理者；效率指標 cron 每次都算本週／本月。"""

from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged

WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday',
            'friday', 'saturday', 'sunday')


@tagged('post_install', '-at_install')
class TestCreatePlannedStatus(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login='planned_status_user',
            groups='base.group_user,dobtor_mail_activity.group_activity_user')
        cls.Activity = cls.env['mail.activity']

    def _create(self, env, **vals):
        base = {
            'summary': 'planned status',
            'user_id': self.user.id,
            'date_deadline': date.today() + timedelta(days=30),
        }
        base.update(vals)
        return env['mail.activity'].create(base)

    def test_create_with_planned_date_derives_status(self):
        today = date.today()
        act = self._create(self.env(user=self.user), planned_date=today)
        self.assertEqual(act.schedule_status, WEEKDAYS[today.weekday()])
        self.assertEqual(act.schedule_week_number, 0)
        self.assertEqual(act.schedule_origin, 'inserted')

    def test_create_next_week_lands_in_next_week(self):
        today = date.today()
        nxt = today - timedelta(days=today.weekday()) + timedelta(days=8)  # 下週二
        act = self._create(self.env(user=self.user), planned_date=nxt)
        self.assertEqual(act.schedule_status, 'tuesday')
        self.assertEqual(act.schedule_week, 'week1')

    def test_explicit_status_is_kept(self):
        today = date.today()
        act = self._create(self.env(user=self.user), planned_date=today,
                           schedule_status='waiting')
        self.assertEqual(act.schedule_status, 'waiting')

    def test_no_planned_date_stays_waiting(self):
        act = self._create(self.env(user=self.user))
        self.assertEqual(act.schedule_status, 'waiting')

    def test_create_past_planned_date_rejected_for_users(self):
        with self.assertRaises(UserError):
            self._create(self.env(user=self.user),
                         planned_date=date.today() - timedelta(days=1))

    def test_admin_gets_activity_manager(self):
        admin = self.env.ref('base.user_admin')
        self.assertTrue(admin.has_group('dobtor_mail_activity.group_activity_manager'))
        erp_mgr = new_test_user(self.env, login='erp_mgr_probe',
                                groups='base.group_user,base.group_erp_manager')
        self.assertTrue(erp_mgr.has_group('dobtor_mail_activity.group_activity_manager'))

    def test_metrics_cron_computes_current_week(self):
        today = date.today()
        self._create(self.env, planned_date=today)
        Metrics = self.env['activity.efficiency.metrics']
        Metrics._cron_compute_metrics()
        Metrics._cron_compute_metrics()  # 冪等：重跑不撞 unique
        week_start = today - timedelta(days=today.weekday())
        rows = Metrics.search([('user_id', '=', self.user.id),
                               ('period_type', '=', 'week'),
                               ('period_start', '=', week_start)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.total_activities, 1)
        self.assertTrue(Metrics.search_count([
            ('user_id', '=', self.user.id), ('period_type', '=', 'month'),
            ('period_start', '=', today.replace(day=1))]))
