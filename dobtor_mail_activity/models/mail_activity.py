# -*- coding: utf-8 -*-
import math
import logging
from collections import defaultdict
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

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
        index=True,
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
        ('merged', 'Merged'),
    ], string='Activity Status', compute='_compute_activity_status', store=True)

    # ===== 來源參考（需求四：note_id 顯示為「來源參考 / Source Reference」）=====
    # note_id  = 這張待辦「從哪張筆記長出來」—— 語意單一，轉移精靈記的就是它。
    # note_ids = 「有哪些筆記引用這張待辦」—— 合併時把被併入者的筆記併進主待辦，
    #            所以必須是多筆。不變式：note_id 若有值，必定是 note_ids 的成員
    #            （由 create/write 維護，見 _sync_note_ids）。
    note_id = fields.Many2one(
        'note.note',
        string='Source Reference',
        index=True,
        ondelete='set null',
        help='Source note this activity originated from',
    )
    note_ids = fields.Many2many(
        'note.note',
        'mail_activity_note_rel', 'activity_id', 'note_id',
        string='Referenced Notes',
        help='All notes referencing this activity (always includes the source '
             'reference). Merging an activity moves its notes here.',
    )

    # ===== 合併 =====
    # 被併入者不刪除：保留記錄 + merged_into_id 指標，讓膠囊可在讀取時轉向，
    # 並支援解除合併。指標可成鏈（A→B→C），解析一律走到終點。
    merged_into_id = fields.Many2one(
        'mail.activity',
        string='Merged Into',
        index=True,
        ondelete='set null',
        readonly=True,
        help='Master activity this one was merged into.',
    )
    merged_activity_ids = fields.One2many(
        'mail.activity',
        'merged_into_id',
        string='Merged Activities',
        readonly=True,
    )
    merged_count = fields.Integer(
        string='Merged Count',
        compute='_compute_merged_count',
    )
    # 視圖條件用：py.js 沒有 len() builtin，不能在 invisible 裡寫 len(note_ids)
    # （伺服端 ast.parse 會過，瀏覽器才炸）
    note_count = fields.Integer(
        string='Referenced Note Count',
        compute='_compute_note_count',
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
        # 週次篩選改走日期區間後，這是主要的過濾與排序欄位
        index=True,
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
        # 週次選擇器與 searchpanel 計數每一次查詢都會用到
        index=True,
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

    @api.depends('active', 'done_date', 'cancel_date', 'merged_into_id')
    def _compute_activity_status(self):
        """計算待辦狀態

        merged 優先於其他狀態：被併入者不寫 done_date / cancel_date，
        單靠 merged_into_id 判別，解除合併時清指標即自動回到 active。
        """
        for activity in self:
            if activity.merged_into_id:
                activity.activity_status = 'merged'
            elif activity.cancel_date:
                activity.activity_status = 'cancelled'
            elif activity.done_date:
                activity.activity_status = 'done'
            elif not activity.active:
                # 防禦：已封存卻沒有任何來由（done/cancel/merge 皆無）。
                # 正常流程不會產生，但 SQL 直改、匯入或舊資料可能出現；
                # 沒有這支的話會算成 'active'，形成「進行中卻在封存區」的矛盾。
                activity.activity_status = 'cancelled'
            else:
                activity.activity_status = 'active'

    @api.depends('merged_activity_ids')
    def _compute_merged_count(self):
        for activity in self:
            activity.merged_count = len(activity.merged_activity_ids)

    @api.depends('note_ids')
    def _compute_note_count(self):
        for activity in self:
            activity.note_count = len(activity.note_ids)

    # ===== 約束 =====

    @api.constrains('note_id', 'note_ids')
    def _check_note_id_in_note_ids(self):
        """守住「來源筆記必為引用集合成員」的不變式。

        create/write 會自動維護，但 API 匯入、批次 UPDATE 或未來新增的寫入路徑
        可能繞過。不變式一破，note.note 端只看 note_ids 的計數與清單就會漏掉
        那筆待辦（筆記上明明有來源關聯，統計卻是 0）。
        """
        for activity in self:
            if activity.note_id and activity.note_id not in activity.note_ids:
                raise ValidationError(_(
                    'The source reference note must also be one of the referenced '
                    'notes. Activity "%(summary)s" points at note "%(note)s" which '
                    'is missing from its referenced notes.',
                    summary=activity.summary or activity.activity_type_id.name or activity.id,
                    note=activity.note_id.display_name,
                ))

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
        """即時計算「模型名稱 / 來源記錄目前名稱」（非 stored，永遠最新）。

        依 res_model 分組批次取名：一頁 80 列若逐筆 browse + display_name，就是
        80 次往返；分組後變成「每個出現過的模型各一次」（通常 2~5 次）。
        display_name 本身仍是 compute，但整批 browse 會共用 prefetch。
        """
        by_model = defaultdict(set)
        for activity in self:
            if activity.res_model and activity.res_id:
                by_model[activity.res_model].add(activity.res_id)

        # {res_model: {res_id: display_name}}；模型不存在或無權讀取則整組留空
        names = {}
        labels = {}
        for res_model, res_ids in by_model.items():
            try:
                Model = self.env[res_model]
            except KeyError:
                _logger.debug('res_document_display: unknown model %s', res_model)
                continue
            labels[res_model] = self.env['ir.model']._get(res_model).name or res_model
            try:
                records = Model.browse(res_ids).exists()
                names[res_model] = {r.id: r.display_name for r in records}
            except Exception as e:
                _logger.debug(
                    'res_document_display: cannot read %s %s: %s', res_model, res_ids, e)
                names[res_model] = {}

        for activity in self:
            if not activity.res_model or not activity.res_id:
                activity.res_document_display = False
                continue
            model_names = names.get(activity.res_model)
            if model_names is None:
                activity.res_document_display = False
                continue
            display_name = model_names.get(activity.res_id)
            if display_name is None:
                # exists() 沒撈到 → 來源記錄已被刪除
                activity.res_document_display = _('(Record Deleted)')
                continue
            model_label = (activity.res_model_id.name
                           or labels.get(activity.res_model)
                           or activity.res_model)
            activity.res_document_display = '%s / %s' % (model_label, display_name)

    @api.model
    def _cron_refresh_res_name(self, batch_limit=5000):
        """定期強制重算 stored res_name，讓來源記錄改名後群組標題能跟上。

        res_name 是 stored 快照，@api.depends('res_model','res_id') 不會因「來源記錄
        改名」而重算（多型參考無法穿透）。報告以 res_name 當群組標題，故以本 cron
        週期性重算，使標題保持新鮮（非即時，取決於 cron 週期）。僅處理仍 active 且
        有關聯文件的待辦，控制成本。

        order='write_date asc' 是必要的：沒有排序時走預設 id 序，超過 batch_limit
        的部分會永遠輪不到（每次都重刷同一批最舊 id）。改以「最久沒被碰過的優先」
        輪替，才能保證每一筆最終都會被刷到。重算本身會更新 write_date，形成輪替。
        """
        activities = self.search([
            ('active', '=', True),
            ('res_model', '!=', False),
            ('res_id', '!=', False),
        ], limit=batch_limit, order='write_date asc, id asc')
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


    # ========== 合併：膠囊轉向 ==========


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

        # 同一個請求內常會對同一批文件重複做存取檢查（分頁器的 count、看板各分組、
        # searchpanel 計數都會各自進到這裡）。_filtered_access 對每個模型都是一次
        # 查詢，且「待辦總覽」放寬成 domain=[] 之後，一頁可能橫跨十幾個模型。
        # 以 env.cr 為生命週期做快取：同一交易內同一 (模型, id) 只檢查一次，
        # 交易結束即失效，不會跨請求殘留過期的權限判定。
        cache = getattr(self.env.cr, '_dobtor_activity_access_cache', None)
        if cache is None:
            cache = defaultdict(dict)
            self.env.cr._dobtor_activity_access_cache = cache

        allowed_ids = defaultdict(set)
        for res_model, res_ids in model_ids.items():
            model_cache = cache[(res_model, self.env.uid)]
            unknown = res_ids - model_cache.keys()
            if unknown:
                records = self.env[res_model].browse(unknown).exists()
                operation = getattr(records, '_mail_post_access', 'read')
                permitted = set(records._filtered_access(operation)._ids)
                # 連「不允許」也要記錄，否則每次都會重新查一遍被擋掉的那些
                for res_id in unknown:
                    model_cache[res_id] = res_id in permitted
            allowed_ids[res_model] = {r for r in res_ids if model_cache.get(r)}

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
        3. 停用 mail.thread 的自動訂閱和追蹤
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

            # 不變式：來源筆記（note_id）必定也在引用集合（note_ids）內，
            # 讓筆記端的計數/清單只需要看 note_ids 一個欄位。
            if vals.get('note_id'):
                vals.setdefault('note_ids', [])
                vals['note_ids'] = list(vals['note_ids']) + [Command.link(vals['note_id'])]

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

        # 直接走官方 create。
        #
        # 這裡曾有一段 _CREATE_BYPASS_APPLICABLE 的繞道，理由寫的是「Odoo 18 的
        # mail.activity.create 有 UnboundLocalError bug」。對照 18.0 原始碼後確認
        # 該 bug 不存在（readable_user_partners 兩個分支都有賦值），而本模組特有的
        # 兩種資料形態也都被官方安全處理：
        #   - 無關聯文件（需求七獨立待辦）：_classify_by_model() 會過濾掉 res 為空者
        #     （mail/models/mail_activity.py:786），不會踩到 self.env[False]。
        #   - 無指派人（未指派待辦）：官方雖會把它們送進 action_notify，但本模組的
        #     action_notify 覆寫已先濾掉無 res / 無 user 者；systray 的 _bus_send
        #     對空 recordset 也是 no-op。
        # 繞道的代價是必須手工複製並持續同步官方約 60 行邏輯（通知、systray、
        # 訂閱），且訂閱從官方的「依模型批次」退化成逐筆 message_subscribe。
        # 若日後在某個 18.0 修訂版真的遇到官方 create 出錯，請在此處記錄實際的
        # traceback 與版本，再考慮重新引入繞道。
        activities = super(MailActivity, self_with_context).create(vals_list)

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


    @api.depends('postpone_history_ids')
    def _compute_postpone_count(self):
        """計算延期次數"""
        for activity in self:
            activity.postpone_count = len(activity.postpone_history_ids)


    # ========== 關聯邏輯圖（需求二/三/五）==========


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
        # 顯示用週天名稱：以 _() 包裹讓代入警告字串前先翻譯（po 已有 週一…週日）
        weekday_names = {
            0: _('Monday'), 1: _('Tuesday'), 2: _('Wednesday'),
            3: _('Thursday'), 4: _('Friday'), 5: _('Saturday'), 6: _('Sunday')
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
                if needs_schedule_date < today:
                    # 過了該安排日（含過了本週）→ 逾期提示
                    activity.schedule_warning = _('Overdue, please schedule immediately')
                else:
                    # 本週內尚未到期 → 需在 本週X 前排定
                    activity.schedule_warning = _(
                        'Needs to be scheduled by this %(weekday)s',
                        weekday=weekday_names.get(weekday, ''))

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

    @staticmethod
    def _apply_x2m_commands(current_ids, commands):
        """把 x2many command list 套到現有 id 集合上，回傳結果集合。

        僅用於 write() 的「值是否真的改變」判斷，不需支援 create/update 語意
        （命令 0/1 一律視為已變更，回傳哨符 None）。
        """
        if not isinstance(commands, (list, tuple)):
            return None
        result = set(current_ids)
        for cmd in commands:
            if not isinstance(cmd, (list, tuple)) or not cmd:
                return None
            code = cmd[0]
            if code == Command.LINK:
                result.add(cmd[1])
            elif code == Command.UNLINK:
                result.discard(cmd[1])
            elif code == Command.CLEAR:
                result.clear()
            elif code == Command.SET:
                result = set(cmd[2] or [])
            else:
                return None  # CREATE / UPDATE / DELETE：無法比對，視為已變更
        return result

    def write(self, vals):
        """覆寫 write 方法以記錄指派變更"""
        # 不變式：來源筆記（note_id）必定也在引用集合（note_ids）內。
        if vals.get('note_id'):
            vals = dict(vals)
            vals['note_ids'] = list(vals.get('note_ids') or []) + [Command.link(vals['note_id'])]

        # 驗證：欄位層級編輯權限（建立者 vs 被指派者）。
        # 建立者可改：類型/急迫/重要（截止日另有專屬守衛）；
        # 被指派者可改：預估工時；相關文件/筆記兩者皆可。
        # 豁免：su、系統管理員、轉移作業（帶 transferred_from_model）、
        #       合併作業（context activity_merge —— 主待辦的執行者未必是它的
        #       建立者或被指派者，但合併本身已在 wizard 對每一筆被併入者驗過權限）。
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            creator_only = {'urgency', 'importance', 'activity_type_id'}
            assignee_only = {'estimated_hours'}
            # target_ref（computed Reference，inverse 寫 res_model_id/res_id）一併納入
            related_fields = {'res_model_id', 'res_id', 'note_id', 'note_ids', 'target_ref'}
            guarded = creator_only | assignee_only | related_fields
            is_transfer = 'transferred_from_model' in vals
            is_merge = bool(self.env.context.get('activity_merge'))
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
                    elif f == 'note_ids':
                        # x2many：把 command list 套到現有集合再比，避免送同一組
                        # 值也判定為已變更；無法解析的命令（create/update）→ 視為變更。
                        newv = self._apply_x2m_commands(cur.ids, newv)
                        cur = set(cur.ids)
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
                if (related_fields & changed) and not is_transfer and not is_merge \
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

    def _action_cancel(self, feedback=False):
        """取消待辦：封存並記錄取消原因。

        記錄方式比照 _action_done：於關聯文件 chatter 留痕（含原因）、原因存入
        feedback 欄位、封存待辦並設 cancel_date；獨立待辦（無 res）僅封存記錄。
        """
        for activity in self:
            # 於關聯文件 chatter 留下取消訊息（含原因）
            if activity.res_model and activity.res_id:
                record = self.env[activity.res_model].sudo().browse(activity.res_id)
                if record.exists():
                    body = _('To-do cancelled: %(summary)s',
                             summary=activity.summary or activity.activity_type_id.display_name or '')
                    if feedback:
                        # Markup：使 <br/> 生效並自動轉義使用者填寫的原因
                        body = Markup('%s<br/>%s') % (
                            body, _('Reason: %(reason)s', reason=feedback))
                    record.message_post(
                        body=body,
                        author_id=self.env.user.partner_id.id,
                        subtype_xmlid='mail.mt_activities',
                        mail_activity_type_id=activity.activity_type_id.id,
                    )

        # 封存並記錄（feedback 存入待辦，與完成一致）
        self.write({
            'active': False,
            'cancel_date': fields.Datetime.now(),
            'feedback': feedback,
        })

        # 發送 bus 通知
        for activity in self:
            if activity.user_id:
                activity.user_id._bus_send(
                    'mail.activity/updated',
                    {'activity_deleted': True, 'count_diff': -1}
                )

    def action_cancel(self):
        """取消待辦：開啟取消原因精靈（需填原因才確認，記錄方式比照完成）。

        表單 header / mark-as-done popover / 清單 / 看板的所有「取消」入口共用，
        統一導向精靈以強制填寫原因。
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cancel Activity'),
            'res_model': 'mail.activity.cancel.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
            }
        }

    def action_restore(self):
        """恢復已封存的待辦

        已合併者不可單獨還原（會憑空多出一筆與主待辦重複的工作），
        必須走 action_unmerge。
        """
        merged = self.filtered('merged_into_id')
        if merged:
            raise UserError(_(
                'These activities were merged into another one and cannot be '
                'restored directly. Use "Unmerge" instead: %(summaries)s',
                summaries=', '.join(
                    m.summary or m.activity_type_id.name or str(m.id) for m in merged
                ),
            ))
        self.write({
            'active': True,
            'done_date': False,
            'cancel_date': False,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    # ========== 合併 ==========


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

    def _continue_todo_action(self):
        """開啟「建立待辦」精靈並帶入本待辦的標題/類型/關聯（客戶/專案/來源
        參考/關聯文件）作為預設值。

        供兩處共用：
          - 完成精靈的「完成並排程下一個」（完成後鏈式建立）
          - 已完成待辦表單的「延續新增待辦」按鈕
        本待辦即使已封存（完成/取消），summary / activity_type_id / res /
        partner / project / note 等欄位仍在，直接讀取即可。
        """
        self.ensure_one()
        ctx = {
            # 關閉新精靈時 soft_reload，讓來源清單/看板即時刷新
            'chained_from_done': True,
            'default_summary': self.summary,
            'default_activity_type_id': self.activity_type_id.id,
        }
        # 有關聯文件才帶（新精靈視為「已知目標」）
        if self.res_model and self.res_id:
            ctx.update({
                'active_model': self.res_model,
                'active_id': self.res_id,
                'active_ids': [self.res_id],
            })
        if self.partner_id:
            ctx['default_partner_id'] = self.partner_id.id
        if self.project_id:
            ctx['default_project_id'] = self.project_id.id
        if self.note_id:
            ctx['default_note_id'] = self.note_id.id
        elif self.note_ids:
            ctx['default_note_id'] = self.note_ids[0].id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create To-do'),
            'res_model': 'mail.activity.create.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': ctx,
        }

    def action_continue_new_activity(self):
        """已完成待辦的「延續新增待辦」：以本待辦資訊開新的建立待辦精靈。"""
        self.ensure_one()
        return self._continue_todo_action()

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
        """取得指定文件的待辦所關聯的 Notes

        注意：一張待辦可引用多張筆記（note_ids），因此同一張待辦會同時出現在
        多個筆記分組底下 —— 各分組 total_count 的**加總會大於實際待辦數**，
        呼叫端（related_notes.js）不應把它們相加當作總數。
        """
        activities = self.with_context(active_test=False).search([
            ('res_model', '=', res_model),
            ('res_id', '=', res_id),
            ('note_ids', '!=', False),
        ])

        notes_activities = defaultdict(list)
        for activity in activities:
            if activity.merged_into_id:
                activity_state = 'merged'
            elif activity.active:
                activity_state = 'active'
            elif activity.done_date:
                activity_state = 'done'
            elif activity.cancel_date:
                activity_state = 'cancelled'
            else:
                activity_state = 'archived'

            for note in activity.note_ids:
                notes_activities[note.id].append({
                    'id': activity.id,
                    'summary': activity.summary or '',
                    'state': activity_state,
                    'note': note,
                })

        notes_data = []
        for note_id, activity_list in notes_activities.items():
            note = activity_list[0]['note']
            note_name = note.name
            if not note_name and note.memo:
                note_name = self._html_to_text(note.memo, max_length=50)

            active_count = sum(1 for a in activity_list if a['state'] == 'active')
            done_count = sum(1 for a in activity_list if a['state'] in ('done', 'cancelled'))
            # 已合併者仍列出（顯示但標示），但它與主待辦是同一件事 —— 單獨算出來，
            # 讓前端能說明分母為何比實際件數大。
            merged_count = sum(1 for a in activity_list if a['state'] == 'merged')
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
                'merged_count': merged_count,
                # 只有「已合併空殼」的筆記不算全部完成（實際內容在別處的主待辦上）
                'is_all_done': active_count == 0 and (total_count - merged_count) > 0,
            })

        return notes_data

    # ========== 週轉換定時任務 ==========


    # ========== 頻道工具方法 ==========


    # ========== 領取與變更指派 ==========


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


    # ========== 週次：以日期區間表達（不依賴 stored 的 schedule_week_number）==========
    #
    # schedule_week / schedule_week_number 是「相對今天」的 stored compute，ORM 只在
    # planned_date / scheduled_date 變動時重算 → 時間流逝就會腐化。過去靠每日 cron
    # 全表重算續命，cron 一旦失效，週次篩選會**靜默**給出錯誤結果。
    #
    # 現在把「篩選」與「顯示」分開：
    #   - 篩選 / 計數 → 一律走本區的日期區間 domain，永遠正確，與 cron 無關。
    #   - 顯示 / 分組 / searchpanel 計數 → 仍用 stored 欄位（Odoo 18 的 searchpanel
    #     與 read_group 都要求 stored），由 cron 增量刷新；失效只影響標籤不影響結果。


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

