# -*- coding: utf-8 -*-

from odoo import api, fields, models


class NoteTranscriptSegment(models.Model):
    """逐字稿段落

    儲存語音辨識的每一段文字，包含：
    - 說話者標籤（SPEAKER_00, SPEAKER_01 等）
    - 時間戳記（開始/結束秒數）
    - 辨識文字內容
    - 信心度分數
    """
    _name = 'note.transcript.segment'
    _description = 'Transcript Segment'
    _order = 'time_start, id'

    note_id = fields.Many2one(
        'note.note',
        string='Meeting Minutes',
        required=True,
        ondelete='cascade',
        index=True,
    )
    recording_id = fields.Many2one(
        'note.recording',
        string='Recording',
        ondelete='cascade',
        index=True,
    )
    speaker_label = fields.Char(
        string='Speaker Label',
        help='Auto-detected speaker label (e.g. SPEAKER_00)',
    )
    speaker_name = fields.Char(
        string='Speaker Name',
        compute='_compute_speaker_name',
        store=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        compute='_compute_speaker_name',
        store=True,
        help='Mapped contact from speaker mapping',
    )
    time_start = fields.Float(
        string='Start (seconds)',
    )
    time_end = fields.Float(
        string='End (seconds)',
    )
    text = fields.Text(
        string='Content',
        required=True,
    )
    confidence = fields.Float(
        string='Confidence',
        digits=(4, 3),
    )

    # ===== 計算方法 =====
    @api.depends('speaker_label', 'note_id.speaker_mapping_ids.speaker_label',
                 'note_id.speaker_mapping_ids.partner_id',
                 'note_id.speaker_mapping_ids.display_name_override')
    def _compute_speaker_name(self):
        """從 speaker mapping 取得說話者名稱"""
        for seg in self:
            mapping = seg.note_id.speaker_mapping_ids.filtered(
                lambda m: m.speaker_label == seg.speaker_label
            )[:1]
            if mapping:
                seg.partner_id = mapping.partner_id
                seg.speaker_name = (
                    mapping.partner_id.name
                    or mapping.display_name_override
                    or seg.speaker_label
                )
            else:
                seg.partner_id = False
                seg.speaker_name = seg.speaker_label

    def _format_time(self, seconds):
        """將秒數格式化為 MM:SS"""
        total = int(seconds or 0)
        minutes, secs = divmod(total, 60)
        return f'{minutes:02d}:{secs:02d}'
