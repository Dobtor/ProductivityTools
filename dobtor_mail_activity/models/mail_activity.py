# -*- coding: utf-8 -*-
import math
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, AccessError
from odoo.release import version_info
from odoo.tools import html2plaintext

# 此 bypass 修正 Odoo 18.0 中 mail.activity create 的 UnboundLocalError bug。
# 若 Odoo 官方在未來版本修正此問題，可移除 bypass。
# 最後驗證版本：18.0
_CREATE_BYPASS_APPLICABLE = version_info[0] <= 18

_logger = logging.getLogger(__name__)


class MailActivity(models.Model):
    """待辦擴展 - 擴展官方 mail.activity 模型

    主要功能:
    - 封存機制：完成/取消待辦時封存而非刪除
    - 排程系統：支援週計畫與預排功能
    - 優先級管理：時間性與重要性標記
    - 工時追蹤：預估與實際工時記錄（支援多次登錄）
    - 歷史追蹤：指派變更與延期記錄
    - 轉移功能：支援待辦在不同文件間轉移
    - 訊息來源：追蹤從訊息建立的待辦
    - 訊息功能：支援發送訊息、建立備註、加入關注者（mail.thread）
    """
    _name = 'mail.activity'
    _inherit = ['mail.activity', 'mail.thread']
    _description = 'Activity'

    # ===== mail.thread 設定 =====
    _mail_post_access = 'read'  # 讀取權限即可發送訊息

    # ========== 欄位定義 ==========

    # ===== 覆寫 user_id 為非必填且無預設值 =====
    user_id = fields.Many2one(
        'res.users',
        string='Assigned to',
        index=True,
        tracking=True,
        required=False,  # 改為非必填
        default=False,   # 移除預設值（官方預設為當前用戶）
    )

    # ===== 覆寫 res_id 為可寫入（官方預設 readonly=True）=====
    # 這讓 target_ref 的 onchange 能正確設定 res_id
    res_id = fields.Many2oneReference(
        index='btree_not_null',
        model_field='res_model',
        readonly=False,  # 改為可寫入
    )

    # ===== 封存相關 =====
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    done_date = fields.Datetime(
        string='Done Datetime',
        readonly=True,
    )
    cancel_date = fields.Datetime(
        string='Cancel Date',
        readonly=True,
    )

    # 注意：原始 state 是計算欄位，無法使用 selection_add
    # 改用 activity_status 來追蹤自定義狀態（activity_state 已被 mixin 使用）
    activity_status = fields.Selection([
        ('active', 'Active'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Activity Status', compute='_compute_activity_status', store=True)

    # ===== 關聯筆記 =====
    note_id = fields.Many2one(
        'note.note',
        string='Related Note',
        index=True,
        ondelete='set null',
        help='Note linked to this activity',
    )

    # ===== res_name 儲存計算結果以提升效能 =====
    res_name = fields.Char(
        string='Document Name',
        compute='_compute_res_name',
        compute_sudo=True,
        store=True,
        help='Display name of the related document',
    )

    # ===== 目標文件選擇（用於建立待辦時選擇關聯文件）=====
    target_ref = fields.Reference(
        string='Target Document',
        selection='_selection_target_model',
        compute='_compute_target_ref',
        inverse='_inverse_target_ref',
    )

    # ===== 排程相關 =====
    schedule_status = fields.Selection([
        ('waiting', 'Waiting'),
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ], string='Schedule Status', default='waiting', index=True,
       group_expand='_group_expand_schedule_status')

    planned_date = fields.Date(
        string='Planned Date',
        help='Date scheduled for this week plan',
    )

    scheduled_date = fields.Date(
        string='Scheduled Date',
        help='For next week pre-scheduling, copied to planned date on week transition',
    )

    schedule_week = fields.Selection([
        ('week_prev', 'Previous Week'),
        ('week0', 'This Week'),
        ('week1', 'Next Week'),
        ('week2', 'Week 3'),
        ('week3', 'Week 4'),
        ('future', 'Future'),
    ], string='Schedule Week', compute='_compute_schedule_week', store=True)

    schedule_week_number = fields.Integer(
        string='Week Number',
        compute='_compute_schedule_week',
        store=True,
        help='0=This Week, 1=Next Week, 2=Week 3, 3=Week 4, 4+=Future',
    )

    schedule_origin = fields.Selection([
        ('planned', 'Planned'),           # 建立週報告時在本週計畫內
        ('inserted', 'Inserted'),         # 週間新增，不在週報告快照中
        ('postponed', 'Postponed'),       # 從延期而來
        ('transferred', 'Transferred'),   # 從其他文件轉移
    ], string='Origin')  # 建立時留空，排入週天時才標記

    original_schedule_week = fields.Char(
        string='Original Schedule Week',
        help='Format: 2026-W02',
    )

    # ===== 轉移追蹤 =====
    transferred_from_model = fields.Char(
        string='Transferred From Model',
        readonly=True,
    )
    transferred_from_id = fields.Integer(
        string='Transferred From ID',
        readonly=True,
    )
    transferred_from_name = fields.Char(
        string='Transferred From',
        compute='_compute_transferred_from_name',
    )
    is_transferred = fields.Boolean(
        string='Is Transferred',
        compute='_compute_is_transferred',
        store=True,
    )

    # ===== 訊息來源追蹤 =====
    source_message_id = fields.Many2one(
        'mail.message',
        string='Source Message',
        index=True,
        readonly=True,
        help='Message this activity was created from',
    )
    source_message_preview = fields.Html(
        string='Message Preview',
        compute='_compute_source_message_preview',
    )

    # ===== 優先級欄位 =====
    urgency = fields.Selection([
        ('urgent', 'Urgent'),
        ('standard', 'Standard'),
        ('flexible', 'Flexible'),
    ], string='Urgency', default='standard')

    importance = fields.Selection([
        ('important', 'Important'),
        ('normal', 'Normal'),
    ], string='Importance', default='normal')

    # ===== 指派歷史 =====
    assignment_history_ids = fields.One2many(
        'mail.activity.assignment.history',
        'activity_id',
        string='Assignment History',
    )

    # ===== 延期歷史 =====
    postpone_history_ids = fields.One2many(
        'mail.activity.postpone.history',
        'activity_id',
        string='Postpone History',
    )

    postpone_count = fields.Integer(
        string='Postpone Count',
        compute='_compute_postpone_count',
        store=True,
    )

    # ===== 工時相關 =====
    estimated_hours = fields.Float(
        string='Estimated Hours',
        help='Estimated time required for execution (hours)',
    )

    # actual_hours：核心為普通欄位（可手動累計）。
    # 安裝 timesheet 橋接模組（dobtor_mail_activity_timesheet）後，
    # 會被改寫為由關聯工時表記錄自動加總的計算欄位。
    actual_hours = fields.Float(
        string='Actual Hours',
        help='Total time spent on this activity (hours).',
    )

    feedback = fields.Text(
        string='Completion Feedback',
    )

    # ===== 關聯顯示（設定驅動，不綁定特定模組）=====
    # partner_id 由 mail.activity.transfer.config 指定的 partner 欄位
    #（或自動探測模型上的 'partner_id'）派生；「關聯文件」顯示沿用既有的
    # res_name（= 來源文件 display_name），同樣不認得任何具體模組。
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        compute='_compute_partner_id',
        store=True,
    )

    # ===== 警告相關 =====
    schedule_warning = fields.Char(
        string='Schedule Warning',
        compute='_compute_schedule_warning',
    )

    needs_schedule_by = fields.Selection([
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ], string='Needs Schedule By', compute='_compute_schedule_warning')

    # ===== 相關待辦（同文件）=====
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='For ordering activities on the same document',
    )

    related_activity_ids = fields.Many2many(
        'mail.activity',
        compute='_compute_related_activity_ids',
        string='Related Activities',
        help='All activities on the same document',
    )

    related_activity_count = fields.Integer(
        string='Related Activity Count',
        compute='_compute_related_activity_ids',
    )

    # ===== 來源訊息擴展 =====
    source_message_type = fields.Selection([
        ('document', 'Document Message'),
        ('channel', 'Channel Message'),
    ], string='Source Message Type', compute='_compute_source_message_context',
       help='Distinguish if message comes from Document Chatter or Discuss Channel')

    context_message_ids = fields.Many2many(
        'mail.message',
        compute='_compute_source_message_context',
        string='Context Messages',
        help='Source message and 2 messages before/after',
    )

    context_messages_html = fields.Html(
        string='Message Context HTML',
        compute='_compute_context_messages_html',
        sanitize=False,  # 保留官方 CSS class
    )

    # ========== Computed Methods ==========

    @api.depends('active', 'done_date', 'cancel_date')
    def _compute_activity_status(self):
        """計算待辦狀態"""
        for activity in self:
            if activity.cancel_date:
                activity.activity_status = 'cancelled'
            elif activity.done_date:
                activity.activity_status = 'done'
            else:
                activity.activity_status = 'active'

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
                        activity.res_name = _('(Record Deleted)')
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
        allowed_models = {m for m, _n in self._selection_target_model()}
        for activity in self:
            if activity.res_model and activity.res_id and activity.res_model in allowed_models:
                activity.target_ref = '%s,%s' % (activity.res_model, activity.res_id)
            else:
                activity.target_ref = False

    def _inverse_target_ref(self):
        """反向設定 res_model_id 和 res_id

        當 target_ref 為空時，自動關聯到用戶的預設待辦筆記。
        """
        for activity in self:
            if activity.target_ref:
                model_name = activity.target_ref._name
                # res_model 是 related 欄位（readonly），只設定 res_model_id 和 res_id
                activity.res_model_id = self.env['ir.model']._get(model_name)
                activity.res_id = activity.target_ref.id
            else:
                # target_ref 為空時，自動關聯到用戶的預設筆記
                # 因為官方 res_model_id 是 NOT NULL，不能設為 False
                target_user = activity.user_id or self.env.user
                default_note = target_user._get_or_create_default_activity_note()
                activity.res_model_id = self.env['ir.model']._get('note.note')
                activity.res_id = default_note.id
                activity.note_id = default_note

    @api.onchange('target_ref')
    def _onchange_target_ref(self):
        """當選擇目標文件時，立即更新 res_model_id 和 res_id

        當清空 target_ref 時，不自動關聯預設筆記，讓用戶自由選擇。
        create() 會在儲存時處理空值情況。
        """
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
        # 不在 onchange 中自動設定預設筆記，避免選擇被強制覆蓋
        # create() 和 _inverse_target_ref() 會在儲存時處理空值

    def _set_default_note(self):
        """設定預設筆記為關聯目標"""
        target_user = self.user_id or self.env.user
        default_note = target_user._get_or_create_default_activity_note()
        self.res_model_id = self.env['ir.model']._get('note.note')
        self.res_id = default_note.id
        self.note_id = default_note

    # 注意：已移除 _check_target_document 約束
    # 改為在 create 時自動關聯到用戶的預設筆記（若未指定目標文件）
    # 這允許建立「獨立待辦」，同時保持與 Odoo mail.activity 設計的相容性

    @api.model_create_multi
    def create(self, vals_list):
        """覆寫 create 方法

        1. 處理 target_ref 轉換為 res_model_id 和 res_id
        2. 若未指定目標文件，自動關聯到用戶的預設待辦筆記
        3. 繞過 Odoo 18 base mail.activity create 中的 UnboundLocalError bug
        4. 停用 mail.thread 的自動訂閱和追蹤
        """
        for vals in vals_list:
            # 處理 target_ref 欄位（格式：'model.name,id'）
            if vals.get('target_ref'):
                target_ref = vals.pop('target_ref')
                if isinstance(target_ref, str) and ',' in target_ref:
                    model_name, res_id_str = target_ref.rsplit(',', 1)
                    try:
                        res_id = int(res_id_str)
                        vals['res_model_id'] = self.env['ir.model']._get(model_name).id
                        vals['res_id'] = res_id
                    except (ValueError, TypeError):
                        _logger.warning('Invalid target_ref format: %s', target_ref)

            # 若未指定目標文件，自動關聯到用戶的預設待辦筆記
            if not vals.get('res_model_id') and not vals.get('res_id'):
                # 決定待辦的擁有者（優先使用 vals 中指定的 user_id）
                target_user_id = vals.get('user_id') or self.env.uid
                target_user = self.env['res.users'].browse(target_user_id)

                # 取得或建立預設筆記
                default_note = target_user._get_or_create_default_activity_note()
                if default_note:
                    vals['res_model_id'] = self.env['ir.model']._get('note.note').id
                    vals['res_id'] = default_note.id
                    vals['note_id'] = default_note.id  # 同時設定 note_id 關聯
                    _logger.debug(
                        'Activity auto-linked to default note %s for user %s',
                        default_note.id, target_user.name
                    )

            # 設定預設的 activity_type_id（如果未提供）
            if not vals.get('activity_type_id'):
                activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
                if activity_type:
                    vals['activity_type_id'] = activity_type.id

        # 使用 context 停用 mail.thread 的自動訂閱和追蹤
        self_with_context = self.with_context(
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            tracking_disable=True,
        )

        if _CREATE_BYPASS_APPLICABLE:
            # 直接呼叫 models.Model.create 繞過 base mail.activity 的 buggy code
            # Odoo 18 的 mail/models/mail_activity.py 有 UnboundLocalError bug
            activities = models.Model.create(self_with_context, vals_list)

            # 手動處理 bus 通知（原本在 base create 中，但有 bug）
            for activity in activities:
                if activity.user_id:
                    try:
                        activity.user_id._bus_send(
                            'mail.activity/updated',
                            {'activity_created': True}
                        )
                    except Exception as e:
                        _logger.debug('Bus notification failed: %s', str(e))

            # 通知被指派人（僅指派給他人時，與原生邏輯一致）
            activities_to_notify = activities.filtered(
                lambda act: act.user_id and act.user_id != self.env.user
            )
            if activities_to_notify:
                user_partners = activities_to_notify.user_id.partner_id
                readable_user_partners = user_partners._filtered_access('read')
                to_sudo = activities_to_notify.filtered(
                    lambda act: act.user_id.partner_id not in readable_user_partners
                )
                other = activities_to_notify - to_sudo
                to_sudo.sudo().action_notify()
                other.action_notify()

            # 手動訂閱被分派人為關聯文件的關注者
            # （bypass 繞過了 core create 中的 message_subscribe 邏輯）
            for activity in activities:
                if activity.user_id and activity.res_model and activity.res_id:
                    try:
                        Model = self.env[activity.res_model]
                        if hasattr(Model, 'message_subscribe'):
                            record = Model.browse(activity.res_id).exists()
                            if record:
                                record.message_subscribe(
                                    partner_ids=activity.user_id.sudo().partner_id.ids
                                )
                    except Exception:
                        _logger.debug(
                            'Failed to subscribe user %s to %s,%s',
                            activity.user_id.name, activity.res_model, activity.res_id,
                            exc_info=True,
                        )
        else:
            activities = super().create(vals_list)

        return activities

    @api.model
    def _group_expand_schedule_status(self, statuses, domain, order=None):
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
                        activity.transferred_from_name = _('(Record Deleted)')
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
                preview = self._html_to_text(body, max_length=200)
                activity.source_message_preview = preview
            else:
                activity.source_message_preview = False

    @api.depends('res_model', 'res_id')
    def _compute_related_activity_ids(self):
        """計算同文件的所有待辦事項（批次優化）"""
        # 收集所有 (res_model, res_id) 組合
        doc_keys = set()
        for activity in self:
            if activity.res_model and activity.res_id:
                doc_keys.add((activity.res_model, activity.res_id))

        # 一次查詢所有相關待辦

        doc_activities = defaultdict(lambda: self.env['mail.activity'])

        if doc_keys:
            domain = ['|'] * (len(doc_keys) - 1)
            for model, res_id in doc_keys:
                domain += [
                    '&',
                    ('res_model', '=', model),
                    ('res_id', '=', res_id),
                ]
                
            all_related = self.with_context(active_test=False).search(
                domain, order='sequence, id'
            )

            for act in all_related:
                doc_activities[(act.res_model, act.res_id)] |= act

        for activity in self:
            if activity.res_model and activity.res_id:
                related = doc_activities[(activity.res_model, activity.res_id)]
                activity.related_activity_ids = related
                activity.related_activity_count = len(related)
            else:
                activity.related_activity_ids = False
                activity.related_activity_count = 0

    @api.depends('source_message_id')
    def _compute_source_message_context(self):
        """計算來源訊息的類型和上下文訊息"""
        for activity in self:
            if activity.source_message_id:
                msg = activity.source_message_id

                # 判斷訊息來源類型
                if msg.model == 'discuss.channel':
                    activity.source_message_type = 'channel'
                elif msg.model and msg.res_id:
                    activity.source_message_type = 'document'
                else:
                    activity.source_message_type = False

                # 用兩次有限查詢取代無限全表搜尋：
                # 查詢來源訊息之後（含）的較舊訊息（desc → id <= msg.id）
                Message = self.env['mail.message']
                base_domain = [
                    ('model', '=', msg.model),
                    ('res_id', '=', msg.res_id),
                    ('message_type', 'in', ['comment', 'email']),
                ]
                older = Message.search(
                    base_domain + [('id', '<=', msg.id)],
                    order='date desc, id desc', limit=3,
                )
                newer = Message.search(
                    base_domain + [('id', '>', msg.id)],
                    order='date asc, id asc', limit=2,
                )
                context_msgs = newer | older
                if context_msgs:
                    activity.context_message_ids = context_msgs
                else:
                    activity.context_message_ids = msg
            else:
                activity.source_message_type = False
                activity.context_message_ids = False

    @api.depends('context_message_ids', 'source_message_id')
    def _compute_context_messages_html(self):
        """使用 QWeb 渲染訊息 HTML，採用官方樣式"""
        for activity in self:
            if activity.context_message_ids:
                activity.context_messages_html = self.env['ir.qweb']._render(
                    'dobtor_mail_activity.message_context_preview',
                    {
                        'messages': activity.context_message_ids,
                        'source_message_id': activity.source_message_id.id if activity.source_message_id else False,
                    }
                )
            else:
                activity.context_messages_html = False

    @api.depends('postpone_history_ids')
    def _compute_postpone_count(self):
        """計算延期次數"""
        for activity in self:
            activity.postpone_count = len(activity.postpone_history_ids)

    @api.depends('res_model', 'res_id')
    def _compute_partner_id(self):
        """設定驅動派生關聯客戶（批次優化，不綁定特定模組）。

        partner 欄位來源優先序：
        1. mail.activity.transfer.config 為該模型指定的 partner_field
        2. 自動探測來源模型上的 'partner_id' 欄位
        皆無則留空。

        如此核心 mail.activity 完全不認得 crm.lead / project.* 等具體模組，
        新增可關聯模型只需在轉移/關聯設定中加一筆。
        """
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()

        # 初始化 + 依模型分組（僅處理目前已安裝、存在的模型）
        model_groups = defaultdict(list)
        for activity in self:
            activity.partner_id = False
            if activity.res_model and activity.res_id and activity.res_model in self.env:
                model_groups[activity.res_model].append(activity)

        for model_name, activities in model_groups.items():
            Model = self.env[model_name]
            partner_field = relation_map.get(model_name, {}).get('partner_field')
            if not partner_field and 'partner_id' in Model._fields:
                partner_field = 'partner_id'
            if not partner_field or partner_field not in Model._fields:
                continue

            res_ids = list({a.res_id for a in activities})
            record_map = {r.id: r for r in Model.browse(res_ids).exists()}
            for activity in activities:
                record = record_map.get(activity.res_id)
                if not record:
                    continue
                try:
                    partner = record[partner_field]
                except Exception as e:
                    _logger.debug(
                        'Failed to read partner field %s on %s: %s',
                        partner_field, model_name, str(e)
                    )
                    continue
                activity.partner_id = partner[:1].id if partner else False

    @api.depends('date_deadline', 'estimated_hours', 'schedule_status')
    def _compute_schedule_warning(self):
        """計算排程警告"""
        weekday_map = {
            0: 'monday', 1: 'tuesday', 2: 'wednesday',
            3: 'thursday', 4: 'friday', 5: 'saturday', 6: 'sunday'
        }
        weekday_names = {
            0: 'Monday', 1: 'Tuesday', 2: 'Wednesday',
            3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'
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
                activity.schedule_warning = _('Needs to be scheduled by %(weekday)s', weekday=weekday_names.get(weekday, ''))

    # ========== Override Methods ==========

    def write(self, vals):
        """覆寫 write 方法以記錄指派變更"""
        # 驗證：date_deadline 只有建立者或系統管理員可以修改
        if 'date_deadline' in vals and not self.env.su:
            for activity in self:
                if activity.create_uid.id != self.env.uid:
                    if not self.env.user.has_group('base.group_system'):
                        raise UserError(_(
                            'Only the creator can modify the due date.\n'
                            'Activity "%(summary)s" was created by %(creator)s.',
                            summary=activity.summary or activity.activity_type_id.name,
                            creator=activity.create_uid.name,
                        ))

        # 驗證：planned_date 只能透過排程操作更新（拖曳/延期/週轉換）
        if 'planned_date' in vals and 'schedule_status' not in vals:
            if not self.env.context.get('skip_schedule_check', False) and not self.env.su:
                raise UserError(_(
                    'Planned date cannot be modified directly.\n'
                    'Please use drag-and-drop on the Kanban board or the schedule bar to update it.'
                ))

        # 驗證：user_id 建立後只能透過領取或變更指派操作修改
        # 豁免：calendar.event._sync_activities() 同步日曆事件時會連帶寫入 user_id
        if 'user_id' in vals and not self.env.su:
            if not self.env.context.get('allow_user_change', False) \
                    and not self.env.context.get('calendar_event_save', False) \
                    and not any(a.calendar_event_id for a in self):
                for activity in self:
                    if activity.id:  # 已存在的記錄才限制
                        raise UserError(_(
                            'Assignee cannot be changed directly after creation.\n'
                            'Please use "Claim" (for unassigned activities) or "Reassign" to change the assignee.'
                        ))

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
                                'Schedule operations are limited to the assignee.\n'
                                'Activity "%s" is assigned to %s, you cannot modify its schedule.',
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
                            'Activity "%s" is scheduled for %s and cannot be manually moved to waiting.\n'
                            'To postpone, please use the "Postpone" function.',
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
                    # 優先使用前端傳遞的週次日期對應表（拖曳時傳入）
                    week_dates = self.env.context.get('schedule_week_dates')
                    target_day_key = vals['schedule_status']
                    if week_dates and target_day_key in week_dates:
                        try:
                            vals['planned_date'] = fields.Date.to_date(week_dates[target_day_key])
                        except (ValueError, TypeError):
                            week_dates = None  # 格式錯誤，回退到計算方式

                    if 'planned_date' not in vals:
                        # 回退：根據目前週次計算日期
                        schedule_week_number = self.env.context.get('schedule_current_week', 0)
                        today = fields.Date.today()
                        current_week_start = today - timedelta(days=today.weekday())
                        target_week_start = current_week_start + timedelta(days=7 * schedule_week_number)
                        vals['planned_date'] = target_week_start + timedelta(days=target_weekday)

                # 如果來源尚未設定，標記為臨時插入（僅當所有記錄均無 origin 時）
                if 'schedule_origin' not in vals:
                    if all(not act.schedule_origin for act in self):
                        vals['schedule_origin'] = 'inserted'

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

        # 關鍵改動：封存而非刪除（工時表由精靈建立，這裡不處理）
        self.write({
            'active': False,
            'done_date': fields.Datetime.now(),
            'feedback': feedback,
        })

        # 發送 bus 通知（使用 Odoo 18 的 _bus_send）
        for activity in self:
            if activity.user_id and activity.date_deadline and activity.date_deadline <= fields.Date.today():
                activity.user_id._bus_send(
                    'mail.activity/updated',
                    {'activity_deleted': True, 'count_diff': -1}
                )

        return messages, next_activities

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
        """開啟來源訊息所在的頁面

        根據訊息來源類型，導航至不同位置：
        - discuss.channel: 開啟 Discuss 介面的對應頻道
        - 其他模型: 開啟文件表單（會自動捲動到 chatter）
        """
        self.ensure_one()
        if not self.source_message_id:
            raise UserError(_('This activity has no source message.'))

        msg = self.source_message_id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        # 處理 Discuss 頻道訊息
        if msg.model == 'discuss.channel' and msg.res_id:
            channel = self.env['discuss.channel'].browse(msg.res_id)
            if not channel.exists():
                raise UserError(_('Source channel no longer exists.'))

            # 確保當前用戶已加入頻道
            partner = self.env.user.partner_id
            if partner:
                member_partners = channel.channel_member_ids.mapped('partner_id')
                if partner not in member_partners:
                    try:
                        channel.add_members(partner_ids=[partner.id])
                    except AccessError:
                        raise UserError(_('Cannot join this channel, you may not have access rights.'))

            # 使用正確的 Odoo 18 Discuss URL 格式
            # /odoo/discuss?active_id=discuss.channel_{channel_id}
            return {
                'type': 'ir.actions.act_url',
                'url': f'{base_url}/odoo/discuss?active_id=discuss.channel_{msg.res_id}',
                'target': 'self',
            }

        # 處理文件 Chatter 訊息
        elif msg.model and msg.res_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': msg.model,
                'res_id': msg.res_id,
                'view_mode': 'form',
                'target': 'current',
                'context': {
                    'message_id': msg.id,  # 可用於前端定位訊息
                }
            }

        else:
            raise UserError(_('Cannot locate source message, message information is incomplete.'))

    def action_transfer_activity(self):
        """開啟轉移 wizard"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer Activity'),
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
            'name': _('Complete Activity'),
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
            'name': _('Postpone to Next Week'),
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
            if not activity.user_id:
                continue
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
    def _html_to_text(self, html_content, max_length=None):
        """將 HTML 轉為純文字（使用 odoo.tools.html2plaintext）"""
        if not html_content:
            return ''
        plain_text = html2plaintext(html_content).strip()
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
                note_name = self._html_to_text(note.memo, max_length=50)

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
                'name': note_name or _('Unnamed Note'),
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

        # 依星期幾分組，批次 write
        weekday_map = {
            0: 'monday', 1: 'tuesday', 2: 'wednesday',
            3: 'thursday', 4: 'friday', 5: 'saturday', 6: 'sunday'
        }
        groups = defaultdict(lambda: self.env['mail.activity'])
        for activity in activities:
            weekday = activity.scheduled_date.weekday()
            groups[weekday] |= activity

        ctx = {'skip_schedule_check': True}
        for weekday, group_activities in groups.items():
            # 同星期的待辦 planned_date 各不同，需逐日處理
            date_groups = defaultdict(lambda: self.env['mail.activity'])
            for act in group_activities:
                date_groups[act.scheduled_date] |= act

            for scheduled_date, acts in date_groups.items():
                acts.with_context(**ctx).write({
                    'planned_date': scheduled_date,
                    'schedule_status': weekday_map.get(weekday, 'waiting'),
                    'scheduled_date': False,
                })

        _logger.info('Weekly transition completed. Processed %d activities.', len(activities))

    @api.model
    def _cron_refresh_schedule_week(self):
        """每日重算 schedule_week / schedule_week_number（修正 stored compute 腐化）。

        這兩個欄位為 stored compute，計算依賴「今天」所在週次，但 ORM 只在
        planned_date / scheduled_date 變更時才重算 → 時間流逝會讓 stored 值腐化
        （例如「本週(0)」過一週後仍停在 0），導致 get_week_info()、週次篩選與
        分組讀到過期資料。此 cron 每日強制重算，確保週次永遠對齊當前日期。
        """
        activities = self.with_context(active_test=False).search([
            '|',
            ('planned_date', '!=', False),
            ('scheduled_date', '!=', False),
        ])
        if not activities:
            return

        # 強制標記 stored computed 欄位需重算（依賴 today，ORM 不會自動觸發）
        for field_name in ('schedule_week', 'schedule_week_number'):
            self.env.add_to_compute(self._fields[field_name], activities)
        activities.flush_recordset(['schedule_week', 'schedule_week_number'])

        _logger.info('Refreshed schedule_week for %d activities.', len(activities))

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
            raise UserError(_('This activity has already been assigned and cannot be claimed.'))

        self.with_context(allow_user_change=True).write({
            'user_id': self.env.user.id,
        })

        # 使用 message_post 記錄領取事件（避免直接串接 Html 欄位）
        self.message_post(
            body=_('%(user)s claimed this activity.', user=self.env.user.name),
            message_type='notification',
        )

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
            raise UserError(_('This activity has not been assigned, please use the claim function.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Change Assignment'),
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

        weekday_map = {
            0: 'monday', 1: 'tuesday', 2: 'wednesday',
            3: 'thursday', 4: 'friday', 5: 'saturday', 6: 'sunday',
        }

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
                # 上週或本週：設定 planned_date + schedule_status
                activity.with_context(skip_schedule_check=True).write({
                    'planned_date': target_date,
                    'schedule_status': weekday_map.get(original_weekday, 'monday'),
                    'scheduled_date': False,
                })
            else:
                # 未來週次：設定 scheduled_date
                activity.with_context(skip_schedule_check=True).write({
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
        """取得五週的日期資訊（供前端使用）：上週、本週、下週、第三週、第四週

        使用單次 read_group 查詢所有 5 週的統計資料，取代原本 5 次獨立查詢。
        """
        today = fields.Date.today()
        current_week_start = today - timedelta(days=today.weekday())

        weekday_keys = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

        # 直接從 selection 欄位取翻譯標籤，確保與欄位定義一致
        selection_labels = dict(self._fields['schedule_week']._description_selection(self.env))
        week_configs = [
            (-1, selection_labels.get('week_prev', 'Previous Week'), 'week_prev'),
            (0, selection_labels.get('week0', 'This Week'), 'week0'),
            (1, selection_labels.get('week1', 'Next Week'), 'week1'),
            (2, selection_labels.get('week2', 'Week 3'), 'week2'),
            (3, selection_labels.get('week3', 'Week 4'), 'week3'),
        ]

        # 單次查詢：以 schedule_week_number 分組統計所有 5 週的待辦數量和工時
        all_week_numbers = [wc[0] for wc in week_configs]
        activities_data = self.read_group(
            domain=[
                ('active', '=', True),
                ('user_id', '=', self.env.uid),
                ('schedule_week_number', 'in', all_week_numbers),
                ('schedule_status', '!=', 'waiting'),
            ],
            fields=['estimated_hours:sum'],
            groupby=['schedule_week_number'],
        )

        # 建立 week_number → {count, hours} 查找表
        week_stats = {}
        for group in activities_data:
            wn = group['schedule_week_number']
            week_stats[wn] = {
                'count': group['schedule_week_number_count'],
                'total_hours': group['estimated_hours'] or 0,
            }

        weeks = []
        for week_number, week_name, week_key in week_configs:
            week_start = current_week_start + timedelta(days=7 * week_number)
            week_end = week_start + timedelta(days=6)

            stats = week_stats.get(week_number, {'count': 0, 'total_hours': 0})

            dates = {}
            for day_index, day_key in enumerate(weekday_keys):
                day_date = week_start + timedelta(days=day_index)
                dates[day_key] = day_date.strftime('%Y-%m-%d')

            start_fmt = week_start.strftime('%Y/%m/%d')
            end_fmt = week_end.strftime('%Y/%m/%d')
            display_name = '%s[%d]%s-%s' % (
                week_name, stats['count'], start_fmt, end_fmt,
            )

            weeks.append({
                'number': week_number,
                'name': week_name,
                'display_name': display_name,
                'key': week_key,
                'start_date': week_start.strftime('%Y-%m-%d'),
                'end_date': week_end.strftime('%Y-%m-%d'),
                'count': stats['count'],
                'total_hours': stats['total_hours'],
                'dates': dates,
            })

        return weeks

    # ========== 相關待辦方法 ==========

    def action_create_related_activity(self):
        """建立同文件的新待辦"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Activity'),
            'res_model': 'mail.activity',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model_id': self.res_model_id.id,
                'default_res_id': self.res_id,
                # 預設排序為當前最大 sequence + 10
                'default_sequence': max(
                    self.related_activity_ids.mapped('sequence') or [0]
                ) + 10,
            },
        }

    def action_resequence_activities(self, activity_ids):
        """重新排序同文件的待辦

        Args:
            activity_ids: 按新順序排列的待辦 ID 列表
        """
        for index, activity_id in enumerate(activity_ids):
            self.browse(activity_id).write({'sequence': (index + 1) * 10})
