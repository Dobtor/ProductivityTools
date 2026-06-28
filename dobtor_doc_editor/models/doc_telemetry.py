"""監控與遙測模型（P2-4）。

提供三個 model 收集 runtime 觀察資料：
    - doc.editor.error.log     ：JS 錯誤 / unhandled promise rejection
    - doc.editor.perf.metric   ：Web Vitals (LCP/FID/CLS) + 業務 timing
                                 （load_ms / first_render_ms / save_latency_ms）
    - doc.editor.export.log    ：匯出事件稽核（誰/何時/哪份/格式/是否帶 alias）

設計取捨：
    - 不外接 Sentry / Datadog（避免商業依賴與資料外流）
    - 用 Odoo model 儲存 → 後台可直接查看、可 join 既有的 res.users
    - 自動清理：cron 每天清 N 天前的記錄（避免無限長大）
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class DocEditorErrorLog(models.Model):
    """前端錯誤紀錄。"""

    _name = 'doc.editor.error.log'
    _description = '文件編輯器錯誤紀錄'
    _order = 'create_date desc'

    doc_id = fields.Many2one('doc.document', string='文件', ondelete='set null', index=True)
    user_id = fields.Many2one('res.users', string='使用者', ondelete='set null', index=True)
    company_id = fields.Many2one('res.company', string='公司', ondelete='set null')
    error_type = fields.Selection([
        ('js_error', 'JS Error'),
        ('promise_rejection', 'Unhandled Promise'),
        ('canvas_error', 'Canvas Editor Error'),
        ('save_failure', 'Save Failure'),
        ('import_failure', 'Import Failure'),
        ('export_failure', 'Export Failure'),
        ('other', '其他'),
    ], string='錯誤類別', required=True, default='other', index=True)
    message = fields.Char(string='訊息', size=512)
    stack_trace = fields.Text(string='Stack trace')
    user_agent = fields.Char(string='User Agent', size=256)
    url = fields.Char(string='URL', size=512)
    extra = fields.Json(string='額外資料', help='前端附帶的 context (例: docId, action)')

    @api.model
    def gc_old_logs(self, days=30):
        """Cron 用：清理 N 天前的錯誤紀錄。"""
        from datetime import timedelta
        threshold = fields.Datetime.now() - timedelta(days=days)
        old = self.search([('create_date', '<', threshold)])
        n = len(old)
        if n:
            old.unlink()
            _logger.info("doc.editor.error.log: gc removed %d old entries", n)
        return n


class DocEditorPerfMetric(models.Model):
    """前端效能指標紀錄。

    每筆代表一個 metric event。常見 metric_type 與其單位：
        load_doc_ms          載入文件總耗時
        first_render_ms      首次渲染完成
        save_latency_ms      save round-trip
        web_vitals_lcp_ms    Largest Contentful Paint
        web_vitals_fid_ms    First Input Delay
        web_vitals_cls       Cumulative Layout Shift（無單位 0-1）
        canvas_set_value_ms  executeSetValue 耗時
    """

    _name = 'doc.editor.perf.metric'
    _description = '文件編輯器效能指標'
    _order = 'create_date desc'

    doc_id = fields.Many2one('doc.document', string='文件', ondelete='set null', index=True)
    user_id = fields.Many2one('res.users', string='使用者', ondelete='set null', index=True)
    metric_type = fields.Char(string='指標類型', required=True, index=True)
    value = fields.Float(string='值', required=True, help='毫秒 / 秒 / 比率（依 metric_type 而定）')
    page_count = fields.Integer(string='文件頁數', help='如為文件層級的 metric')
    extra = fields.Json(string='額外資料')

    @api.model
    def gc_old_metrics(self, days=14):
        """Cron 用：清理 N 天前的效能紀錄（保留期較短，量大）。"""
        from datetime import timedelta
        threshold = fields.Datetime.now() - timedelta(days=days)
        old = self.search([('create_date', '<', threshold)])
        n = len(old)
        if n:
            old.unlink()
            _logger.info("doc.editor.perf.metric: gc removed %d old entries", n)
        return n

    @api.model
    def aggregate_recent(self, metric_type, hours=24):
        """簡易彙總：min / max / mean / count。

        給 admin dashboard 或 health-check 用。
        """
        from datetime import timedelta
        threshold = fields.Datetime.now() - timedelta(hours=hours)
        recs = self.search([
            ('metric_type', '=', metric_type),
            ('create_date', '>=', threshold),
        ])
        if not recs:
            return {'count': 0}
        values = recs.mapped('value')
        return {
            'count': len(values),
            'min': min(values),
            'max': max(values),
            'mean': sum(values) / len(values),
        }


class DocEditorExportLog(models.Model):
    """文件匯出事件紀錄（稽核用）。

    每筆代表一次「使用者主動下載」的匯出（PDF / DOCX）。
    與 perf.metric 分開：這是業務稽核資料（誰在何時匯出哪份文件、
    是否帶入實際值），需要可篩選的結構化欄位、保留期較長，
    不適合塞進通用的 metric_type/value 結構。
    """

    _name = 'doc.editor.export.log'
    _description = '文件匯出紀錄'
    _order = 'create_date desc'

    doc_id = fields.Many2one('doc.document', string='文件', ondelete='set null', index=True)
    user_id = fields.Many2one('res.users', string='匯出者', ondelete='set null', index=True,
                              default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', string='公司', ondelete='set null',
                                 default=lambda self: self.env.company)
    file_format = fields.Selection([
        ('pdf', 'PDF'),
        ('docx', 'DOCX'),
    ], string='格式', required=True, index=True)
    with_alias = fields.Boolean(
        string='已帶入實際值',
        help='True＝匯出時帶入綁定 record，alias 已渲染成實際值；'
             'False＝未綁定 record，輸出 token 原文。',
    )
    file_size = fields.Integer(string='檔案大小 (bytes)')
    record_ref = fields.Char(string='來源記錄', size=128,
                             help='匯出當下綁定的「model,res_id」（稽核追溯用）')
    source = fields.Selection([
        ('form_button', 'Form 按鈕'),
        ('editor', '編輯器'),
        ('batch', '批次匯出'),
        ('other', '其他'),
    ], string='來源', default='other', index=True)

    @api.model
    def record_export(self, doc, file_format, with_alias, file_size, source='other'):
        """寫一筆匯出紀錄。任何例外都吞掉——log 失敗絕不可擋住下載。"""
        try:
            record_ref = False
            if doc.model_id and doc.res_id:
                record_ref = f'{doc.model_id.model},{doc.res_id}'
            return self.sudo().create({
                'doc_id': doc.id,
                'user_id': self.env.uid,
                'company_id': self.env.company.id,
                'file_format': file_format,
                'with_alias': bool(with_alias),
                'file_size': file_size or 0,
                'record_ref': record_ref,
                'source': source,
            })
        except Exception:
            _logger.warning("doc.editor.export.log: 寫入匯出紀錄失敗", exc_info=True)
            return False

    @api.model
    def gc_old_logs(self, days=180):
        """Cron 用：清理 N 天前的匯出紀錄（稽核資料保留較久，預設半年）。"""
        from datetime import timedelta
        threshold = fields.Datetime.now() - timedelta(days=days)
        old = self.search([('create_date', '<', threshold)])
        n = len(old)
        if n:
            old.unlink()
            _logger.info("doc.editor.export.log: gc removed %d old entries", n)
        return n

    @api.model
    def get_no_alias_summary(self, hours=24):
        """回傳最近 N 小時內「未帶入實際值」的匯出摘要。

        with_alias=False 代表使用者匯出了沒綁 model_id/res_id 的文件，
        產出的是 {{ varname }} / 《token》 原文而非實際值——通常是設定遺漏。
        給 health-check / dashboard 主動查詢用（對齊 perf.metric.aggregate_recent）。
        """
        from datetime import timedelta
        threshold = fields.Datetime.now() - timedelta(hours=hours)
        recs = self.search([
            ('with_alias', '=', False),
            ('create_date', '>=', threshold),
        ])
        docs = recs.mapped('doc_id')
        return {
            'count': len(recs),
            'hours': hours,
            'doc_ids': docs.ids,
            'doc_names': docs.mapped('name'),
        }

    @api.model
    def _cron_health_check_no_alias(self, hours=24):
        """Cron：每天檢查「匯出 token 原文」事件，有就 logger.warning。

        刻意只記 log 不發 mail / 不建 activity：
            - 避免每天重複騷擾匯出者
            - log 會進 docker logs，可被既有 health 監控（gstack /health）抓取
        """
        summary = self.get_no_alias_summary(hours=hours)
        if summary['count']:
            _logger.warning(
                "doc.editor.export.log health-check：最近 %d 小時有 %d 筆匯出未帶入實際值"
                "（輸出 token 原文），涉及文件 %s。請確認這些文件已綁定關聯模型與記錄。",
                hours, summary['count'], summary['doc_ids'],
            )
        return summary['count']
