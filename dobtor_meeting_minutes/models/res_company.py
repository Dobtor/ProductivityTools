# -*- coding: utf-8 -*-

import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..utils.security import redact_display_key
from ..utils.crypto import (
    encrypt as crypto_encrypt,
    decrypt as crypto_decrypt,
    is_encrypted,
    get_ciphertext_version,
    bump_key_version,
)

_logger = logging.getLogger(__name__)

API_KEY_PARAM = 'dobtor_meeting_minutes.transcription_api_key'
# UI 顯示用：當使用者在 UI 看到的字串包含此字元（●）時，視為「未變更」
_MASK_CHAR = '●'


class ResCompany(models.Model):
    """公司擴展 -- 會議記錄設定

    新增語音辨識與 AI 摘要設定。
    摘要產生改用 ai.chatbot 平台，不再直接設定 API key/URL/model。
    """
    _inherit = 'res.company'

    # ===== 語音辨識設定 =====
    transcription_provider = fields.Selection([
        ('assemblyai', 'AssemblyAI (Recommended)'),
        ('api', 'OpenAI Whisper API'),
        ('remote', 'Remote whisperX Service'),
    ], string='Transcription Provider', default='assemblyai',
       help='AssemblyAI: cloud API with built-in speaker diarization, no deployment needed.\n'
            'OpenAI Whisper: cloud API, no speaker diarization.\n'
            'Remote whisperX: self-hosted Docker service with GPU.')
    transcription_service_url = fields.Char(
        string='Transcription Service URL',
        help='URL of the whisperX transcription service (e.g. http://gpu-server:8765)',
    )
    # transcription_api_key 存於 ir.config_parameter
    # key: dobtor_meeting_minutes.transcription_api_key
    transcription_model_size = fields.Selection([
        ('base', 'Base (Fast)'),
        ('medium', 'Medium (Balanced)'),
        ('large-v3', 'Large-v3 (Best Quality)'),
    ], string='Model Size', default='large-v3',
       help='Only used for Remote whisperX mode.')
    transcription_language = fields.Char(
        string='Language',
        default='zh',
        help='Language code for transcription (e.g. zh, en, ja)',
    )

    # ===== 摘要設定（透過 AI Chatbot 平台）=====
    meeting_summary_chatbot_id = fields.Many2one(
        'ai.chatbot',
        string='Meeting Summary AI Chatbot',
        help='Select the AI Chatbot to use for generating meeting summaries.',
    )
    summary_prompt_preset = fields.Selection([
        ('formal', 'Formal Meeting Minutes'),
        ('brainstorm', 'Brainstorming Session'),
        ('standup', 'Daily Standup / Sprint Review'),
        ('project', 'Project Status Meeting'),
    ], string='Prompt Preset', default='formal',
       help='Fallback preset — used when no custom template is selected.')
    summary_prompt_template_id = fields.Many2one(
        'note.summary.template',
        string='Custom Summary Template',
        help='Override the preset with a custom template. '
             'Managers can add/edit templates under Meeting Minutes > Summary Templates.',
        domain="[('active', '=', True)]",
    )


class ResConfigSettings(models.TransientModel):
    """系統設定擴展 -- 會議記錄設定頁"""
    _inherit = 'res.config.settings'

    def action_test_transcription_connection(self):
        """連線測試 -- 快速驗證 provider 設定是否可用

        不送音檔，只驗證 API key / URL 有效。
        對 AssemblyAI：呼叫 /v2/transcript/LIST?limit=1（驗 key）
        對 OpenAI：呼叫 /v1/models（驗 key）
        對 Remote：呼叫 /health 或根路徑（驗 URL 可連）
        """
        self.ensure_one()
        self.execute()  # 保存當前設定
        company = self.env.company
        provider = company.transcription_provider
        if not provider:
            raise UserError(_('Please configure a transcription provider first.'))

        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'dobtor_meeting_minutes.transcription_api_key',
        )

        try:
            if provider == 'assemblyai':
                if not api_key:
                    raise UserError(_('AssemblyAI API key is not configured.'))
                resp = requests.get(
                    'https://api.assemblyai.com/v2/transcript?limit=1',
                    headers={'authorization': api_key},
                    timeout=15,
                )
                self._assert_ok(resp, 'AssemblyAI')
            elif provider == 'api':
                if not api_key:
                    raise UserError(_('OpenAI API key is not configured.'))
                resp = requests.get(
                    'https://api.openai.com/v1/models',
                    headers={'Authorization': f'Bearer {api_key}'},
                    timeout=15,
                )
                self._assert_ok(resp, 'OpenAI')
            elif provider == 'remote':
                url = company.transcription_service_url
                if not url:
                    raise UserError(_('Transcription service URL is not configured.'))
                try:
                    resp = requests.get(f'{url.rstrip("/")}/health', timeout=10)
                except requests.exceptions.RequestException:
                    resp = requests.get(url.rstrip('/'), timeout=10)
                self._assert_ok(resp, 'whisperX')
            else:
                raise UserError(_('Unknown provider: %s', provider))
        except requests.exceptions.Timeout:
            raise UserError(_('Connection test timed out.'))
        except requests.exceptions.ConnectionError as e:
            raise UserError(_('Cannot connect: %s', str(e)))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Connection OK'),
                'message': _('Provider "%s" responded successfully.', provider),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _assert_ok(self, resp, provider):
        if resp.ok:
            return
        body = (resp.text or '')[:300]
        raise UserError(_(
            '%(provider)s returned HTTP %(status)s: %(body)s',
            provider=provider, status=resp.status_code, body=body or '(empty body)',
        ))

    # ===== 語音辨識設定 =====
    transcription_provider = fields.Selection(
        related='company_id.transcription_provider',
        readonly=False,
    )
    transcription_service_url = fields.Char(
        related='company_id.transcription_service_url',
        readonly=False,
    )
    transcription_api_key = fields.Char(
        string='Transcription API Key',
        config_parameter=API_KEY_PARAM,
        help='API key for AssemblyAI or OpenAI. '
             'Once saved, only the last 4 characters are shown. '
             'Leave unchanged (●●●●) to keep the existing key.',
    )
    transcription_api_key_is_set = fields.Boolean(
        compute='_compute_transcription_api_key_is_set',
        help='True when an API key is already configured.',
    )

    @api.depends('transcription_api_key')
    def _compute_transcription_api_key_is_set(self):
        """Computed for UI hints — indicates whether key is already set."""
        stored = self.env['ir.config_parameter'].sudo().get_param(API_KEY_PARAM, '')
        for rec in self:
            rec.transcription_api_key_is_set = bool(stored)

    @api.model
    def get_values(self):
        """讀設定時解密 + 遮蔽顯示"""
        res = super().get_values()
        stored = res.get('transcription_api_key') or ''
        if stored:
            try:
                real_key = crypto_decrypt(stored, env=self.env)
            except Exception:
                _logger.exception('[security] Failed to decrypt API key — showing redacted placeholder')
                real_key = stored
            res['transcription_api_key'] = redact_display_key(real_key, visible_tail=4)
        return res

    def set_values(self):
        """寫設定時：
        - 若顯示仍是遮蔽值（含 ●）或空值但舊值存在 → 不覆寫（保留既有加密值）
        - 若真實值變更 → 加密後寫入 + 審計
        """
        ICP = self.env['ir.config_parameter'].sudo()
        stored = ICP.get_param(API_KEY_PARAM, '')
        new_value = self.transcription_api_key or ''

        # 以解密後的純文字作為比對基準
        current_plain = crypto_decrypt(stored, env=self.env) if stored else ''
        key_unchanged_display = bool(stored) and (_MASK_CHAR in new_value or not new_value)

        if key_unchanged_display:
            # 恢復已加密的原值，讓 super().set_values() 寫回同一筆加密值
            self.transcription_api_key = stored
            super().set_values()
            return

        if new_value and new_value != current_plain:
            # 真實變更 — 先記錄稽核，然後加密寫入
            self._audit_api_key_change(current_plain, new_value)
            encrypted = crypto_encrypt(new_value, env=self.env)
            self.transcription_api_key = encrypted

        super().set_values()

    def action_rotate_transcription_api_key(self):
        """觸發 key rotation：提升 version 號 + re-encrypt 舊資料

        前置：管理員已將：
        - 舊 key 移到 DOBTOR_MM_FERNET_KEY_OLD_1
        - 新 key 放 DOBTOR_MM_FERNET_KEY
        然後點此按鈕。
        """
        self.ensure_one()
        self._reencrypt_api_keys()
        bump_key_version(self.env)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Key Rotation Completed'),
                'message': _('All stored API keys have been re-encrypted with the new key.'),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _reencrypt_api_keys(self):
        """Re-encrypt all ir.config_parameter API keys that are older than current version"""
        ICP = self.env['ir.config_parameter'].sudo()
        current_version = int(ICP.get_param('dobtor_meeting_minutes.fernet_key_version', '1'))
        raw = ICP.get_param(API_KEY_PARAM, '')
        if not raw or not is_encrypted(raw):
            return
        stored_version = get_ciphertext_version(raw)
        if stored_version == current_version:
            return
        plaintext = crypto_decrypt(raw, env=self.env)
        if plaintext:
            re_enc = crypto_encrypt(plaintext, env=self.env)
            ICP.set_param(API_KEY_PARAM, re_enc)
            _logger.warning(
                '[security] Re-encrypted %s from v%s to v%s',
                API_KEY_PARAM, stored_version, current_version,
            )

    @api.model
    def _cron_reencrypt_api_keys(self):
        """Cron: 確保所有加密值使用最新 key version"""
        self._reencrypt_api_keys()

    def _audit_api_key_change(self, old_key, new_key):
        """記錄 API key 變更供稽核

        寫入：
        - server log（一律寫）
        - ir.logging（供後台檢索）
        - 當 res.company 支援 mail.thread 時 message_post
        """
        user = self.env.user
        old_disp = redact_display_key(old_key) if old_key else '(empty)'
        new_disp = redact_display_key(new_key) if new_key else '(empty)'
        msg = (
            f'Transcription API key changed by {user.login} '
            f'({user.name}, id={user.id}) '
            f'from {old_disp} to {new_disp}'
        )
        _logger.warning('[security] %s', msg)

        try:
            self.env['ir.logging'].sudo().create({
                'name': 'dobtor_meeting_minutes.security',
                'type': 'server',
                'dbname': self.env.cr.dbname,
                'level': 'WARNING',
                'message': msg,
                'path': __name__,
                'func': 'set_values',
                'line': '0',
            })
        except Exception:
            _logger.exception('ir.logging audit failed')

        try:
            if hasattr(self.env.company, 'message_post'):
                self.env.company.message_post(
                    body=msg,
                    subject=_('Transcription API key updated'),
                    message_type='notification',
                )
        except Exception:
            _logger.exception('message_post audit failed')
    transcription_model_size = fields.Selection(
        related='company_id.transcription_model_size',
        readonly=False,
    )
    transcription_language = fields.Char(
        related='company_id.transcription_language',
        readonly=False,
    )

    # ===== 摘要設定 =====
    meeting_summary_chatbot_id = fields.Many2one(
        related='company_id.meeting_summary_chatbot_id',
        readonly=False,
    )
    summary_prompt_preset = fields.Selection(
        related='company_id.summary_prompt_preset',
        readonly=False,
    )
    summary_prompt_template_id = fields.Many2one(
        related='company_id.summary_prompt_template_id',
        readonly=False,
    )
