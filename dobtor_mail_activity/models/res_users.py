# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ResUsers(models.Model):
    """用戶擴展

    新增週約定工作時數欄位，用於：
    - 週報告工時統計基準
    - 效率指標計算參考
    - 工時超時警示
    """
    _inherit = 'res.users'

    weekly_committed_hours = fields.Float(
        string='約定時數',
        default=40.0,
        help='每週約定工作時數，用於週報告和效率指標計算',
    )

    # ===== 週報告相關欄位 =====
    weekly_report_ids = fields.One2many(
        'weekly.report',
        'user_id',
        string='週報告',
    )

    weekly_report_count = fields.Integer(
        string='週報告數',
        compute='_compute_weekly_report_count',
    )

    # ===== 效率指標相關欄位 =====
    efficiency_metrics_ids = fields.One2many(
        'activity.efficiency.metrics',
        'user_id',
        string='效率指標',
    )

    latest_efficiency_index = fields.Float(
        string='最新效率指數',
        compute='_compute_latest_efficiency',
        help='最近一週的效率指數（滿分 5 分）',
    )

    # ===== 週報排程配置 =====
    weekly_schedule_config_id = fields.One2many(
        'weekly.schedule.config',
        'user_id',
        string='週報排程配置',
    )

    # ========== Computed Methods ==========

    @api.depends('weekly_report_ids')
    def _compute_weekly_report_count(self):
        for user in self:
            user.weekly_report_count = len(user.weekly_report_ids)

    @api.depends('efficiency_metrics_ids', 'efficiency_metrics_ids.efficiency_index')
    def _compute_latest_efficiency(self):
        for user in self:
            latest_metric = self.env['activity.efficiency.metrics'].search([
                ('user_id', '=', user.id),
                ('period_type', '=', 'week'),
            ], order='period_end desc', limit=1)
            user.latest_efficiency_index = (
                latest_metric.efficiency_index if latest_metric else 0
            )

    # ========== Action Methods ==========

    def action_view_weekly_reports(self):
        """查看用戶的週報告"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s 的週報告') % self.name,
            'res_model': 'weekly.report',
            'view_mode': 'list,form',
            'domain': [('user_id', '=', self.id)],
            'context': {'default_user_id': self.id},
        }

    def action_view_efficiency_metrics(self):
        """查看用戶的效率指標"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s 的效率指標') % self.name,
            'res_model': 'activity.efficiency.metrics',
            'view_mode': 'list,form',
            'domain': [('user_id', '=', self.id)],
            'context': {'default_user_id': self.id},
        }

    def action_open_weekly_schedule_config(self):
        """開啟週報排程配置"""
        self.ensure_one()
        config = self.env['weekly.schedule.config'].search([
            ('user_id', '=', self.id)
        ], limit=1)

        if not config:
            config = self.env['weekly.schedule.config'].create({
                'user_id': self.id,
            })

        return {
            'type': 'ir.actions.act_window',
            'name': _('%s 的週報排程') % self.name,
            'res_model': 'weekly.schedule.config',
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'current',
        }
