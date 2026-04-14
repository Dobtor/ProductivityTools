# -*- coding: utf-8 -*-

import base64
import logging
import time
import threading
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# 錄音限制常數
MAX_RECORDING_DURATION = 7200   # 2 小時
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB


class NoteRecording(models.Model):
    """會議錄音

    儲存會議記錄的錄音檔案，支援：
    - 瀏覽器端錄音上傳
    - 非同步語音辨識（STT + 說話者辨識）
    - 多段錄音管理（含時間偏移合併）
    """
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
        string='Name',
        compute='_compute_name',
        store=True,
    )
    attachment_id = fields.Many2one(
        'ir.attachment',
        string='Audio File',
        required=True,
        ondelete='cascade',
    )
    duration = fields.Float(
        string='Duration (seconds)',
        help='Recording duration in seconds',
    )
    record_start = fields.Datetime(
        string='Recording Start',
    )
    record_end = fields.Datetime(
        string='Recording End',
    )
    time_offset = fields.Float(
        string='Time Offset (seconds)',
        compute='_compute_time_offset',
        store=True,
        help='Offset relative to the first recording, for merging multi-segment transcripts.',
    )
    file_format = fields.Char(
        string='Format',
        help='Audio file format (e.g. webm, wav, mp3)',
    )
    file_size = fields.Integer(
        string='File Size (bytes)',
    )
    state = fields.Selection([
        ('uploaded', 'Uploaded'),
        ('processing', 'Processing'),
        ('done', 'Transcribed'),
        ('error', 'Error'),
    ], string='Status', default='uploaded', required=True)
    error_message = fields.Text(
        string='Error Message',
    )
    audio_url = fields.Char(
        string='Audio URL',
        compute='_compute_audio_url',
    )

    # ===== 計算方法 =====
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
            if rec.attachment_id:
                rec.audio_url = f'/web/content/{rec.attachment_id.id}?download=false'
            else:
                rec.audio_url = False

    @api.depends('record_start', 'note_id.recording_ids.record_start')
    def _compute_time_offset(self):
        """計算相對於第一段錄音的時間偏移（秒）

        用於多段錄音合併逐字稿時，將各段的相對時間戳
        轉換為整場會議的絕對時間戳。
        """
        for rec in self:
            if not rec.record_start or not rec.note_id:
                rec.time_offset = 0.0
                continue
            siblings = rec.note_id.recording_ids.filtered('record_start').sorted('record_start')
            if not siblings:
                rec.time_offset = 0.0
                continue
            first_start = siblings[0].record_start
            rec.time_offset = (rec.record_start - first_start).total_seconds()

    # ===== 格式化方法 =====
    def _format_duration(self):
        """將秒數格式化為 HH:MM:SS"""
        self.ensure_one()
        total = int(self.duration or 0)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        return f'{minutes:02d}:{seconds:02d}'

    # ===== 業務方法 =====
    @api.model
    def create_from_browser(self, vals):
        """從瀏覽器錄音建立記錄

        Args:
            vals: dict with keys:
                - note_id: int
                - audio_base64: str (base64 encoded audio)
                - duration: float (seconds)
                - file_format: str (e.g. 'webm')
                - record_start: str (ISO datetime)
                - record_end: str (ISO datetime)

        Returns:
            dict with recording info
        """
        note = self.env['note.note'].browse(vals['note_id'])
        if not note.exists():
            raise UserError(_('Meeting minutes not found.'))
        # 存取權限檢查
        note.check_access_rights('write')
        note.check_access_rule('write')

        # 檔案大小限制
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

        # 錄音時長限制
        duration = vals.get('duration', 0)
        if duration > MAX_RECORDING_DURATION:
            raise UserError(_(
                'Recording is too long (%(dur).0f minutes). Maximum allowed is %(max).0f minutes.',
                dur=duration / 60,
                max=MAX_RECORDING_DURATION / 60,
            ))

        # 解析前端傳入的 ISO datetime 字串
        record_start = self._parse_iso_datetime(vals.get('record_start'))
        record_end = self._parse_iso_datetime(vals.get('record_end'))

        file_format = vals.get('file_format', 'webm')

        # 建立 attachment
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
        """解析 ISO datetime 字串為 Odoo datetime"""
        if not iso_str:
            return False
        try:
            return fields.Datetime.to_datetime(
                iso_str.replace('T', ' ').replace('Z', '')[:19]
            )
        except (ValueError, AttributeError):
            return fields.Datetime.now()

    def action_transcribe(self):
        """觸發語音辨識（非同步）

        使用獨立 thread 執行辨識，完成後透過 bus.bus 通知前端。
        """
        for rec in self:
            if rec.state == 'processing':
                raise UserError(_('This recording is already being processed.'))

        for rec in self:
            rec.write({
                'state': 'processing',
                'error_message': False,
            })
            rec.note_id.write({'transcript_state': 'processing'})

        # 在獨立 thread 中執行辨識，避免阻塞 Odoo worker
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

    @api.model
    def _async_transcribe_worker(self, db_name, uid, recording_ids):
        """獨立 thread 中的辨識工作（新 cursor + 新 environment）"""
        import odoo
        registry = odoo.registry(db_name)

        with registry.cursor() as cr:
            env = api.Environment(cr, uid, {})
            recordings = env['note.recording'].browse(recording_ids)
            total = len(recording_ids)

            for idx, rec in enumerate(recordings, 1):
                error_msg = False
                try:
                    rec._process_transcription()
                    cr.commit()
                except Exception as e:
                    cr.rollback()
                    env.invalidate_all()
                    error_msg = str(e)
                    _logger.exception('Transcription failed for recording %s', rec.id)
                    rec.write({
                        'state': 'error',
                        'error_message': error_msg,
                    })
                    rec.note_id.write({'transcript_state': 'error'})
                    cr.commit()

                # 發送 bus.bus 通知（含進度）
                try:
                    state = 'error' if error_msg else 'done'
                    transcript_state = 'error' if error_msg else rec.note_id.transcript_state
                    env['bus.bus']._sendone(
                        env.user.partner_id,
                        'note_recording/transcription_update',
                        {
                            'recording_id': rec.id,
                            'note_id': rec.note_id.id,
                            'state': state,
                            'transcript_state': transcript_state,
                            'error_message': error_msg or '',
                            'progress_done': idx,
                            'progress_total': total,
                        },
                    )
                    cr.commit()
                except Exception:
                    cr.rollback()
                    _logger.exception('Failed to send bus notification for recording %s', rec.id)

    def _process_transcription(self):
        """執行語音辨識處理"""
        self.ensure_one()
        provider = self.env.company.transcription_provider
        if not provider:
            raise UserError(_('Please configure a transcription provider in Settings.'))

        handler = getattr(self, f'_transcribe_{provider}', None)
        if not handler:
            raise UserError(_('Unsupported transcription provider: %s', provider))

        segments = handler()
        self._save_segments(segments)
        self.write({'state': 'done'})

        # 更新 note 狀態
        note = self.note_id
        all_done = all(r.state == 'done' for r in note.recording_ids)
        if all_done:
            note.write({'transcript_state': 'done'})

    def _transcribe_assemblyai(self):
        """AssemblyAI 模式 -- 內建 STT + 說話者辨識，無需部署

        流程：
        1. 上傳音檔取得 upload_url
        2. 送出轉錄請求（含 speaker_labels=True）
        3. 輪詢等待完成
        4. 解析回傳結果
        """
        self.ensure_one()
        company = self.env.company
        api_key = self.env['ir.config_parameter'].sudo().get_param('dobtor_meeting_minutes.transcription_api_key')
        if not api_key:
            raise UserError(_('Please configure the AssemblyAI API key in Settings > Productivity Tools.'))

        headers = {'authorization': api_key}
        audio_data = base64.b64decode(self.attachment_id.datas)

        # Step 1: 上傳音檔
        _logger.info('AssemblyAI: uploading audio for recording %s (%d bytes)', self.id, len(audio_data))
        try:
            upload_resp = requests.post(
                'https://api.assemblyai.com/v2/upload',
                headers=headers,
                data=audio_data,
                timeout=300,
            )
            upload_resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise UserError(_('AssemblyAI upload failed: %s', str(e)))

        upload_url = upload_resp.json().get('upload_url')
        if not upload_url:
            raise UserError(_('AssemblyAI upload failed: no upload URL returned.'))

        # Step 2: 送出轉錄請求
        language = company.transcription_language or 'zh'
        transcript_req = {
            'audio_url': upload_url,
            'speaker_labels': True,
        }
        if language:
            transcript_req['language_code'] = language

        try:
            submit_resp = requests.post(
                'https://api.assemblyai.com/v2/transcript',
                headers={**headers, 'content-type': 'application/json'},
                json=transcript_req,
                timeout=60,
            )
            submit_resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise UserError(_('AssemblyAI transcription request failed: %s', str(e)))

        transcript_id = submit_resp.json().get('id')
        if not transcript_id:
            raise UserError(_('AssemblyAI: no transcript ID returned.'))

        # Step 3: 輪詢等待完成（最多 10 分鐘）
        polling_url = f'https://api.assemblyai.com/v2/transcript/{transcript_id}'
        max_wait = 600
        waited = 0
        poll_interval = 5

        while waited < max_wait:
            try:
                poll_resp = requests.get(polling_url, headers=headers, timeout=30)
                poll_resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                raise UserError(_('AssemblyAI polling error: %s', str(e)))

            result = poll_resp.json()
            status = result.get('status')

            if status == 'completed':
                break
            elif status == 'error':
                error_msg = result.get('error', 'Unknown error')
                raise UserError(_('AssemblyAI transcription error: %s', error_msg))
            elif status in ('queued', 'processing'):
                time.sleep(poll_interval)
                waited += poll_interval
            else:
                raise UserError(_('AssemblyAI unexpected status: %s', status))
        else:
            raise UserError(_('AssemblyAI transcription timed out after %d seconds.', max_wait))

        # Step 4: 解析 utterances（含說話者標籤）
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
                    'speaker': 'SPEAKER_00',
                    'start': 0,
                    'end': self.duration or 0,
                    'text': text,
                    'confidence': result.get('confidence', 0),
                })

        _logger.info('AssemblyAI: completed for recording %s, %d segments', self.id, len(segments))
        return segments

    def _transcribe_api(self):
        """OpenAI Whisper API 模式 -- 純轉文字，無說話者辨識"""
        self.ensure_one()
        company = self.env.company
        api_key = self.env['ir.config_parameter'].sudo().get_param('dobtor_meeting_minutes.transcription_api_key')
        if not api_key:
            raise UserError(_('Please configure the OpenAI API key in Settings.'))

        audio_data = base64.b64decode(self.attachment_id.datas)

        try:
            response = requests.post(
                'https://api.openai.com/v1/audio/transcriptions',
                headers={'Authorization': f'Bearer {api_key}'},
                files={'file': (f'recording.{self.file_format}', audio_data)},
                data={
                    'model': 'whisper-1',
                    'language': company.transcription_language or 'zh',
                    'response_format': 'verbose_json',
                    'timestamp_granularities[]': 'segment',
                },
                timeout=600,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise UserError(_('OpenAI Whisper API error: %s', str(e)))

        result = response.json()
        segments = []
        for seg in result.get('segments', []):
            segments.append({
                'speaker': 'SPEAKER_00',
                'start': seg.get('start', 0),
                'end': seg.get('end', 0),
                'text': seg.get('text', ''),
                'confidence': seg.get('avg_logprob', 0),
            })
        return segments

    def _transcribe_remote(self):
        """遠端微服務模式 -- 呼叫自建的 whisperX Docker 服務"""
        self.ensure_one()
        company = self.env.company
        url = company.transcription_service_url
        if not url:
            raise UserError(_('Please configure the transcription service URL in Settings.'))

        audio_data = base64.b64decode(self.attachment_id.datas)

        try:
            response = requests.post(
                f'{url.rstrip("/")}/transcribe',
                files={'audio': (f'recording.{self.file_format}', audio_data)},
                data={
                    'language': company.transcription_language or 'zh',
                    'model_size': company.transcription_model_size or 'large-v3',
                },
                timeout=600,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise UserError(_('Cannot connect to transcription service at %s', url))
        except requests.exceptions.Timeout:
            raise UserError(_('Transcription service timed out. The recording may be too long.'))
        except requests.exceptions.HTTPError as e:
            raise UserError(_('Transcription service error: %s', str(e)))

        result = response.json()
        return result.get('segments', [])

    def _save_segments(self, segments):
        """儲存辨識結果到 transcript segments

        會自動加上 time_offset，讓多段錄音的逐字稿
        以整場會議的絕對時間排序。
        """
        self.ensure_one()
        Segment = self.env['note.transcript.segment']

        # 清除此錄音的舊 segments
        Segment.search([('recording_id', '=', self.id)]).unlink()

        offset = self.time_offset or 0.0

        # 收集所有出現的 speaker labels
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

        # 自動建立 speaker mapping（如果不存在）
        Mapping = self.env['note.speaker.mapping']
        existing_labels = Mapping.search([
            ('note_id', '=', self.note_id.id),
        ]).mapped('speaker_label')

        new_mappings = []
        for label in sorted(speaker_labels):
            if label not in existing_labels:
                new_mappings.append({
                    'note_id': self.note_id.id,
                    'speaker_label': label,
                })
        if new_mappings:
            Mapping.create(new_mappings)

    @api.model
    def _cron_cleanup_stale_processing(self):
        """定時清理超時的 processing 狀態

        當 worker 被回收或 thread 異常終止時，
        recording/note 可能卡在 processing 狀態。
        此 cron 將超過 30 分鐘仍為 processing 的記錄重設為 error。
        """
        timeout = fields.Datetime.subtract(fields.Datetime.now(), minutes=30)
        stale_recordings = self.search([
            ('state', '=', 'processing'),
            ('write_date', '<', timeout),
        ])
        if stale_recordings:
            _logger.info('Cleaning up %d stale processing recordings', len(stale_recordings))
            stale_recordings.write({
                'state': 'error',
                'error_message': _('Processing timed out. Please try again.'),
            })
            # 同步更新關聯 note 的 transcript_state
            for note in stale_recordings.mapped('note_id'):
                if note.transcript_state == 'processing':
                    note.write({'transcript_state': 'error'})

        # 也清理超時的摘要
        stale_notes = self.env['note.note'].search([
            ('summary_state', '=', 'processing'),
            ('write_date', '<', timeout),
        ])
        if stale_notes:
            _logger.info('Cleaning up %d stale processing summaries', len(stale_notes))
            stale_notes.write({'summary_state': 'error'})

    def action_play(self):
        """播放錄音（回傳附件下載 URL）"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.attachment_id.id}?download=false',
            'target': 'new',
        }
