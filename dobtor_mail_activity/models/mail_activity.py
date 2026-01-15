# -*- coding: utf-8 -*-
import math
import re
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.tools import is_html_empty

_logger = logging.getLogger(__name__)


class MailActivity(models.Model):
    """待辦擴展 - 擴展官方 mail.activity 模型

    主要功能:
    - 封存機制：完成/取消待辦時封存而非刪除
    - 排程系統：支援週計畫與預排功能
    - 優先級管理：時間性與重要性標記
    - 工時追蹤：預估與實際工時記錄
    - 歷史追蹤：指派變更與延期記錄
    - 轉移功能：支援待辦在不同文件間轉移
    - 訊息來源：追蹤從訊息建立的待辦
    """
    _inherit = 'mail.activity'

    # ===== 覆寫 user_id 為非必填且無預設值 =====
    user_id = fields.Many2one(
        'res.users',
        string='指派給',
        index=True,
        tracking=True,
        required=False,  # 改為非必填
        default=False,   # 移除預設值（官方預設為當前用戶）
    )

    # ===== 封存相關 =====
    active = fields.Boolean(
        string='啟用',
        default=True,
    )
    done_date = fields.Datetime(
        string='完成時間',
        readonly=True,
    )
    cancel_date = fields.Datetime(
        string='取消時間',
        readonly=True,
    )

    # 注意：原始 state 是計算欄位，無法使用 selection_add
    # 改用 activity_state 來追蹤自定義狀態
    activity_state = fields.Selection([
        ('active', '進行中'),
        ('done', '已完成'),
        ('cancelled', '已取消'),
    ], string='待辦狀態', compute='_compute_activity_state', store=True)

    # ===== 關聯筆記 =====
    note_id = fields.Many2one(
        'note.note',
        string='關聯筆記',
        index=True,
        ondelete='set null',
        help='待辦關聯的筆記本',
    )

    # ===== res_name 儲存計算結果以提升效能 =====
    res_name = fields.Char(
        string='文件名稱',
        compute='_compute_res_name',
        compute_sudo=True,
        store=True,
        help='關聯文件的顯示名稱',
    )

    # ===== 目標文件選擇（用於建立待辦時選擇關聯文件）=====
    target_ref = fields.Reference(
        string='目標文件',
        selection='_selection_target_model',
        compute='_compute_target_ref',
        inverse='_inverse_target_ref',
    )

    # ===== 排程相關 =====
    schedule_status = fields.Selection([
        ('waiting', '等待排程'),
        ('monday', '週一'),
        ('tuesday', '週二'),
        ('wednesday', '週三'),
        ('thursday', '週四'),
        ('friday', '週五'),
        ('saturday', '週六'),
        ('sunday', '週日'),
    ], string='排程狀態', default='waiting', index=True,
       group_expand='_group_expand_schedule_status')

    planned_date = fields.Date(
        string='計畫日期',
        help='排入本週計畫的日期',
    )

    scheduled_date = fields.Date(
        string='預排日期',
        help='用於下週預排，週轉換時複製到計畫日期',
    )

    schedule_week = fields.Selection([
        ('week_prev', '上週'),
        ('week0', '本週'),
        ('week1', '下週'),
        ('week2', '第三週'),
        ('week3', '第四週'),
        ('future', '未來'),
    ], string='排程週次', compute='_compute_schedule_week', store=True)

    schedule_week_number = fields.Integer(
        string='週次編號',
        compute='_compute_schedule_week',
        store=True,
        help='0=本週, 1=下週, 2=第三週, 3=第四週, 4+=未來',
    )

    schedule_origin = fields.Selection([
        ('planned', '計畫工作'),      # 建立週報告時在本週計畫內
        ('inserted', '臨時插入'),     # 週間新增，不在週報告快照中
        ('postponed', '延期'),        # 從延期而來
        ('transferred', '轉移'),      # 從其他文件轉移
    ], string='來源')  # 建立時留空，排入週天時才標記

    original_schedule_week = fields.Char(
        string='原始預排週次',
        help='格式：2026-W02',
    )

    # ===== 轉移追蹤 =====
    transferred_from_model = fields.Char(
        string='轉移來源模型',
        readonly=True,
    )
    transferred_from_id = fields.Integer(
        string='轉移來源 ID',
        readonly=True,
    )
    transferred_from_name = fields.Char(
        string='轉移來源',
        compute='_compute_transferred_from_name',
    )
    is_transferred = fields.Boolean(
        string='已轉移',
        compute='_compute_is_transferred',
        store=True,
    )

    # ===== 訊息來源追蹤 =====
    source_message_id = fields.Many2one(
        'mail.message',
        string='來源訊息',
        index=True,
        readonly=True,
        help='建立此待辦的來源訊息',
    )
    source_message_preview = fields.Html(
        string='訊息預覽',
        compute='_compute_source_message_preview',
    )

    # ===== 優先級欄位 =====
    urgency = fields.Selection([
        ('urgent', '緊急'),
        ('standard', '標準'),
        ('flexible', '彈性'),
    ], string='時間性', default='standard')

    importance = fields.Selection([
        ('important', '重要'),
        ('normal', '一般'),
    ], string='重要性', default='normal')

    # ===== 指派歷史 =====
    assignment_history_ids = fields.One2many(
        'mail.activity.assignment.history',
        'activity_id',
        string='指派歷史',
    )

    # ===== 延期歷史 =====
    postpone_history_ids = fields.One2many(
        'mail.activity.postpone.history',
        'activity_id',
        string='延期歷史',
    )

    postpone_count = fields.Integer(
        string='延期次數',
        compute='_compute_postpone_count',
        store=True,
    )

    # ===== 工時相關 =====
    estimated_hours = fields.Float(
        string='預估工時',
        help='預估執行所需時間（小時）',
    )

    actual_hours = fields.Float(
        string='執行工時',
        help='實際執行時間（小時）',
    )

    timesheet_id = fields.Many2one(
        'account.analytic.line',
        string='工時表記錄',
        readonly=True,
    )

    feedback = fields.Text(
        string='完成回饋',
    )

    # ===== 關聯顯示（計算欄位）=====
    partner_id = fields.Many2one(
        'res.partner',
        string='客戶',
        compute='_compute_related_records',
        store=True,
    )

    project_id = fields.Many2one(
        'project.project',
        string='專案',
        compute='_compute_related_records',
        store=True,
    )

    crm_lead_id = fields.Many2one(
        'crm.lead',
        string='CRM 商機',
        compute='_compute_related_records',
        store=True,
    )

    # ===== 警告相關 =====
    schedule_warning = fields.Char(
        string='排程警告',
        compute='_compute_schedule_warning',
    )

    needs_schedule_by = fields.Selection([
        ('monday', '週一'),
        ('tuesday', '週二'),
        ('wednesday', '週三'),
        ('thursday', '週四'),
        ('friday', '週五'),
        ('saturday', '週六'),
        ('sunday', '週日'),
    ], string='需於週X前安排', compute='_compute_schedule_warning')

    # ========== Computed Methods ==========

    @api.depends('active', 'done_date', 'cancel_date')
    def _compute_activity_state(self):
        """計算待辦狀態"""
        for activity in self:
            if activity.cancel_date:
                activity.activity_state = 'cancelled'
            elif activity.done_date:
                activity.activity_state = 'done'
            else:
                activity.activity_state = 'active'

    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        """覆寫原始方法，確保即時取得來源單據名稱"""
        for activity in self:
            if activity.res_model and activity.res_id:
                try:
                    record = self.env[activity.res_model].browse(activity.res_id)
                    if record.exists():
                        activity.res_name = record.display_name
                    else:
                        activity.res_name = _('(記錄已刪除)')
                except Exception as e:
                    _logger.debug(
                        'Failed to compute res_name for activity %s: %s',
                        activity.id, str(e)
                    )
                    activity.res_name = False
            else:
                activity.res_name = False

    @api.model
    def _selection_target_model(self):
        """取得允許的目標模型選項（使用共用方法）"""
        return self.env['mail.activity.transfer.config'].get_target_model_selection()

    @api.depends('res_model', 'res_id')
    def _compute_target_ref(self):
        """計算 target_ref Reference 欄位"""
        for activity in self:
            if activity.res_model and activity.res_id:
                activity.target_ref = '%s,%s' % (activity.res_model, activity.res_id)
            else:
                activity.target_ref = False

    def _inverse_target_ref(self):
        """反向設定 res_model_id 和 res_id"""
        for activity in self:
            if activity.target_ref:
                model_name = activity.target_ref._name
                # res_model 是 related 欄位（readonly），只設定 res_model_id 和 res_id
                activity.res_model_id = self.env['ir.model']._get(model_name)
                activity.res_id = activity.target_ref.id
            else:
                activity.res_model_id = False
                activity.res_id = False

    @api.onchange('target_ref')
    def _onchange_target_ref(self):
        """當選擇目標文件時，立即更新 res_model_id 和 res_id"""
        if self.target_ref:
            try:
                target = self.target_ref
                target_id = getattr(target, 'id', False)
                if target_id:
                    model_name = target._name
                    self.res_model_id = self.env['ir.model']._get(model_name)
                    self.res_id = target_id
            except Exception as e:
                _logger.warning('Error in _onchange_target_ref: %s', str(e))
                self.res_model_id = False
                self.res_id = False
        else:
            self.res_model_id = False
            self.res_id = False

    @api.constrains('res_model_id', 'res_id')
    def _check_target_document(self):
        """確保待辦有關聯的目標文件"""
        for activity in self:
            if not activity.res_model_id or not activity.res_id:
                raise ValidationError(_('請選擇「目標文件」，待辦必須關聯到一個文件記錄。'))

    @api.model
    def _group_expand_schedule_status(self, statuses, domain, order):
        """確保所有排程狀態都顯示在 Kanban 視圖中"""
        return [
            'waiting', 'monday', 'tuesday', 'wednesday',
            'thursday', 'friday', 'saturday', 'sunday',
        ]

    @api.depends('planned_date', 'scheduled_date')
    def _compute_schedule_week(self):
        """計算排程週次（支援上週到第四週）"""
        today = fields.Date.today()
        current_week_start = today - timedelta(days=today.weekday())

        week_mapping = {
            -1: 'week_prev',  # 上週
            0: 'week0',  # 本週
            1: 'week1',  # 下週
            2: 'week2',  # 第三週
            3: 'week3',  # 第四週
        }

        for activity in self:
            date_to_check = activity.planned_date or activity.scheduled_date
            if not date_to_check:
                activity.schedule_week = False
                activity.schedule_week_number = -999  # 無日期
            else:
                # 計算日期與本週一的週數差異
                days_diff = (date_to_check - current_week_start).days
                week_number = days_diff // 7

                if week_number < -1:
                    # 更早的週次視為上週
                    activity.schedule_week = 'week_prev'
                    activity.schedule_week_number = -1
                elif week_number <= 3:
                    activity.schedule_week = week_mapping.get(week_number, 'week0')
                    activity.schedule_week_number = week_number
                else:
                    activity.schedule_week = 'future'
                    activity.schedule_week_number = week_number

    @api.depends('transferred_from_model', 'transferred_from_id')
    def _compute_is_transferred(self):
        """計算是否為轉移待辦"""
        for activity in self:
            activity.is_transferred = bool(
                activity.transferred_from_model and activity.transferred_from_id
            )

    @api.depends('transferred_from_model', 'transferred_from_id')
    def _compute_transferred_from_name(self):
        """計算轉移來源名稱"""
        for activity in self:
            if activity.transferred_from_model and activity.transferred_from_id:
                try:
                    record = self.env[activity.transferred_from_model].browse(
                        activity.transferred_from_id)
                    if record.exists():
                        activity.transferred_from_name = record.display_name
                    else:
                        activity.transferred_from_name = _('(記錄已刪除)')
                except Exception as e:
                    _logger.debug(
                        'Failed to compute transferred_from_name for activity %s: %s',
                        activity.id, str(e)
                    )
                    activity.transferred_from_name = False
            else:
                activity.transferred_from_name = False

    @api.depends('source_message_id')
    def _compute_source_message_preview(self):
        """計算來源訊息預覽"""
        for activity in self:
            if activity.source_message_id:
                msg = activity.source_message_id
                body = msg.body or ''
                # 截取前 200 字元作為預覽
                preview = self._strip_html_tags(body, max_length=200)
                activity.source_message_preview = preview
            else:
                activity.source_message_preview = False

    @api.depends('postpone_history_ids')
    def _compute_postpone_count(self):
        """計算延期次數"""
        for activity in self:
            activity.postpone_count = len(activity.postpone_history_ids)

    @api.depends('res_model', 'res_id')
    def _compute_related_records(self):
        """計算關聯的客戶、專案和 CRM（批次優化版本）"""
        # 初始化所有待辦的關聯欄位
        for activity in self:
            activity.partner_id = False
            activity.project_id = False
            activity.crm_lead_id = False

        # 依模型分組待辦，批次處理
        model_groups = defaultdict(list)
        for activity in self:
            if activity.res_model and activity.res_id:
                model_groups[activity.res_model].append(activity)

        # 批次處理每個模型
        for model_name, activities in model_groups.items():
            try:
                res_ids = [a.res_id for a in activities]
                records = self.env[model_name].browse(res_ids).exists()
                record_map = {r.id: r for r in records}

                for activity in activities:
                    record = record_map.get(activity.res_id)
                    if not record:
                        continue

                    # CRM Lead
                    if model_name == 'crm.lead':
                        activity.crm_lead_id = record.id
                        activity.partner_id = record.partner_id.id if record.partner_id else False

                    # Project Task
                    elif model_name == 'project.task':
                        activity.project_id = record.project_id.id if record.project_id else False
                        activity.partner_id = record.partner_id.id if record.partner_id else False

                    # Project
                    elif model_name == 'project.project':
                        activity.project_id = record.id
                        activity.partner_id = record.partner_id.id if record.partner_id else False

                    # Other models with partner_id
                    elif hasattr(record, 'partner_id') and record.partner_id:
                        activity.partner_id = record.partner_id.id

            except Exception as e:
                _logger.debug(
                    'Failed to compute related records for model %s: %s',
                    model_name, str(e)
                )

    @api.depends('date_deadline', 'estimated_hours', 'schedule_status')
    def _compute_schedule_warning(self):
        """計算排程警告"""
        weekday_map = {
            0: 'monday', 1: 'tuesday', 2: 'wednesday',
            3: 'thursday', 4: 'friday', 5: 'saturday', 6: 'sunday'
        }
        weekday_names = {
            0: '週一', 1: '週二', 2: '週三',
            3: '週四', 4: '週五', 5: '週六', 6: '週日'
        }

        today = fields.Date.today()
        week_end = today + timedelta(days=(6 - today.weekday()))

        for activity in self:
            activity.schedule_warning = False
            activity.needs_schedule_by = False

            if activity.schedule_status != 'waiting':
                continue
            if not activity.date_deadline:
                continue

            # 計算需安排日期
            estimated_days = math.ceil(
                (activity.estimated_hours or 0) / 8
            ) if activity.estimated_hours else 0
            needs_schedule_date = activity.date_deadline - timedelta(days=estimated_days)

            if needs_schedule_date <= week_end:
                weekday = needs_schedule_date.weekday()
                activity.needs_schedule_by = weekday_map.get(weekday)
                activity.schedule_warning = _('需於%s前安排執行') % weekday_names.get(weekday, '')

    # ========== Override Methods ==========

    @api.model_create_multi
    def create(self, vals_list):
        """覆寫 create 方法，處理 target_ref 欄位"""
        for vals in vals_list:
            # 如果有 target_ref，從中解析 res_model_id 和 res_id
            target_ref = vals.get('target_ref')
            if target_ref:
                # target_ref 格式為 "model,id"
                if isinstance(target_ref, str) and ',' in target_ref:
                    model, res_id = target_ref.split(',', 1)
                    vals['res_model_id'] = self.env['ir.model']._get(model).id
                    vals['res_id'] = int(res_id)

            # 確保 res_model_id 和 res_id 都有值
            if vals.get('res_model_id') and not vals.get('res_id'):
                raise UserError(_('請選擇「目標文件」，待辦必須關聯到一個文件記錄。'))

        return super().create(vals_list)

    def write(self, vals):
        """覆寫 write 方法以記錄指派變更"""
        # 驗證：只有被指派人或系統管理員可以設定排程相關欄位
        schedule_fields = {'planned_date', 'schedule_status', 'scheduled_date'}
        changing_schedule = bool(schedule_fields & set(vals.keys()))

        if changing_schedule and not self.env.su:
            # 檢查是否為內部操作（延期、週轉換等）
            is_internal_operation = self.env.context.get('skip_schedule_check', False)
            if not is_internal_operation:
                for activity in self:
                    # 若待辦有指派人，則只有被指派人可以修改排程
                    if activity.user_id and activity.user_id.id != self.env.uid:
                        # 允許系統管理員操作
                        if not self.env.user.has_group('base.group_system'):
                            raise UserError(_(
                                '排程操作僅限被指派人執行。\n'
                                '待辦「%s」已指派給 %s，您無法修改其排程。',
                                activity.summary or activity.activity_type_id.name,
                                activity.user_id.name
                            ))

        # 驗證：已排程的待辦不能手動改為等待排程，只能透過延期作業
        if vals.get('schedule_status') == 'waiting':
            # 延期作業會同時清除 planned_date，手動操作不會
            is_postpone_operation = vals.get('planned_date') is False
            if not is_postpone_operation:
                for activity in self:
                    if activity.planned_date:
                        raise UserError(_(
                            '待辦「%s」已排程至 %s，無法手動移至等待排程。\n'
                            '如需延期，請使用「延期」功能。',
                            activity.summary or activity.activity_type_id.name,
                            activity.planned_date.strftime('%Y-%m-%d')
                        ))

        # 記錄指派變更
        if 'user_id' in vals:
            for activity in self:
                if activity.user_id.id != vals.get('user_id'):
                    self.env['mail.activity.assignment.history'].sudo().create({
                        'activity_id': activity.id,
                        'previous_user_id': activity.user_id.id,
                        'new_user_id': vals.get('user_id'),
                    })

        # 處理排程狀態變更時自動設定計畫日期和來源標記
        if 'schedule_status' in vals and vals['schedule_status'] != 'waiting':
            weekday_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2,
                'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
            }
            target_weekday = weekday_map.get(vals['schedule_status'])
            if target_weekday is not None:
                # 自動設定計畫日期
                if 'planned_date' not in vals:
                    today = fields.Date.today()
                    current_weekday = today.weekday()
                    days_diff = target_weekday - current_weekday
                    if days_diff < 0:
                        days_diff += 7
                    vals['planned_date'] = today + timedelta(days=days_diff)

                # 如果來源尚未設定，標記為臨時插入
                if 'schedule_origin' not in vals:
                    for activity in self:
                        if not activity.schedule_origin:
                            vals['schedule_origin'] = 'inserted'
                            break

        return super().write(vals)

    # ===== 覆寫完成邏輯 =====
    def _action_done(self, feedback=False, attachment_ids=None):
        """覆寫：封存而非刪除待辦

        Odoo 18 變更說明：
        - 使用 message_post_with_source 取代 message_post_with_view
        - 使用 Command API 處理 attachment_ids
        - 注意 keep_done 邏輯的變化
        """
        messages = self.env['mail.message']
        next_activities_values = []

        # 處理附件
        attachments = self.env['ir.attachment'].search_read([
            ('res_model', '=', self._name),
            ('res_id', 'in', self.ids),
        ], ['id', 'res_id'])

        activity_attachments = defaultdict(list)
        for attachment in attachments:
            activity_attachments[attachment['res_id']].append(attachment['id'])

        for model, activity_data in self._classify_by_model().items():
            records_sudo = self.env[model].sudo().browse(activity_data['record_ids'])
            for record_sudo, activity in zip(records_sudo, activity_data['activities']):
                # 處理自動下一待辦（trigger 類型）
                if activity.chaining_type == 'trigger':
                    vals = activity.with_context(
                        activity_previous_deadline=activity.date_deadline
                    )._prepare_next_activity_values()
                    next_activities_values.append(vals)

                # 發送完成訊息（使用 Odoo 18 的 message_post_with_source）
                activity_message = record_sudo.message_post_with_source(
                    'mail.message_activity_done',
                    attachment_ids=attachment_ids,
                    author_id=self.env.user.partner_id.id,
                    render_values={
                        'activity': activity,
                        'feedback': feedback,
                        'display_assignee': activity.user_id != self.env.user,
                    },
                    mail_activity_type_id=activity.activity_type_id.id,
                    subtype_xmlid='mail.mt_activities',
                )

                # 移動附件到訊息
                if activity_attachments[activity.id]:
                    message_attachments = self.env['ir.attachment'].browse(
                        activity_attachments[activity.id])
                    if message_attachments:
                        message_attachments.write({
                            'res_id': activity_message.id,
                            'res_model': activity_message._name,
                        })
                        activity_message.attachment_ids = message_attachments
                messages |= activity_message

        # 建立下一待辦
        next_activities = self.env['mail.activity']
        if next_activities_values:
            next_activities = self.env['mail.activity'].create(next_activities_values)

        # 關鍵改動：封存而非刪除
        self.write({
            'active': False,
            'done_date': fields.Datetime.now(),
            'feedback': feedback,
        })

        # 建立工時表記錄
        for activity in self:
            activity._create_timesheet_entry()

        # 發送 bus 通知（使用 Odoo 18 的 _bus_send）
        for activity in self:
            if activity.user_id and activity.date_deadline and activity.date_deadline <= fields.Date.today():
                activity.user_id._bus_send(
                    'mail.activity/updated',
                    {'activity_deleted': True, 'count_diff': -1}
                )

        return messages, next_activities

    def _create_timesheet_entry(self):
        """完成待辦時建立工時表記錄 - 遵循 hr_timesheet 官方模式"""
        self.ensure_one()

        # 檢查是否有執行工時
        if not self.actual_hours or self.actual_hours <= 0:
            return False

        # 確認用戶有員工記錄
        employee = self.user_id.employee_id if self.user_id else False
        if not employee:
            _logger.warning(
                'User %s has no employee record, skipping timesheet for activity %s.',
                self.user_id.name if self.user_id else 'Unknown', self.id
            )
            return False

        if not employee.active:
            _logger.warning(
                'Employee %s is inactive, skipping timesheet for activity %s.',
                employee.name, self.id
            )
            return False

        project = False
        task_id = False

        # 情況 1：關聯 project.task
        if self.res_model == 'project.task':
            task = self.env['project.task'].browse(self.res_id)
            if task.exists() and task.project_id:
                # 確認專案允許工時表
                if hasattr(task.project_id, 'allow_timesheets') and task.project_id.allow_timesheets:
                    project = task.project_id
                    task_id = task.id

        # 情況 2：關聯 crm.lead（如果有專案關聯）
        elif self.res_model == 'crm.lead':
            lead = self.env['crm.lead'].browse(self.res_id)
            if hasattr(lead, 'project_id') and lead.project_id:
                if hasattr(lead.project_id, 'allow_timesheets') and lead.project_id.allow_timesheets:
                    project = lead.project_id

        # 情況 3：無專案，使用預設
        if not project:
            default_project = self.env.company.default_timesheet_project_id
            if default_project:
                # 確認預設專案允許工時表
                if hasattr(default_project, 'allow_timesheets') and default_project.allow_timesheets:
                    project = default_project
                else:
                    _logger.warning(
                        'Default project %s does not allow timesheets.',
                        default_project.name
                    )
                    return False
            else:
                _logger.warning(
                    'Activity %s completed but no project for timesheet. '
                    'Model: %s, ID: %s',
                    self.id, self.res_model, self.res_id
                )
                return False

        # 關鍵：確保 analytic_account_id 存在（官方 hr_timesheet 必要條件）
        if not project.analytic_account_id:
            _logger.warning(
                'Project %s has no analytic account, cannot create timesheet.',
                project.name
            )
            return False

        if not project.analytic_account_id.active:
            _logger.warning(
                'Project %s analytic account is inactive.',
                project.name
            )
            return False

        # 準備工時表值
        vals = {
            'date': self.planned_date or fields.Date.today(),
            'name': self.feedback or self.summary or _('待辦執行'),
            'unit_amount': self.actual_hours,
            'employee_id': employee.id,
            'user_id': self.user_id.id,
            'project_id': project.id,
            'task_id': task_id,
            'account_id': project.analytic_account_id.id,
            'company_id': project.analytic_account_id.company_id.id or project.company_id.id,
        }

        try:
            timesheet = self.env['account.analytic.line'].sudo().create(vals)
            self.timesheet_id = timesheet.id
            return timesheet
        except Exception as e:
            _logger.error('Failed to create timesheet for activity %s: %s', self.id, str(e))
            return False

    def action_cancel(self):
        """取消待辦（封存）"""
        self.write({
            'active': False,
            'cancel_date': fields.Datetime.now(),
        })
        # 發送 bus 通知
        for activity in self:
            if activity.user_id:
                activity.user_id._bus_send(
                    'mail.activity/updated',
                    {'activity_deleted': True, 'count_diff': -1}
                )
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_restore(self):
        """恢復已封存的待辦"""
        self.write({
            'active': True,
            'done_date': False,
            'cancel_date': False,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_open_document(self):
        """打開相關文件"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_source_message(self):
        """開啟來源訊息所在的文件"""
        self.ensure_one()
        if not self.source_message_id:
            raise UserError(_('此待辦沒有來源訊息。'))

        msg = self.source_message_id

        # 若訊息在 discuss 頻道，確保當前用戶已加入頻道
        # 注意：Odoo 18 使用 discuss.channel 取代 mail.channel
        if msg.model == 'discuss.channel' and msg.res_id:
            channel = self.env['discuss.channel'].browse(msg.res_id)
            if channel.exists():
                partner = self.env.user.partner_id
                if partner:
                    # Odoo 18 使用 channel_member_ids
                    member_partners = channel.channel_member_ids.mapped('partner_id')
                    if partner not in member_partners:
                        try:
                            channel.add_members(partner_ids=[partner.id])
                        except AccessError:
                            raise UserError(_('無法加入此頻道，您可能沒有存取權限。'))

        if msg.model and msg.res_id:
            # 開啟訊息所在的文件，並帶上 message_id 參數以便定位
            return {
                'type': 'ir.actions.act_window',
                'res_model': msg.model,
                'res_id': msg.res_id,
                'view_mode': 'form',
                'target': 'current',
                'context': {
                    'message_id': msg.id,
                }
            }
        else:
            # 訊息不在特定文件上（可能是 discuss 頻道訊息）
            return {
                'type': 'ir.actions.act_url',
                'url': '/mail/channel?message_id=%s' % msg.id,
                'target': 'self',
            }

    def action_transfer_activity(self):
        """開啟轉移 wizard"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('轉移待辦'),
            'res_model': 'mail.activity.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
                'default_source_model': self.res_model,
                'default_source_id': self.res_id,
            }
        }

    def action_done_wizard(self):
        """開啟完成 wizard"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('完成待辦'),
            'res_model': 'mail.activity.done.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
            }
        }

    def action_postpone_wizard(self):
        """開啟延期 wizard"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('延至下週'),
            'res_model': 'mail.activity.postpone.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
            }
        }

    def action_done(self):
        """覆寫原始 action_done，開啟完成 wizard"""
        if self.env.context.get('mail_activity_quick_update'):
            return super().action_done()
        return self.action_done_wizard()

    # ===== 覆寫通知方法：支援自定義郵件模板 =====
    def action_notify(self):
        """覆寫：支援使用 Activity Type 設定的自定義郵件模板發送通知

        若 Activity Type 設定了 use_custom_notify=True 且有 notify_template_id，
        則使用該模板發送郵件；否則使用原始的系統預設通知。
        """
        if not self:
            return

        # 分離使用自定義模板和預設通知的待辦
        custom_notify_activities = self.env['mail.activity']
        default_notify_activities = self.env['mail.activity']

        for activity in self:
            activity_type = activity.activity_type_id
            if (activity_type and
                    hasattr(activity_type, 'use_custom_notify') and
                    activity_type.use_custom_notify and
                    activity_type.notify_template_id):
                custom_notify_activities |= activity
            else:
                default_notify_activities |= activity

        # 處理自定義模板通知
        for activity in custom_notify_activities:
            template = activity.activity_type_id.notify_template_id
            # 使用被指派者的語言
            if activity.user_id.lang:
                template = template.with_context(lang=activity.user_id.lang)

            # 發送郵件給被指派者
            template.send_mail(
                activity.res_id,
                force_send=False,
                email_values={
                    'email_to': activity.user_id.email,
                    'recipient_ids': [Command.link(activity.user_id.partner_id.id)],
                },
            )
            _logger.info(
                'Activity %s: sent custom notification using template %s to %s',
                activity.id, template.name, activity.user_id.name
            )

        # 處理預設通知（調用原始方法）
        if default_notify_activities:
            super(MailActivity, default_notify_activities).action_notify()

    # ========== 工具方法 ==========

    @api.model
    def _strip_html_tags(self, html_content, max_length=None):
        """清理 HTML 標籤，提取純文字"""
        if not html_content:
            return ''
        plain_text = re.sub(r'<[^>]+>', '', html_content)
        plain_text = plain_text.strip()
        if max_length and len(plain_text) > max_length:
            return plain_text[:max_length] + '...'
        return plain_text

    # ========== 關聯筆記 API ==========

    @api.model
    def get_related_notes(self, res_model, res_id):
        """取得指定文件的待辦所關聯的 Notes"""
        activities = self.with_context(active_test=False).search([
            ('res_model', '=', res_model),
            ('res_id', '=', res_id),
            ('note_id', '!=', False),
        ])

        notes_activities = defaultdict(list)
        for activity in activities:
            if activity.active:
                activity_state = 'active'
            elif activity.done_date:
                activity_state = 'done'
            elif activity.cancel_date:
                activity_state = 'cancelled'
            else:
                activity_state = 'archived'

            notes_activities[activity.note_id.id].append({
                'id': activity.id,
                'summary': activity.summary or '',
                'state': activity_state,
                'note': activity.note_id,
            })

        notes_data = []
        for note_id, activity_list in notes_activities.items():
            note = activity_list[0]['note']
            note_name = note.name
            if not note_name and note.memo:
                note_name = self._strip_html_tags(note.memo, max_length=50)

            active_count = sum(1 for a in activity_list if a['state'] == 'active')
            done_count = sum(1 for a in activity_list if a['state'] in ('done', 'cancelled'))
            total_count = len(activity_list)

            activities_info = [{
                'id': a['id'],
                'summary': a['summary'],
                'state': a['state'],
            } for a in activity_list]

            notes_data.append({
                'id': note_id,
                'name': note_name or _('未命名筆記'),
                'activities': activities_info,
                'total_count': total_count,
                'active_count': active_count,
                'done_count': done_count,
                'is_all_done': active_count == 0 and total_count > 0,
            })

        return notes_data

    # ========== 週轉換定時任務 ==========

    @api.model
    def _cron_weekly_transition(self):
        """每週一凌晨執行的排程任務"""
        today = fields.Date.today()
        if today.weekday() != 0:  # 只在週一執行
            return

        # 找出下週預排的待辦（已有 scheduled_date 但無 planned_date）
        activities = self.search([
            ('scheduled_date', '!=', False),
            ('planned_date', '=', False),
            ('active', '=', True),
        ])

        for activity in activities:
            weekday = activity.scheduled_date.weekday()
            weekday_map = {
                0: 'monday', 1: 'tuesday', 2: 'wednesday',
                3: 'thursday', 4: 'friday', 5: 'saturday', 6: 'sunday'
            }
            # 使用 context 標記跳過權限檢查（系統定時任務）
            activity.with_context(skip_schedule_check=True).write({
                'planned_date': activity.scheduled_date,
                'schedule_status': weekday_map.get(weekday, 'waiting'),
                'scheduled_date': False,
            })

        _logger.info('Weekly transition completed. Processed %d activities.', len(activities))

    # ========== 頻道工具方法 ==========

    @api.model
    def _add_user_to_channel_from_message(self, message, user):
        """將用戶加入訊息所在的 Discuss 頻道（共用方法）

        Args:
            message: mail.message 記錄或 False
            user: res.users 記錄

        注意：Odoo 18 使用 discuss.channel 取代 mail.channel
        """
        if not message or not user:
            return

        # 檢查訊息是否來自 discuss 頻道
        if message.model == 'discuss.channel' and message.res_id:
            channel = self.env['discuss.channel'].browse(message.res_id)
            if channel.exists():
                partner = user.partner_id
                if partner:
                    # 檢查用戶是否已在頻道中
                    member_partners = channel.channel_member_ids.mapped('partner_id')
                    if partner not in member_partners:
                        try:
                            channel.add_members(partner_ids=[partner.id])
                        except Exception as e:
                            _logger.debug(
                                'Could not add user %s to channel %s: %s',
                                user.id, channel.id, str(e)
                            )

    # ========== 領取與變更指派 ==========

    def _add_user_to_source_channel(self, user):
        """將用戶加入來源訊息所在的 Discuss 頻道"""
        self.ensure_one()
        self._add_user_to_channel_from_message(self.source_message_id, user)

    def action_claim_activity(self):
        """領取待辦（將 user_id 設為當前用戶）"""
        self.ensure_one()
        if self.user_id:
            raise UserError(_('此待辦已被指派，無法領取。'))

        now = fields.Datetime.now()
        claim_note = _('\n\n--- %s 領取此待辦 ---') % now.strftime('%Y-%m-%d %H:%M')

        self.write({
            'user_id': self.env.user.id,
            'note': (self.note or '') + claim_note,
        })

        # 將領取者加入來源訊息所在的頻道
        self._add_user_to_source_channel(self.env.user)

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_reassign_activity(self):
        """開啟變更指派 wizard"""
        self.ensure_one()
        if not self.user_id:
            raise UserError(_('此待辦尚未指派，請使用領取功能。'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('變更指派'),
            'res_model': 'mail.activity.reassign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
            }
        }

    # ========== 週次排程方法 ==========

    def action_schedule_to_week(self, week_number):
        """將待辦排程至指定週次

        Args:
            week_number: -1=上週, 0=本週, 1=下週, 2=第三週, 3=第四週
        Returns:
            重新載入視圖的 action
        """
        today = fields.Date.today()
        current_week_start = today - timedelta(days=today.weekday())
        target_week_start = current_week_start + timedelta(days=7 * week_number)

        for activity in self:
            # 保持原有的星期幾，或預設為週一
            if activity.planned_date:
                original_weekday = activity.planned_date.weekday()
            elif activity.scheduled_date:
                original_weekday = activity.scheduled_date.weekday()
            else:
                original_weekday = 0  # 預設週一

            target_date = target_week_start + timedelta(days=original_weekday)

            # 根據週次設定不同欄位
            if week_number <= 0:
                # 上週或本週：設定 planned_date
                activity.write({
                    'planned_date': target_date,
                    'scheduled_date': False,
                })
            else:
                # 未來週次：設定 scheduled_date
                activity.write({
                    'scheduled_date': target_date,
                    'planned_date': False,
                })

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_schedule_to_week_prev(self):
        """排程至上週"""
        return self.action_schedule_to_week(-1)

    def action_schedule_to_week0(self):
        """排程至本週"""
        return self.action_schedule_to_week(0)

    def action_schedule_to_week1(self):
        """排程至下週"""
        return self.action_schedule_to_week(1)

    def action_schedule_to_week2(self):
        """排程至第三週"""
        return self.action_schedule_to_week(2)

    def action_schedule_to_week3(self):
        """排程至第四週"""
        return self.action_schedule_to_week(3)

    @api.model
    def get_week_info(self):
        """取得五週的日期資訊（供前端使用）：上週、本週、下週、第三週、第四週"""
        today = fields.Date.today()
        current_week_start = today - timedelta(days=today.weekday())

        # 週天對應的 schedule_status 值
        weekday_keys = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

        # 週次設定：從 -1 (上週) 到 3 (第四週)
        week_configs = [
            (-1, '上週', 'week_prev'),
            (0, '本週', 'week0'),
            (1, '下週', 'week1'),
            (2, '第三週', 'week2'),
            (3, '第四週', 'week3'),
        ]

        weeks = []
        for week_number, week_name, week_key in week_configs:
            week_start = current_week_start + timedelta(days=7 * week_number)
            week_end = week_start + timedelta(days=6)

            # 計算該週的待辦數量（不含等待排程）
            domain = [
                ('active', '=', True),
                ('user_id', '=', self.env.uid),
                ('schedule_week_number', '=', week_number),
                ('schedule_status', '!=', 'waiting'),
            ]
            # 使用 read_group 一次取得數量和總工時
            result = self.read_group(
                domain=domain,
                fields=['estimated_hours:sum'],
                groupby=[],
            )
            count = result[0].get('__count', 0) if result else 0
            total_hours = result[0].get('estimated_hours', 0) if result else 0

            # 建立每天的日期對應表
            dates = {}
            for day_index, day_key in enumerate(weekday_keys):
                day_date = week_start + timedelta(days=day_index)
                dates[day_key] = day_date.strftime('%Y-%m-%d')

            weeks.append({
                'number': week_number,
                'name': week_name,
                'key': week_key,
                'start_date': week_start.strftime('%Y-%m-%d'),
                'end_date': week_end.strftime('%Y-%m-%d'),
                'count': count,
                'total_hours': total_hours,
                'dates': dates,
            })

        return weeks
