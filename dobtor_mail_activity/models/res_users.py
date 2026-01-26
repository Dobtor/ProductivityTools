# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ResUsers(models.Model):
    """用戶擴展

    新增週約定工作時數欄位，用於：
    - 週報告工時統計基準
    - 效率指標計算參考
    - 工時超時警示

    新增預設待辦筆記，用於：
    - 建立待辦時若未選擇目標文件，自動關聯到此筆記
    - 支援「獨立待辦」的使用情境
    """
    _inherit = 'res.users'

    # 允許用戶修改/讀取自己的這些欄位（無需管理員權限）
    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + [
            'default_activity_note_id',
            'weekly_committed_hours',
        ]

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + [
            'default_activity_note_id',
            'weekly_committed_hours',
            'weekly_report_count',
            'latest_efficiency_index',
        ]

    weekly_committed_hours = fields.Float(
        string='Committed Hours',
        default=40.0,
        help='Weekly committed working hours, used for weekly report and efficiency metrics calculation',
    )

    # ===== 預設待辦筆記 =====
    default_activity_note_id = fields.Many2one(
        'note.note',
        string='Default Activity Note',
        help='When creating activity without selecting a target document, it will be automatically linked to this note.',
    )

    # ===== 週報告相關欄位 =====
    weekly_report_ids = fields.One2many(
        'weekly.report',
        'user_id',
        string='Weekly Reports',
    )

    weekly_report_count = fields.Integer(
        string='Weekly Report Count',
        compute='_compute_weekly_report_count',
    )

    # ===== 效率指標相關欄位 =====
    efficiency_metrics_ids = fields.One2many(
        'activity.efficiency.metrics',
        'user_id',
        string='Efficiency Metrics',
    )

    latest_efficiency_index = fields.Float(
        string='Latest Efficiency Index',
        compute='_compute_latest_efficiency',
        help='Efficiency index of the most recent week (max 5 points)',
    )

    # ===== 週報排程配置 =====
    weekly_schedule_config_id = fields.One2many(
        'weekly.schedule.config',
        'user_id',
        string='Weekly Schedule Configuration',
    )

    # ========== CRUD Methods ==========

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to auto-create default note stages for new users"""
        users = super().create(vals_list)
        users._create_default_note_stages()
        return users

    def _create_default_note_stages(self):
        """Create default note stages for users

        Creates 4 default stages for each user:
        - Notes (筆記)
        - Meeting Minutes (會議記錄)
        - Manuals (說明書)
        - References (參考資料)
        """
        NoteStage = self.env['note.stage'].sudo()

        default_stages = [
            {'name': 'Notes', 'sequence': 1, 'fold': False},
            {'name': 'Meeting Minutes', 'sequence': 5, 'fold': False},
            {'name': 'Manuals', 'sequence': 10, 'fold': False},
            {'name': 'References', 'sequence': 50, 'fold': True},
        ]

        for user in self:
            # Check if user already has stages
            existing_stages = NoteStage.search_count([('user_id', '=', user.id)])
            if existing_stages > 0:
                continue

            # Create default stages for user
            for stage_vals in default_stages:
                NoteStage.create({
                    **stage_vals,
                    'user_id': user.id,
                })

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
            'name': _('%s Weekly Reports') % self.name,
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
            'name': _('%s Efficiency Metrics') % self.name,
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
            'name': _('%s Weekly Schedule') % self.name,
            'res_model': 'weekly.schedule.config',
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ========== 預設待辦筆記方法 ==========

    def _get_or_create_default_activity_note(self):
        """取得或建立用戶的預設待辦筆記

        若用戶已設定預設筆記且該筆記存在，則返回該筆記。
        否則自動建立一個新的預設筆記並設定給用戶。

        Returns:
            note.note: 用戶的預設待辦筆記
        """
        self.ensure_one()

        # 檢查是否已有預設筆記且存在
        if self.default_activity_note_id and self.default_activity_note_id.exists():
            return self.default_activity_note_id

        # 建立新的預設筆記
        note = self.env['note.note'].sudo().create({
            'memo': _('<p><strong>%s Activity Inbox</strong></p>'
                      '<p>This is your default activity note. Activities without a specified target document will be automatically linked here.</p>') % self.name,
            'user_id': self.id,
        })

        # 設定為用戶的預設筆記
        self.sudo().write({'default_activity_note_id': note.id})

        return note

    @api.model
    def get_current_user_default_note(self):
        """取得當前用戶的預設待辦筆記（API 方法）

        Returns:
            note.note: 當前用戶的預設待辦筆記
        """
        return self.env.user._get_or_create_default_activity_note()
