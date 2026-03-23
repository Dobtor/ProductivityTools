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
    _description = 'Weekly Schedule Configuration'
    _order = 'user_id'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )

    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        default=lambda self: self.env.user,
        index=True,
        ondelete='cascade',
    )

    active = fields.Boolean(
        string='Active',
        default=True,
        help='When enabled, weekly schedule activities will be created automatically',
    )

    activity_type_id = fields.Many2one(
        'mail.activity.type',
        string='Activity Type',
        required=True,
        default=lambda self: self._default_activity_type(),
        ondelete='restrict',
    )

    schedule_day = fields.Selection([
        ('0', 'Monday'),
        ('1', 'Tuesday'),
        ('2', 'Wednesday'),
        ('3', 'Thursday'),
        ('4', 'Friday'),
        ('5', 'Saturday'),
        ('6', 'Sunday'),
    ], string='Schedule Day', default='0', required=True,
       help='Automatically create activities on this day each week')

    schedule_time = fields.Selection([
        ('morning', 'Morning (08:00)'),
        ('noon', 'Noon (12:00)'),
        ('evening', 'Evening (18:00)'),
    ], string='Schedule Time', default='morning')

    deadline_offset = fields.Integer(
        string='Deadline Offset (Days)',
        default=0,
        help='Deadline = Schedule Day + Offset Days. 0 means due on the same day.',
    )

    target_model = fields.Selection([
        ('note.note', 'Note'),
        ('res.users', 'User'),
        ('weekly.report', 'Weekly Report'),
    ], string='Target Document Type', default='res.users', required=True,
       help='Activity will be linked to this type of document')

    note_id = fields.Many2one(
        'note.note',
        string='Specified Note',
        domain="[('user_id', '=', user_id)]",
        help='When target document type is "Note", specify the note to link',
    )

    auto_create_note = fields.Boolean(
        string='Auto Create Note',
        default=False,
        help='When target document type is "Note" and no note is specified, automatically create a new note',
    )

    summary_template = fields.Char(
        string='Summary Template',
        default='Weekly Schedule - {week}',
        help='Available variables: {week}=Week number, {user}=User name, {date}=Date',
    )

    include_note = fields.Boolean(
        string='Include Default Note',
        default=True,
        help='Include activity type default note when creating activity',
    )

    last_created_date = fields.Date(
        string='Last Created Date',
        readonly=True,
    )

    last_activity_id = fields.Many2one(
        'mail.activity',
        string='Last Created Activity',
        readonly=True,
        ondelete='set null',
    )

    _sql_constraints = [
        ('user_unique', 'unique(user_id)', 'Each user can only have one weekly schedule configuration!')
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
                record.name = _('%(user)s Weekly Schedule', user=record.user_id.name)
            else:
                record.name = _('Weekly Schedule')

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
                'name': _('Created Activity'),
                'res_model': 'mail.activity',
                'res_id': activity.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            raise UserError(_('Failed to create activity. Please check the configuration.'))

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
                iso_year, iso_week, _ = today.isocalendar()
                week_str = '%d-W%02d' % (iso_year, iso_week)
                note = self.env['note.note'].create({
                    'user_id': self.user_id.id,
                    'memo': _('<p>Weekly Schedule - %(week)s</p><p>This week work plan</p>', week=week_str),
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
        iso_year, iso_week, _ = today.isocalendar()
        week_str = '%d-W%02d' % (iso_year, iso_week)

        summary = self.summary_template or _('Weekly Schedule')
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

        批次建立所有待辦以減少資料庫交互。
        """
        today = fields.Date.today()
        today_weekday = str(today.weekday())

        # 找出今天需要建立待辦的配置
        configs = self.search([
            ('active', '=', True),
            ('schedule_day', '=', today_weekday),
        ])

        # 第一階段：過濾 + 準備 vals（_get_target_record 可能有副作用）
        vals_list = []
        config_list = []
        for config in configs:
            if config.last_created_date == today:
                _logger.debug(
                    'Weekly schedule for user %s already created today.',
                    config.user_id.name
                )
                continue

            if config.last_activity_id and config.last_activity_id.active:
                _logger.info(
                    'Skipping weekly schedule for user %s: previous activity still active.',
                    config.user_id.name
                )
                continue

            if not config.activity_type_id:
                _logger.warning(
                    'Weekly schedule config %s has no activity type.', config.id
                )
                continue

            target_model, target_id = config._get_target_record()
            if not target_model or not target_id:
                _logger.warning(
                    'Weekly schedule config %s has no valid target.', config.id
                )
                continue

            target_model_rec = self.env['ir.model']._get(target_model)
            deadline = today + timedelta(days=config.deadline_offset)

            activity_vals = {
                'activity_type_id': config.activity_type_id.id,
                'summary': config._get_summary(),
                'date_deadline': deadline,
                'user_id': config.user_id.id,
                'res_model_id': target_model_rec.id,
                'res_id': target_id,
            }
            if config.include_note and config.activity_type_id.default_description:
                activity_vals['note'] = config.activity_type_id.default_description

            vals_list.append(activity_vals)
            config_list.append(config)

        if not vals_list:
            _logger.info('Weekly schedule cron completed. No activities to create.')
            return True

        # 第二階段：批次建立待辦
        try:
            activities = self.env['mail.activity'].sudo().create(vals_list)
        except Exception as e:
            _logger.error('Failed to batch create weekly schedule activities: %s', str(e))
            return True

        # 第三階段：批次更新配置記錄
        for config, activity in zip(config_list, activities):
            config.write({
                'last_created_date': today,
                'last_activity_id': activity.id,
            })

        _logger.info(
            'Weekly schedule cron completed. Created %d activities.',
            len(activities)
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
            'name': _('My Weekly Schedule'),
            'res_model': 'weekly.schedule.config',
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'current',
        }
