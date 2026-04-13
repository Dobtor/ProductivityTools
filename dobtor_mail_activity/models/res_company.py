# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    """公司擴展

    新增預設工時表專案欄位，用於：
    - 待辦完成時自動建立工時表記錄
    - 當待辦關聯文件無專案時的預設專案

    新增語音辨識與摘要設定。
    """
    _inherit = 'res.company'

    default_timesheet_project_id = fields.Many2one(
        'project.project',
        string='Default Timesheet Project',
        domain="[('allow_timesheets', '=', True), '|', ('company_id', '=', False), ('company_id', '=', id)]",
        help='When activity is completed without an associated project, this project will be used to create timesheet entries. '
             'The project must have timesheets enabled.',
    )

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
    # transcription_api_key 已移至 ir.config_parameter
    # key: dobtor_mail_activity.transcription_api_key
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

    # ===== 摘要設定 =====
    summary_provider = fields.Selection([
        ('claude', 'Claude API'),
        ('openai', 'OpenAI API'),
        ('ollama', 'Local Ollama'),
    ], string='Summary Provider', default='claude')
    # summary_api_key 已移至 ir.config_parameter
    # key: dobtor_mail_activity.summary_api_key
    summary_api_url = fields.Char(
        string='Summary API URL',
        help='API URL for Ollama (e.g. http://localhost:11434)',
    )
    summary_model_name = fields.Char(
        string='Summary Model',
        help='Model name for Ollama (e.g. llama3)',
    )
    summary_prompt_preset = fields.Selection([
        ('formal', 'Formal Meeting Minutes'),
        ('brainstorm', 'Brainstorming Session'),
        ('standup', 'Daily Standup / Sprint Review'),
        ('project', 'Project Status Meeting'),
    ], string='Prompt Preset', default='formal',
       help='Select a predefined prompt template for meeting summaries.')
    summary_prompt_template = fields.Text(
        string='Custom Prompt Override',
        help='Custom prompt template (overrides preset). Use {transcript} as placeholder.',
    )


class ResConfigSettings(models.TransientModel):
    """系統設定擴展

    在系統設定中顯示預設工時表專案設定和語音辨識設定。
    """
    _inherit = 'res.config.settings'

    timesheet_project_id = fields.Many2one(
        related='company_id.default_timesheet_project_id',
        string='Default Timesheet Project',
        readonly=False,
        domain="[('allow_timesheets', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )

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
        config_parameter='dobtor_mail_activity.transcription_api_key',
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
    summary_provider = fields.Selection(
        related='company_id.summary_provider',
        readonly=False,
    )
    summary_api_key = fields.Char(
        string='Summary API Key',
        config_parameter='dobtor_mail_activity.summary_api_key',
    )
    summary_api_url = fields.Char(
        related='company_id.summary_api_url',
        readonly=False,
    )
    summary_model_name = fields.Char(
        related='company_id.summary_model_name',
        readonly=False,
    )
    summary_prompt_preset = fields.Selection(
        related='company_id.summary_prompt_preset',
        readonly=False,
    )
    summary_prompt_template = fields.Text(
        related='company_id.summary_prompt_template',
        readonly=False,
    )
