# -*- coding: utf-8 -*-
import logging
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
    _description = '效率指標'
    _order = 'period_end desc'

    user_id = fields.Many2one(
        'res.users',
        string='用戶',
        index=True,
        ondelete='cascade',
    )

    department_id = fields.Many2one(
        'hr.department',
        string='部門',
        index=True,
        ondelete='set null',
    )

    period_type = fields.Selection([
        ('week', '週'),
        ('month', '月'),
        ('quarter', '季'),
    ], string='期間類型', required=True, index=True)

    period_start = fields.Date(
        string='期間起始',
        required=True,
        index=True,
    )

    period_end = fields.Date(
        string='期間結束',
        required=True,
        index=True,
    )

    period_name = fields.Char(
        string='期間名稱',
        compute='_compute_period_name',
        store=True,
        help='格式：2026-W02（週）、2026-01（月）、2026-Q1（季）',
    )

    # ===== 基礎統計 =====
    total_activities = fields.Integer(
        string='總待辦數',
        default=0,
    )
    completed_activities = fields.Integer(
        string='完成待辦數',
        default=0,
    )
    on_time_activities = fields.Integer(
        string='準時完成數',
        default=0,
        help='在截止日前完成的待辦數',
    )
    postponed_activities = fields.Integer(
        string='延期待辦數',
        default=0,
    )
    cancelled_activities = fields.Integer(
        string='取消待辦數',
        default=0,
    )

    # ===== 工時統計 =====
    total_estimated_hours = fields.Float(
        string='總預估工時',
        default=0,
    )
    total_actual_hours = fields.Float(
        string='總執行工時',
        default=0,
    )

    # ===== 來源統計 =====
    planned_source_count = fields.Integer(
        string='預排計畫數',
        default=0,
        help='來源為「計畫工作」的待辦數',
    )
    inserted_source_count = fields.Integer(
        string='臨時插入數',
        default=0,
        help='來源為「臨時插入」的待辦數',
    )

    # ===== 計算指標 =====
    completion_rate = fields.Float(
        string='完成率',
        compute='_compute_metrics',
        store=True,
        help='完成數 / 總數 * 100',
    )

    on_time_rate = fields.Float(
        string='準時完成率',
        compute='_compute_metrics',
        store=True,
        help='準時完成數 / 完成數 * 100',
    )

    estimation_accuracy = fields.Float(
        string='預估準確度',
        compute='_compute_metrics',
        store=True,
        help='1 - |預估-實際| / 預估 * 100',
    )

    postpone_rate = fields.Float(
        string='延期率',
        compute='_compute_metrics',
        store=True,
        help='延期數 / 總數 * 100',
    )

    efficiency_index = fields.Float(
        string='效率指數',
        compute='_compute_metrics',
        store=True,
        help='綜合效率評分（滿分 5 分）',
    )

    _sql_constraints = [
        ('unique_user_period', 'unique(user_id, period_type, period_start)',
         '同一用戶在同一期間只能有一筆效率指標記錄！'),
    ]

    # ========== Computed Methods ==========

    @api.depends('period_start', 'period_end', 'period_type')
    def _compute_period_name(self):
        for record in self:
            if not record.period_start:
                record.period_name = ''
                continue

            if record.period_type == 'week':
                record.period_name = record.period_start.strftime('%Y-W%W')
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
        """計算特定期間的效率指標

        Args:
            period_start: 期間起始日期
            period_end: 期間結束日期
            period_type: 期間類型（week/month/quarter）
        """
        # 取得所有內部用戶
        users = self.env['res.users'].search([
            ('share', '=', False),
            ('active', '=', True),
        ])

        created_count = 0
        for user in users:
            # 檢查是否已有記錄
            existing = self.search([
                ('user_id', '=', user.id),
                ('period_start', '=', period_start),
                ('period_end', '=', period_end),
                ('period_type', '=', period_type),
            ])
            if existing:
                continue

            # 取得期間內的待辦（包含已封存）
            activities = self.env['mail.activity'].with_context(
                active_test=False
            ).search([
                ('user_id', '=', user.id),
                ('planned_date', '>=', period_start),
                ('planned_date', '<=', period_end),
            ])

            if not activities:
                continue

            # 單次迭代計算所有統計值（優化效能）
            total = len(activities)
            completed = 0
            on_time = 0
            postponed = 0
            cancelled = 0
            total_estimated = 0
            total_actual = 0
            planned_count = 0
            inserted_count = 0

            for activity in activities:
                total_estimated += activity.estimated_hours or 0
                total_actual += activity.actual_hours or 0

                # 完成狀態判斷
                if activity.done_date:
                    completed += 1
                    # 準時判斷：完成日期 <= 截止日期
                    if activity.date_deadline and activity.done_date.date() <= activity.date_deadline:
                        on_time += 1

                # 延期判斷：有延期歷史
                if activity.postpone_count > 0:
                    postponed += 1

                # 取消判斷
                if activity.cancel_date:
                    cancelled += 1

                # 來源統計
                if activity.schedule_origin == 'planned':
                    planned_count += 1
                elif activity.schedule_origin == 'inserted':
                    inserted_count += 1

            # 取得部門
            department_id = False
            if hasattr(user, 'employee_id') and user.employee_id:
                if user.employee_id.department_id:
                    department_id = user.employee_id.department_id.id

            # 建立效率指標記錄
            self.create({
                'user_id': user.id,
                'department_id': department_id,
                'period_type': period_type,
                'period_start': period_start,
                'period_end': period_end,
                'total_activities': total,
                'completed_activities': completed,
                'on_time_activities': on_time,
                'postponed_activities': postponed,
                'cancelled_activities': cancelled,
                'total_estimated_hours': total_estimated,
                'total_actual_hours': total_actual,
                'planned_source_count': planned_count,
                'inserted_source_count': inserted_count,
            })
            created_count += 1

        _logger.info(
            'Efficiency metrics computed for period %s to %s (%s). Created %d records.',
            period_start, period_end, period_type, created_count
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
                'title': _('計算完成'),
                'message': _('已計算 %s 至 %s 的週效率指標') % (week_start, week_end),
                'sticky': False,
                'type': 'success',
            }
        }
