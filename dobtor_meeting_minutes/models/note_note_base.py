# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _, Command
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class NoteNote(models.Model):
    """筆記本 - 個人筆記管理

    提供類似便利貼的筆記功能，支援：
    - 階段式看板管理
    - 標籤分類
    - 待辦整合
    - 封存機制
    """
    _name = 'note.note'
    _description = 'Note'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'sequence, id desc'

    # ===== 基本欄位 =====
    name = fields.Text(
        string='Note Summary',
        compute='_compute_name',
        store=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Owner',
        default=lambda self: self.env.uid,
        index=True,
    )
    memo = fields.Html(
        string='Note Content',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=0,
    )
    color = fields.Integer(
        string='Color Index',
        default=0,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help="Uncheck to archive this note, archived notes will not appear in the list.",
    )

    # ===== 類型欄位（可由子模組透過 selection_add 擴展） =====
    note_type = fields.Selection([
        ('note', 'Note'),
    ], string='Type', default='note', tracking=True)

    # ===== 階段欄位 =====
    stage_id = fields.Many2one(
        'note.stage',
        string='Stage',
        compute='_compute_stage_id',
        inverse='_inverse_stage_id',
        store=True,
        # 不設 default：default 會被當成明確寫入值而跳過 compute，
        # 使代建筆記存成建立者的階段（見 _compute_stage_id）
        group_expand='_read_group_stage_ids',
    )
    stage_ids = fields.Many2many(
        'note.stage',
        'note_note_stage_rel',
        'note_id',
        'stage_id',
        string='User Stages',
        default=lambda self: self._get_default_stage_id(),
    )

    # ===== 狀態欄位 =====
    open = fields.Boolean(
        string='Open',
        default=True,
    )
    date_done = fields.Date(
        string='Done Date',
    )

    # ===== 標籤欄位 =====
    tag_ids = fields.Many2many(
        'note.tag',
        'note_note_tag_rel',
        'note_id',
        'tag_id',
        string='Tags',
    )
    main_tag_id = fields.Many2one(
        'note.tag',
        string='Main Tag',
        compute='_compute_main_tag_id',
        store=True,
        help="The first tag of the note, used for the left tree filter panel.",
    )

    # ===== 筆記專屬待辦關聯欄位 =====
    # 注意：不要覆寫 mail.activity.mixin 的 activity_ids，否則會影響標準活動功能
    #
    # 多對多（不是 One2many）：一張待辦可被多張筆記引用 —— 合併待辦時，被併入者
    # 的筆記會全部併進主待辦。欄位順序與 mail.activity.note_ids 相反（本表是
    # note 端）。mail.activity 維護「note_id 必為 note_ids 成員」的不變式，
    # 所以這裡只看 note_ids 一個欄位即可涵蓋來源與引用。
    note_activity_ids = fields.Many2many(
        'mail.activity',
        'mail_activity_note_rel', 'note_id', 'activity_id',
        string='Note Activities',
        help='Activities referencing this note (including those created from it)',
    )
    note_activity_count = fields.Integer(
        string='Note Activity Count',
        compute='_compute_note_activity_count',
    )
    note_active_activity_count = fields.Integer(
        string='Active Note Activities',
        compute='_compute_note_activity_count',
    )

    # ===== 計算方法 =====
    @api.depends('memo')
    def _compute_name(self):
        """從筆記內容的第一行取得筆記名稱"""
        for note in self:
            text = html2plaintext(note.memo) if note.memo else ''
            note.name = text.strip().replace('*', '').split("\n")[0]

    @api.depends('tag_ids')
    def _compute_main_tag_id(self):
        """取得第一個標籤作為主要標籤"""
        for note in self:
            note.main_tag_id = note.tag_ids[:1]

    @api.depends('note_activity_ids', 'note_activity_ids.active')
    def _compute_note_activity_count(self):
        """計算筆記關聯待辦數量（透過 note_ids 引用，批次優化）"""
        if not self.ids:
            for note in self:
                note.note_activity_count = 0
                note.note_active_activity_count = 0
            return

        Activity = self.env['mail.activity'].with_context(active_test=False)
        total_map = self._count_activities_by_note(Activity, [])
        active_map = self._count_activities_by_note(Activity, [('active', '=', True)])

        for note in self:
            note.note_activity_count = total_map.get(note.id, 0)
            note.note_active_activity_count = active_map.get(note.id, 0)

    def _count_activities_by_note(self, Activity, extra_domain):
        """以單次 _read_group 統計「每張筆記幾筆待辦」。

        groupby 用的是 many2many（Odoo 18 支援，會自動 join rel table），但分組
        結果會包含「同一批待辦所引用、卻不在 self 內」的筆記，故需再過濾一次。
        """
        note_ids = set(self.ids)
        groups = Activity._read_group(
            [('note_ids', 'in', self.ids)] + extra_domain,
            groupby=['note_ids'],
            aggregates=['__count'],
        )
        return {
            note.id: count
            for note, count in groups
            if note and note.id in note_ids
        }

    @api.depends('stage_ids', 'user_id')
    def _compute_stage_id(self):
        """計算筆記「擁有者」的階段。

        ☠️ 本欄位 store=True，曾以「目前使用者」計算：誰建立就存誰的階段。
        週排程 cron 以 OdooBot 身分 auto_create_note 替使用者建週筆記 →
        存成 OdooBot 的階段 → 擁有者讀不到該 note.stage（ir.rule 限本人）→
        打開「個人筆記」整頁 Access Error。stored 值只能有一個，故以擁有者為準
        （個人筆記的清單/看板本來就只列 user_id = uid）。
        """
        Stage = self.env['note.stage'].sudo()
        first_stage_by_owner = {}
        for note in self:
            owner = note.user_id or self.env.user
            own_stages = note.sudo().stage_ids.filtered(
                lambda stage: stage.user_id == owner
            )
            if own_stages:
                note.stage_id = own_stages[:1].id
                continue
            if owner.id not in first_stage_by_owner:
                Stage._ensure_user_stages(owner.id)
                first_stage_by_owner[owner.id] = Stage.search(
                    [('user_id', '=', owner.id)], limit=1).id
            note.stage_id = first_stage_by_owner[owner.id]

    def _inverse_stage_id(self):
        """更新階段關聯：只替換「新階段所屬使用者」的那一筆，保留其他人的。"""
        for note in self.filtered('stage_id'):
            new_stage = note.stage_id.sudo()
            kept = note.sudo().stage_ids.filtered(
                lambda stage: stage.user_id != new_stage.user_id
            )
            note.stage_ids = [Command.set((new_stage | kept).ids)]

    @api.model
    def _recompute_owner_stages(self):
        """修正「階段不屬於擁有者」的既有筆記（冪等）。

        舊版 stage_id 以建立者計算並 store（cron 代建的週筆記存成 OdooBot 的階段
        → 擁有者開「個人筆記」AccessError）。原本由 dobtor_mail_activity 18.0.1.9.0
        的 migration 修正；筆記搬到本模組後，跨版升級時那支已無法執行，改由本模組
        的 migration 與 post-init hook 呼叫這裡。
        """
        self.env.cr.execute("""
            SELECT n.id
              FROM note_note n
              LEFT JOIN note_stage s ON s.id = n.stage_id
             WHERE n.user_id IS NOT NULL
               AND (s.id IS NULL OR s.user_id IS DISTINCT FROM n.user_id)
        """)
        notes = self.with_context(active_test=False).browse([r[0] for r in self.env.cr.fetchall()])
        if notes:
            self.env.add_to_compute(self._fields['stage_id'], notes)
            notes.flush_recordset(['stage_id'])
        return len(notes)

    @api.model
    def _recompute_calendar_note_counts(self):
        """重算 calendar.event.note_count（stored）。舊版 note.calendar_event_id 的
        關聯由 dobtor_mail_activity 的 migration 以 SQL 補進多對多表，不會觸發重算。"""
        self.env.cr.execute("SELECT DISTINCT event_id FROM calendar_event_note_rel")
        events = self.env['calendar.event'].with_context(active_test=False).browse(
            [r[0] for r in self.env.cr.fetchall()])
        if events:
            self.env.add_to_compute(self.env['calendar.event']._fields['note_count'], events)
            events.flush_recordset(['note_count'])
        return len(events)

    # ===== 預設值方法 =====
    def _get_default_stage_id(self):
        """取得當前用戶的預設階段（若無則自動建立）"""
        self.env['note.stage']._ensure_user_stages()
        return self.env['note.stage'].search(
            [('user_id', '=', self.env.uid)],
            limit=1,
        )

    @api.model
    def _read_group_stage_ids(self, stages, domain, order=None):
        """看板視圖階段展開 - 顯示當前用戶的所有階段（若無則自動建立）"""
        self.env['note.stage']._ensure_user_stages()
        return self.env['note.stage'].search([('user_id', '=', self.env.uid)])

    # ===== CRUD 方法 =====
    @api.model
    def name_create(self, name):
        """從名稱快速建立筆記"""
        record = self.create({'memo': name})
        return record.id, record.display_name

    # ===== 動作方法 =====
    def action_close(self):
        """關閉筆記"""
        return self.write({
            'open': False,
            'date_done': fields.Date.today(),
        })

    def action_open(self):
        """重新開啟筆記"""
        return self.write({
            'open': True,
            'date_done': False,
        })

    def action_view_activities(self):
        """查看關聯待辦"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Related Activities'),
            'res_model': 'mail.activity',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('note_ids', 'in', self.id)],
            'context': {'active_test': False},
        }

    # ===== API 方法 =====
    def get_related_documents(self):
        """取得關聯文件（CRM/Task）- 對外 API 方法

        ⚠️ 本模組內部無呼叫端（related_notes.js 用的是反向的
        mail.activity.get_related_notes）。刻意保留為公開 API 供外部整合，
        若確定無人使用可直接刪除。


        Returns:
            list: 包含關聯文件資訊的字典列表
        """
        self.ensure_one()
        activities = self.env['mail.activity'].with_context(active_test=False).search([
            ('note_ids', 'in', self.id),
            ('is_transferred', '=', True),
        ])

        documents = []
        seen = set()
        for activity in activities:
            key = (activity.res_model, activity.res_id)
            if key not in seen:
                seen.add(key)
                documents.append({
                    'res_model': activity.res_model,
                    'res_id': activity.res_id,
                    'res_name': activity.res_name,
                    'activity_summary': activity.summary,
                    'activity_status': 'active' if activity.active else 'done',
                })

        return documents
