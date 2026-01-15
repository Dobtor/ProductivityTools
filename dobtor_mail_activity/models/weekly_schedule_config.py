# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WeeklyScheduleConfig(models.Model):
    """週報排程配置

    用於配置自動建立週報排程待辦，支援：
    - 指定建立日期和時段
    - 關聯到筆記本、用戶或週報告
    - 自動建立筆記本
    - 摘要模板支援變數替換
    """
    _name = 'weekly.schedule.config'
    _description = '週報排程配置'
    _order = 'user_id'

    name = fields.Char(
        string='名稱',
        compute='_compute_name',
        store=True,
    )

    user_id = fields.Many2one(
        'res.users',
        string='用戶',
        required=True,
        default=lambda self: self.env.user,
        index=True,
        ondelete='cascade',
    )

    active = fields.Boolean(
        string='啟用',
        default=True,
        help='啟用後將自動建立週報排程待辦',
    )

    activity_type_id = fields.Many2one(
        'mail.activity.type',
        string='待辦類型',
        required=True,
        default=lambda self: self._default_activity_type(),
        ondelete='restrict',
    )

    schedule_day = fields.Selection([
        ('0', '週一'),
        ('1', '週二'),
        ('2', '週三'),
        ('3', '週四'),
        ('4', '週五'),
        ('5', '週六'),
        ('6', '週日'),
    ], string='建立日期', default='0', required=True,
       help='每週在此日期自動建立待辦')

    schedule_time = fields.Selection([
        ('morning', '上午 (08:00)'),
        ('noon', '中午 (12:00)'),
        ('evening', '晚上 (18:00)'),
    ], string='建立時段', default='morning')

    deadline_offset = fields.Integer(
        string='截止日偏移（天）',
        default=0,
        help='截止日期 = 建立日期 + 偏移天數。0 表示當天截止。',
    )

    target_model = fields.Selection([
        ('note.note', '筆記本'),
        ('res.users', '用戶'),
        ('weekly.report', '週報告'),
    ], string='關聯文件類型', default='res.users', required=True,
       help='待辦將關聯到此類型的文件')

    note_id = fields.Many2one(
        'note.note',
        string='指定筆記本',
        domain="[('user_id', '=', user_id)]",
        help='當關聯文件類型為「筆記本」時，指定關聯的筆記本',
    )

    auto_create_note = fields.Boolean(
        string='自動建立筆記本',
        default=False,
        help='當關聯文件類型為「筆記本」且未指定筆記本時，自動建立新筆記本',
    )

    summary_template = fields.Char(
        string='摘要模板',
        default='週報排程 - {week}',
        help='可用變數：{week}=週次, {user}=用戶名稱, {date}=日期',
    )

    include_note = fields.Boolean(
        string='包含預設說明',
        default=True,
        help='建立待辦時包含待辦類型的預設說明',
    )

    last_created_date = fields.Date(
        string='上次建立日期',
        readonly=True,
    )

    last_activity_id = fields.Many2one(
        'mail.activity',
        string='上次建立的待辦',
        readonly=True,
        ondelete='set null',
    )

    _sql_constraints = [
        ('user_unique', 'unique(user_id)', '每個用戶只能有一個週報排程配置！')
    ]

    # ========== Default Methods ==========

    @api.model
    def _default_activity_type(self):
        """取得預設待辦類型"""
        return self.env.ref(
            'dobtor_mail_activity.mail_activity_type_weekly_report_schedule',
            raise_if_not_found=False
        )

    # ========== Computed Methods ==========

    @api.depends('user_id')
    def _compute_name(self):
        for record in self:
            if record.user_id:
                record.name = _('%s 的週報排程') % record.user_id.name
            else:
                record.name = _('週報排程')

    # ========== Onchange Methods ==========

    @api.onchange('target_model')
    def _onchange_target_model(self):
        """當關聯文件類型變更時，清除筆記本選擇"""
        if self.target_model != 'note.note':
            self.note_id = False
            self.auto_create_note = False

    # ========== Business Methods ==========

    def action_create_activity_now(self):
        """手動立即建立待辦"""
        self.ensure_one()
        activity = self._create_weekly_activity()
        if activity:
            return {
                'type': 'ir.actions.act_window',
                'name': _('已建立的待辦'),
                'res_model': 'mail.activity',
                'res_id': activity.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            raise UserError(_('建立待辦失敗，請檢查配置。'))

    def _get_target_record(self):
        """取得目標文件記錄

        Returns:
            tuple: (model_name, record_id) 或 (False, False)
        """
        self.ensure_one()

        if self.target_model == 'res.users':
            return ('res.users', self.user_id.id)

        elif self.target_model == 'note.note':
            if self.note_id:
                return ('note.note', self.note_id.id)
            elif self.auto_create_note:
                # 自動建立筆記本
                today = fields.Date.today()
                week_str = today.strftime('%Y-W%W')
                note = self.env['note.note'].create({
                    'user_id': self.user_id.id,
                    'memo': _('<p>週報排程 - %s</p><p>本週工作計畫</p>') % week_str,
                })
                return ('note.note', note.id)
            else:
                # 沒有指定筆記本，使用用戶
                _logger.warning(
                    'Weekly schedule config %s: no note specified, falling back to user.',
                    self.id
                )
                return ('res.users', self.user_id.id)

        elif self.target_model == 'weekly.report':
            # 找到或建立本週的週報告
            today = fields.Date.today()
            week_start = today - timedelta(days=today.weekday())
            report = self.env['weekly.report'].search([
                ('user_id', '=', self.user_id.id),
                ('week_start', '=', week_start),
            ], limit=1)
            if not report:
                report = self.env['weekly.report'].create({
                    'user_id': self.user_id.id,
                    'week_start': week_start,
                })
            return ('weekly.report', report.id)

        return (False, False)

    def _get_summary(self):
        """取得待辦摘要（支援變數替換）"""
        self.ensure_one()
        today = fields.Date.today()
        week_str = today.strftime('%Y-W%W')

        summary = self.summary_template or _('週報排程')
        summary = summary.replace('{week}', week_str)
        summary = summary.replace('{user}', self.user_id.name or '')
        summary = summary.replace('{date}', today.strftime('%Y-%m-%d'))

        return summary

    def _create_weekly_activity(self):
        """建立週報排程待辦

        Returns:
            mail.activity: 建立的待辦記錄，或 False 表示失敗
        """
        self.ensure_one()

        if not self.active:
            _logger.info(
                'Weekly schedule config %s is inactive, skipping.',
                self.id
            )
            return False

        if not self.activity_type_id:
            _logger.warning(
                'Weekly schedule config %s has no activity type.',
                self.id
            )
            return False

        # 取得目標文件
        target_model, target_id = self._get_target_record()
        if not target_model or not target_id:
            _logger.warning(
                'Weekly schedule config %s has no valid target.',
                self.id
            )
            return False

        # 取得目標模型的 ir.model
        target_model_rec = self.env['ir.model']._get(target_model)

        # 計算截止日期
        today = fields.Date.today()
        deadline = today + timedelta(days=self.deadline_offset)

        # 準備待辦值
        activity_vals = {
            'activity_type_id': self.activity_type_id.id,
            'summary': self._get_summary(),
            'date_deadline': deadline,
            'user_id': self.user_id.id,
            'res_model_id': target_model_rec.id,
            'res_id': target_id,
        }

        # 包含預設說明
        if self.include_note and self.activity_type_id.default_description:
            activity_vals['note'] = self.activity_type_id.default_description

        # 建立待辦（使用 sudo 確保有權限建立）
        try:
            activity = self.env['mail.activity'].sudo().create(activity_vals)
        except Exception as e:
            _logger.error(
                'Failed to create weekly schedule activity for config %s: %s',
                self.id, str(e)
            )
            return False

        # 更新配置記錄
        self.write({
            'last_created_date': today,
            'last_activity_id': activity.id,
        })

        _logger.info(
            'Created weekly schedule activity %s for user %s',
            activity.id, self.user_id.name
        )

        return activity

    # ========== Cron Methods ==========

    @api.model
    def _cron_create_weekly_activities(self):
        """定時任務：建立週報排程待辦

        在配置指定的星期幾自動建立待辦。
        會檢查：
        - 配置是否啟用
        - 今天是否已建立過
        - 上次建立的待辦是否仍在進行中
        """
        today = fields.Date.today()
        today_weekday = str(today.weekday())

        # 找出今天需要建立待辦的配置
        configs = self.search([
            ('active', '=', True),
            ('schedule_day', '=', today_weekday),
        ])

        created_count = 0
        for config in configs:
            # 檢查今天是否已經建立過
            if config.last_created_date == today:
                _logger.debug(
                    'Weekly schedule for user %s already created today.',
                    config.user_id.name
                )
                continue

            # 檢查上次建立的待辦是否還在進行中
            if config.last_activity_id and config.last_activity_id.active:
                _logger.info(
                    'Skipping weekly schedule for user %s: previous activity still active.',
                    config.user_id.name
                )
                continue

            try:
                activity = config._create_weekly_activity()
                if activity:
                    created_count += 1
            except Exception as e:
                _logger.error(
                    'Failed to create weekly schedule activity for user %s: %s',
                    config.user_id.name, str(e)
                )

        _logger.info(
            'Weekly schedule cron completed. Created %d activities.',
            created_count
        )

        return True

    # ========== Action Methods ==========

    @api.model
    def action_open_my_config(self):
        """開啟當前用戶的配置（如果不存在則建立）"""
        config = self.search([('user_id', '=', self.env.uid)], limit=1)
        if not config:
            config = self.create({
                'user_id': self.env.uid,
            })

        return {
            'type': 'ir.actions.act_window',
            'name': _('我的週報排程'),
            'res_model': 'weekly.schedule.config',
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'current',
        }
