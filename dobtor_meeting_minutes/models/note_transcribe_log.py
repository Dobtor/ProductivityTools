# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..utils.constants import (
    TRANSCRIPTION_PROVIDER_SELECTION,
    TRANSCRIBE_LOG_STATE_SELECTION,
    RETRIABLE_ERROR_CODES,
)


class NoteTranscribeLog(models.Model):
    """逐字稿執行紀錄

    每次 transcribe 執行（成功或失敗）皆建立一筆，用於：
    - 錯誤分類與診斷（provider / http_status / response_snippet / traceback）
    - 重試判定（retriable 依 state 計算）
    - 統計與趨勢（pivot by provider × state × day）
    - 監控告警（連續失敗時觸發 activity + message_post）
    """
    _name = 'note.transcribe.log'
    _description = 'Transcription Execution Log'
    _order = 'create_date desc, id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name', store=True)

    recording_id = fields.Many2one(
        'note.recording',
        string='Recording',
        required=True,
        ondelete='cascade',
        index=True,
    )
    note_id = fields.Many2one(
        'note.note',
        related='recording_id.note_id',
        store=True,
        index=True,
    )

    provider = fields.Selection(selection=TRANSCRIPTION_PROVIDER_SELECTION)

    attempt_no = fields.Integer(
        string='Attempt #',
        default=1,
        required=True,
    )

    state = fields.Selection(
        selection=TRANSCRIBE_LOG_STATE_SELECTION,
        string='Result',
        required=True, index=True,
        default='internal_error',
    )

    error_message = fields.Text()
    http_status = fields.Integer()
    http_url = fields.Char()
    response_snippet = fields.Text(
        help='First 2KB of HTTP response body (sensitive data masked).',
    )
    traceback = fields.Text()

    request_latency_ms = fields.Integer(string='Latency (ms)')
    audio_bytes = fields.Integer(string='Audio Size (bytes)')
    audio_duration = fields.Float(string='Audio Duration (s)')

    started_at = fields.Datetime()
    ended_at = fields.Datetime()

    retriable = fields.Boolean(
        compute='_compute_retriable',
        store=True,
        help='Whether this failure class is eligible for automatic retry.',
    )

    @api.depends('state', 'http_status')
    def _compute_retriable(self):
        for log in self:
            if log.state in RETRIABLE_ERROR_CODES:
                log.retriable = True
            elif log.state == 'http_error' and log.http_status and log.http_status >= 500:
                log.retriable = True
            else:
                log.retriable = False

    @api.depends('recording_id', 'attempt_no', 'state')
    def _compute_display_name(self):
        state_dict = dict(self._fields['state'].selection)
        for log in self:
            rec_name = (log.recording_id.name or f'#{log.recording_id.id}') if log.recording_id else '?'
            log.display_name = _(
                '%(rec)s / attempt %(n)s / %(state)s',
                rec=rec_name, n=log.attempt_no,
                state=state_dict.get(log.state, log.state),
            )

    def action_retry(self):
        """從 log 觸發該錄音的重試（僅 retriable 可用）"""
        self.ensure_one()
        if not self.retriable:
            raise UserError(_('This failure is not retriable.'))
        return self.recording_id.action_retry_transcribe()

    def action_open_recording(self):
        """跳轉到對應錄音表單"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'note.recording',
            'res_id': self.recording_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
