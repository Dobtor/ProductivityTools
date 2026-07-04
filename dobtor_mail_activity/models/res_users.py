# -*- coding: utf-8 -*-

from odoo import api, fields, models, modules, _


class ResUsers(models.Model):
    """用戶擴展

    新增週約定工作時數欄位，用於：
    - 週報告工時統計基準
    - 效率指標計算參考
    - 工時超時警示

    （需求七：已移除「預設待辦筆記」設計 —— 待辦可無關聯文件的獨立存在。）
    """
    _inherit = 'res.users'

    # 允許用戶修改/讀取自己的這些欄位（無需管理員權限）
    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + [
            'weekly_committed_hours',
        ]

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + [
            'weekly_committed_hours',
            'weekly_report_count',
            'latest_efficiency_index',
        ]

    weekly_committed_hours = fields.Float(
        string='Committed Hours',
        default=40.0,
        help='Weekly committed working hours, used for weekly report and efficiency metrics calculation',
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

        # 批次查詢已有 stage 的用戶
        existing_data = NoteStage._read_group(
            [('user_id', 'in', self.ids)],
            ['user_id'],
            ['__count'],
        )
        users_with_stages = {user.id for user, _count in existing_data}

        # 批次建立所有缺少 stage 的用戶的預設 stages
        vals_list = []
        for user in self:
            if user.id in users_with_stages:
                continue
            for stage_vals in default_stages:
                vals_list.append({
                    **stage_vals,
                    'user_id': user.id,
                })

        if vals_list:
            NoteStage.create(vals_list)

    # ========== Computed Methods ==========

    @api.depends('weekly_report_ids')
    def _compute_weekly_report_count(self):
        if not self.ids:
            for user in self:
                user.weekly_report_count = 0
            return
        report_data = self.env['weekly.report']._read_group(
            [('user_id', 'in', self.ids)],
            ['user_id'],
            ['__count'],
        )
        count_map = {user.id: count for user, count in report_data}
        for user in self:
            user.weekly_report_count = count_map.get(user.id, 0)

    @api.depends('efficiency_metrics_ids', 'efficiency_metrics_ids.efficiency_index')
    def _compute_latest_efficiency(self):
        if not self.ids:
            for user in self:
                user.latest_efficiency_index = 0
            return
        # 批次查詢：每用戶最新一筆 week 類型記錄
        # 先取得每用戶最大 period_end，再查對應的 efficiency_index
        Metrics = self.env['activity.efficiency.metrics']
        latest_records = Metrics.search([
            ('user_id', 'in', self.ids),
            ('period_type', '=', 'week'),
        ], order='period_end desc')
        # 取每用戶第一筆（最新）
        user_metric_map = {}
        for rec in latest_records:
            if rec.user_id.id not in user_metric_map:
                user_metric_map[rec.user_id.id] = rec.efficiency_index
        for user in self:
            user.latest_efficiency_index = user_metric_map.get(user.id, 0)

    # ========== Action Methods ==========

    def action_view_weekly_reports(self):
        """查看用戶的週報告"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('%(user)s Weekly Reports', user=self.name),
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
            'name': _('%(user)s Efficiency Metrics', user=self.name),
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
            'name': _('%(user)s Weekly Schedule', user=self.name),
            'res_model': 'weekly.schedule.config',
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # 需求七：已移除 _get_or_create_default_activity_note /
    # get_current_user_default_note（不再有預設待辦筆記）。

    # ========== 系統匣待辦分組（需求七相容）==========

    @api.model
    def _get_activity_groups(self):
        """容許「獨立待辦」（需求七：res_model 為空）於系統匣分組。

        核心 mail/models/res_users.py 對每筆待辦執行
        ``self.env[activity.res_model].browse(...)``，遇到 res_model 為空的獨立待辦
        時 ``self.env[False]`` → ``KeyError: False``。

        為保留 calendar（今日會議）/contacts（圖示）/project_todo（拆分待辦/任務）
        對結果的增修，本覆寫仍呼叫 super()，僅以 context 旗標讓核心鏈中對
        mail.activity 的搜尋排除獨立待辦（見 mail.activity._search 覆寫）；隨後再把
        獨立待辦併入核心既有的 'mail.activity'（「其他活動」）分組。
        """
        groups = super(
            ResUsers,
            self.with_context(activity_systray_skip_standalone=True),
        )._get_activity_groups()

        standalone = self.env["mail.activity"].search([
            ("user_id", "=", self.env.uid),
            ("res_model", "=", False),
        ])
        if standalone:
            self._inject_standalone_activity_group(groups, standalone)
        return groups

    def _inject_standalone_activity_group(self, groups, standalone):
        """把獨立待辦（res_model 空）併入系統匣「其他活動」(mail.activity) 分組。"""
        group = next(
            (g for g in groups if g.get('model') == 'mail.activity'), None)
        if group is None:
            Model = self.env['mail.activity']
            module = Model._original_module
            model = self.env['ir.model']._get('mail.activity')
            group = {
                'id': model.id,
                'name': _("Other activities"),
                'model': 'mail.activity',
                'type': 'activity',
                'icon': module and modules.module.get_module_icon(module),
                'total_count': 0,
                'today_count': 0,
                'overdue_count': 0,
                'planned_count': 0,
                'view_type': getattr(Model, '_systray_view', 'list'),
                'activity_ids': [],
            }
            groups.append(group)
        group.setdefault('activity_ids', [])
        for activity in standalone:
            group['activity_ids'].append(activity.id)
            group["%s_count" % activity.state] += 1
            if activity.state in ('today', 'overdue'):
                group['total_count'] += 1
