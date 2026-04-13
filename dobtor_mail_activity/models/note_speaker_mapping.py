# -*- coding: utf-8 -*-

from odoo import fields, models


class NoteSpeakerMapping(models.Model):
    """說話者身分對應

    將語音辨識產生的匿名標籤（SPEAKER_00）
    對應到實際的會議出席者或手動輸入的姓名。
    """
    _name = 'note.speaker.mapping'
    _description = 'Speaker Mapping'
    _order = 'speaker_label'

    note_id = fields.Many2one(
        'note.note',
        string='Meeting Minutes',
        required=True,
        ondelete='cascade',
        index=True,
    )
    speaker_label = fields.Char(
        string='Speaker Label',
        required=True,
        help='Auto-detected label (e.g. SPEAKER_00)',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        help='Map to a meeting attendee',
    )
    display_name_override = fields.Char(
        string='Display Name',
        help='Manual name override (used when not mapped to a contact)',
    )

    _sql_constraints = [
        ('unique_note_speaker', 'UNIQUE(note_id, speaker_label)',
         'Each speaker label must be unique per meeting minutes.'),
    ]
