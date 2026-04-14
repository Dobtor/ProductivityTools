# -*- coding: utf-8 -*-

import base64
import logging
import uuid
import threading

from markupsafe import escape as html_escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

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
    """會議記錄擴展

    在 note.note 基礎上新增會議記錄功能，包含：
    - 錄音與逐字稿（STT + 說話者辨識）
    - AI 摘要產生（透過 ChatbotEngine）
    - 簽名流程（Portal 多方簽名）
    - PDF 報告

    portal.mixin 透過 dobtor_mail_activity 的 base model 繼承鏈已包含，
    此處不重複混入以避免 Many2many 欄位衝突。
    """
    _inherit = 'note.note'

    # ===== 會議記錄類型 =====
    note_type = fields.Selection(
        selection_add=[('meeting', 'Meeting Minutes')],
        ondelete={'meeting': 'set default'},
    )

    # ===== 狀態 =====
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('partial', 'Partially Signed'),
        ('signed', 'Fully Signed'),
    ], string='Status', default='draft', tracking=True)

    # ===== 鎖定狀態 =====
    is_locked = fields.Boolean(
        string='Locked',
        compute='_compute_is_locked',
        store=True,
        help='Meeting minutes is locked after being sent for signature',
    )

    # ===== 簽名者 =====
    signer_ids = fields.Many2many(
        'res.partner',
        'note_note_signer_rel',
        'note_id',
        'partner_id',
        string='Required Signers',
        help='Partners who must sign this meeting minutes',
    )

    # ===== 簽名記錄 =====
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

    # ===== 可選擇的簽名者 =====
    available_signer_ids = fields.Many2many(
        'res.partner',
        string='Available Signers',
        compute='_compute_available_signer_ids',
        help='Partners who can be selected as signers (from calendar event attendees)',
    )

    # ===== 錄音與逐字稿 =====
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

    # ===== 會議摘要 =====
    meeting_summary = fields.Html(
        string='Meeting Summary',
    )
    summary_state = fields.Selection([
        ('none', 'None'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], string='Summary Status', default='none')

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

    @api.depends('calendar_event_ids', 'calendar_event_ids.partner_ids')
    def _compute_available_signer_ids(self):
        """計算可選擇的簽名者（從關聯行事曆事件的參與者中取得）"""
        for note in self:
            partners = self.env['res.partner']
            for event in note.calendar_event_ids:
                partners |= event.partner_ids
            note.available_signer_ids = partners

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

    # ===== CRUD 方法 =====
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
                if note.is_locked:
                    # 重設草稿時允許修改
                    if vals.get('state') == 'draft':
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

    # ===== Portal 方法 =====
    def _compute_access_url(self):
        """計算 Portal 存取網址"""
        super()._compute_access_url()
        for note in self:
            note.access_url = f'/my/meeting/{note.id}'

    def _get_signer_status(self, partner):
        """檢查特定簽名者的簽名狀態"""
        self.ensure_one()
        signature = self.signature_ids.filtered(
            lambda s: s.partner_id == partner and s.is_signed
        )
        return bool(signature)

    def _has_to_be_signed_by(self, partner):
        """檢查是否需要此人簽名"""
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
                note.message_post(
                    body=_('All signers have signed the meeting minutes.'),
                    message_type='notification',
                )
            elif some_signed and note.state == 'sent':
                note.write({'state': 'partial'})

    def _get_signature_for_partner(self, partner):
        """取得特定合作夥伴的簽名記錄"""
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
                    'message': _('The following signers are not calendar event attendees: %(signers)s',
                                 signers=', '.join(invalid_signers.mapped('name'))),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # 確保有 access_token
        if not self.access_token:
            self.access_token = str(uuid.uuid4())

        # 為每位簽名者建立簽名記錄（如果不存在）
        existing_signers = self.signature_ids.mapped('partner_id')
        new_signers = self.signer_ids - existing_signers
        if new_signers:
            self.env['note.signature'].create([{
                'note_id': self.id,
                'partner_id': signer.id,
            } for signer in new_signers])

        # 更新狀態
        self.write({'state': 'sent'})

        # 為每位簽名者發送個別郵件
        template = self.env.ref(
            'dobtor_meeting_minutes.mail_template_meeting_minutes',
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
                    body=_('Meeting minutes sent for signature. Failed to notify: %(signers)s',
                           signers=', '.join(failed_signers)),
                    message_type='notification',
                )
            else:
                self.message_post(
                    body=_('Meeting minutes sent for signature to: %(signers)s',
                           signers=', '.join(self.signer_ids.mapped('name'))),
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
        return recordings.action_transcribe()

    # ===== AI 摘要（透過 ChatbotEngine）=====
    def action_generate_summary(self):
        """從逐字稿產生會議摘要（非同步，透過 ChatbotEngine）"""
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

        chatbot = self.env.company.meeting_summary_chatbot_id
        if not chatbot:
            raise UserError(_(
                'Please configure a Meeting Summary AI Chatbot in Settings > Productivity Tools.'
            ))

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
        """獨立 thread 中的摘要產生工作（使用 ChatbotEngine）"""
        import odoo
        registry = odoo.registry(db_name)

        with registry.cursor() as cr:
            env = api.Environment(cr, uid, {})
            note = env['note.note'].browse(note_id)
            summary_state = 'error'

            try:
                transcript_text = note._format_transcript_for_llm()
                prompt = note._get_default_summary_prompt()
                prompt = prompt.replace('{transcript}', transcript_text)

                summary_html = note._generate_summary_via_chatbot(prompt)

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

            # 發送 bus.bus 通知
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

    def _generate_summary_via_chatbot(self, prompt):
        """使用 ChatbotEngine 產生會議摘要

        Args:
            prompt: 完整的 prompt 文字（含逐字稿）

        Returns:
            str: AI 回覆的 HTML 摘要文字

        Raises:
            UserError: 當 chatbot 未設定或 API 呼叫失敗時
        """
        self.ensure_one()
        chatbot = self.env.company.meeting_summary_chatbot_id
        if not chatbot:
            raise UserError(_(
                'Please configure a Meeting Summary AI Chatbot in Settings > Productivity Tools.'
            ))

        from odoo.addons.dobtor_ai_chatbot.services.chatbot_engine import ChatbotEngine

        engine = ChatbotEngine(self.env, chatbot)
        result = engine.chat(
            message=prompt,
            enable_tools=False,
            save_conversation=False,
        )

        if not result.get('success'):
            error_msg = result.get('error', 'Unknown error')
            raise UserError(_('AI summary generation failed: %s', error_msg))

        content = result.get('content', '')
        if not content:
            raise UserError(_('AI returned empty summary.'))

        return content

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
        """取得摘要 Prompt -- 依公司設定的 preset"""
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
