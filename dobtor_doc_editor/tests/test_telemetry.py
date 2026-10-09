"""Tests for monitoring & telemetry models (P2-4)。"""

from datetime import timedelta

from odoo import fields
from odoo.tests.common import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

from .session_probe import SessionAliveMixin


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
class TestTelemetryRoutes(SessionAliveMixin, HttpCase):
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
        # ☠️ 2026-10-09：這個類別偶發過一次（1 failed + 1 error，隨後連跑三次
        # 全綠），而當時它沒有這道檢查，所以那一次的原因沒有留下任何證據。
        # 見 tests/session_probe.py 的檔頭與 §7.9。
        self._assert_session_alive('setUp')
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


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestExportLog(TransactionCase):
    """`doc.editor.export.log` 的四支方法。

    ☠️ 這個模型原本**整支零測試**——包含一支每天跑的 cron
    （`cron_health_check_no_alias` → `_cron_health_check_no_alias`）。
    這是紀律 13 的「半死測試」更糟的版本：不是測試沒人跑，是**production
    程式碼每天在無人看管的情況下跑，而沒有任何東西證明它還能跑**。
    （2026-10-09 稽核發現。觸發點是當時試做的 static CI 第一次真的執行就紅在
    檢查本身——CI 後來撤掉了（ADR-028），但「寫好了但從沒執行過」這條線索
    留下來，拿去查全模組就查到這裡。）
    """

    def setUp(self):
        super().setUp()
        self.Export = self.env['doc.editor.export.log']
        self.doc = self.env['doc.document'].create({'name': '匯出紀錄測試文件'})

    # ─── record_export ────────────────────────────────────────────────

    def test_record_export_writes_the_row(self):
        rec = self.Export.record_export(
            self.doc, 'pdf', with_alias=False, file_size=1234, source='editor')
        self.assertTrue(rec, 'record_export 回 False＝寫入失敗被吞掉了')
        self.assertEqual(rec.doc_id, self.doc)
        self.assertEqual(rec.file_format, 'pdf')
        self.assertFalse(rec.with_alias)
        self.assertEqual(rec.file_size, 1234)
        self.assertEqual(rec.source, 'editor')
        self.assertEqual(rec.user_id, self.env.user)

    def test_record_ref_only_when_bound(self):
        """record_ref 是稽核追溯用的「model,res_id」；沒綁定就該是 False。"""
        unbound = self.Export.record_export(
            self.doc, 'pdf', with_alias=False, file_size=1)
        self.assertFalse(unbound.record_ref)

        partner = self.env['res.partner'].create({'name': '匯出紀錄測試夥伴'})
        self.doc.write({
            'model_id': self.env['ir.model']._get('res.partner').id,
            'res_id': partner.id,
        })
        bound = self.Export.record_export(
            self.doc, 'docx', with_alias=True, file_size=2)
        self.assertEqual(bound.record_ref, 'res.partner,%d' % partner.id)

    def test_record_export_contains_a_database_failure(self):
        """☠️ 這一則是這批的重點：docstring 說「log 失敗絕不可擋住下載」。

        try/except **只接得住 Python 例外**。資料庫層的錯誤會讓 PostgreSQL
        整筆交易進入 aborted，於是吞掉之後呼叫端接下來的 DB 動作全部失敗
        ——`action_export_pdf` 在那一行之後 4 行就 `ir.attachment.create(...)`。

        所以斷言不是「回 False」（沒 savepoint 也會回 False），而是
        **交易還活著**：後面的 ORM 操作做得成。移掉 savepoint 這一則會紅。
        """
        from unittest.mock import patch
        Model = type(self.Export)
        original = Model.create

        def explode_in_the_database(model_self, vals):
            # 真的讓 PG 進入 aborted 狀態——不是丟一個 Python 例外假裝。
            model_self.env.cr.execute('SELECT 1 / 0')
            return original(model_self, vals)

        # 這個失敗是**刻意**的，所以把它的 log 消音：odoo.sql_db 會記一筆
        # ERROR、record_export 自己會記一筆 WARNING。不消音的話每次跑測試都
        # 在 log 裡留紅字——那正是「訓練大家無視紅燈」，跟 CI gate 不該配上
        # 偶發失敗是同一個理由。
        muted = mute_logger(
            'odoo.sql_db',
            'odoo.addons.dobtor_doc_editor.models.doc_telemetry')
        with patch.object(Model, 'create', explode_in_the_database), muted:
            result = self.Export.record_export(
                self.doc, 'pdf', with_alias=True, file_size=1)
        self.assertFalse(result, '寫入失敗時要回 False')

        # 關鍵：呼叫端接下來要做的事（建 attachment）必須還做得成。
        att = self.env['ir.attachment'].create({
            'name': 'savepoint-regression.pdf',
            'type': 'binary',
            'res_model': 'doc.document',
            'res_id': self.doc.id,
        })
        self.assertTrue(att.exists(),
                        '交易被中止了——savepoint 沒有把失敗圍住')

    # ─── gc_old_logs（export log 版，預設 180 天）──────────────────────

    def test_gc_keeps_recent_removes_old(self):
        """☠️ 這支與 doc.editor.error.log 的 gc_old_logs **同名不同實作**
        （預設 180 天 vs 30 天）。測到的是 error log 那一支不算測到這一支。
        """
        recent = self.Export.record_export(
            self.doc, 'pdf', with_alias=True, file_size=1)
        old = self.Export.record_export(
            self.doc, 'pdf', with_alias=True, file_size=1)
        self.env.cr.execute(
            "UPDATE doc_editor_export_log SET create_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=200), old.id))
        self.Export.invalidate_recordset()

        n = self.Export.gc_old_logs(days=180)
        self.assertGreaterEqual(n, 1)
        self.assertFalse(old.exists(), '200 天前的紀錄沒被清掉')
        self.assertTrue(recent.exists(), '剛剛寫的紀錄被清掉了')

    # ─── get_no_alias_summary ＋ 每天跑的 cron ─────────────────────────

    def test_no_alias_summary_counts_only_unbound_exports(self):
        self.Export.record_export(self.doc, 'pdf', with_alias=True, file_size=1)
        self.Export.record_export(self.doc, 'pdf', with_alias=False, file_size=1)
        self.Export.record_export(self.doc, 'docx', with_alias=False, file_size=1)

        summary = self.Export.get_no_alias_summary(hours=24)
        self.assertEqual(summary['count'], 2,
                         'with_alias=True 的那筆不該被算進來')
        self.assertEqual(summary['hours'], 24)
        self.assertIn(self.doc.id, summary['doc_ids'])
        self.assertIn(self.doc.name, summary['doc_names'])

    def test_no_alias_summary_respects_the_time_window(self):
        old = self.Export.record_export(
            self.doc, 'pdf', with_alias=False, file_size=1)
        self.env.cr.execute(
            "UPDATE doc_editor_export_log SET create_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(hours=48), old.id))
        self.Export.invalidate_recordset()
        self.assertEqual(self.Export.get_no_alias_summary(hours=24)['count'], 0)
        self.assertEqual(self.Export.get_no_alias_summary(hours=72)['count'], 1)

    def test_cron_health_check_warns_and_returns_count(self):
        """每天跑的那一支。刻意只記 log 不發 mail——所以要驗 log 真的有寫。"""
        self.Export.record_export(self.doc, 'pdf', with_alias=False, file_size=1)
        logger = 'odoo.addons.dobtor_doc_editor.models.doc_telemetry'
        with self.assertLogs(logger, level='WARNING') as captured:
            n = self.Export._cron_health_check_no_alias(hours=24)
        self.assertEqual(n, 1)
        self.assertTrue(
            any('未帶入實際值' in line for line in captured.output),
            'health-check 沒有寫出可被監控抓取的 warning：%r' % captured.output)

    def test_cron_health_check_is_silent_when_everything_is_bound(self):
        """沒有問題時不可以留 warning——每天叫一次狼來了就沒人看了。"""
        self.Export.record_export(self.doc, 'pdf', with_alias=True, file_size=1)
        logger = 'odoo.addons.dobtor_doc_editor.models.doc_telemetry'
        with self.assertNoLogs(logger, level='WARNING'):
            self.assertEqual(
                self.Export._cron_health_check_no_alias(hours=24), 0)
