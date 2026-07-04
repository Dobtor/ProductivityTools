# -*- coding: utf-8 -*-
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class ActivityEfficiencyMetrics(models.Model):
    """效率指標

    用於統計用戶或部門的待辦執行效率，支援：
    - 週/月/季不同期間類型
    - 完成率、準時率、預估準確度等指標
    - 綜合效率指數計算
    - 定時任務自動計算
    """
    _name = 'activity.efficiency.metrics'
    _description = 'Efficiency Metrics'
    _order = 'period_end desc'

    user_id = fields.Many2one(
        'res.users',
        string='User',
        index=True,
        ondelete='cascade',
    )

    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        index=True,
        ondelete='set null',
    )

    period_type = fields.Selection([
        ('week', 'Week'),
        ('month', 'Month'),
        ('quarter', 'Quarter'),
    ], string='Period Type', required=True, index=True)

    period_start = fields.Date(
        string='Period Start',
        required=True,
        index=True,
    )

    period_end = fields.Date(
        string='Period End',
        required=True,
        index=True,
    )

    period_name = fields.Char(
        string='Period Name',
        compute='_compute_period_name',
        store=True,
        help='Format: 2026-W02 (week), 2026-01 (month), 2026-Q1 (quarter)',
    )

    # ===== 基礎統計 =====
    total_activities = fields.Integer(
        string='Total Activities',
        default=0,
    )
    completed_activities = fields.Integer(
        string='Completed Activities',
        default=0,
    )
    on_time_activities = fields.Integer(
        string='On-time Completions',
        default=0,
        help='Number of activities completed before deadline',
    )
    postponed_activities = fields.Integer(
        string='Postponed Activities',
        default=0,
    )
    cancelled_activities = fields.Integer(
        string='Cancelled Activities',
        default=0,
    )

    # ===== 工時統計 =====
    total_estimated_hours = fields.Float(
        string='Total Estimated Hours',
        default=0,
    )
    total_actual_hours = fields.Float(
        string='Total Actual Hours',
        default=0,
    )

    # ===== 來源統計 =====
    planned_source_count = fields.Integer(
        string='Planned Count',
        default=0,
        help='Number of activities with "Planned" origin',
    )
    inserted_source_count = fields.Integer(
        string='Inserted Count',
        default=0,
        help='Number of activities with "Inserted" origin',
    )

    # ===== 計算指標 =====
    completion_rate = fields.Float(
        string='Completion Rate',
        compute='_compute_metrics',
        store=True,
        help='Completed / Total * 100',
    )

    on_time_rate = fields.Float(
        string='On-time Rate',
        compute='_compute_metrics',
        store=True,
        help='On-time Completions / Completed * 100',
    )

    estimation_accuracy = fields.Float(
        string='Estimation Accuracy',
        compute='_compute_metrics',
        store=True,
        help='1 - |Estimated - Actual| / Estimated * 100',
    )

    postpone_rate = fields.Float(
        string='Postpone Rate',
        compute='_compute_metrics',
        store=True,
        help='Postponed / Total * 100',
    )

    efficiency_index = fields.Float(
        string='Efficiency Index',
        compute='_compute_metrics',
        store=True,
        help='Comprehensive efficiency score (max 5 points)',
    )

    _sql_constraints = [
        ('unique_user_period', 'unique(user_id, period_type, period_start)',
         'Each user can only have one efficiency metric record per period!'),
    ]

    # ========== Computed Methods ==========

    @api.depends('period_start', 'period_end', 'period_type')
    def _compute_period_name(self):
        for record in self:
            if not record.period_start:
                record.period_name = ''
                continue

            if record.period_type == 'week':
                iso_year, iso_week, _dow = record.period_start.isocalendar()
                record.period_name = '%d-W%02d' % (iso_year, iso_week)
            elif record.period_type == 'month':
                record.period_name = record.period_start.strftime('%Y-%m')
            elif record.period_type == 'quarter':
                quarter = (record.period_start.month - 1) // 3 + 1
                record.period_name = '%s-Q%d' % (record.period_start.year, quarter)
            else:
                record.period_name = str(record.period_start)

    @api.depends(
        'total_activities',
        'completed_activities',
        'on_time_activities',
        'postponed_activities',
        'total_estimated_hours',
        'total_actual_hours'
    )
    def _compute_metrics(self):
        for record in self:
            # 完成率 = 完成數 / 總數 * 100
            if record.total_activities:
                record.completion_rate = (
                    record.completed_activities / record.total_activities * 100
                )
            else:
                record.completion_rate = 0

            # 準時完成率 = 準時完成數 / 完成數 * 100
            if record.completed_activities:
                record.on_time_rate = (
                    record.on_time_activities / record.completed_activities * 100
                )
            else:
                record.on_time_rate = 0

            # 預估準確度 = 1 - |預估-實際| / 預估 * 100
            if record.total_estimated_hours:
                deviation = abs(
                    record.total_estimated_hours - record.total_actual_hours
                )
                record.estimation_accuracy = max(
                    0, (1 - deviation / record.total_estimated_hours) * 100
                )
            else:
                record.estimation_accuracy = 0

            # 延期率 = 延期數 / 總數 * 100
            if record.total_activities:
                record.postpone_rate = (
                    record.postponed_activities / record.total_activities * 100
                )
            else:
                record.postpone_rate = 0

            # 效率指數 = 加權平均（滿分 5 分）
            # 權重：完成率 30% + 準時率 30% + 準確度 25% + (100-延期率) 15%
            # 將百分比轉換為 5 分制
            record.efficiency_index = (
                (record.completion_rate * 0.30 +
                 record.on_time_rate * 0.30 +
                 record.estimation_accuracy * 0.25 +
                 (100 - record.postpone_rate) * 0.15) / 20
            )

    # ========== Cron Methods ==========

    @api.model
    def _cron_compute_metrics(self):
        """定時計算效率指標

        執行時機：
        - 每週一計算上週指標
        - 每月1號計算上月指標
        - 每季第一天計算上季指標
        """
        today = fields.Date.today()

        # 週一計算上週指標
        if today.weekday() == 0:
            week_end = today - timedelta(days=1)  # 上週日
            week_start = week_end - timedelta(days=6)  # 上週一
            self._compute_period_metrics(week_start, week_end, 'week')

        # 每月1號計算上月指標
        if today.day == 1:
            last_month_end = today - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            self._compute_period_metrics(last_month_start, last_month_end, 'month')

        # 每季第一天計算上季指標
        if today.month in [1, 4, 7, 10] and today.day == 1:
            quarter_end = today - timedelta(days=1)
            # 計算上季第一天
            quarter_month = ((quarter_end.month - 1) // 3) * 3 + 1
            quarter_start = quarter_end.replace(month=quarter_month, day=1)
            self._compute_period_metrics(quarter_start, quarter_end, 'quarter')

    def _compute_period_metrics(self, period_start, period_end, period_type):
        """計算特定期間的效率指標（批次優化）

        Args:
            period_start: 期間起始日期
            period_end: 期間結束日期
            period_type: 期間類型（week/month/quarter）
        """
        # 批次取得已存在記錄（用於 upsert）
        existing_records = {
            r.user_id.id: r for r in self.search([
                ('period_start', '=', period_start),
                ('period_end', '=', period_end),
                ('period_type', '=', period_type),
            ])
        }

        # 一次查詢所有內部用戶在期間內的待辦（取代 N 次 search）
        all_activities = self.env['mail.activity'].with_context(
            active_test=False
        ).search_read([
            ('user_id', '!=', False),
            ('user_id.share', '=', False),
            ('planned_date', '>=', period_start),
            ('planned_date', '<=', period_end),
        ], [
            'user_id', 'estimated_hours', 'actual_hours',
            'done_date', 'date_deadline', 'cancel_date',
            'postpone_count', 'schedule_origin',
        ])

        # 依 user_id 分組
        user_activities = defaultdict(list)
        for act in all_activities:
            uid = act['user_id'][0]
            user_activities[uid].append(act)

        if not user_activities:
            _logger.info(
                'Efficiency metrics: no new data for period %s to %s (%s).',
                period_start, period_end, period_type
            )
            return

        # 批次取得部門資訊（一次查詢）
        user_ids = list(user_activities.keys())
        employees = self.env['hr.employee'].search_read([
            ('user_id', 'in', user_ids),
            ('active', '=', True),
        ], ['user_id', 'department_id'])
        user_department_map = {
            emp['user_id'][0]: emp['department_id'][0] if emp['department_id'] else False
            for emp in employees
        }

        # 批次建立或更新效率指標記錄（upsert 模式）
        create_list = []
        update_count = 0
        for uid, activities in user_activities.items():
            total = len(activities)
            completed = 0
            on_time = 0
            postponed = 0
            cancelled = 0
            total_estimated = 0.0
            total_actual = 0.0
            planned_count = 0
            inserted_count = 0

            for act in activities:
                total_estimated += act['estimated_hours'] or 0
                total_actual += act['actual_hours'] or 0

                if act['done_date']:
                    completed += 1
                    # done_date 為 UTC datetime，date_deadline 為本地 Date；
                    # 先轉本地時區再取日期，避免近午夜完成被誤判準時/逾期（UTC+8）。
                    done_local_date = fields.Datetime.context_timestamp(
                        self, act['done_date']).date()
                    if act['date_deadline'] and done_local_date <= act['date_deadline']:
                        on_time += 1

                if (act['postpone_count'] or 0) > 0:
                    postponed += 1

                if act['cancel_date']:
                    cancelled += 1

                origin = act['schedule_origin']
                if origin == 'planned':
                    planned_count += 1
                elif origin == 'inserted':
                    inserted_count += 1

            metric_vals = {
                'department_id': user_department_map.get(uid, False),
                'total_activities': total,
                'completed_activities': completed,
                'on_time_activities': on_time,
                'postponed_activities': postponed,
                'cancelled_activities': cancelled,
                'total_estimated_hours': total_estimated,
                'total_actual_hours': total_actual,
                'planned_source_count': planned_count,
                'inserted_source_count': inserted_count,
            }

            existing = existing_records.get(uid)
            if existing:
                existing.write(metric_vals)
                update_count += 1
            else:
                metric_vals.update({
                    'user_id': uid,
                    'period_type': period_type,
                    'period_start': period_start,
                    'period_end': period_end,
                })
                create_list.append(metric_vals)

        if create_list:
            self.create(create_list)

        _logger.info(
            'Efficiency metrics computed for period %s to %s (%s). Created %d, updated %d records.',
            period_start, period_end, period_type, len(create_list), update_count
        )

    @api.model
    def action_compute_current_week(self):
        """手動計算當前週的效率指標（供測試或手動觸發）"""
        today = fields.Date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        self._compute_period_metrics(week_start, week_end, 'week')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Calculation Complete'),
                'message': _('Weekly efficiency metrics calculated from %(start)s to %(end)s', start=week_start, end=week_end),
                'sticky': False,
                'type': 'success',
            }
        }
