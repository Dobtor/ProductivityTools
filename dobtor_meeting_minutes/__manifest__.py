# -*- coding: utf-8 -*-
{
    'name': 'Meeting Minutes',
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Meeting minutes with recording, transcription, speaker diarization and AI summary',
    'description': """
Meeting Minutes
===============
Complete meeting minutes management system:

* Recording & Transcription
  - Browser-based audio recording
  - Speech-to-text with speaker diarization (AssemblyAI / OpenAI Whisper / whisperX)
  - Multi-segment recording with automatic time offset merging
  - Inline audio player and transcript editing

* AI Summary
  - Generate structured summaries via AI Chatbot platform
  - 4 preset prompt templates (formal, brainstorm, standup, project)
  - Export transcript as TXT or SRT

* Signature Workflow
  - Portal-based multi-party signature
  - Email notifications for signing requests
  - PDF report generation

* Portal Access
  - Token-based access for signers
  - Meeting detail view with signature modal
    """,
    'author': 'Dobtor SI',
    'website': 'https://www.dobtor.com',
    'depends': [
        'dobtor_mail_activity',
        'dobtor_ai_chatbot',
        'calendar',
        'portal',
    ],
    'data': [
        # Security
        'security/security.xml',
        'security/ir.model.access.csv',
        # Reports
        'report/ir_actions_report.xml',
        'report/report_meeting_minutes_templates.xml',
        # Data
        'data/ai_chatbot_data.xml',
        'data/mail_template_data.xml',
        'data/cron_data.xml',
        # Views
        'views/note_views.xml',
        'views/note_recording_views.xml',
        'views/note_signature_views.xml',
        'views/res_company_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu_views.xml',
        # Portal
        'views/meeting_portal_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dobtor_meeting_minutes/static/src/components/**/*',
            'dobtor_meeting_minutes/static/src/views/**/*',
            'dobtor_meeting_minutes/static/src/scss/**/*',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
