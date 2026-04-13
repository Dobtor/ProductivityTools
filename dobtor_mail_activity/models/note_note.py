# -*- coding: utf-8 -*-

import base64
import logging
import uuid
import threading
import requests

from markupsafe import escape as html_escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

SUMMARY_PROMPT_PRESETS = {
    'formal': {
        'name': 'Formal Meeting Minutes',
        'name_zh': '正式會議記錄',
        'prompt': (
            '你是專業的會議記錄助理。請根據以下逐字稿產生結構化的會議摘要。\n\n'
            '## 輸出格式（使用 HTML 標籤）\n'
            '1. <h4>會議主題</h4>：一句話概述\n'
            '2. <h4>出席者</h4>：列出所有發言者\n'
            '3. <h4>討論要點</h4>：分點列出主要討論內容\n'
            '4. <h4>決議事項</h4>：明確的決定，含負責人\n'
            '5. <h4>待辦事項</h4>：具體的 action items，含負責人與期限\n\n'
            '請使用繁體中文回覆，輸出為 HTML 格式。\n\n'
            '## 逐字稿\n{transcript}'
        ),
    },
    'brainstorm': {
        'name': 'Brainstorming Session',
        'name_zh': '腦力激盪紀要',
        'prompt': (
            '你是創意會議的記錄助理。請根據以下逐字稿整理出腦力激盪的結果。\n\n'
            '## 輸出格式（使用 HTML 標籤）\n'
            '1. <h4>主題</h4>：討論的核心問題\n'
            '2. <h4>提出的想法</h4>：列出所有被提及的想法或方案，標注提出者\n'
            '3. <h4>篩選結果</h4>：哪些想法被認可、哪些被排除，附原因\n'
            '4. <h4>下一步行動</h4>：後續要做的事\n\n'
            '請使用繁體中文回覆，輸出為 HTML 格式。\n\n'
            '## 逐字稿\n{transcript}'
        ),
    },
    'standup': {
        'name': 'Daily Standup / Sprint Review',
        'name_zh': '每日站會 / Sprint 回顧',
        'prompt': (
            '你是敏捷開發團隊的會議記錄助理。請根據以下逐字稿整理站會或回顧會議。\n\n'
            '## 輸出格式（使用 HTML 標籤）\n'
            '依每位發言者分段：\n'
            '<h4>[姓名]</h4>\n'
            '<ul>\n'
            '  <li><b>昨天完成</b>：...</li>\n'
            '  <li><b>今天計畫</b>：...</li>\n'
            '  <li><b>遇到的阻礙</b>：...</li>\n'
            '</ul>\n\n'
            '最後加上 <h4>需要協調的事項</h4>。\n\n'
            '請使用繁體中文回覆，輸出為 HTML 格式。\n\n'
            '## 逐字稿\n{transcript}'
        ),
    },
    'project': {
        'name': 'Project Status Meeting',
        'name_zh': '專案進度會議',
        'prompt': (
            '你是專案管理的會議記錄助理。請根據以下逐字稿產生專案進度會議摘要。\n\n'
            '## 輸出格式（使用 HTML 標籤）\n'
            '1. <h4>專案概況</h4>：目前整體狀態（正常/延遲/風險）\n'
            '2. <h4>各模組進度</h4>：依負責人或模組分段報告\n'
            '3. <h4>風險與問題</h4>：需要注意的風險和待解問題\n'
            '4. <h4>決議事項</h4>：會議中做出的決定\n'
            '5. <h4>下次里程碑</h4>：下一個檢查點的日期和目標\n\n'
            '請使用繁體中文回覆，輸出為 HTML 格式。\n\n'
            '## 逐字稿\n{transcript}'
        ),
    },
}

_logger = logging.getLogger(__name__)


class NoteNote(models.Model):
    """筆記本 - 個人筆記管理與會議記錄

    提供類似便利貼的筆記功能，支援：
    - 階段式看板管理
    - 標籤分類
    - 待辦整合
    - 封存機制
    - 會議記錄（含 PDF 報告、Portal 檢視、簽名確認）
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

    # ===== 會議記錄欄位 =====
    note_type = fields.Selection([
        ('note', 'Note'),
        ('meeting', 'Meeting Minutes'),
    ], string='Type', default='note', tracking=True)

    # 指定簽名者（從行事曆事件參與者中選擇）
    signer_ids = fields.Many2many(
        'res.partner',
        'note_note_signer_rel',
        'note_id',
        'partner_id',
        string='Required Signers',
        help='Partners who must sign this meeting minutes',
    )

    # 簽名記錄
    signature_ids = fields.One2many(
        'note.signature',
        'note_id',
        string='Signatures',
    )
    signature_count = fields.Integer(
        string='Signature Count',
        compute='_compute_signature_count',
    )
    signed_count = fields.Integer(
        string='Signed Count',
        compute='_compute_signature_count',
    )
    all_signed = fields.Boolean(
        string='All Signed',
        compute='_compute_all_signed',
        store=True,
    )

    # 狀態
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('partial', 'Partially Signed'),
        ('signed', 'Fully Signed'),
    ], string='Status', default='draft', tracking=True)

    # 鎖定狀態（會議記錄寄出後鎖定內容）
    is_locked = fields.Boolean(
        string='Locked',
        compute='_compute_is_locked',
        store=True,
        help='Meeting minutes is locked after being sent for signature',
    )

    # ===== 階段欄位 =====
    stage_id = fields.Many2one(
        'note.stage',
        string='Stage',
        compute='_compute_stage_id',
        inverse='_inverse_stage_id',
        store=True,
        default=lambda self: self._get_default_stage_id(),
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

    # ===== 日曆事件關聯欄位 =====
    calendar_event_ids = fields.Many2many(
        'calendar.event',
        'calendar_event_note_rel',
        'note_id',
        'event_id',
        string='Calendar Events',
        help='Calendar events linked to this note',
    )
    calendar_event_count = fields.Integer(
        string='Event Count',
        compute='_compute_calendar_event_count',
    )
    # 可選擇的簽名者（從關聯行事曆事件的參與者中取得）
    available_signer_ids = fields.Many2many(
        'res.partner',
        string='Available Signers',
        compute='_compute_available_signer_ids',
        help='Partners who can be selected as signers (from calendar event attendees)',
    )

    # ===== 錄音與逐字稿欄位 =====
    recording_ids = fields.One2many(
        'note.recording',
        'note_id',
        string='Recordings',
    )
    recording_count = fields.Integer(
        string='Recording Count',
        compute='_compute_recording_count',
    )
    transcript_ids = fields.One2many(
        'note.transcript.segment',
        'note_id',
        string='Transcript Segments',
    )
    transcript_html = fields.Html(
        string='Transcript (Formatted)',
        compute='_compute_transcript_html',
        store=True,
    )
    transcript_state = fields.Selection([
        ('none', 'None'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], string='Transcript Status', default='none')
    speaker_mapping_ids = fields.One2many(
        'note.speaker.mapping',
        'note_id',
        string='Speaker Mapping',
    )

    # ===== 會議摘要欄位 =====
    meeting_summary = fields.Html(
        string='Meeting Summary',
    )
    summary_state = fields.Selection([
        ('none', 'None'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], string='Summary Status', default='none')

    # ===== 筆記專屬待辦關聯欄位 =====
    # 注意：不要覆寫 mail.activity.mixin 的 activity_ids，否則會影響標準活動功能
    note_activity_ids = fields.One2many(
        'mail.activity',
        'note_id',
        string='Note Activities',
        help='Activities linked via note_id (activities created from note)',
    )
    note_activity_count = fields.Integer(
        string='Note Activity Count',
        compute='_compute_note_activity_count',
    )
    note_active_activity_count = fields.Integer(
        string='Active Note Activities',
        compute='_compute_note_activity_count',
    )

    # ===== 預設範本 =====
    @api.model
    def _default_meeting_memo_template(self):
        """會議記錄預設章節範本"""
        return (
            '<h3>議程</h3>'
            '<ul><li><br/></li></ul>'
            '<h3>討論事項</h3>'
            '<p><br/></p>'
            '<h3>決議事項</h3>'
            '<ul><li><br/></li></ul>'
            '<h3>待辦追蹤</h3>'
            '<ul><li><br/></li></ul>'
        )

    @api.onchange('note_type')
    def _onchange_note_type_memo(self):
        """切換為會議記錄時，若 memo 為空則自動帶入章節範本"""
        if self.note_type == 'meeting' and not self.memo:
            self.memo = self._default_meeting_memo_template()

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

    @api.depends('recording_ids')
    def _compute_recording_count(self):
        """計算錄音數量"""
        for note in self:
            note.recording_count = len(note.recording_ids)

    @api.depends('transcript_ids', 'transcript_ids.text',
                 'transcript_ids.speaker_name', 'transcript_ids.speaker_label',
                 'transcript_ids.time_start',
                 'speaker_mapping_ids.partner_id',
                 'speaker_mapping_ids.display_name_override')
    def _compute_transcript_html(self):
        """產生格式化逐字稿 HTML"""
        for note in self:
            if not note.transcript_ids:
                note.transcript_html = False
                continue

            lines = []
            current_speaker = None
            for seg in note.transcript_ids.sorted('time_start'):
                time_str = seg._format_time(seg.time_start)
                name = html_escape(seg.speaker_name or seg.speaker_label or _('Unknown'))
                text = html_escape(seg.text or '')

                if name != current_speaker:
                    current_speaker = name
                    lines.append(
                        f'<div class="o_transcript_segment mb-2">'
                        f'<div class="o_transcript_speaker fw-bold text-primary">'
                        f'<span class="o_transcript_time text-muted me-2">[{time_str}]</span>'
                        f'{name}：'
                        f'</div>'
                        f'<div class="o_transcript_text ms-4">{text}</div>'
                        f'</div>'
                    )
                else:
                    lines.append(
                        f'<div class="o_transcript_segment mb-1">'
                        f'<div class="o_transcript_text ms-4">{text}</div>'
                        f'</div>'
                    )

            note.transcript_html = ''.join(lines)

    @api.depends('calendar_event_ids')
    def _compute_calendar_event_count(self):
        """計算關聯日曆事件數量"""
        for note in self:
            note.calendar_event_count = len(note.calendar_event_ids)

    @api.depends('calendar_event_ids', 'calendar_event_ids.partner_ids')
    def _compute_available_signer_ids(self):
        """計算可選擇的簽名者（從關聯行事曆事件的參與者中取得）"""
        for note in self:
            partners = self.env['res.partner']
            for event in note.calendar_event_ids:
                partners |= event.partner_ids
            note.available_signer_ids = partners

    @api.depends('note_activity_ids', 'note_activity_ids.active')
    def _compute_note_activity_count(self):
        """計算筆記關聯待辦數量（透過 note_id 關聯，批次優化）"""
        if not self.ids:
            for note in self:
                note.note_activity_count = 0
                note.note_active_activity_count = 0
            return

        Activity = self.env['mail.activity'].with_context(active_test=False)
        # 一次查詢所有 note 的待辦總數
        total_data = Activity.read_group(
            domain=[('note_id', 'in', self.ids)],
            fields=['note_id'],
            groupby=['note_id'],
        )
        total_map = {d['note_id'][0]: d['note_id_count'] for d in total_data}

        # 一次查詢所有 note 的 active 待辦數
        active_data = Activity.read_group(
            domain=[('note_id', 'in', self.ids), ('active', '=', True)],
            fields=['note_id'],
            groupby=['note_id'],
        )
        active_map = {d['note_id'][0]: d['note_id_count'] for d in active_data}

        for note in self:
            note.note_activity_count = total_map.get(note.id, 0)
            note.note_active_activity_count = active_map.get(note.id, 0)

    @api.depends('signature_ids', 'signature_ids.is_signed')
    def _compute_signature_count(self):
        """計算簽名數量"""
        for note in self:
            note.signature_count = len(note.signature_ids)
            note.signed_count = len(note.signature_ids.filtered('is_signed'))

    @api.depends('signature_ids.is_signed', 'signer_ids')
    def _compute_all_signed(self):
        """檢查是否全部簽名完成"""
        for note in self:
            if note.note_type != 'meeting' or not note.signer_ids:
                note.all_signed = False
            else:
                # 檢查所有指定簽名者是否都已簽名
                signed_partners = note.signature_ids.filtered('is_signed').mapped('partner_id')
                note.all_signed = all(
                    signer in signed_partners for signer in note.signer_ids
                )

    @api.depends('note_type', 'state')
    def _compute_is_locked(self):
        """計算是否鎖定（會議記錄寄出後鎖定）"""
        for note in self:
            note.is_locked = (
                note.note_type == 'meeting'
                and note.state in ('sent', 'partial', 'signed')
            )

    @api.depends('stage_ids')
    def _compute_stage_id(self):
        """計算當前用戶的階段"""
        first_user_stage = self.env['note.stage'].search(
            [('user_id', '=', self.env.uid)],
            limit=1,
        )
        for note in self:
            user_stages = note.stage_ids.filtered(
                lambda stage: stage.user_id == self.env.user
            )
            note.stage_id = user_stages[:1] or first_user_stage

    def _inverse_stage_id(self):
        """更新用戶階段關聯"""
        for note in self.filtered('stage_id'):
            other_user_stages = note.stage_ids.filtered(
                lambda stage: stage.user_id != self.env.user
            )
            note.stage_ids = note.stage_id | other_user_stages

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

    def write(self, vals):
        """覆寫 write 方法以實現鎖定檢查

        會議記錄在寄出簽名後，以下欄位將被鎖定：
        - memo (內容)
        - signer_ids (指定簽名者)
        - note_type (類型)
        """
        # 定義鎖定欄位清單
        locked_fields = {
            'memo', 'signer_ids', 'note_type',
        }

        # 允許的欄位（即使鎖定也可以修改）
        allowed_fields = {
            'state', 'signature_ids', 'access_token', 'is_locked',
            'all_signed', 'message_ids', 'activity_ids',
            # 筆記相關欄位（會議記錄鎖定時仍可改）
            'stage_id', 'stage_ids', 'tag_ids', 'color', 'sequence',
            'active', 'open', 'date_done',
            # 日曆事件可以在鎖定後新增
            'calendar_event_ids',
            # 錄音/逐字稿/摘要（鎖定後仍可操作）
            'recording_ids', 'transcript_ids', 'transcript_html',
            'transcript_state', 'speaker_mapping_ids',
            'meeting_summary', 'summary_state',
        }

        # 檢查是否嘗試修改鎖定欄位
        fields_to_modify = set(vals.keys())
        locked_fields_to_modify = fields_to_modify & locked_fields

        if locked_fields_to_modify:
            for note in self:
                # 只檢查已鎖定的會議記錄
                if note.is_locked:
                    # 檢查是否為重設草稿操作
                    if vals.get('state') == 'draft':
                        # 重設草稿時允許修改
                        continue

                    raise ValidationError(
                        _('Cannot modify locked meeting minutes.\n\n'
                          'The following fields are locked after sending for signature:\n'
                          '- Content (memo)\n'
                          '- Required Signers\n'
                          '- Type\n\n'
                          'To modify, please reset to draft first (this will clear all signatures).')
                    )

        return super().write(vals)

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
            'domain': [('note_id', '=', self.id)],
            'context': {'active_test': False},
        }

    def action_view_calendar_events(self):
        """查看關聯日曆事件"""
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Related Events'),
            'res_model': 'calendar.event',
            'view_mode': 'calendar,list,form',
            'views': [(False, 'calendar'), (False, 'list'), (False, 'form')],
            'domain': [('id', 'in', self.calendar_event_ids.ids)],
            'context': {
                'default_note_ids': [(4, self.id)],
            },
        }
        if len(self.calendar_event_ids) == 1:
            action['view_mode'] = 'form'
            action['views'] = [(False, 'form')]
            action['res_id'] = self.calendar_event_ids.id
        return action

    def action_add_calendar_event(self):
        """新增日曆事件並關聯到此筆記"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Schedule Meeting'),
            'res_model': 'calendar.event',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_name': self.name or _('Meeting'),
                'default_note_ids': [(4, self.id)],
            },
        }

    # ===== API 方法 =====
    def get_related_documents(self):
        """取得關聯文件（CRM/Task）- API 方法

        Returns:
            list: 包含關聯文件資訊的字典列表
        """
        self.ensure_one()
        activities = self.env['mail.activity'].with_context(active_test=False).search([
            ('note_id', '=', self.id),
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

    # ===== Portal 方法 =====
    def _compute_access_url(self):
        """計算 Portal 存取網址"""
        super()._compute_access_url()
        for note in self:
            note.access_url = f'/my/meeting/{note.id}'

    def _get_signer_status(self, partner):
        """檢查特定簽名者的簽名狀態

        Args:
            partner: res.partner 記錄

        Returns:
            bool: 是否已簽名
        """
        self.ensure_one()
        signature = self.signature_ids.filtered(
            lambda s: s.partner_id == partner and s.is_signed
        )
        return bool(signature)

    def _has_to_be_signed_by(self, partner):
        """檢查是否需要此人簽名

        Args:
            partner: res.partner 記錄

        Returns:
            bool: 是否需要此人簽名
        """
        self.ensure_one()
        return (
            self.note_type == 'meeting'
            and self.state in ('sent', 'partial')
            and partner in self.signer_ids
            and not self._get_signer_status(partner)
        )

    def _has_to_be_signed(self):
        """檢查會議記錄是否需要簽名"""
        self.ensure_one()
        return (
            self.note_type == 'meeting'
            and self.state in ('sent', 'partial')
            and self.signer_ids
            and not self.all_signed
        )

    def _check_all_signed(self):
        """檢查是否全部簽名完成，並更新狀態"""
        for note in self:
            if note.note_type != 'meeting':
                continue

            signed_partners = note.signature_ids.filtered('is_signed').mapped('partner_id')
            if not note.signer_ids:
                continue

            all_signed = all(signer in signed_partners for signer in note.signer_ids)
            some_signed = any(signer in signed_partners for signer in note.signer_ids)

            if all_signed:
                note.write({'state': 'signed'})
                # 發送簽名完成通知
                note.message_post(
                    body=_('All signers have signed the meeting minutes.'),
                    message_type='notification',
                )
            elif some_signed and note.state == 'sent':
                note.write({'state': 'partial'})

    def _get_signature_for_partner(self, partner):
        """取得特定合作夥伴的簽名記錄

        Args:
            partner: res.partner 記錄

        Returns:
            note.signature 記錄或 False
        """
        self.ensure_one()
        return self.signature_ids.filtered(lambda s: s.partner_id == partner)[:1]

    # ===== 會議記錄動作 =====
    def action_send_for_signature(self):
        """寄出會議記錄請求簽名"""
        self.ensure_one()
        if self.note_type != 'meeting':
            return

        if not self.calendar_event_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('Please link at least one calendar event before sending for signature.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        if not self.signer_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('Please specify at least one signer from the calendar event attendees.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # 驗證簽名者必須是行事曆參與者
        invalid_signers = self.signer_ids - self.available_signer_ids
        if invalid_signers:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('The following signers are not calendar event attendees: %(signers)s', signers=', '.join(invalid_signers.mapped('name'))),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # 確保有 access_token
        if not self.access_token:
            self.access_token = str(uuid.uuid4())

        # 為每位簽名者建立簽名記錄（如果不存在），批次建立
        existing_signers = self.signature_ids.mapped('partner_id')
        new_signers = self.signer_ids - existing_signers
        if new_signers:
            self.env['note.signature'].create([{
                'note_id': self.id,
                'partner_id': signer.id,
            } for signer in new_signers])

        # 更新狀態
        self.write({'state': 'sent'})

        # 為每位簽名者發送個別郵件（包含專屬簽名連結）
        template = self.env.ref(
            'dobtor_mail_activity.mail_template_meeting_minutes',
            raise_if_not_found=False
        )

        if template:
            failed_signers = []
            for signature in self.signature_ids.filtered(lambda s: not s.is_signed):
                signer_portal_url = signature._get_portal_url()
                try:
                    template.with_context(
                        signer_portal_url=signer_portal_url,
                        signer_name=signature.partner_id.name,
                    ).send_mail(
                        self.id,
                        force_send=False,
                        email_values={
                            'recipient_ids': [(4, signature.partner_id.id)],
                            'email_to': signature.partner_id.email,
                        },
                    )
                except Exception as e:
                    _logger.warning(
                        'Failed to send meeting minutes email to %s: %s',
                        signature.partner_id.name, str(e)
                    )
                    failed_signers.append(signature.partner_id.name)

            if failed_signers:
                self.message_post(
                    body=_('Meeting minutes sent for signature. Failed to notify: %(signers)s', signers=', '.join(failed_signers)),
                    message_type='notification',
                )
            else:
                self.message_post(
                    body=_('Meeting minutes sent for signature to: %(signers)s', signers=', '.join(self.signer_ids.mapped('name'))),
                    message_type='notification',
                )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Meeting minutes sent to %(count)d signer(s).', count=len(self.signer_ids)),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_signatures(self):
        """查看簽名記錄"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Signatures'),
            'res_model': 'note.signature',
            'view_mode': 'list,form',
            'domain': [('note_id', '=', self.id)],
            'context': {'default_note_id': self.id},
        }

    def action_reset_to_draft(self):
        """重設為草稿狀態"""
        self.ensure_one()
        if self.state != 'draft':
            self.write({'state': 'draft'})
            # 清除現有簽名
            self.signature_ids.unlink()
        return True

    def action_preview_portal(self):
        """在 Portal 預覽會議記錄"""
        self.ensure_one()
        if not self.access_token:
            self.access_token = str(uuid.uuid4())
        return {
            'type': 'ir.actions.act_url',
            'url': self.get_portal_url(),
            'target': 'new',
        }

    # ===== 錄音與逐字稿動作 =====
    def action_transcribe_all(self):
        """辨識所有已上傳的錄音"""
        self.ensure_one()
        recordings = self.recording_ids.filtered(lambda r: r.state in ('uploaded', 'error'))
        if not recordings:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Information'),
                    'message': _('No recordings to transcribe.'),
                    'type': 'info',
                    'sticky': False,
                }
            }
        # 一次傳入所有錄音，在單一 thread 中依序處理
        return recordings.action_transcribe()

    def action_generate_summary(self):
        """從逐字稿產生會議摘要（非同步）"""
        self.ensure_one()
        if not self.transcript_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('No transcript available. Please transcribe recordings first.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        company = self.env.company
        provider = company.summary_provider
        if not provider:
            raise UserError(_('Please configure a summary provider in Settings.'))

        handler = getattr(self, f'_summarize_{provider}', None)
        if not handler:
            raise UserError(_('Unsupported summary provider: %s', provider))

        self.write({'summary_state': 'processing'})

        # 在獨立 thread 中執行，避免阻塞
        db_name = self.env.cr.dbname
        note_id = self.id
        uid = self.env.uid

        thread = threading.Thread(
            target=self._async_summary_worker,
            args=(db_name, uid, note_id),
            daemon=True,
        )
        thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Summary Generation Started'),
                'message': _('Generating summary in background. You will be notified when complete.'),
                'type': 'info',
                'sticky': False,
            }
        }

    @api.model
    def _async_summary_worker(self, db_name, uid, note_id):
        """獨立 thread 中的摘要產生工作"""
        import odoo
        registry = odoo.registry(db_name)

        with registry.cursor() as cr:
            env = api.Environment(cr, uid, {})
            note = env['note.note'].browse(note_id)
            summary_state = 'error'

            try:
                transcript_text = note._format_transcript_for_llm()
                company = env.company
                provider = company.summary_provider

                prompt_template = company.summary_prompt_template or note._get_default_summary_prompt()
                prompt = prompt_template.replace('{transcript}', transcript_text)

                handler = getattr(note, f'_summarize_{provider}')
                summary_html = handler(prompt)

                note.write({
                    'meeting_summary': summary_html,
                    'summary_state': 'done',
                })
                summary_state = 'done'
                cr.commit()
            except Exception as e:
                cr.rollback()
                env.invalidate_all()
                _logger.exception('Summary generation failed for note %s', note_id)
                note.write({'summary_state': 'error'})
                cr.commit()

            # 發送 bus.bus 通知（用已確定的 state，避免讀取 rollback 後的快取）
            try:
                env['bus.bus']._sendone(
                    env.user.partner_id,
                    'note_recording/summary_update',
                    {
                        'note_id': note_id,
                        'summary_state': summary_state,
                    },
                )
                cr.commit()
            except Exception:
                cr.rollback()
                _logger.exception('Failed to send bus notification for summary %s', note_id)

    def action_apply_summary_to_memo(self):
        """將摘要寫入 memo 欄位"""
        self.ensure_one()
        if self.is_locked:
            raise UserError(_('Meeting minutes is locked. Cannot modify content.'))
        if not self.meeting_summary:
            raise UserError(_('No summary available to apply.'))
        self.memo = (self.memo or '') + '<hr/>' + self.meeting_summary
        return True

    # ===== 逐字稿匯出 =====
    def action_export_transcript_txt(self):
        """匯出逐字稿為 TXT 檔"""
        self.ensure_one()
        if not self.transcript_ids:
            raise UserError(_('No transcript available to export.'))

        content = self._format_transcript_for_llm()
        filename = f"transcript_{self.name or self.id}.txt"

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content.encode('utf-8')),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'text/plain',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def action_export_transcript_srt(self):
        """匯出逐字稿為 SRT 字幕檔"""
        self.ensure_one()
        if not self.transcript_ids:
            raise UserError(_('No transcript available to export.'))

        lines = []
        for idx, seg in enumerate(self.transcript_ids.sorted('time_start'), 1):
            start_srt = self._seconds_to_srt_time(seg.time_start)
            end_srt = self._seconds_to_srt_time(seg.time_end)
            name = seg.speaker_name or seg.speaker_label or ''
            prefix = f'[{name}] ' if name else ''
            lines.append(f'{idx}')
            lines.append(f'{start_srt} --> {end_srt}')
            lines.append(f'{prefix}{seg.text}')
            lines.append('')

        content = '\n'.join(lines)
        filename = f"transcript_{self.name or self.id}.srt"

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content.encode('utf-8')),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/x-subrip',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    @staticmethod
    def _seconds_to_srt_time(seconds):
        """將秒數轉換為 SRT 時間格式 HH:MM:SS,mmm"""
        total_ms = int((seconds or 0) * 1000)
        hours, remainder = divmod(total_ms, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        secs, ms = divmod(remainder, 1000)
        return f'{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}'

    def _format_transcript_for_llm(self):
        """將逐字稿格式化為 LLM 輸入文字"""
        self.ensure_one()
        lines = []
        for seg in self.transcript_ids.sorted('time_start'):
            name = seg.speaker_name or seg.speaker_label or _('Unknown')
            minutes = int(seg.time_start // 60)
            seconds = int(seg.time_start % 60)
            time_str = f'{minutes:02d}:{seconds:02d}'
            lines.append(f'[{time_str}] {name}：{seg.text}')
        return '\n'.join(lines)

    @api.model
    def _get_default_summary_prompt(self):
        """取得摘要 Prompt — 依公司設定的 preset 或自訂"""
        company = self.env.company
        preset_key = company.summary_prompt_preset
        if preset_key and preset_key in SUMMARY_PROMPT_PRESETS:
            return SUMMARY_PROMPT_PRESETS[preset_key]['prompt']
        # fallback: formal
        return SUMMARY_PROMPT_PRESETS['formal']['prompt']

    @api.model
    def get_summary_prompt_presets(self):
        """回傳可用的 prompt 預設清單（給前端使用）"""
        return [
            {'key': k, 'name': v['name'], 'name_zh': v['name_zh']}
            for k, v in SUMMARY_PROMPT_PRESETS.items()
        ]

    def _summarize_claude(self, prompt):
        """使用 Claude API 產生摘要"""
        api_key = self.env['ir.config_parameter'].sudo().get_param('dobtor_mail_activity.summary_api_key')
        if not api_key:
            raise UserError(_('Please configure the summary API key in Settings.'))

        try:
            response = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                },
                json={
                    'model': 'claude-sonnet-4-20250514',
                    'max_tokens': 4096,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=120,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise UserError(_('Claude API error: %s', str(e)))
        result = response.json()
        return result['content'][0]['text']

    def _summarize_openai(self, prompt):
        """使用 OpenAI API 產生摘要"""
        api_key = self.env['ir.config_parameter'].sudo().get_param('dobtor_mail_activity.summary_api_key')
        if not api_key:
            raise UserError(_('Please configure the summary API key in Settings.'))

        try:
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': 'gpt-4o',
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': 4096,
                },
                timeout=120,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise UserError(_('OpenAI API error: %s', str(e)))
        result = response.json()
        return result['choices'][0]['message']['content']

    def _summarize_ollama(self, prompt):
        """使用本地 Ollama 產生摘要"""
        company = self.env.company
        api_url = company.summary_api_url
        if not api_url:
            raise UserError(_('Please configure the Ollama API URL in Settings.'))

        try:
            response = requests.post(
                f'{api_url.rstrip("/")}/api/generate',
                json={
                    'model': company.summary_model_name or 'llama3',
                    'prompt': prompt,
                    'stream': False,
                },
                timeout=300,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise UserError(_('Ollama API error: %s', str(e)))
        result = response.json()
        return result.get('response', '')
