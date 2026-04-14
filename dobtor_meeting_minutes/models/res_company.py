# -*- coding: utf-8 -*-

from odoo import fields, models


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
       help='Select a predefined prompt template for meeting summaries.')


class ResConfigSettings(models.TransientModel):
    """系統設定擴展 -- 會議記錄設定頁"""
    _inherit = 'res.config.settings'

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
        config_parameter='dobtor_meeting_minutes.transcription_api_key',
    )
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
