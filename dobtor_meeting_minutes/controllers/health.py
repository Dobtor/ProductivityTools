# -*- coding: utf-8 -*-
"""Health / monitoring endpoint

僅供後端監控系統（Prometheus / Uptime 等）拉取統計資訊。
- auth='user'：避免公開 API 外洩內部指標
- 回傳最近 1 小時統計 + 即時狀態
"""

from datetime import timedelta

from odoo import fields, http
from odoo.http import request, Response


class MeetingHealthController(http.Controller):

    @http.route('/meeting_minutes/health', type='json', auth='user', methods=['POST'])
    def health(self):
        """回傳 transcribe 子系統健康指標

        Response:
            {
              "status": "ok" | "degraded" | "unhealthy",
              "processing_count": int,
              "stale_count": int,             # processing 超過 15 分鐘
              "failures_1h": int,
              "successes_1h": int,
              "failure_rate_1h": float,       # 0.0 ~ 1.0
              "by_state_24h": {state: count},
              "latest_success_at": iso str or null,
              "latest_failure_at": iso str or null,
            }
        """
        env = request.env
        Recording = env['note.recording']
        Log = env['note.transcribe.log']
        now = fields.Datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(hours=24)
        stale_cutoff = now - timedelta(minutes=15)

        processing_count = Recording.search_count([('state', '=', 'processing')])
        stale_count = Recording.search_count([
            ('state', '=', 'processing'),
            ('write_date', '<', stale_cutoff),
        ])

        success_1h = Log.search_count([
            ('state', '=', 'success'),
            ('create_date', '>=', one_hour_ago),
        ])
        fail_1h = Log.search_count([
            ('state', '!=', 'success'),
            ('create_date', '>=', one_hour_ago),
        ])
        total_1h = success_1h + fail_1h
        failure_rate = round(fail_1h / total_1h, 3) if total_1h else 0.0

        # by_state_24h
        groups = Log._read_group(
            domain=[('create_date', '>=', one_day_ago)],
            groupby=['state'],
            aggregates=['__count'],
        )
        by_state = {state: count for state, count in groups}

        latest_success = Log.search(
            [('state', '=', 'success')],
            order='id desc', limit=1,
        )
        latest_failure = Log.search(
            [('state', '!=', 'success')],
            order='id desc', limit=1,
        )

        # 健康狀態判定
        if stale_count > 0:
            status = 'unhealthy'
        elif failure_rate >= 0.5 and total_1h >= 3:
            status = 'degraded'
        else:
            status = 'ok'

        return {
            'status': status,
            'processing_count': processing_count,
            'stale_count': stale_count,
            'successes_1h': success_1h,
            'failures_1h': fail_1h,
            'failure_rate_1h': failure_rate,
            'by_state_24h': by_state,
            'latest_success_at': latest_success.create_date.isoformat() if latest_success else None,
            'latest_failure_at': latest_failure.create_date.isoformat() if latest_failure else None,
        }

    @http.route('/meeting_minutes/metrics', type='http', auth='user', methods=['GET'])
    def metrics(self):
        """OpenMetrics (Prometheus) 格式輸出

        可直接被 Prometheus scraper 採集：
            scrape_configs:
              - job_name: 'odoo_meeting_minutes'
                static_configs:
                  - targets: ['odoo.example.com']
                metrics_path: /meeting_minutes/metrics
                bearer_token: '<session token>'

        指標：
        - dobtor_mm_recording_total{state}       counter
        - dobtor_mm_transcribe_log_total{state}  counter（24h 視窗）
        - dobtor_mm_summary_log_total{state}     counter（24h 視窗）
        - dobtor_mm_processing_count             gauge
        - dobtor_mm_stale_count                  gauge
        - dobtor_mm_latency_ms_bucket{le=...}    histogram（24h）
        """
        env = request.env
        now = fields.Datetime.now()
        one_day_ago = now - timedelta(hours=24)

        lines = []

        def add_metric(name, help_text, mtype, samples):
            lines.append(f'# HELP {name} {help_text}')
            lines.append(f'# TYPE {name} {mtype}')
            for labels, value in samples:
                label_str = ''
                if labels:
                    label_str = '{' + ','.join(f'{k}="{v}"' for k, v in labels.items()) + '}'
                lines.append(f'{name}{label_str} {value}')

        # Recording state counts (current)
        Rec = env['note.recording']
        rec_groups = Rec._read_group(domain=[], groupby=['state'], aggregates=['__count'])
        add_metric(
            'dobtor_mm_recording_total',
            'Current count of recordings by state',
            'gauge',
            [({'state': s}, c) for s, c in rec_groups],
        )

        # Processing + stale
        processing = Rec.search_count([('state', '=', 'processing')])
        stale = Rec.search_count([
            ('state', '=', 'processing'),
            ('write_date', '<', now - timedelta(minutes=15)),
        ])
        add_metric('dobtor_mm_processing_count', 'Recordings currently in processing', 'gauge',
                   [({}, processing)])
        add_metric('dobtor_mm_stale_count', 'Stale processing recordings (>15min)', 'gauge',
                   [({}, stale)])

        # Transcribe log by state (24h)
        TLog = env['note.transcribe.log']
        tlog_groups = TLog._read_group(
            domain=[('create_date', '>=', one_day_ago)],
            groupby=['state', 'provider'],
            aggregates=['__count'],
        )
        add_metric(
            'dobtor_mm_transcribe_log_total',
            'Transcribe log entries in last 24h',
            'counter',
            [({'state': s or 'unknown', 'provider': p or 'unknown'}, c) for s, p, c in tlog_groups],
        )

        # Summary log by state (24h)
        try:
            SLog = env['note.summary.log']
            slog_groups = SLog._read_group(
                domain=[('create_date', '>=', one_day_ago)],
                groupby=['state'],
                aggregates=['__count'],
            )
            add_metric(
                'dobtor_mm_summary_log_total',
                'Summary log entries in last 24h',
                'counter',
                [({'state': s}, c) for s, c in slog_groups],
            )
        except Exception:
            pass  # 模型可能未安裝

        # Latency histogram (24h) — simplified (5 buckets + sum + count)
        buckets = [1000, 5000, 15000, 60000, 300000, float('inf')]
        latencies = TLog.search([
            ('create_date', '>=', one_day_ago),
            ('request_latency_ms', '>', 0),
        ]).mapped('request_latency_ms')
        cumulative = 0
        lines.append('# HELP dobtor_mm_transcribe_latency_ms Transcribe latency distribution')
        lines.append('# TYPE dobtor_mm_transcribe_latency_ms histogram')
        for b in buckets[:-1]:
            count = sum(1 for l in latencies if l <= b)
            lines.append(f'dobtor_mm_transcribe_latency_ms_bucket{{le="{b}"}} {count}')
        lines.append(f'dobtor_mm_transcribe_latency_ms_bucket{{le="+Inf"}} {len(latencies)}')
        lines.append(f'dobtor_mm_transcribe_latency_ms_sum {sum(latencies)}')
        lines.append(f'dobtor_mm_transcribe_latency_ms_count {len(latencies)}')

        body = '\n'.join(lines) + '\n'
        return Response(body, content_type='text/plain; version=0.0.4; charset=utf-8', status=200)
