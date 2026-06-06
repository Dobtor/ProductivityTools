# -*- coding: utf-8 -*-

import base64
import io
import logging
import os
import time
import threading
import traceback as tb_module

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..utils.constants import (
    MAX_RECORDING_DURATION, MAX_FILE_SIZE,
    STALE_PROCESSING_MINUTES,
    AUTO_RETRY_BACKOFF_MINUTES, AUTO_RETRY_MAX_ATTEMPTS,
    CONSECUTIVE_FAILURE_ALERT,
    RESPONSE_SNIPPET_LIMIT,
    LOG_RETENTION_DAYS_SUCCESS, LOG_RETENTION_DAYS_FAILURE,
    RECORDING_STATE_SELECTION,
    VALID_TRANSCRIBE_ERROR_CODES,
    HTTP_TIMEOUT_UPLOAD, HTTP_TIMEOUT_SUBMIT, HTTP_TIMEOUT_POLL, HTTP_TIMEOUT_FULL,
    MAX_POLL_WAIT, POLL_INTERVAL,
)
from ..utils.security import mask_secrets
from ..utils.crypto import decrypt as crypto_decrypt

_logger = logging.getLogger(__name__)


class TranscribeError(Exception):
    """分類化的轉錄錯誤

    用 code 區分錯誤類型，讓前端、log 與監控可做差異化處理。
    """

    def __init__(self, code, message, http_status=None, response_snippet=None, http_url=None):
        self.code = code if code in VALID_TRANSCRIBE_ERROR_CODES else 'internal_error'
        self.message = message
        self.http_status = http_status or 0
        self.response_snippet = response_snippet
        self.http_url = http_url
        super().__init__(message)


class NoteRecording(models.Model):
    _name = 'note.recording'
    _description = 'Meeting Recording'
    _order = 'record_start, id'

    note_id = fields.Many2one(
        'note.note',
        string='Meeting Minutes',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(
        compute='_compute_name',
        store=True,
    )
    attachment_id = fields.Many2one(
        'ir.attachment',
        string='Audio File',
        required=True,
        ondelete='cascade',
    )
    duration = fields.Float(string='Duration (seconds)')
    record_start = fields.Datetime()
    record_end = fields.Datetime()
    time_offset = fields.Float(
        string='Time Offset (seconds)',
        compute='_compute_time_offset',
        store=True,
        help='Offset relative to the first recording, for merging multi-segment transcripts.',
    )
    file_format = fields.Char()
    file_size = fields.Integer(string='File Size (bytes)')
    state = fields.Selection(
        selection=RECORDING_STATE_SELECTION,
        string='Status', default='uploaded', required=True,
    )
    error_message = fields.Text(
        help='Summary from the latest transcription attempt. See Transcription History for full detail.',
    )
    audio_url = fields.Char(
        string='Audio URL',
        compute='_compute_audio_url',
        store=True,
    )

    # Worker 偵測（T1）— 讓 cleanup cron 能快速識別死 thread
    worker_pid = fields.Integer(
        string='Worker PID',
        help='OS PID of the thread currently processing this recording. '
             'Cleared on completion. Used by cleanup cron to detect dead workers.',
    )
    worker_started_at = fields.Datetime(
        string='Worker Started At',
        help='When the current worker started processing.',
    )

    # 錯誤追蹤
    log_ids = fields.One2many(
        'note.transcribe.log', 'recording_id',
        string='Transcription History',
    )
    log_count = fields.Integer(compute='_compute_log_count')
    latest_log_id = fields.Many2one(
        'note.transcribe.log',
        compute='_compute_latest_log',
    )
    can_retry = fields.Boolean(
        compute='_compute_latest_log',
        help='True when state=error and latest log is retriable and under max attempts.',
    )

    @api.depends('record_start')
    def _compute_name(self):
        for rec in self:
            if rec.record_start:
                rec.name = _('Recording %s', rec.record_start.strftime('%Y-%m-%d %H:%M'))
            else:
                rec.name = _('Recording #%s', rec.id or 'new')

    @api.depends('attachment_id')
    def _compute_audio_url(self):
        for rec in self:
            rec.audio_url = f'/web/content/{rec.attachment_id.id}?download=false' if rec.attachment_id else False

    @api.depends('record_start', 'note_id.recording_ids.record_start')
    def _compute_time_offset(self):
        for rec in self:
            if not rec.record_start or not rec.note_id:
                rec.time_offset = 0.0
                continue
            siblings = rec.note_id.recording_ids.filtered('record_start').sorted('record_start')
            if not siblings:
                rec.time_offset = 0.0
                continue
            rec.time_offset = (rec.record_start - siblings[0].record_start).total_seconds()

    @api.depends('log_ids')
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.log_ids)

    @api.depends('log_ids', 'state')
    def _compute_latest_log(self):
        for rec in self:
            last = rec.log_ids.sorted('id', reverse=True)[:1]
            rec.latest_log_id = last.id if last else False
            rec.can_retry = bool(
                rec.state == 'error' and last and last.retriable
                and last.attempt_no < AUTO_RETRY_MAX_ATTEMPTS
            )

    def _format_duration(self):
        self.ensure_one()
        total = int(self.duration or 0)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        return f'{minutes:02d}:{seconds:02d}'

    def _format_error_summary(self, log):
        parts = []
        provider_label = dict(log._fields['provider'].selection).get(log.provider) if log.provider else None
        if provider_label:
            parts.append(f'[{provider_label}]')
        state_label = dict(log._fields['state'].selection).get(log.state, log.state)
        parts.append(state_label)
        if log.http_status:
            parts.append(f'HTTP {log.http_status}')
        header = ' '.join(parts)
        body = (log.error_message or '').strip()
        return f'{header}\n{body}' if body else header

    # ===== 業務方法 =====
    @api.model
    def create_from_browser(self, vals):
        note = self.env['note.note'].browse(vals['note_id'])
        if not note.exists():
            raise UserError(_('Meeting minutes not found.'))
        note.check_access_rights('write')
        note.check_access_rule('write')

        audio_b64 = vals.get('audio_base64', '')
        if audio_b64:
            file_size = len(base64.b64decode(audio_b64))
            if file_size > MAX_FILE_SIZE:
                raise UserError(_(
                    'Recording file is too large (%(size).1f MB). Maximum allowed is %(max).0f MB.',
                    size=file_size / (1024 * 1024),
                    max=MAX_FILE_SIZE / (1024 * 1024),
                ))
        else:
            file_size = 0

        duration = vals.get('duration', 0)
        if duration > MAX_RECORDING_DURATION:
            raise UserError(_(
                'Recording is too long (%(dur).0f minutes). Maximum allowed is %(max).0f minutes.',
                dur=duration / 60,
                max=MAX_RECORDING_DURATION / 60,
            ))

        record_start = self._parse_iso_datetime(vals.get('record_start'))
        record_end = self._parse_iso_datetime(vals.get('record_end'))
        file_format = vals.get('file_format', 'webm')

        attachment = self.env['ir.attachment'].create({
            'name': f"recording_{record_start or fields.Datetime.now()}.{file_format}",
            'type': 'binary',
            'datas': audio_b64,
            'res_model': 'note.note',
            'res_id': note.id,
            'mimetype': f"audio/{file_format}",
        })

        recording = self.create({
            'note_id': note.id,
            'attachment_id': attachment.id,
            'duration': duration,
            'record_start': record_start,
            'record_end': record_end,
            'file_format': file_format,
            'file_size': file_size,
        })

        return {
            'id': recording.id,
            'name': recording.name,
            'duration': recording.duration,
            'state': recording.state,
        }

    @api.model
    def _parse_iso_datetime(self, iso_str):
        if not iso_str:
            return False
        try:
            return fields.Datetime.to_datetime(
                iso_str.replace('T', ' ').replace('Z', '')[:19]
            )
        except (ValueError, AttributeError):
            return fields.Datetime.now()

    def action_transcribe(self):
        """觸發語音辨識（非同步）— 先 create job 再 spawn thread

        Job row 作為持久化佇列：即使 thread 立即死亡，cron 可接手。
        """
        for rec in self:
            if rec.state == 'processing':
                raise UserError(_('This recording is already being processed.'))

        # 建立 pending jobs（unique constraint 會擋重複）
        self.env['note.transcribe.job'].create_for_recordings(self)

        for rec in self:
            rec.write({'state': 'processing', 'error_message': False})

        for note in self.mapped('note_id'):
            note.write({'transcript_state': 'processing'})

        # 先 commit job + state，確保重啟也能被 cron 接手
        self.env.cr.commit()

        db_name = self.env.cr.dbname
        recording_ids = self.ids
        uid = self.env.uid

        thread = threading.Thread(
            target=self._async_transcribe_worker,
            args=(db_name, uid, recording_ids),
            daemon=True,
        )
        thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transcription Started'),
                'message': _('Processing %d recording(s) in background. You will be notified when complete.', len(self)),
                'type': 'info',
                'sticky': False,
            }
        }

    def action_retry_transcribe(self):
        """使用者手動重試（檢查次數上限）"""
        for rec in self:
            last = rec.latest_log_id
            if last and last.attempt_no >= AUTO_RETRY_MAX_ATTEMPTS:
                raise UserError(_(
                    'Maximum retry attempts (%d) reached. Please check Settings and try again manually.',
                    AUTO_RETRY_MAX_ATTEMPTS,
                ))
        return self.action_transcribe()

    def action_cancel_processing(self):
        """取消卡住的處理（手動介入）"""
        for rec in self:
            if rec.state != 'processing':
                raise UserError(_('Only processing recordings can be cancelled.'))
        self.env['note.transcribe.log'].create([{
            'recording_id': rec.id,
            'provider': self.env.company.transcription_provider or False,
            'attempt_no': rec._next_attempt_no(),
            'state': 'stale_worker',
            'error_message': _('Cancelled by user.'),
            'audio_bytes': rec.file_size or 0,
            'audio_duration': rec.duration or 0,
            'started_at': rec.write_date,
            'ended_at': fields.Datetime.now(),
        } for rec in self])
        self.write({
            'state': 'error',
            'error_message': _('Cancelled by user.'),
        })
        for note in self.mapped('note_id'):
            note._recompute_transcript_state()
        return True

    @api.model
    def _async_transcribe_worker(self, db_name, uid, recording_ids):
        """獨立 thread 中執行辨識 — 每筆錄音寫一筆 transcribe.log + 更新 job"""
        import odoo
        registry = odoo.registry(db_name)

        with registry.cursor() as cr:
            env = api.Environment(cr, uid, {})
            recordings = env['note.recording'].browse(recording_ids)
            total = len(recording_ids)
            Job = env['note.transcribe.job']

            for idx, rec in enumerate(recordings, 1):
                # 嘗試 claim 對應 job（如有）
                job = Job.search(
                    [('recording_id', '=', rec.id), ('state', '=', 'pending')],
                    limit=1, order='id desc',
                )
                if job:
                    # Atomic transition pending → running
                    self.env.cr.execute("""
                        UPDATE note_transcribe_job
                        SET state='running', picked_at=NOW(), worker_pid=%s
                        WHERE id=%s AND state='pending'
                    """, (os.getpid(), job.id))
                    if self.env.cr.rowcount == 0:
                        job = Job.browse()  # someone else claimed; just process rec
                    cr.commit()

                rec._run_single_transcription(cr, env, idx, total)

                # 更新 job 狀態
                if job and job.exists():
                    rec.invalidate_recordset(['state', 'latest_log_id', 'error_message'])
                    if rec.state == 'done':
                        job._mark_done(rec.latest_log_id)
                    else:
                        job._mark_failed(
                            rec.error_message or 'Unknown',
                            rec.latest_log_id,
                        )
                    cr.commit()

    @staticmethod
    def _is_pid_alive(pid):
        """檢查 OS 上是否還存在該 PID（跨平台；Windows 會以 psutil-like fallback 判斷）

        注意：PID 可能被重用，故搭配 worker_started_at 門檻使用才可靠。
        """
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False

    def _run_single_transcription(self, cr, env, idx, total):
        """單筆錄音的完整執行流程（成功/失敗皆寫 log）"""
        self.ensure_one()
        rec = self
        Log = env['note.transcribe.log']
        # 優先讀 note 所屬公司（multi-company 情境下，thread env.company 可能不對）
        provider_company = rec.note_id.company_id or env.company
        provider = provider_company.transcription_provider or False
        attempt_no = rec._next_attempt_no()
        started_at = fields.Datetime.now()
        t0 = time.monotonic()

        # 寫入 worker 指紋（T1 — 幫助 cleanup cron 偵測死 thread）
        try:
            rec.write({
                'worker_pid': os.getpid(),
                'worker_started_at': started_at,
            })
            cr.commit()
        except Exception:
            cr.rollback()
            _logger.exception('[transcribe] failed to stamp worker PID on recording=%s', rec.id)

        log_base = {
            'recording_id': rec.id,
            'provider': provider,
            'attempt_no': attempt_no,
            'audio_bytes': rec.file_size or 0,
            'audio_duration': rec.duration or 0,
            'started_at': started_at,
        }

        error_code = None
        error_msg = None
        log = False

        try:
            rec._process_transcription()
            cr.commit()
            log = Log.create({
                **log_base,
                'state': 'success',
                'ended_at': fields.Datetime.now(),
                'request_latency_ms': int((time.monotonic() - t0) * 1000),
            })
            cr.commit()
        except TranscribeError as e:
            cr.rollback()
            env.invalidate_all()
            error_code = e.code
            error_msg = e.message
            _logger.warning(
                '[transcribe] recording=%s provider=%s code=%s attempt=%s: %s',
                rec.id, provider, error_code, attempt_no, error_msg,
            )
            log = Log.create({
                **log_base,
                'state': e.code,
                'error_message': error_msg,
                'http_status': e.http_status,
                'http_url': e.http_url,
                'response_snippet': e.response_snippet,
                'traceback': mask_secrets(tb_module.format_exc()),
                'ended_at': fields.Datetime.now(),
                'request_latency_ms': int((time.monotonic() - t0) * 1000),
            })
            rec.write({'state': 'error', 'error_message': rec._format_error_summary(log)})
            cr.commit()
        except Exception as e:
            cr.rollback()
            env.invalidate_all()
            error_code = 'internal_error'
            error_msg = str(e)
            _logger.exception('[transcribe] recording=%s attempt=%s unexpected error', rec.id, attempt_no)
            log = Log.create({
                **log_base,
                'state': 'internal_error',
                'error_message': error_msg,
                'traceback': mask_secrets(tb_module.format_exc()),
                'ended_at': fields.Datetime.now(),
                'request_latency_ms': int((time.monotonic() - t0) * 1000),
            })
            rec.write({'state': 'error', 'error_message': rec._format_error_summary(log)})
            cr.commit()

        # 清除 worker 指紋
        try:
            rec.write({'worker_pid': 0, 'worker_started_at': False})
            cr.commit()
        except Exception:
            cr.rollback()

        # 重算 note 彙整狀態
        try:
            rec.note_id._recompute_transcript_state()
            cr.commit()
        except Exception:
            cr.rollback()
            _logger.exception('[transcribe] recompute_state failed note=%s', rec.note_id.id)

        # 連續失敗告警
        if error_code:
            try:
                rec._maybe_notify_consecutive_failures(log)
                cr.commit()
            except Exception:
                cr.rollback()
                _logger.exception('[transcribe] consecutive-failure alert failed')

        # bus.bus 通知（送給 note 擁有者，cron 重試時也能送達）
        try:
            target_partner = rec.note_id.user_id.partner_id or env.user.partner_id
            env['bus.bus']._sendone(
                target_partner,
                'note_recording/transcription_update',
                {
                    'recording_id': rec.id,
                    'note_id': rec.note_id.id,
                    'state': 'error' if error_code else 'done',
                    'transcript_state': rec.note_id.transcript_state,
                    'error_code': error_code or '',
                    'error_message': error_msg or '',
                    'log_id': log.id if log else 0,
                    'progress_done': idx,
                    'progress_total': total,
                },
            )
            cr.commit()
        except Exception:
            cr.rollback()
            _logger.exception('[transcribe] bus notification failed recording=%s', rec.id)

    def _next_attempt_no(self):
        self.ensure_one()
        last = self.env['note.transcribe.log'].search(
            [('recording_id', '=', self.id)],
            order='attempt_no desc', limit=1,
        )
        return (last.attempt_no + 1) if last else 1

    def _maybe_notify_consecutive_failures(self, log):
        """連續 N 次相同錯誤碼 → activity + mt_comment email 給 note 擁有者

        - activity 顯示在 note 的活動列
        - mt_comment 會觸發 email 給 followers
        """
        self.ensure_one()
        if not log or log.state == 'success':
            return
        recent = self.env['note.transcribe.log'].search(
            [('note_id', '=', self.note_id.id)],
            order='id desc', limit=CONSECUTIVE_FAILURE_ALERT,
        )
        if len(recent) < CONSECUTIVE_FAILURE_ALERT:
            return
        codes = recent.mapped('state')
        if codes[0] == 'success' or not all(c == codes[0] for c in codes):
            return
        prior = self.env['note.transcribe.log'].search(
            [('note_id', '=', self.note_id.id)],
            order='id desc',
            offset=CONSECUTIVE_FAILURE_ALERT,
            limit=1,
        )
        if prior and prior.state == codes[0]:
            return  # 已通知過

        state_label = dict(log._fields['state'].selection).get(codes[0], codes[0])
        summary = _('Transcription repeatedly failing: %s', state_label)
        body = _(
            'The last %(n)d transcription attempts on this meeting minutes '
            'have all failed with code "%(code)s". Latest message: %(msg)s',
            n=CONSECUTIVE_FAILURE_ALERT, code=codes[0], msg=log.error_message or '',
        )
        user = self.note_id.user_id or self.env.user
        try:
            self.note_id.activity_schedule(
                'mail.mail_activity_data_warning',
                user_id=user.id,
                summary=summary, note=body,
            )
        except Exception:
            _logger.exception('activity_schedule failed for note %s', self.note_id.id)

        try:
            self.note_id.message_post(
                body=body,
                subject=summary,
                subtype_xmlid='mail.mt_comment',
                message_type='comment',
                partner_ids=user.partner_id.ids,
            )
        except Exception:
            _logger.exception('message_post failed for note %s', self.note_id.id)

    def _process_transcription(self):
        """執行語音辨識處理（由 handler 決定 provider 實作）"""
        self.ensure_one()
        provider = self.env.company.transcription_provider
        if not provider:
            raise TranscribeError('config_error', _('Please configure a transcription provider in Settings.'))

        handler = getattr(self, f'_transcribe_{provider}', None)
        if not handler:
            raise TranscribeError('config_error', _('Unsupported transcription provider: %s', provider))

        segments = handler()
        self._save_segments(segments)
        self.write({'state': 'done'})

    # ===== HTTP helper =====
    def _call_http(self, method, url, *, error_prefix='', timeout=HTTP_TIMEOUT_SUBMIT, **kwargs):
        """呼叫外部 HTTP，失敗時一律丟 TranscribeError 並附帶 body + status"""
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.Timeout as e:
            raise TranscribeError(
                'timeout',
                _('%(prefix)s timed out: %(err)s', prefix=error_prefix, err=str(e)),
                http_url=url,
            ) from e
        except requests.exceptions.ConnectionError as e:
            raise TranscribeError(
                'network_error',
                _('%(prefix)s cannot connect: %(err)s', prefix=error_prefix, err=str(e)),
                http_url=url,
            ) from e
        except requests.exceptions.RequestException as e:
            raise TranscribeError(
                'network_error',
                _('%(prefix)s request error: %(err)s', prefix=error_prefix, err=str(e)),
                http_url=url,
            ) from e

        if not resp.ok:
            body = resp.text if resp.text else ''
            snippet = mask_secrets(body[:RESPONSE_SNIPPET_LIMIT])
            status = resp.status_code
            if status == 429:
                code = 'quota_exceeded'
            elif status in (401, 403):
                code = 'config_error'
            else:
                code = 'http_error'
            raise TranscribeError(
                code,
                _(
                    '%(prefix)s HTTP %(status)s: %(body)s',
                    prefix=error_prefix, status=status, body=(snippet[:500] or '(empty body)'),
                ),
                http_status=status,
                response_snippet=snippet,
                http_url=url,
            )
        return resp

    def _read_audio_bytes(self):
        """讀取音檔原始 bytes — 使用 attachment.raw 避免 base64 decode 成本

        優勢：
        - attachment.raw 直接回傳 bytes（disk-backed 時走 mmap）
        - 省下 base64 text→bytes 的 33% 記憶體佔用
        """
        self.ensure_one()
        return self.attachment_id.raw or b''

    def _get_transcription_api_key(self):
        """Read and decrypt API key from ir.config_parameter."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'dobtor_meeting_minutes.transcription_api_key'
        )
        return crypto_decrypt(raw, env=self.env) if raw else ''

    def _get_transcription_company(self):
        """取轉錄設定來源公司 — 優先用 note.company_id，fallback env.company

        這樣在 cron/thread 執行時（env.company 可能是 admin 的 company），
        仍能讀到建立 note 當下的正確公司設定。
        """
        self.ensure_one()
        note_company = self.note_id.company_id if hasattr(self.note_id, 'company_id') else False
        return note_company or self.env.company

    def _transcribe_assemblyai(self):
        """AssemblyAI 模式 -- 內建 STT + 說話者辨識"""
        self.ensure_one()
        company = self._get_transcription_company()
        api_key = self._get_transcription_api_key()
        if not api_key:
            raise TranscribeError(
                'config_error',
                _('Please configure the AssemblyAI API key in Settings > Productivity Tools.'),
            )

        headers = {'authorization': api_key}
        audio_data = self._read_audio_bytes()

        # Step 1: 上傳音檔 — 使用 BytesIO 讓 requests 可分塊送出
        _logger.info('AssemblyAI: uploading audio for recording %s (%d bytes)', self.id, len(audio_data))
        try:
            upload_resp = self._call_http(
                'POST',
                'https://api.assemblyai.com/v2/upload',
                error_prefix='AssemblyAI upload',
                headers=headers,
                data=io.BytesIO(audio_data),
                timeout=HTTP_TIMEOUT_UPLOAD,
            )
        except TranscribeError as e:
            if e.code in ('http_error', 'network_error', 'timeout'):
                raise TranscribeError(
                    'upload_failed', e.message,
                    http_status=e.http_status,
                    response_snippet=e.response_snippet,
                    http_url=e.http_url,
                ) from e
            raise

        try:
            upload_url = upload_resp.json().get('upload_url')
        except ValueError as e:
            raise TranscribeError(
                'parse_error', _('AssemblyAI upload response is not valid JSON.'),
                response_snippet=mask_secrets(upload_resp.text[:RESPONSE_SNIPPET_LIMIT]),
            ) from e
        if not upload_url:
            raise TranscribeError(
                'upload_failed', _('AssemblyAI upload returned no upload_url.'),
                response_snippet=mask_secrets(upload_resp.text[:RESPONSE_SNIPPET_LIMIT]),
            )

        # Step 2: 送出轉錄請求
        transcript_req = {
            'audio_url': upload_url,
            'speaker_labels': True,
            'speech_models': ['universal-3-pro', 'universal-2'],
        }
        language = company.transcription_language or 'zh'
        if language:
            transcript_req['language_code'] = language

        submit_resp = self._call_http(
            'POST', 'https://api.assemblyai.com/v2/transcript',
            error_prefix='AssemblyAI submit',
            headers={**headers, 'content-type': 'application/json'},
            json=transcript_req,
            timeout=HTTP_TIMEOUT_SUBMIT,
        )
        try:
            transcript_id = submit_resp.json().get('id')
        except ValueError as e:
            raise TranscribeError(
                'parse_error', _('AssemblyAI submit response is not valid JSON.'),
                response_snippet=mask_secrets(submit_resp.text[:RESPONSE_SNIPPET_LIMIT]),
            ) from e
        if not transcript_id:
            raise TranscribeError(
                'parse_error', _('AssemblyAI: no transcript ID returned.'),
                response_snippet=mask_secrets(submit_resp.text[:RESPONSE_SNIPPET_LIMIT]),
            )

        # Step 3: 輪詢等待完成
        polling_url = f'https://api.assemblyai.com/v2/transcript/{transcript_id}'
        waited = 0
        result = None
        while waited < MAX_POLL_WAIT:
            poll_resp = self._call_http(
                'GET', polling_url,
                error_prefix='AssemblyAI polling',
                headers=headers, timeout=HTTP_TIMEOUT_POLL,
            )
            try:
                result = poll_resp.json()
            except ValueError as e:
                raise TranscribeError(
                    'parse_error', _('AssemblyAI polling response is not valid JSON.'),
                    response_snippet=mask_secrets(poll_resp.text[:RESPONSE_SNIPPET_LIMIT]),
                ) from e
            status = result.get('status')
            if status == 'completed':
                break
            if status == 'error':
                raise TranscribeError(
                    'http_error',
                    _('AssemblyAI transcription error: %s', result.get('error', 'Unknown error')),
                    response_snippet=mask_secrets(str(result)[:RESPONSE_SNIPPET_LIMIT]),
                )
            if status in ('queued', 'processing'):
                time.sleep(POLL_INTERVAL)
                waited += POLL_INTERVAL
                continue
            raise TranscribeError(
                'parse_error', _('AssemblyAI unexpected status: %s', status),
                response_snippet=mask_secrets(str(result)[:RESPONSE_SNIPPET_LIMIT]),
            )
        else:
            raise TranscribeError('timeout', _('AssemblyAI transcription timed out after %d seconds.', MAX_POLL_WAIT))

        # Step 4: 解析
        segments = []
        utterances = result.get('utterances', [])
        if utterances:
            for utt in utterances:
                segments.append({
                    'speaker': utt.get('speaker', 'A'),
                    'start': (utt.get('start', 0) or 0) / 1000.0,
                    'end': (utt.get('end', 0) or 0) / 1000.0,
                    'text': utt.get('text', ''),
                    'confidence': utt.get('confidence', 0),
                })
        else:
            text = result.get('text', '')
            if text:
                segments.append({
                    'speaker': 'SPEAKER_00', 'start': 0,
                    'end': self.duration or 0, 'text': text,
                    'confidence': result.get('confidence', 0),
                })

        _logger.info('AssemblyAI: completed for recording %s, %d segments', self.id, len(segments))
        return segments

    def _transcribe_api(self):
        """OpenAI Whisper API 模式"""
        self.ensure_one()
        company = self._get_transcription_company()
        api_key = self._get_transcription_api_key()
        if not api_key:
            raise TranscribeError('config_error', _('Please configure the OpenAI API key in Settings.'))

        audio_data = self._read_audio_bytes()

        resp = self._call_http(
            'POST', 'https://api.openai.com/v1/audio/transcriptions',
            error_prefix='OpenAI Whisper',
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': (f'recording.{self.file_format}', io.BytesIO(audio_data))},
            data={
                'model': 'whisper-1',
                'language': company.transcription_language or 'zh',
                'response_format': 'verbose_json',
                'timestamp_granularities[]': 'segment',
            },
            timeout=HTTP_TIMEOUT_FULL,
        )
        try:
            result = resp.json()
        except ValueError as e:
            raise TranscribeError(
                'parse_error', _('OpenAI Whisper response is not valid JSON.'),
                response_snippet=mask_secrets(resp.text[:RESPONSE_SNIPPET_LIMIT]),
            ) from e

        return [{
            'speaker': 'SPEAKER_00',
            'start': seg.get('start', 0),
            'end': seg.get('end', 0),
            'text': seg.get('text', ''),
            'confidence': seg.get('avg_logprob', 0),
        } for seg in result.get('segments', [])]

    def _transcribe_remote(self):
        """遠端微服務模式 -- 呼叫自建的 whisperX Docker 服務"""
        self.ensure_one()
        company = self._get_transcription_company()
        url = company.transcription_service_url
        if not url:
            raise TranscribeError('config_error', _('Please configure the transcription service URL in Settings.'))

        audio_data = self._read_audio_bytes()

        resp = self._call_http(
            'POST', f'{url.rstrip("/")}/transcribe',
            error_prefix='whisperX',
            files={'audio': (f'recording.{self.file_format}', io.BytesIO(audio_data))},
            data={
                'language': company.transcription_language or 'zh',
                'model_size': company.transcription_model_size or 'large-v3',
            },
            timeout=HTTP_TIMEOUT_FULL,
        )
        try:
            result = resp.json()
        except ValueError as e:
            raise TranscribeError(
                'parse_error', _('whisperX response is not valid JSON.'),
                response_snippet=mask_secrets(resp.text[:RESPONSE_SNIPPET_LIMIT]),
            ) from e
        return result.get('segments', [])

    def _save_segments(self, segments):
        self.ensure_one()
        Segment = self.env['note.transcript.segment']
        Segment.search([('recording_id', '=', self.id)]).unlink()

        offset = self.time_offset or 0.0
        speaker_labels = set()
        vals_list = []
        for seg in segments:
            speaker = seg.get('speaker', 'SPEAKER_00')
            speaker_labels.add(speaker)
            vals_list.append({
                'note_id': self.note_id.id,
                'recording_id': self.id,
                'speaker_label': speaker,
                'time_start': seg.get('start', 0) + offset,
                'time_end': seg.get('end', 0) + offset,
                'text': seg.get('text', ''),
                'confidence': seg.get('confidence', 0),
            })

        if vals_list:
            Segment.create(vals_list)

        Mapping = self.env['note.speaker.mapping']
        existing_labels = Mapping.search(
            [('note_id', '=', self.note_id.id)]
        ).mapped('speaker_label')

        new_mappings = [{
            'note_id': self.note_id.id,
            'speaker_label': label,
        } for label in sorted(speaker_labels) if label not in existing_labels]
        if new_mappings:
            Mapping.create(new_mappings)

    # ===== Cron =====
    @api.model
    def _cron_cleanup_stale_processing(self):
        """清理超時/死亡 processing + 寫 log 保留線索

        偵測策略：
        1. 快速路徑：worker_pid 不存在於 OS（thread crashed）→ 立即清理
        2. 保險路徑：write_date 超過 STALE_PROCESSING_MINUTES → 清理
        """
        now = fields.Datetime.now()
        timeout = fields.Datetime.subtract(now, minutes=STALE_PROCESSING_MINUTES)
        # 保險路徑：時間超過門檻
        time_stale = self.search([
            ('state', '=', 'processing'),
            ('write_date', '<', timeout),
        ])
        # 快速路徑：有 PID 但 process 已不存在（且至少啟動 60 秒避免誤判剛起 thread）
        candidates = self.search([
            ('state', '=', 'processing'),
            ('worker_pid', '>', 0),
            ('worker_started_at', '<',
             fields.Datetime.subtract(now, seconds=60)),
        ])
        pid_dead = candidates.filtered(lambda r: not self._is_pid_alive(r.worker_pid))
        stale_recordings = time_stale | pid_dead
        if stale_recordings:
            _logger.info('Cleaning up %d stale processing recordings', len(stale_recordings))
            Log = self.env['note.transcribe.log']
            Log.create([{
                'recording_id': rec.id,
                'provider': self.env.company.transcription_provider or False,
                'attempt_no': rec._next_attempt_no(),
                'state': 'stale_worker',
                'error_message': _(
                    'Processing timed out after %d minutes — worker likely died.',
                    STALE_PROCESSING_MINUTES,
                ),
                'audio_bytes': rec.file_size or 0,
                'audio_duration': rec.duration or 0,
                'started_at': rec.write_date,
                'ended_at': fields.Datetime.now(),
            } for rec in stale_recordings])
            stale_recordings.write({
                'state': 'error',
                'error_message': _('Processing timed out. Please try again.'),
                'worker_pid': 0,
                'worker_started_at': False,
            })
            for note in stale_recordings.mapped('note_id'):
                note._recompute_transcript_state()

        # Summary stale 偵測 — 同樣走時間 + PID 雙路徑
        Note = self.env['note.note']
        time_stale_notes = Note.search([
            ('summary_state', '=', 'processing'),
            ('write_date', '<', timeout),
        ])
        pid_candidates = Note.search([
            ('summary_state', '=', 'processing'),
            ('summary_worker_pid', '>', 0),
            ('summary_worker_started_at', '<',
             fields.Datetime.subtract(now, seconds=60)),
        ])
        pid_dead_notes = pid_candidates.filtered(
            lambda n: not self._is_pid_alive(n.summary_worker_pid)
        )
        stale_notes = time_stale_notes | pid_dead_notes
        if stale_notes:
            _logger.info('Cleaning up %d stale processing summaries', len(stale_notes))
            stale_notes.write({
                'summary_state': 'error',
                'summary_worker_pid': 0,
                'summary_worker_started_at': False,
            })

    @api.model
    def _cron_auto_retry_transcription(self):
        """自動重試：retriable 且未達次數上限 + 已過退避時間"""
        errored = self.search([('state', '=', 'error')])
        if not errored:
            return
        now = fields.Datetime.now()
        to_retry = self.env['note.recording']
        for rec in errored:
            last = rec.latest_log_id
            if not last or not last.retriable:
                continue
            if last.attempt_no >= AUTO_RETRY_MAX_ATTEMPTS:
                continue
            wait_min = AUTO_RETRY_BACKOFF_MINUTES.get(last.attempt_no, 45)
            if not last.create_date:
                continue
            if (now - last.create_date).total_seconds() < wait_min * 60:
                continue
            to_retry |= rec
        if to_retry:
            _logger.info('Auto-retrying %d transcription(s)', len(to_retry))
            try:
                to_retry.action_transcribe()
            except Exception:
                _logger.exception('Auto-retry batch failed')

    @api.model
    def _cron_cleanup_old_logs(self):
        """清理舊 log — 成功 30 天、失敗 180 天後刪除"""
        Log = self.env['note.transcribe.log']
        cutoff_success = fields.Datetime.subtract(fields.Datetime.now(), days=LOG_RETENTION_DAYS_SUCCESS)
        cutoff_failure = fields.Datetime.subtract(fields.Datetime.now(), days=LOG_RETENTION_DAYS_FAILURE)

        old_success = Log.search([
            ('state', '=', 'success'),
            ('create_date', '<', cutoff_success),
        ])
        old_failure = Log.search([
            ('state', '!=', 'success'),
            ('create_date', '<', cutoff_failure),
        ])

        total = len(old_success) + len(old_failure)
        if total:
            _logger.info(
                'Cleaning up transcribe logs: %d success (>%dd), %d failures (>%dd)',
                len(old_success), LOG_RETENTION_DAYS_SUCCESS,
                len(old_failure), LOG_RETENTION_DAYS_FAILURE,
            )
            (old_success | old_failure).unlink()

    # ===== 動作 =====
    def action_play(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.attachment_id.id}?download=false',
            'target': 'new',
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transcription History'),
            'res_model': 'note.transcribe.log',
            'view_mode': 'list,form',
            'domain': [('recording_id', '=', self.id)],
            'context': {'default_recording_id': self.id},
        }
