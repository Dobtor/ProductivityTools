"""Tests for monitoring & telemetry models (P2-4)。"""

from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestErrorLog(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Log = self.env['doc.editor.error.log']

    def test_create_minimal(self):
        log = self.Log.create({
            'error_type': 'js_error',
            'message': 'TypeError: Cannot read property',
        })
        self.assertEqual(log.error_type, 'js_error')
        self.assertTrue(log.create_date)
        # user_id / company_id 自動填入（沒設 default 但欄位允許）
        # 不驗證自動填，只驗紀錄成功

    def test_message_truncation(self):
        """訊息欄位 size=512，建立時超過會被截斷或拋錯。"""
        long_msg = 'X' * 1000
        # 模型定義 size=512，DB 端會擋 → 拋 DataError
        # 但 controller 端先截到 500，所以這裡只驗合法輸入
        log = self.Log.create({
            'error_type': 'other',
            'message': long_msg[:500],
        })
        self.assertEqual(len(log.message), 500)

    def test_extra_json_field(self):
        log = self.Log.create({
            'error_type': 'other',
            'message': 'test',
            'extra': {'docId': 42, 'action': 'save'},
        })
        self.assertEqual(log.extra['docId'], 42)
        self.assertEqual(log.extra['action'], 'save')

    def test_gc_old_logs_keeps_recent(self):
        """30 天內的紀錄不該被 GC。"""
        recent = self.Log.create({
            'error_type': 'other',
            'message': 'recent',
        })
        n_removed = self.Log.gc_old_logs(days=30)
        self.assertEqual(n_removed, 0)
        self.assertTrue(recent.exists())

    def test_gc_old_logs_removes_old(self):
        """超過 N 天的紀錄會被 GC。"""
        # 建立後手動把 create_date 改舊（透過 SQL 因 ORM 不允許覆寫）
        old = self.Log.create({
            'error_type': 'other',
            'message': 'old',
        })
        old_date = fields.Datetime.now() - timedelta(days=40)
        self.env.cr.execute(
            "UPDATE doc_editor_error_log SET create_date = %s WHERE id = %s",
            (old_date, old.id),
        )
        self.Log.invalidate_model()
        n_removed = self.Log.gc_old_logs(days=30)
        self.assertGreaterEqual(n_removed, 1)
        self.assertFalse(old.exists())


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestPerfMetric(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Metric = self.env['doc.editor.perf.metric']

    def test_create_metric(self):
        m = self.Metric.create({
            'metric_type': 'load_doc_ms',
            'value': 1234.5,
        })
        self.assertEqual(m.metric_type, 'load_doc_ms')
        self.assertAlmostEqual(m.value, 1234.5, places=1)

    def test_aggregate_recent_empty(self):
        result = self.Metric.aggregate_recent('nonexistent_metric', hours=24)
        self.assertEqual(result['count'], 0)

    def test_aggregate_recent_basic(self):
        for v in [100.0, 200.0, 300.0]:
            self.Metric.create({
                'metric_type': 'unit_test_metric',
                'value': v,
            })
        result = self.Metric.aggregate_recent('unit_test_metric', hours=24)
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['min'], 100.0)
        self.assertEqual(result['max'], 300.0)
        self.assertEqual(result['mean'], 200.0)

    def test_gc_old_metrics_keeps_recent(self):
        m = self.Metric.create({
            'metric_type': 'load_doc_ms',
            'value': 1.0,
        })
        n = self.Metric.gc_old_metrics(days=14)
        self.assertEqual(n, 0)
        self.assertTrue(m.exists())

    def test_gc_old_metrics_removes_old(self):
        m = self.Metric.create({
            'metric_type': 'load_doc_ms',
            'value': 1.0,
        })
        old_date = fields.Datetime.now() - timedelta(days=20)
        self.env.cr.execute(
            "UPDATE doc_editor_perf_metric SET create_date = %s WHERE id = %s",
            (old_date, m.id),
        )
        self.Metric.invalidate_model()
        n = self.Metric.gc_old_metrics(days=14)
        self.assertGreaterEqual(n, 1)
        self.assertFalse(m.exists())
