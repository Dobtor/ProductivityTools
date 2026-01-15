# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, ValidationError


class WeeklyReport(models.Model):
    """週報告

    用於記錄每週計畫與執行回顧，支援：
    - 上週執行回顧（比對快照與實際執行）
    - 本週計畫快照（凍結當時狀態供下週比對）
    - 未來安排與尚未安排的待辦
    - 統計指標計算
    """
    _name = 'weekly.report'
    _description = '週報告'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'week_start desc'

    name = fields.Char(
        string='報告名稱',
        compute='_compute_name',
        store=True,
    )

    user_id = fields.Many2one(
        'res.users',
        string='用戶',
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
        index=True,
    )

    week_start = fields.Date(
        string='週起始日',
        required=True,
        index=True,
    )

    week_end = fields.Date(
        string='週結束日',
        compute='_compute_week_end',
        store=True,
    )

    week_number = fields.Char(
        string='週次',
        compute='_compute_week_number',
        store=True,
        help='格式：2026-W02',
    )

    state = fields.Selection([
        ('draft', '草稿'),
        ('confirmed', '已確認'),
    ], string='狀態', default='draft', tracking=True)

    # ===== 上週執行回顧（比對結果）=====
    previous_week_review_ids = fields.One2many(
        'weekly.report.review.line',
        'report_id',
        string='上週執行回顧',
    )

    # ===== 本週計畫（即時連結）=====
    this_week_activity_ids = fields.Many2many(
        'mail.activity',
        'weekly_report_this_week_activity_rel',
        'report_id',
        'activity_id',
        string='本週計畫',
    )

    # ===== 本週計畫快照（關鍵！供下週比對）=====
    this_week_snapshot_ids = fields.One2many(
        'weekly.report.snapshot.line',
        'report_id',
        string='本週計畫快照',
    )

    # ===== 未來安排 =====
    future_activity_ids = fields.Many2many(
        'mail.activity',
        'weekly_report_future_activity_rel',
        'report_id',
        'activity_id',
        string='未來安排',
    )

    # ===== 尚未安排 =====
    unscheduled_activity_ids = fields.Many2many(
        'mail.activity',
        'weekly_report_unscheduled_activity_rel',
        'report_id',
        'activity_id',
        string='尚未安排',
    )

    # ===== 統計資訊 =====
    total_planned_hours = fields.Float(
        string='本週計畫工時',
        compute='_compute_stats',
        store=True,
    )

    total_review_planned_hours = fields.Float(
        string='上週計畫工時',
        compute='_compute_stats',
        store=True,
    )

    total_review_actual_hours = fields.Float(
        string='上週實際工時',
        compute='_compute_stats',
        store=True,
    )

    completion_rate = fields.Float(
        string='完成率',
        compute='_compute_stats',
        store=True,
        help='上週回顧中已完成的比例（百分比）',
    )

    planned_completion_rate = fields.Float(
        string='計畫完成率',
        compute='_compute_stats',
        store=True,
        help='上週計畫內工作的完成率（百分比）',
    )

    inserted_count = fields.Integer(
        string='臨時插入數',
        compute='_compute_stats',
        store=True,
    )

    # ===== 自評建議 =====
    self_evaluation = fields.Html(
        string='自評或建議',
    )

    # ===== 前一週報告（用於比對）=====
    previous_report_id = fields.Many2one(
        'weekly.report',
        string='前一週報告',
        compute='_compute_previous_report',
    )

    _sql_constraints = [
        ('user_week_unique', 'unique(user_id, week_start)',
         '同一用戶在同一週只能有一份週報告！'),
    ]

    # ========== Computed Methods ==========

    @api.depends('user_id', 'week_start')
    def _compute_name(self):
        for report in self:
            if report.week_start:
                week_str = report.week_start.strftime('%Y-W%W')
                user_name = report.user_id.name if report.user_id else ''
                report.name = _('%s 週報告 (%s)') % (user_name, week_str)
            else:
                report.name = _('週報告')

    @api.depends('week_start')
    def _compute_week_end(self):
        for report in self:
            if report.week_start:
                report.week_end = report.week_start + timedelta(days=6)
            else:
                report.week_end = False

    @api.depends('week_start')
    def _compute_week_number(self):
        for report in self:
            if report.week_start:
                report.week_number = report.week_start.strftime('%Y-W%W')
            else:
                report.week_number = False

    @api.depends('week_start', 'user_id')
    def _compute_previous_report(self):
        for report in self:
            if report.week_start and report.user_id:
                prev_week_start = report.week_start - timedelta(days=7)
                prev_report = self.search([
                    ('user_id', '=', report.user_id.id),
                    ('week_start', '=', prev_week_start),
                    ('state', '=', 'confirmed'),
                ], limit=1)
                report.previous_report_id = prev_report
            else:
                report.previous_report_id = False

    @api.depends(
        'this_week_snapshot_ids',
        'this_week_snapshot_ids.estimated_hours',
        'previous_week_review_ids',
        'previous_week_review_ids.planned_hours',
        'previous_week_review_ids.actual_hours',
        'previous_week_review_ids.status',
        'previous_week_review_ids.source'
    )
    def _compute_stats(self):
        for report in self:
            # 本週計畫工時
            report.total_planned_hours = sum(
                line.estimated_hours or 0
                for line in report.this_week_snapshot_ids
            )

            # 上週回顧統計
            review_lines = report.previous_week_review_ids
            if not review_lines:
                report.total_review_planned_hours = 0
                report.total_review_actual_hours = 0
                report.completion_rate = 0
                report.planned_completion_rate = 0
                report.inserted_count = 0
                continue

            # 單次迭代計算所有統計值（優化 N+1 查詢）
            total_count = len(review_lines)
            total_planned_hours = 0
            total_actual_hours = 0
            completed_count = 0
            planned_count = 0
            planned_completed = 0
            inserted_count = 0

            for line in review_lines:
                total_planned_hours += line.planned_hours or 0
                total_actual_hours += line.actual_hours or 0

                if line.status == 'completed':
                    completed_count += 1
                if line.source == 'planned':
                    planned_count += 1
                    if line.status == 'completed':
                        planned_completed += 1
                elif line.source == 'inserted':
                    inserted_count += 1

            report.total_review_planned_hours = total_planned_hours
            report.total_review_actual_hours = total_actual_hours
            report.completion_rate = (
                completed_count / total_count * 100
            ) if total_count else 0
            report.planned_completion_rate = (
                planned_completed / planned_count * 100
            ) if planned_count else 0
            report.inserted_count = inserted_count

    # ========== Default Methods ==========

    @api.model
    def default_get(self, fields_list):
        """設定預設週起始日為本週一"""
        res = super().default_get(fields_list)
        today = fields.Date.today()
        week_start = today - timedelta(days=today.weekday())
        res['week_start'] = week_start
        return res

    # ========== Business Methods ==========

    def _get_previous_report(self):
        """取得前一週已確認的報告"""
        self.ensure_one()
        if not self.week_start or not self.user_id:
            return False

        prev_week_start = self.week_start - timedelta(days=7)
        return self.search([
            ('user_id', '=', self.user_id.id),
            ('week_start', '=', prev_week_start),
            ('state', '=', 'confirmed'),
        ], limit=1)

    def _generate_previous_week_review(self):
        """產生上週執行回顧記錄

        比對上週報告的計畫快照與實際執行情況，
        產生回顧記錄，並檢查是否有待處理的待辦。

        Raises:
            UserError: 若上週有待處理的待辦未完成或延期
        """
        self.ensure_one()

        # 取得上週報告的快照
        prev_report = self._get_previous_report()
        planned_snapshot = (
            prev_report.this_week_snapshot_ids
            if prev_report
            else self.env['weekly.report.snapshot.line']
        )
        planned_activity_ids = set(
            line.activity_id.id for line in planned_snapshot if line.activity_id
        )
        snapshot_map = {
            line.activity_id.id: line
            for line in planned_snapshot
            if line.activity_id
        }

        # 取得上週實際執行的待辦
        prev_week_start = self.week_start - timedelta(days=7)
        prev_week_end = self.week_start - timedelta(days=1)

        actual_activities = self.env['mail.activity'].with_context(
            active_test=False
        ).search([
            ('user_id', '=', self.user_id.id),
            ('planned_date', '>=', prev_week_start),
            ('planned_date', '<=', prev_week_end),
        ])

        # 清除舊的回顧記錄（使用 Command API）
        self.write({
            'previous_week_review_ids': [Command.clear()],
        })

        review_lines = []
        pending_activities = []

        # 處理實際執行的待辦
        for activity in actual_activities:
            is_planned = activity.id in planned_activity_ids
            snapshot_line = snapshot_map.get(activity.id)

            # 判斷狀態
            if activity.active and not activity.done_date:
                status = 'pending'
                pending_activities.append(activity)
            elif activity.done_date:
                status = 'completed'
            elif activity.cancel_date:
                status = 'cancelled'
            else:
                status = 'postponed'

            review_lines.append({
                'report_id': self.id,
                'activity_id': activity.id,
                'snapshot_line_id': snapshot_line.id if snapshot_line else False,
                'source': 'planned' if is_planned else 'inserted',
                'status': status,
                'summary': activity.summary,
                'planned_hours': snapshot_line.estimated_hours if snapshot_line else 0,
                'actual_hours': activity.actual_hours or 0,
                'planned_date': activity.planned_date,
                'done_date': activity.done_date,
            })

        # 檢查計畫中但未執行的待辦（不在實際執行列表中）
        executed_ids = set(a.id for a in actual_activities)
        for snapshot_line in planned_snapshot:
            if not snapshot_line.activity_id:
                continue
            if snapshot_line.activity_id.id in executed_ids:
                continue

            activity = snapshot_line.activity_id
            if activity.exists():
                if activity.active and not activity.done_date:
                    status = 'pending'
                    pending_activities.append(activity)
                elif not activity.active:
                    status = 'postponed'
                else:
                    status = 'pending'
                    pending_activities.append(activity)
            else:
                status = 'cancelled'

            review_lines.append({
                'report_id': self.id,
                'activity_id': activity.id if activity.exists() else False,
                'snapshot_line_id': snapshot_line.id,
                'source': 'planned',
                'status': status,
                'summary': snapshot_line.summary,
                'planned_hours': snapshot_line.estimated_hours,
                'actual_hours': 0,
                'planned_date': snapshot_line.planned_date,
                'done_date': False,
            })

        # 檢查是否有待處理待辦
        if pending_activities:
            activity_names = ', '.join(
                a.summary or _('(無摘要)') for a in pending_activities[:5]
            )
            if len(pending_activities) > 5:
                activity_names += _(' 等 %d 項') % len(pending_activities)

            raise UserError(_(
                '上週有 %d 個待辦未處理，請先完成或延期後再建立報告：\n%s'
            ) % (len(pending_activities), activity_names))

        # 建立回顧記錄
        if review_lines:
            self.env['weekly.report.review.line'].create(review_lines)

    def _generate_this_week_snapshot(self):
        """產生本週計畫快照

        凍結本週計畫待辦的當前狀態，供下週回顧比對使用。
        同時標記待辦的 schedule_origin 為 'planned'。
        """
        self.ensure_one()

        # 載入本週計畫
        this_week_activities = self.env['mail.activity'].search([
            ('user_id', '=', self.user_id.id),
            ('planned_date', '>=', self.week_start),
            ('planned_date', '<=', self.week_end),
            ('active', '=', True),
        ])

        # 使用 Command API 設定 Many2many
        self.write({
            'this_week_activity_ids': [Command.set(this_week_activities.ids)],
        })

        # 清除舊快照並建立新快照
        self.write({
            'this_week_snapshot_ids': [Command.clear()],
        })

        snapshot_lines = []
        for activity in this_week_activities:
            snapshot_lines.append({
                'report_id': self.id,
                'activity_id': activity.id,
                'user_id': activity.user_id.id,
                'summary': activity.summary,
                'estimated_hours': activity.estimated_hours,
                'planned_date': activity.planned_date,
                'date_deadline': activity.date_deadline,
                'urgency': activity.urgency,
                'importance': activity.importance,
            })

            # 標記為計畫工作（若尚未標記）
            if not activity.schedule_origin:
                activity.write({'schedule_origin': 'planned'})

        if snapshot_lines:
            self.env['weekly.report.snapshot.line'].create(snapshot_lines)

    def _generate_future_activities(self):
        """載入未來安排的待辦（本週之後）"""
        self.ensure_one()

        future_start = self.week_end + timedelta(days=1)
        future_activities = self.env['mail.activity'].search([
            ('user_id', '=', self.user_id.id),
            '|',
            ('planned_date', '>=', future_start),
            ('scheduled_date', '>=', future_start),
            ('active', '=', True),
        ])

        self.write({
            'future_activity_ids': [Command.set(future_activities.ids)],
        })

    def _generate_unscheduled_activities(self):
        """載入尚未安排的待辦（等待排程）"""
        self.ensure_one()

        unscheduled = self.env['mail.activity'].search([
            ('user_id', '=', self.user_id.id),
            ('schedule_status', '=', 'waiting'),
            ('active', '=', True),
        ])

        self.write({
            'unscheduled_activity_ids': [Command.set(unscheduled.ids)],
        })

    def action_generate_report(self):
        """產生報告內容（主方法）

        執行順序：
        1. 產生上週執行回顧
        2. 建立本週計畫快照
        3. 載入未來安排
        4. 載入尚未安排
        """
        self.ensure_one()

        if self.state == 'confirmed':
            raise UserError(_('已確認的報告無法重新產生，請先重設為草稿。'))

        # Step 1: 產生上週執行回顧
        self._generate_previous_week_review()

        # Step 2: 建立本週計畫快照
        self._generate_this_week_snapshot()

        # Step 3: 載入未來安排
        self._generate_future_activities()

        # Step 4: 載入尚未安排
        self._generate_unscheduled_activities()

        return True

    def action_confirm(self):
        """確認報告"""
        for report in self:
            if not report.this_week_snapshot_ids:
                raise UserError(_('請先產生報告內容（至少需要本週計畫快照）'))
            if report.state == 'confirmed':
                raise UserError(_('報告已經確認，無法重複確認。'))

        self.write({'state': 'confirmed'})
        return True

    def action_reset_draft(self):
        """重設為草稿"""
        self.write({'state': 'draft'})
        return True


class WeeklyReportSnapshotLine(models.Model):
    """本週計畫快照 - 凍結當時狀態供下週比對

    當週報告確認時，會將本週計畫的待辦資訊凍結到此模型，
    供下週產生報告時作為比對基準。
    """
    _name = 'weekly.report.snapshot.line'
    _description = '週報告計畫快照'
    _order = 'planned_date, id'

    report_id = fields.Many2one(
        'weekly.report',
        string='週報告',
        required=True,
        ondelete='cascade',
        index=True,
    )

    activity_id = fields.Many2one(
        'mail.activity',
        string='待辦',
        ondelete='set null',
        index=True,
    )

    user_id = fields.Many2one(
        'res.users',
        string='負責人',
    )

    # 快照欄位（凍結當時值）
    summary = fields.Char(
        string='摘要',
    )
    estimated_hours = fields.Float(
        string='預估工時',
    )
    planned_date = fields.Date(
        string='計畫日期',
    )
    date_deadline = fields.Date(
        string='截止日',
    )
    urgency = fields.Selection([
        ('urgent', '緊急'),
        ('standard', '標準'),
        ('flexible', '彈性'),
    ], string='時間性')
    importance = fields.Selection([
        ('important', '重要'),
        ('normal', '一般'),
    ], string='重要性')


class WeeklyReportReviewLine(models.Model):
    """上週執行回顧 - 比對結果

    記錄上週計畫與實際執行的比對結果，
    包含完成狀態、工時差異等資訊。
    """
    _name = 'weekly.report.review.line'
    _description = '週報告執行回顧'
    _order = 'source, planned_date, id'

    report_id = fields.Many2one(
        'weekly.report',
        string='週報告',
        required=True,
        ondelete='cascade',
        index=True,
    )

    activity_id = fields.Many2one(
        'mail.activity',
        string='待辦',
        ondelete='set null',
        index=True,
    )

    snapshot_line_id = fields.Many2one(
        'weekly.report.snapshot.line',
        string='原計畫快照',
        ondelete='set null',
    )

    # 比對資訊
    source = fields.Selection([
        ('planned', '計畫內'),
        ('inserted', '臨時插入'),
    ], string='來源')

    status = fields.Selection([
        ('completed', '已完成'),
        ('postponed', '已延期'),
        ('cancelled', '已取消'),
        ('pending', '待處理'),
    ], string='狀態')

    # 內容欄位
    summary = fields.Char(
        string='摘要',
    )
    planned_hours = fields.Float(
        string='計畫工時',
    )
    actual_hours = fields.Float(
        string='實際工時',
    )
    planned_date = fields.Date(
        string='計畫日期',
    )
    done_date = fields.Datetime(
        string='完成時間',
    )

    # 工時差異
    hours_diff = fields.Float(
        string='工時差異',
        compute='_compute_hours_diff',
        store=True,
        help='實際工時 - 計畫工時',
    )

    @api.depends('planned_hours', 'actual_hours')
    def _compute_hours_diff(self):
        for line in self:
            line.hours_diff = (line.actual_hours or 0) - (line.planned_hours or 0)
