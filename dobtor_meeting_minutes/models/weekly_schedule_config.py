# -*- coding: utf-8 -*-
"""週排程 × 筆記：目標文件可選「筆記」，並可自動建立週筆記（自 dobtor_mail_activity 搬入）。"""

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class WeeklyScheduleConfig(models.Model):
    _inherit = 'weekly.schedule.config'

    target_model = fields.Selection(
        selection_add=[('note.note', 'Note')],
        ondelete={'note.note': 'set default'},
    )
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

    @api.onchange('target_model')
    def _onchange_target_model(self):
        """當關聯文件類型變更時，清除筆記本選擇"""
        if self.target_model != 'note.note':
            self.note_id = False
            self.auto_create_note = False

    def _get_target_record(self):
        self.ensure_one()
        if self.target_model != 'note.note':
            return super()._get_target_record()
        if self.note_id:
            return ('note.note', self.note_id.id)
        if self.auto_create_note:
            today = fields.Date.today()
            iso_year, iso_week, _dow = today.isocalendar()
            week_str = '%d-W%02d' % (iso_year, iso_week)
            note = self.env['note.note'].create({
                'user_id': self.user_id.id,
                'memo': _('<p>Weekly Schedule - %(week)s</p><p>This week work plan</p>', week=week_str),
            })
            return ('note.note', note.id)
        _logger.warning(
            'Weekly schedule config %s: no note specified, falling back to user.', self.id)
        return ('res.users', self.user_id.id)
