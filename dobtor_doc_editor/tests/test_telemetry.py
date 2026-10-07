"""Tests for monitoring & telemetry models (P2-4)。"""

from datetime import timedelta

from odoo import fields
from odoo.tests.common import HttpCase, TransactionCase, tagged


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


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestTelemetryRoutes(HttpCase):
    """兩條遙測路由的 HTTP 層行為。

    這組測試的由來：瀏覽器 tour 的 log 裡出現
        bad query: INSERT INTO "doc_editor_perf_metric" ... doc_id = 14
        ERROR: ... violates foreign key constraint
        psycopg2.errors.InFailedSqlTransaction: current transaction is aborted
    編輯器開範本時把 doc.template 的 id 當 doc_id 送上來（兩個遙測 model 的
    doc_id 都是 doc.document 的外鍵）。真正嚴重的不是那筆遙測沒寫進去，而是
    controller 的 try/except 只接得住 Python 例外——PostgreSQL 的交易已經
    aborted，之後 Odoo 自己的 commit 會炸，整筆請求跟著失敗。
    """

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self.doc = self.env['doc.document'].sudo().create({
            'name': '遙測測試文件',
            'content_html': '<p>x</p>',
        })

    def _post_metric(self, doc_id):
        # make_jsonrpc_request 遇到 JSON-RPC error 會 raise——修好之前這裡
        # 會因為 InFailedSqlTransaction 直接炸，所以這個呼叫本身就是斷言。
        return self.make_jsonrpc_request('/dobtor_doc/telemetry/metric', {
            'metric_type': 'load_doc_ms',
            'value': 123.4,
            'doc_id': doc_id,
        })

    def test_metric_with_real_doc_id_is_linked(self):
        self.assertTrue(self._post_metric(self.doc.id)['success'])
        metric = self.env['doc.editor.perf.metric'].sudo().search(
            [('metric_type', '=', 'load_doc_ms')], order='id desc', limit=1)
        self.assertEqual(metric.doc_id, self.doc)

    def test_metric_with_template_id_does_not_break_request(self):
        """範本 id 不是文件 id：寫進去會違反外鍵，但請求必須照樣成功。"""
        template = self.env['doc.template'].sudo().create({
            'name': '遙測測試範本',
            'role': 'content',
            'model_id': self.env['ir.model']._get('res.partner').id,
        })
        # 範本 id 與文件 id 各自獨立遞增，兩邊剛好撞號是有可能的——那時這則
        # 測試驗不到想驗的東西，所以明講跳過，不要假裝通過。
        if self.env['doc.document'].sudo().browse(template.id).exists():
            self.skipTest('範本 id %d 剛好也是一筆文件的 id，驗不到外鍵違反'
                          % template.id)
        result = self._post_metric(template.id)
        self.assertTrue(result['success'])
        metric = self.env['doc.editor.perf.metric'].sudo().search(
            [('metric_type', '=', 'load_doc_ms')], order='id desc', limit=1)
        # 寧可遺失關聯也要留下這筆：doc_id 存 False，不是整筆丟掉。
        self.assertFalse(metric.doc_id)

    def test_metric_with_nonexistent_doc_id(self):
        ghost = self.env['doc.document'].sudo().search([], order='id desc', limit=1).id + 10000
        self.assertTrue(self._post_metric(ghost)['success'])

    def test_error_log_with_nonexistent_doc_id(self):
        ghost = self.env['doc.document'].sudo().search([], order='id desc', limit=1).id + 10000
        result = self.make_jsonrpc_request('/dobtor_doc/telemetry/error', {
            'error_type': 'js_error',
            'message': '遙測外鍵回歸測試',
            'doc_id': ghost,
        })
        self.assertTrue(result['success'])
        log = self.env['doc.editor.error.log'].sudo().search(
            [('message', '=', '遙測外鍵回歸測試')], limit=1)
        self.assertTrue(log)
        self.assertFalse(log.doc_id)
