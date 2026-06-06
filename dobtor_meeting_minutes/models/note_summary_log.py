# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class NoteSummaryLog(models.Model):
    """會議摘要執行紀錄 — 與 note.transcribe.log 對稱

    追蹤每次摘要產生的結果：
    - 錯誤分類與診斷（chatbot_error / parse_error / config_error）
    - chatbot token 使用量與延遲
    - 歷史 prompt 長度（輸入控制）
    """
    _name = 'note.summary.log'
    _description = 'Summary Generation Log'
    _order = 'create_date desc, id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name', store=True)

    note_id = fields.Many2one(
        'note.note',
        string='Meeting',
        required=True,
        ondelete='cascade',
        index=True,
    )
    chatbot_id = fields.Many2one('ai.chatbot', string='Chatbot')
    template_id = fields.Many2one(
        'note.summary.template',
        string='Prompt Template',
    )

    attempt_no = fields.Integer(
        string='Attempt #',
        default=1,
        required=True,
    )

    state = fields.Selection([
        ('success', 'Success'),
        ('config_error', 'Config Error'),
        ('chatbot_error', 'Chatbot Error'),
        ('empty_response', 'Empty Response'),
        ('parse_error', 'Parse Error'),
        ('stale_worker', 'Stale Worker'),
        ('internal_error', 'Internal Error'),
    ], string='Result', required=True, index=True, default='internal_error')

    error_message = fields.Text()
    traceback = fields.Text()

    prompt_length = fields.Integer(
        string='Prompt Chars',
        help='Length of the full prompt sent to the chatbot.',
    )
    transcript_length = fields.Integer(
        string='Transcript Chars',
        help='Length of the transcript text injected into the prompt.',
    )
    response_length = fields.Integer(
        string='Response Chars',
    )
    request_latency_ms = fields.Integer(string='Latency (ms)')

    started_at = fields.Datetime()
    ended_at = fields.Datetime()

    retriable = fields.Boolean(
        compute='_compute_retriable',
        store=True,
    )

    @api.depends('state')
    def _compute_retriable(self):
        retriable_codes = ('chatbot_error', 'stale_worker', 'empty_response')
        for log in self:
            log.retriable = log.state in retriable_codes

    @api.depends('note_id', 'attempt_no', 'state')
    def _compute_display_name(self):
        state_dict = dict(self._fields['state'].selection)
        for log in self:
            note_name = (log.note_id.name or f'#{log.note_id.id}') if log.note_id else '?'
            log.display_name = _(
                '%(note)s / attempt %(n)s / %(state)s',
                note=note_name, n=log.attempt_no,
                state=state_dict.get(log.state, log.state),
            )

    def action_retry(self):
        """從 log 觸發該 note 的摘要重新產生"""
        self.ensure_one()
        if not self.retriable:
            raise UserError(_('This failure is not retriable.'))
        return self.note_id.action_generate_summary()

    def action_open_note(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'note.note',
            'res_id': self.note_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
