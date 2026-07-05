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
        required=False,  # 需求七：獨立待辦可無 res（與 res_model_id 一致）
    )

    # ===== 覆寫 res_model_id 為非必填（需求七：允許無關聯文件的獨立待辦）=====
    # 官方為 required=True(NOT NULL) + SQL CHECK(res_id NOT NULL)，本模組原以
    # 「預設筆記本」規避。需求七移除該規避，改為讓 res 真正可空。
    res_model_id = fields.Many2one(
        'ir.model',
        'Document Model',
        index=True,
        ondelete='cascade',
        required=False,  # 官方為 True
    )

    # 中和官方 SQL 約束 check_res_id_is_set（同名覆寫為恆真）；殘留於 DB 的
    # 舊約束由 migration 18.0.1.6.0 DROP。
    _sql_constraints = [
        ('check_res_id_is_set', 'CHECK(1=1)',
         'Standalone activities may have no related document (res_id is optional).'),
    ]

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

    # ===== 來源參考（需求四：note_id 顯示為「來源參考 / Source Reference」）=====
    note_id = fields.Many2one(
        'note.note',
        string='Source Reference',
        index=True,
        ondelete='set null',
        help='Source note referenced by this activity',
    )

    # 需求四：核心 note（HTML）欄位顯示為「待辦註記 / Todo Note」
    note = fields.Html(string='Todo Note')

    # ===== res_name 儲存計算結果以提升效能 =====
    res_name = fields.Char(
        string='Document Name',
        compute='_compute_res_name',
        compute_sudo=True,
        store=True,
        help='Display name of the related document',
    )

    # ===== 即時關聯文件顯示（模型名稱 / 來源記錄目前名稱）=====
    # 刻意「非 stored」：每次讀取即時計算，永遠反映來源記錄目前的 display_name，
    # 不像 res_name（stored 快照）會在來源改名後 stale。用於視圖顯示，取代 res_name。
    res_document_display = fields.Char(
        string='Related Document',
        compute='_compute_res_document_display',
        compute_sudo=True,
        help='Live "<model label> / <current record name>"; not stored, so it '
             'always reflects the source record current name (unlike res_name).',
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

    # ===== 工時表整合（原 dobtor_mail_activity_timesheet 併入）=====
    # 本模組硬相依 hr_timesheet，actual_hours 改為由關聯工時表記錄
    # （timesheet_ids）自動加總；工時表記錄由完成精靈依「啟用工時記錄」
    # 開關建立（見 res.company.dobtor_activity_timesheet_enabled）。
    timesheet_ids = fields.One2many(
        'account.analytic.line',
        'activity_id',
        string='Timesheet Entries',
    )
    actual_hours = fields.Float(
        string='Actual Hours',
        compute='_compute_actual_hours',
        store=True,
        readonly=True,
        help='Total of all logged hours (from linked timesheet entries).',
    )

    # 非儲存：供表單 Timesheet 分頁 invisible 綁定（需求九功能開關）。
    timesheet_feature_enabled = fields.Boolean(
        string='Timesheet Feature Enabled',
        compute='_compute_timesheet_feature_enabled',
    )

    feedback = fields.Text(
        string='Completion Feedback',
    )

    # ===== 欄位層級編輯權限（依當前使用者與待辦的關係，非儲存）=====
    # 供表單以 readonly 綁定：建立者可編輯類型/急迫/重要/截止日，被指派者可編輯
    # 預估工時；相關文件/筆記兩者皆可。系統管理員與新記錄一律視為可編輯。
    can_edit_as_creator = fields.Boolean(
        string='Editable by Creator',
        compute='_compute_edit_roles',
    )
    can_edit_as_assignee = fields.Boolean(
        string='Editable by Assignee',
        compute='_compute_edit_roles',
    )

    # ===== 關聯顯示（設定驅動，不綁定特定模組）=====
    # partner_id 由 mail.activity.transfer.config 指定的 partner 欄位
    #（或自動探測模型上的 'partner_id'）派生；「關聯文件」顯示沿用既有的
    # res_name（= 來源文件 display_name），同樣不認得任何具體模組。
    # partner_id：可手填（需求五）。不再是純 compute —— 改由 helper
    # _derive_partner_from_source() 於 res/project onchange 與 create 時派生：
    # res 記錄的 partner_field → 專案客戶 → 否則留空/手填（手填不被覆寫）。
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        index=True,
        store=True,
    )

    # ===== 專案關聯（需求二/三/五/六共用；設定驅動 FK）=====
    # 可空、可手填。與 res 雙向 onchange（見 _onchange_*）：選 project 後可用
    # 邏輯圖挑 res；直接選 res 亦反推 project。
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        index=True,
        help='Related project. Used for the relation diagram, customer '
             'fallback and grouped report.',
    )

    # 承載關聯邏輯圖 widget 的錨點欄位（非儲存、無資料意義；widget 讀取整筆記錄）
    relation_diagram_anchor = fields.Boolean(
        string='Relation Diagram',
        compute='_compute_relation_diagram_anchor',
    )

    def _compute_relation_diagram_anchor(self):
        for activity in self:
            activity.relation_diagram_anchor = False

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

    @api.depends('res_model', 'res_id', 'res_model_id')
    def _compute_res_document_display(self):
        """即時計算「模型名稱 / 來源記錄目前名稱」（非 stored，永遠最新）。"""
        for activity in self:
            if not activity.res_model or not activity.res_id:
                activity.res_document_display = False
                continue
            try:
                record = self.env[activity.res_model].browse(activity.res_id)
                if not record.exists():
                    activity.res_document_display = _('(Record Deleted)')
                    continue
                model_label = activity.res_model_id.name \
                    or self.env['ir.model']._get(activity.res_model).name \
                    or activity.res_model
                activity.res_document_display = '%s / %s' % (
                    model_label, record.display_name)
            except Exception as e:
                _logger.debug(
                    'Failed to compute res_document_display for activity %s: %s',
                    activity.id, str(e))
                activity.res_document_display = False

    @api.model
    def _cron_refresh_res_name(self, batch_limit=5000):
        """定期強制重算 stored res_name，讓來源記錄改名後群組標題能跟上。

        res_name 是 stored 快照，@api.depends('res_model','res_id') 不會因「來源記錄
        改名」而重算（多型參考無法穿透）。報告以 res_name 當群組標題，故以本 cron
        週期性重算，使標題保持新鮮（非即時，取決於 cron 週期）。僅處理仍 active 且
        有關聯文件的待辦，控制成本。
        """
        activities = self.search([
            ('active', '=', True),
            ('res_model', '!=', False),
            ('res_id', '!=', False),
        ], limit=batch_limit)
        if not activities:
            return
        # 清快取後直接重算 compute（賦值 stored 欄位 → flush 落地）
        activities.invalidate_recordset(['res_name'])
        activities._compute_res_name()
        activities.flush_recordset(['res_name'])
        _logger.info('Cron: refreshed res_name for %s activities.', len(activities))

    @api.model
    def _selection_target_model(self):
        """取得允許的目標模型選項（使用共用方法）"""
        return self.env['mail.activity.transfer.config'].get_target_model_selection()

    @api.model
    def get_editor_default_note_id(self):
        """需求七：已移除「預設筆記本」設計 —— 不再有個人待辦筆記。

        富文字編輯器內嵌清單/時鐘在「無對應記錄」情境下不再退回預設筆記；
        呼叫端（activity_clock_toolbar.js）對 False 有優雅退化（顯示空）。
        """
        return False

    @api.model
    def _editor_activity_domain(self, bind, res_model=False, res_id=False, note_id=False):
        """編輯器內嵌清單/時鐘共用的綁定 domain。

        :param bind: 'note' 綁 note_id、'res' 綁 res_model/res_id、其他綁個人筆記
        """
        if bind == 'note' and note_id:
            note_id = int(note_id)
            # note.note 編輯器：除了 res 指向本筆記，也以 note_id 關聯顯示
            # （即使活動 res 指向其他文件，只要 note_id 是本筆記也納入）。
            return [
                '|',
                '&', ('res_model', '=', 'note.note'), ('res_id', '=', note_id),
                ('note_id', '=', note_id),
            ]
        if bind == 'res' and res_model and res_id:
            return [('res_model', '=', res_model), ('res_id', '=', int(res_id))]
        # 需求七：無預設筆記 —— 退回「目前使用者的獨立待辦（無關聯文件）」
        return [('user_id', '=', self.env.uid), ('res_model', '=', False)]

    @api.model
    def get_editor_activities(self, bind, res_model=False, res_id=False, note_id=False, limit=0):
        """供富文字編輯器內嵌清單即時抓取活動（含已封存的完成/取消以便顯示歷史）。

        :param limit: 0 表示不限；>0 時多取 1 筆以判斷是否還有更多
        :return: {'activities': list[dict], 'has_more': bool}
        """
        domain = self._editor_activity_domain(bind, res_model, res_id, note_id)
        fetch = (limit + 1) if limit else None
        activities = self.with_context(active_test=False).search(
            domain, order='active desc, date_deadline asc, id asc', limit=fetch)
        has_more = bool(limit) and len(activities) > limit
        if limit:
            activities = activities[:limit]
        result = []
        for act in activities:
            result.append({
                'id': act.id,
                'summary': act.summary or (act.activity_type_id.name or ''),
                'date_deadline': act.date_deadline and str(act.date_deadline) or False,
                'state': act.state or 'planned',
                'activity_status': act.activity_status,
                'active': act.active,
                'user_id': act.user_id.id,
                'user_name': act.user_id.name or '',
                # 即時「模型 / 記錄名」（取代 stored 快照 res_name，避免傳出 stale 值）
                'res_name': act.res_document_display or '',
                'activity_type_name': act.activity_type_id.name or '',
            })
        return {'activities': result, 'has_more': has_more}

    @api.model
    def get_editor_activity_summary(self, bind, res_model=False, res_id=False, note_id=False):
        """供工具列時鐘輕量查詢：只回進行中活動的 ids 與最嚴重狀態（不組完整 dict）。

        :return: {'ids': list[int], 'worst': 'overdue'|'today'|'planned'|'none'}
        """
        domain = self._editor_activity_domain(bind, res_model, res_id, note_id)
        domain = [('active', '=', True)] + domain
        activities = self.search(domain, order='date_deadline asc, id asc')
        states = set(activities.mapped('state'))
        if 'overdue' in states:
            worst = 'overdue'
        elif 'today' in states:
            worst = 'today'
        elif activities:
            worst = 'planned'
        else:
            worst = 'none'
        return {'ids': activities.ids, 'worst': worst}

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

        需求七：target_ref 為空時，res 真正清空（不再回填預設筆記）。
        """
        for activity in self:
            if activity.target_ref:
                model_name = activity.target_ref._name
                # res_model 是 related 欄位（readonly），只設定 res_model_id 和 res_id
                activity.res_model_id = self.env['ir.model']._get(model_name)
                activity.res_id = activity.target_ref.id
            else:
                # 獨立待辦：res 清空
                activity.res_model_id = False
                activity.res_id = False

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
        # 需求七：不在 onchange 中自動設定預設筆記；清空即為獨立待辦

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """覆寫官方存取過濾，支援 res 為空的獨立待辦（需求七）。

        官方 mail.activity._search（mail/models/mail_activity.py）對
        user_id != uid 的列會 self.env[res_model].browse(...) 做文件存取檢查，
        res_model 為空時會 KeyError（未指派視圖 user_id=False 會踩到）。

        本覆寫直接以 models.Model._search 取基礎查詢（繞過官方 _search 的
        存取過濾，避免遞迴與崩潰），再套用修正版過濾：res 為空的列一律放行
        （無文件可據以 gate），其餘沿用官方之文件存取檢查。
        """
        # 系統匣待辦分組（res.users._get_activity_groups）以此旗標排除獨立待辦：
        # 核心 mail 版會對每筆待辦 self.env[res_model].browse(...)，res_model 為空
        # 時 self.env[False] → KeyError。獨立待辦改由該覆寫另行併入「其他活動」。
        if self.env.context.get('activity_systray_skip_standalone'):
            domain = domain + [('res_model', '!=', False)]

        # 系統管理員略過額外過濾
        if self.env.is_superuser():
            return models.Model._search(self, domain, offset, limit, order)

        query = models.Model._search(self, domain, offset, limit, order)
        fnames_to_read = ['id', 'res_model', 'res_id', 'user_id']
        rows = self.env.execute_query(query.select(
            *[self._field_to_sql(self._table, fname) for fname in fnames_to_read],
        ))

        # 依模型分組需檢查存取的 res（跳過 res 為空者）
        model_ids = defaultdict(set)
        for __, res_model, res_id, user_id in rows:
            if user_id != self.env.uid and res_model:
                model_ids[res_model].add(res_id)

        allowed_ids = defaultdict(set)
        for res_model, res_ids in model_ids.items():
            records = self.env[res_model].browse(res_ids).exists()
            operation = getattr(records, '_mail_post_access', 'read')
            allowed_ids[res_model] = set(records._filtered_access(operation)._ids)

        activities = self.browse(
            id_
            for id_, res_model, res_id, user_id in rows
            # 自己的待辦、或無關聯文件的獨立待辦、或文件可存取者
            if user_id == self.env.uid or not res_model or res_id in allowed_ids[res_model]
        )
        return activities._as_query(order)

    def _check_access(self, operation):
        """支援 res 為空的獨立待辦（需求七）之存取檢查。

        官方 mail.activity._check_access（mail/models/mail_activity.py）依 res_model
        分組後 self.env[doc_model].browse(...) 做文件層存取 gating，res_model 為空時
        self.env[False] → KeyError（讀取獨立待辦即踩到）。

        獨立待辦無關聯文件，無從以文件 gate，應只受基礎存取規則（ir.rule /
        ir.model.access，即 models.Model._check_access）約束。故將獨立待辦自官方
        文件 gating 拆出：有關聯文件者沿用官方鏈，獨立待辦僅跑基礎檢查，最後合併
        兩者的 forbidden 記錄。
        """
        standalone = self.filtered(lambda a: not a.res_model)
        if not standalone:
            return super()._check_access(operation)

        combined_forbidden = self.browse()
        linked = self - standalone
        if linked:
            # 重新進入本方法（此時 standalone 為空）→ 走官方鏈含文件 gating
            linked_result = linked._check_access(operation)
            if linked_result:
                combined_forbidden |= linked_result[0]
        # 獨立待辦：略過官方文件 gating，只用基礎存取檢查
        standalone_result = models.Model._check_access(standalone, operation)
        if standalone_result:
            combined_forbidden |= standalone_result[0]

        if not combined_forbidden:
            return None
        return (
            combined_forbidden,
            lambda: combined_forbidden._make_access_error(operation),
        )

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

            # 需求七：不再自動關聯預設筆記；res 允許為空（獨立待辦）。

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

            # 通知被指派人（僅指派給他人時，與原生邏輯一致）；
            # mail_activity_quick_update context 下不寄信/推播（與 base create 一致）。
            if self.env.context.get('mail_activity_quick_update'):
                activities_to_notify = self.env['mail.activity']
            else:
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

            # systray 計數 bus 通知：僅對「已到期的待辦」按使用者分組送出，
            # 並帶 count_diff（與 base create 一致，避免 systray 計數不同步）。
            todo_activities = activities.filtered(
                lambda act: act.user_id and act.active and act.date_deadline
                and act.date_deadline <= fields.Date.context_today(act)
            )
            for user, user_activities in todo_activities.grouped('user_id').items():
                try:
                    user._bus_send(
                        'mail.activity/updated',
                        {'activity_created': True, 'count_diff': len(user_activities)},
                    )
                except Exception as e:
                    _logger.debug('Bus notification failed: %s', str(e))

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

        # 需求五：未帶客戶者，依來源（res → 專案客戶）派生（不覆寫已帶入者）
        activities.filtered(lambda a: not a.partner_id)._derive_partner_from_source()

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

    def _derive_partner_from_source(self, force=False):
        """設定驅動派生關聯客戶（需求五，不綁定特定模組）。

        來源優先序（每筆待辦）：
        1. res 記錄的 partner 欄位（transfer.config.partner_field，或自動探測
           res 模型上的 'partner_id'）
        2. 待辦 project_id 的客戶（project.partner_id）—— 需求五「以專案客戶帶入」
        3. 皆無 → 不動（保留手填/留空）

        預設只在「partner 尚未設定」時填入（force=False），以免覆寫手填值；
        force=True 時（來源明確變更）一律以派生值覆寫。
        """
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()

        # 依 res 模型分組批次讀取（僅存在的模型）
        model_groups = defaultdict(list)
        for activity in self:
            if activity.res_model and activity.res_id and activity.res_model in self.env:
                model_groups[activity.res_model].append(activity)

        # 先算出每筆的 res-partner 候選
        res_partner = {}
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
                    # partner_field 若被誤設為非關聯欄位（如 Char），partner[:1].id
                    # 會 AttributeError；一併包進 try 防呆（設定驅動功能）。
                    res_partner[activity.id] = partner[:1].id if partner else False
                except Exception as e:
                    _logger.debug('Failed to read partner field %s on %s: %s',
                                  partner_field, model_name, str(e))
                    continue

        # 依 candidate 分組後批次 write（同 partner 一次寫），避免逐筆 N 次 write
        to_write = defaultdict(lambda: self.env['mail.activity'])
        for activity in self:
            candidate = res_partner.get(activity.id) or activity.project_id.partner_id.id
            if candidate and (force or not activity.partner_id):
                to_write[candidate] |= activity
        for candidate, activities in to_write.items():
            activities.partner_id = candidate

    def _project_from_res(self, res_model, res_id):
        """依 transfer.config.project_field 由 res 記錄反推 project（需求三）。

        res 為 project.project 本身 → 回傳自身；否則讀該模型的 project_field。
        回傳 project.project 記錄集（可能為空）。
        """
        Project = self.env['project.project']
        if not res_model or not res_id or res_model not in self.env:
            return Project
        if res_model == 'project.project':
            return Project.browse(res_id).exists()
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()
        project_field = relation_map.get(res_model, {}).get('project_field')
        Model = self.env[res_model]
        if not project_field or project_field not in Model._fields:
            return Project
        record = Model.browse(res_id).exists()
        if not record:
            return Project
        try:
            return record[project_field][:1]
        except Exception:
            return Project

    @api.model
    def _partner_from_res(self, res_model, res_id):
        """由 res 記錄反推 partner id（唯讀，供關聯圖「客戶為根」fallback）。

        依 transfer.config.partner_field，或自動探測 res 模型的 'partner_id'。
        與 _derive_partner_from_source 的 res-partner 候選邏輯一致，但不寫入。
        回傳 partner id 或 False。
        """
        if not res_model or not res_id or res_model not in self.env:
            return False
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()
        partner_field = relation_map.get(res_model, {}).get('partner_field')
        Model = self.env[res_model]
        if not partner_field and 'partner_id' in Model._fields:
            partner_field = 'partner_id'
        if not partner_field or partner_field not in Model._fields:
            return False
        record = Model.browse(res_id).exists()
        if not record:
            return False
        try:
            partner = record[partner_field]
        except Exception:
            return False
        return partner[:1].id if partner else False

    @api.onchange('res_model_id', 'res_id')
    def _onchange_res_fill_project_partner(self):
        """需求三/五：選定 res 後，反推專案並派生客戶。

        - project_id 空時由 res 反推帶入（force 專案，因 res 明確變更）
        - partner 依 _derive_partner_from_source（res 客戶 > 專案客戶）
        """
        for activity in self:
            if activity.res_model and activity.res_id:
                if not activity.project_id:
                    project = activity._project_from_res(activity.res_model, activity.res_id)
                    if project:
                        activity.project_id = project.id
                activity._derive_partner_from_source(force=True)

    @api.onchange('project_id')
    def _onchange_project_fill_partner(self):
        """需求五：選定/變更專案後，若客戶尚未設定則以專案客戶帶入。"""
        for activity in self:
            if activity.project_id and not activity.partner_id:
                activity._derive_partner_from_source(force=False)

    # ========== 關聯邏輯圖（需求二/三/五）==========

    _RELATION_TREE_LIMIT = 100  # 每模型節點上限，避免樹過大

    @api.model
    def get_relation_tree(self, project_id=False, partner_id=False,
                          res_model=False, res_id=False):
        """回傳向右邏輯圖的 node_tree（需求二/三/五）。

        以「直接外鍵(FK)為軸」（使用者選擇）：
        - 有 project（或由 res 反推得到）→ 以專案為根，依 transfer.config
          的 project_field 展開各模型（CRM/任務/…）中屬於該專案的紀錄。
        - 否則有 partner → 以客戶為根，依 partner_field 展開各模型中屬於
          該客戶的紀錄（需求五：依客戶縮小 res 選擇範圍）。
        - 皆無 → 空樹。

        節點 data 帶 {res_model, res_id}，供前端點擊回填 res。
        """
        Project = self.env['project.project']
        project = Project.browse(project_id).exists() if project_id else Project
        if not project and res_model and res_id:
            project = self._project_from_res(res_model, res_id)

        # 方案 C：無專案且前端未傳 partner 時，由 res(如 crm.lead)反推客戶，
        # 確保「CRM 尚未建專案但有客戶」仍能顯示客戶為根的關聯樹。
        if not project and not partner_id and res_model and res_id:
            partner_id = self._partner_from_res(res_model, res_id)

        if project:
            root = {
                'id': 'project_%s' % project.id,
                'topic': project.display_name,
                'expanded': True,
                'data': {'res_model': 'project.project', 'res_id': project.id},
                'children': self._project_scoped_children(project),
            }
        elif partner_id:
            partner = self.env['res.partner'].browse(partner_id).exists()
            if not partner:
                return self._empty_tree()
            root = {
                'id': 'partner_%s' % partner.id,
                'topic': partner.display_name,
                'expanded': True,
                'data': {'res_model': 'res.partner', 'res_id': partner.id},
                'children': self._partner_scoped_children(partner),
            }
        else:
            return self._empty_tree()

        return {
            'meta': {'name': 'activity_relation', 'version': '1.0'},
            'format': 'node_tree',
            'data': root,
        }

    @api.model
    def _empty_tree(self):
        return {
            'meta': {'name': 'activity_relation', 'version': '1.0'},
            'format': 'node_tree',
            'data': {'id': 'empty', 'topic': _('No related records'),
                     'expanded': True, 'data': {}, 'children': []},
        }

    @api.model
    def _relation_group_node(self, node_id, model_label, leaves, truncated):
        """模型分組節點（不帶 res，不可回填），內含葉節點。"""
        return {
            'id': node_id,
            'topic': '%s (%s%s)' % (model_label, len(leaves), '+' if truncated else ''),
            'expanded': True,
            'data': {},
            'children': leaves,
        }

    @api.model
    def _record_leaf(self, model_name, rec, todos_by_res, extra_children=None):
        """單筆記錄葉節點（帶 {res_model,res_id} 可回填）。
        結構子節點（如子任務）為圖上的子節點（往右）；未完成待辦不再是節點，
        改以 data.todos 掛在本節點，前端在節點內以 level-down/up 鈕垂直下拉呈現。
        """
        children = list(extra_children or [])
        return {
            'id': '%s_%s' % (model_name, rec.id),
            'topic': rec.display_name,
            'expanded': True,
            'data': {
                'res_model': model_name,
                'res_id': rec.id,
                'todos': todos_by_res.get(rec.id, []),
            },
            'children': children,
        }

    @api.model
    def _task_forest_nodes(self, tasks, acts_by_res):
        """把 project.task 記錄依 parent_id 建成森林（需求：子任務放上層任務下）。
        僅在給定集合內巢狀；上層任務不在集合者，該任務視為頂層。
        回傳頂層任務節點清單。
        """
        task_ids = set(tasks.ids)
        by_parent = defaultdict(list)
        tops = []
        for t in tasks:
            parent = t.parent_id
            if parent and parent.id in task_ids:
                by_parent[parent.id].append(t)
            else:
                tops.append(t)

        # 全部互為子代（資料成環，project.task 有祖先約束理論上不會發生）時
        # tops 為空 → 全列為頂層保底，避免整組任務被靜默丟棄
        if not tops and tasks:
            tops = list(tasks)

        def build(task, seen):
            if task.id in seen:
                return None  # 防環：無窮遞迴保護
            seen = seen | {task.id}
            sub_nodes = [n for n in (build(s, seen) for s in by_parent.get(task.id, [])) if n]
            return self._record_leaf('project.task', task, acts_by_res,
                                     extra_children=sub_nodes)

        return [n for n in (build(t, frozenset()) for t in tops) if n]

    @api.model
    def _model_leaves(self, model_name, records, acts_by_res):
        """依模型產生葉節點清單：task 走森林巢狀，其餘為平列。"""
        if model_name == 'project.task':
            return self._task_forest_nodes(records, acts_by_res)
        return [self._record_leaf(model_name, r, acts_by_res) for r in records]

    @api.model
    def _project_scoped_children(self, project):
        """專案為根：各設定模型中 project_field==project 的紀錄。
        任務依 parent_id 巢狀；每模型一個群組節點。
        """
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()
        children = []
        for model_name, cfg in relation_map.items():
            if model_name not in self.env:
                continue
            fk_field = cfg.get('project_field')
            Model = self.env[model_name]
            if not fk_field or fk_field not in Model._fields:
                continue
            try:
                records = Model.search(
                    [(fk_field, '=', project.id)], limit=self._RELATION_TREE_LIMIT + 1)
            except Exception as e:
                _logger.debug('relation tree search failed on %s.%s: %s',
                              model_name, fk_field, str(e))
                continue
            if not records:
                continue
            truncated = len(records) > self._RELATION_TREE_LIMIT
            records = records[:self._RELATION_TREE_LIMIT]
            acts = self._incomplete_activities_by_res(model_name, records.ids)
            leaves = self._model_leaves(model_name, records, acts)
            model_label = self.env['ir.model']._get(model_name).name or model_name
            children.append(self._relation_group_node(
                'group_project_%s' % model_name, model_label, leaves, truncated))
        return children

    @api.model
    def _partner_scoped_children(self, partner):
        """客戶為根（需求五 + 巢狀）：
        - 有專案 FK 的模型（商機/任務/銷售訂單…）依其 project_id 歸入專案節點下；
          無專案者集中在「未歸專案」的模型群組。
        - 任務再依 parent_id 巢狀。
        - 無專案 FK 的模型（採購單/會計傳票/服務單…）維持平列模型群組。
        - project.project 本身作為巢狀節點，不另列平列群組。
        """
        relation_map = self.env['mail.activity.transfer.config']._get_relation_map()
        # 分類設定模型
        project_fk_models = {}   # model -> project_field
        flat_models = []         # 無 project_field、但可依 partner 過濾的模型
        for model_name, cfg in relation_map.items():
            if model_name not in self.env:
                continue
            if model_name == 'project.project':
                continue  # 專案本身作為節點，稍後處理
            Model = self.env[model_name]
            partner_field = cfg.get('partner_field') or (
                'partner_id' if 'partner_id' in Model._fields else False)
            if not partner_field or partner_field not in Model._fields:
                continue
            proj_field = cfg.get('project_field')
            if proj_field and proj_field in Model._fields:
                project_fk_models[model_name] = (proj_field, partner_field)
            else:
                flat_models.append((model_name, partner_field))

        # 有專案 FK 的模型：查客戶紀錄，依 project_id 分桶
        by_project = {}    # (proj_id, model_name) -> recordset（同模型才 union）
        noproject = {}     # model_name -> recordset
        acts_maps = {}
        referenced_project_ids = set()
        for model_name, (proj_field, partner_field) in project_fk_models.items():
            Model = self.env[model_name]
            try:
                records = Model.search(
                    [(partner_field, '=', partner.id)], limit=self._RELATION_TREE_LIMIT + 1)
            except Exception as e:
                _logger.debug('relation tree search failed on %s: %s', model_name, str(e))
                continue
            if not records:
                continue
            records = records[:self._RELATION_TREE_LIMIT]
            acts_maps[model_name] = self._incomplete_activities_by_res(model_name, records.ids)
            for rec in records:
                proj = rec[proj_field][:1]
                if proj:
                    referenced_project_ids.add(proj.id)
                    key = (proj.id, model_name)
                    by_project[key] = by_project.get(key, Model.browse()) | rec
                else:
                    noproject[model_name] = noproject.get(model_name, Model.browse()) | rec

        children = []

        # 專案節點：客戶自己的專案 ∪ 被紀錄引用到的專案
        Project = self.env['project.project']
        own_projects = Project.search(
            [('partner_id', '=', partner.id)], limit=self._RELATION_TREE_LIMIT + 1)
        project_ids = list(dict.fromkeys(own_projects.ids + list(referenced_project_ids)))
        project_acts = self._incomplete_activities_by_res('project.project', project_ids)
        for proj in Project.browse(project_ids).exists():
            subgroups = []
            for model_name in project_fk_models:
                recs = by_project.get((proj.id, model_name))
                if not recs:
                    continue
                leaves = self._model_leaves(model_name, recs, acts_maps.get(model_name, {}))
                model_label = self.env['ir.model']._get(model_name).name or model_name
                subgroups.append(self._relation_group_node(
                    'group_proj_%s_%s' % (proj.id, model_name), model_label, leaves, False))
            # 專案節點本身也是可回填的 res，且掛自身未完成待辦
            children.append(self._record_leaf(
                'project.project', proj, project_acts, extra_children=subgroups))

        # 無專案的紀錄：集中為「未歸專案」模型群組
        for model_name in project_fk_models:
            recs = noproject.get(model_name)
            if not recs:
                continue
            leaves = self._model_leaves(model_name, recs, acts_maps.get(model_name, {}))
            model_label = self.env['ir.model']._get(model_name).name or model_name
            children.append(self._relation_group_node(
                'group_noproj_%s' % model_name,
                _('%s (no project)') % model_label, leaves, False))

        # 無專案 FK 的模型：平列模型群組
        for model_name, partner_field in flat_models:
            Model = self.env[model_name]
            try:
                records = Model.search(
                    [(partner_field, '=', partner.id)], limit=self._RELATION_TREE_LIMIT + 1)
            except Exception as e:
                _logger.debug('relation tree search failed on %s: %s', model_name, str(e))
                continue
            if not records:
                continue
            truncated = len(records) > self._RELATION_TREE_LIMIT
            records = records[:self._RELATION_TREE_LIMIT]
            acts = self._incomplete_activities_by_res(model_name, records.ids)
            leaves = self._model_leaves(model_name, records, acts)
            model_label = self.env['ir.model']._get(model_name).name or model_name
            children.append(self._relation_group_node(
                'group_partner_%s' % model_name, model_label, leaves, truncated))

        return children

    @api.model
    def _incomplete_activities_by_res(self, model_name, res_ids):
        """批次查某模型多筆記錄底下「尚未完成」的 mail.activity，回傳
        {res_id: [待辦 dict,...]}（供關聯圖記錄節點內的下拉待辦清單）。

        未完成 = active=True 且未完成(done)、未取消(cancel)。單一查詢避免 N+1。
        待辦 dict：{activity_id, label, deadline(字串), severity('over'/'soon'/'ok')}。
        severity 依截止日相對今日（本地時區）：逾期 over、3 日內 soon、其餘 ok。
        """
        if not res_ids:
            return {}
        activities = self.with_context(active_test=False).search([
            ('res_model', '=', model_name),
            ('res_id', 'in', res_ids),
            ('active', '=', True),
            ('done_date', '=', False),
            ('cancel_date', '=', False),
        ], order='date_deadline asc, id asc', limit=self._RELATION_TREE_LIMIT + 1)
        today = fields.Date.context_today(self)
        soon_limit = today + timedelta(days=3)
        result = {}
        for act in activities:
            label = act.summary or act.activity_type_id.display_name or _('To-do')
            dl = act.date_deadline
            severity = 'ok'
            if dl:
                if dl < today:
                    severity = 'over'
                elif dl <= soon_limit:
                    severity = 'soon'
            result.setdefault(act.res_id, []).append({
                'activity_id': act.id,
                'label': label,
                'deadline': fields.Date.to_string(dl) if dl else '',
                'severity': severity,
            })
        return result

    @api.depends('timesheet_ids', 'timesheet_ids.unit_amount')
    def _compute_actual_hours(self):
        """執行工時 = 所有登錄工時的總合（原 timesheet 橋接併入）。"""
        for activity in self:
            activity.actual_hours = sum(
                activity.timesheet_ids.mapped('unit_amount')
            )

    def _compute_timesheet_feature_enabled(self):
        """公司層「啟用工時記錄」開關（需求九功能開關，非儲存）。"""
        enabled = self.env.company.dobtor_activity_timesheet_enabled
        for activity in self:
            activity.timesheet_feature_enabled = enabled

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

    @api.depends('create_uid', 'user_id')
    def _compute_edit_roles(self):
        """計算當前使用者對此待辦的編輯角色（建立者 / 被指派者）。

        非儲存計算，每次讀取以當前 env.user 求值。系統管理員與尚未建立的
        新記錄一律視為可編輯，避免擋住管理與建立流程。
        """
        uid = self.env.uid
        is_admin = self.env.user.has_group('base.group_system')
        for activity in self:
            is_new = not activity.id
            activity.can_edit_as_creator = (
                is_new or is_admin or activity.create_uid.id == uid
            )
            activity.can_edit_as_assignee = (
                is_new or is_admin
                or (bool(activity.user_id) and activity.user_id.id == uid)
            )

    # ========== Override Methods ==========

    def write(self, vals):
        """覆寫 write 方法以記錄指派變更"""
        # 驗證：欄位層級編輯權限（建立者 vs 被指派者）。
        # 建立者可改：類型/急迫/重要（截止日另有專屬守衛）；
        # 被指派者可改：預估工時；相關文件/筆記兩者皆可。
        # 豁免：su、系統管理員、轉移作業（帶 transferred_from_model）。
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            creator_only = {'urgency', 'importance', 'activity_type_id'}
            assignee_only = {'estimated_hours'}
            # target_ref（computed Reference，inverse 寫 res_model_id/res_id）一併納入
            related_fields = {'res_model_id', 'res_id', 'note_id', 'target_ref'}
            guarded = creator_only | assignee_only | related_fields
            is_transfer = 'transferred_from_model' in vals
            uid = self.env.uid
            for activity in self:
                if not activity.id:
                    continue
                # 只在「值真的改變」時套限制，避免整筆 vals（API/copy/部分 wizard
                # 送未變更欄位）誤觸 UserError
                changed = set()
                for f in guarded:
                    if f not in vals:
                        continue
                    cur = activity[f]
                    newv = vals[f]
                    if f == 'target_ref':
                        # Reference 欄位：activity[f] 回傳 recordset，vals[f] 是
                        # 'model,id' 字串。需還原成同格式再比，否則恆判定為已變更。
                        cur = ('%s,%s' % (cur._name, cur.id)) if cur else False
                        newv = newv or False
                    elif isinstance(cur, models.BaseModel):
                        cur = cur.id or False
                        newv = newv or False
                    if cur != newv:
                        changed.add(f)
                if not changed:
                    continue
                is_creator = activity.create_uid.id == uid
                is_assignee = bool(activity.user_id) and activity.user_id.id == uid
                if (creator_only & changed) and not is_creator:
                    raise UserError(_(
                        'Only the creator can edit the activity type, urgency or importance.'
                    ))
                # 僅在「有指派對象」時才限定被指派者；未指派（需求七獨立/未領取
                # 待辦）時放行，否則預估工時將無人可改。
                if (assignee_only & changed) and activity.user_id and not is_assignee:
                    raise UserError(_(
                        'Only the assignee can edit the estimated hours.'
                    ))
                if (related_fields & changed) and not is_transfer \
                        and not (is_creator or is_assignee):
                    raise UserError(_(
                        'Only the creator or assignee can change the related document or note.'
                    ))

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

        # 驗證：planned_date 直接寫入（無 schedule_status）的新規則
        #   - 空值卡：可直接挑日期 → 放行，並由日期反推 schedule_status（擋過去）。
        #   - 有值卡：禁止直接改日期 → 只能同週換天（拖曳/狀態列）或延期清空。
        if 'planned_date' in vals and 'schedule_status' not in vals:
            new_planned = vals.get('planned_date')
            is_internal = self.env.context.get('skip_schedule_check', False)
            if new_planned and not is_internal and not self.env.su:
                # 有值卡不可直接改日期
                for activity in self:
                    if activity.planned_date:
                        raise UserError(_(
                            'Planned date cannot be changed directly once set.\n'
                            'Use same-week drag-and-drop or the schedule bar to change the '
                            'day, or use "Postpone" to clear it first.'
                        ))
                # 擋過去：直接挑的日期不可早於今天
                new_planned_date = fields.Date.to_date(new_planned)
                if new_planned_date < fields.Date.today():
                    raise UserError(_('Planned date cannot be earlier than today.'))
                # 空值首次設定：由日期星期幾反推 schedule_status
                weekday_status_map = {
                    0: 'monday', 1: 'tuesday', 2: 'wednesday', 3: 'thursday',
                    4: 'friday', 5: 'saturday', 6: 'sunday',
                }
                vals['schedule_status'] = weekday_status_map[new_planned_date.weekday()]
                if 'schedule_origin' not in vals:
                    vals['schedule_origin'] = 'inserted'

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

        # 記錄指派變更（批次建立，避免逐筆 create 的 N+1）
        if 'user_id' in vals:
            history_vals = [
                {
                    'activity_id': activity.id,
                    'previous_user_id': activity.user_id.id,
                    'new_user_id': vals.get('user_id'),
                }
                for activity in self
                if activity.user_id.id != vals.get('user_id')
            ]
            if history_vals:
                self.env['mail.activity.assignment.history'].sudo().create(history_vals)

        # 處理排程狀態變更時自動設定計畫日期和來源標記
        per_record_planned = None
        if 'schedule_status' in vals and vals['schedule_status'] != 'waiting':
            weekday_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2,
                'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
            }
            target_weekday = weekday_map.get(vals['schedule_status'])
            if target_weekday is not None and 'planned_date' not in vals:
                # 換天（無明確 planned_date）：逐筆推導日期
                #   - 有值卡：鎖該筆「自身週」內換天，不跨週。
                #   - 空值卡：依檢視 context（拖曳日期 / 當前週）放置。
                per_record_planned = {}
                for activity in self:
                    if activity.planned_date:
                        wk_start = activity.planned_date - timedelta(
                            days=activity.planned_date.weekday())
                        per_record_planned[activity.id] = \
                            wk_start + timedelta(days=target_weekday)
                    else:
                        per_record_planned[activity.id] = \
                            self._derive_planned_date_from_context(
                                vals['schedule_status'], target_weekday)

            # 如果來源尚未設定，標記為臨時插入（僅當所有記錄均無 origin 時）
            if 'schedule_origin' not in vals:
                if all(not act.schedule_origin for act in self):
                    vals['schedule_origin'] = 'inserted'

        # 寫入：若各筆推導出不同日期，逐筆寫入；否則單次寫入。
        if per_record_planned is not None:
            distinct_dates = set(per_record_planned.values())
            if len(distinct_dates) <= 1:
                if distinct_dates:
                    vals['planned_date'] = distinct_dates.pop()
                result = super().write(vals)
            else:
                result = True
                for activity in self:
                    rec_vals = dict(vals, planned_date=per_record_planned[activity.id])
                    result = super(MailActivity, activity).write(rec_vals)
        else:
            result = super().write(vals)

        # 維持不變式 planned_date <= date_deadline：逾期則順延截止日並留 log。
        self._enforce_deadline_invariant()

        return result

    def _derive_planned_date_from_context(self, status_key, target_weekday):
        """空值卡換天時，依前端檢視 context 推導計畫日期。

        優先採用拖曳帶入的當週日期對應表（schedule_week_dates）；否則依
        目前檢視週次（schedule_current_week）計算。「全部」檢視無單一週次
        （非整數）時 fallback 為本週。
        """
        week_dates = self.env.context.get('schedule_week_dates')
        if week_dates and status_key in week_dates:
            try:
                return fields.Date.to_date(week_dates[status_key])
            except (ValueError, TypeError):
                pass
        schedule_week_number = self.env.context.get('schedule_current_week', 0)
        if not isinstance(schedule_week_number, int):
            schedule_week_number = 0  # 「全部」檢視 → 預設本週
        today = fields.Date.today()
        current_week_start = today - timedelta(days=today.weekday())
        target_week_start = current_week_start + timedelta(days=7 * schedule_week_number)
        return target_week_start + timedelta(days=target_weekday)

    def _enforce_deadline_invariant(self):
        """維持 planned_date <= date_deadline 不變式。

        計畫日期晚於截止日（直接挑遠期、或建立者把截止日縮短到計畫日之前）時，
        以系統權限把截止日順延/拉回到計畫日（繞過「建立者限定」守門），並留下
        notification log。skip_deadline_invariant 防遞迴（自然停止點為兩者相等）。
        """
        if self.env.context.get('skip_deadline_invariant'):
            return
        log_bodies = {}
        for activity in self:
            planned = activity.planned_date
            deadline = activity.date_deadline
            if planned and deadline and planned > deadline:
                activity.sudo().with_context(
                    skip_schedule_check=True,
                    skip_deadline_invariant=True,
                    tracking_disable=True,  # 避免與下方明確 log 重複的自動追蹤訊息
                ).write({'date_deadline': planned})
                log_bodies[activity.id] = _(
                    'Due date adjusted to keep it on/after the planned date: '
                    '%(old)s → %(new)s (planned date %(planned)s).',
                    old=deadline.strftime('%Y-%m-%d'),
                    new=planned.strftime('%Y-%m-%d'),
                    planned=planned.strftime('%Y-%m-%d'),
                )
        # 純記錄（不發通知給 follower），多筆一次寫入。
        if log_bodies:
            self._message_log_batch(bodies=log_bodies)

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
        # 需求七：獨立待辦（res 為空）無關聯文件，改開啟待辦本身，避免回傳
        # res_model=False 造成前端動作錯誤。
        if not self.res_model or not self.res_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mail.activity',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'current',
            }
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
            # Dispatched client-side via doAction(rawDict); Odoo 18's
            # _preprocessAction requires `views` (it won't derive it from
            # view_mode), otherwise it throws "reading 'map' of undefined".
            'views': [(False, 'form')],
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
            'views': [(False, 'form')],
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
            'views': [(False, 'form')],
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

        # 自訂模板無法寄送時，退回預設通知（避免完全不通知）
        fallback_notify_activities = self.env['mail.activity']

        # 處理自定義模板通知
        for activity in custom_notify_activities:
            if not activity.user_id:
                continue
            template = activity.activity_type_id.notify_template_id
            # 獨立待辦（res 為空）或模板 model 與 res_model 不符 → 跳過自訂模板寄送，
            # 避免 template.send_mail(False) 對不存在文件寄信（需求七防禦），
            # 改由預設通知路徑處理，確保被指派者仍收到通知
            if not activity.res_model or not activity.res_id or \
                    (template.model and template.model != activity.res_model):
                _logger.debug(
                    'Activity %s: custom notify skipped (no matching res document), '
                    'falling back to default notify', activity.id)
                fallback_notify_activities |= activity
                continue
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

        # 處理預設通知（調用原始方法）；併入自訂模板無法寄送而退回的待辦
        default_notify_activities |= fallback_notify_activities
        # 需求七：獨立待辦（res 為空）無關聯文件，核心 action_notify 會
        # self.env['ir.model']._get(False) / self.env[False].browse(...) → KeyError。
        # 其 systray 計數已於 create 覆寫發送；此處略過「文件式」郵件/inbox 通知
        # （無文件可據以發送），避免崩潰。
        notifiable = default_notify_activities.filtered(
            lambda a: a.res_model and a.res_id)
        skipped = default_notify_activities - notifiable
        if skipped:
            _logger.debug(
                'action_notify: skip document-based notify for %s standalone '
                'activities (no related document); systray count already sent on create.',
                len(skipped))
        if notifiable:
            super(MailActivity, notifiable).action_notify()

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
        """將待辦排程至指定週次（保持原星期幾，移動到目標週）。

        Args:
            week_number: 相對週次偏移（-1=上週, 0=本週, 1=下週；正數為未來週，
                走 scheduled_date 預排）。
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

    @api.model
    def get_week_info(self):
        """取得週次選單資訊（供前端使用）：上週、本週、下週、全部。

        以單次 read_group 統計上/本/下週的數量與工時，另對「全部」做一次無
        週次過濾的彙總（含 waiting / 遠期 / 無日期）。
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
        ]

        # 單次查詢：以 schedule_week_number 分組統計上/本/下週的待辦數量和工時
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

        # 「全部」：無週次過濾的整體彙總（含 waiting / 遠期 / 無日期）
        all_data = self.read_group(
            domain=[('active', '=', True), ('user_id', '=', self.env.uid)],
            fields=['estimated_hours:sum'],
            groupby=[],
        )
        all_count = all_data[0]['__count'] if all_data else 0
        all_hours = (all_data[0]['estimated_hours'] or 0) if all_data else 0
        all_name = _('All')
        weeks.append({
            'number': 'all',
            'name': all_name,
            'display_name': '%s[%d]' % (all_name, all_count),
            'key': 'all',
            'start_date': False,
            'end_date': False,
            'count': all_count,
            'total_hours': all_hours,
            'dates': {},
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
