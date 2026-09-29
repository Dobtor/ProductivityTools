# -*- coding: utf-8 -*-

from datetime import date, timedelta
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestWeeklyReport(TransactionCase):
    """測試週報告功能"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')

    def test_01_create_weekly_report(self):
        """測試建立週報告"""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        report = self.env['weekly.report'].create({
            'user_id': self.user.id,
            'week_start': week_start,
        })

        self.assertTrue(report.id)
        self.assertEqual(report.user_id.id, self.user.id)
        self.assertEqual(report.state, 'draft')

    def test_02_report_week_number(self):
        """測試週次編號計算"""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        report = self.env['weekly.report'].create({
            'user_id': self.user.id,
            'week_start': week_start,
        })

        self.assertTrue(report.week_number)
        self.assertIn('W', report.week_number)

    def test_03_report_confirm(self):
        """測試確認週報告"""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        # 確認前必須先產生內容（至少一筆本週計畫快照）
        self.env['mail.activity'].create({
            'summary': '本週計畫',
            'user_id': self.user.id,
            'date_deadline': week_start + timedelta(days=6),
            'planned_date': week_start + timedelta(days=1),
            'schedule_status': 'tuesday',
        })
        report = self.env['weekly.report'].create({
            'user_id': self.user.id,
            'week_start': week_start,
        })
        report.action_generate_report()
        self.assertTrue(report.this_week_snapshot_ids)

        report.action_confirm()
        self.assertEqual(report.state, 'confirmed')


@tagged('post_install', '-at_install')
class TestEfficiencyMetrics(TransactionCase):
    """測試效率指標功能"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')

    def test_01_create_metrics(self):
        """測試建立效率指標"""
        metrics = self.env['activity.efficiency.metrics'].create({
            'user_id': self.user.id,
            # 模型的欄位是 period_type / period_start / period_end，不是 date；
            # 三個都是 required（unique(user_id, period_type, period_start)）
            'period_type': 'week',
            'period_start': date.today(),
            'period_end': date.today(),
            'total_activities': 10,
            'completed_activities': 8,
            'total_estimated_hours': 20.0,
            'total_actual_hours': 18.5,
        })

        self.assertTrue(metrics.id)

    def test_02_metrics_compute(self):
        """測試效率指標計算"""
        metrics = self.env['activity.efficiency.metrics'].create({
            'user_id': self.user.id,
            # 模型的欄位是 period_type / period_start / period_end，不是 date；
            # 三個都是 required（unique(user_id, period_type, period_start)）
            'period_type': 'week',
            'period_start': date.today(),
            'period_end': date.today(),
            'total_activities': 10,
            'completed_activities': 8,
            'total_estimated_hours': 20.0,
            'total_actual_hours': 18.5,
        })

        # 檢查是否有計算欄位
        if hasattr(metrics, 'completion_rate'):
            self.assertEqual(metrics.completion_rate, 80.0)


@tagged('post_install', '-at_install')
class TestWeeklyScheduleConfig(TransactionCase):
    """測試週報排程配置"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 每位使用者只能有一份配置 → 用獨立使用者，不受既有資料影響
        cls.user = cls.env['res.users'].create({
            'name': 'Schedule Config User', 'login': 'schedule_config_user',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def test_01_create_config(self):
        """測試建立排程配置"""
        config = self.env['weekly.schedule.config'].create({
            'user_id': self.user.id,
            'target_model': 'res.users',
            'schedule_day': '0',  # 週一
        })

        self.assertTrue(config.id)
        self.assertEqual(config._get_target_record(), ('res.users', self.user.id))
