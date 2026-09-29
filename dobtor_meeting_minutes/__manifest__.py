# -*- coding: utf-8 -*-
{
    'name': 'Meeting Minutes',
    'version': '18.0.3.0.0',
    'category': 'Productivity',
    'summary': 'Notes and meeting minutes: personal notes, recording, transcription and signatures',
    'description': """
Notes & Meeting Minutes
=======================
Personal notes (note.note: stages, tags, archive, "Personal Notes" app) and
complete meeting minutes management. Integrates with dobtor_mail_activity:
source note / referenced notes on activities, related notes in chatter,
to-do lists inside notes, weekly schedule notes.

* Recording & Transcription
  - Browser-based audio recording
  - Speech-to-text with speaker diarization (AssemblyAI / OpenAI Whisper / whisperX)
  - Multi-segment recording with automatic time offset merging
  - Inline audio player and transcript editing

* Transcript Export
  - Export transcript as TXT or SRT

  Note: AI meeting summary (via the AI Chatbot platform) is provided by the
  optional bridge module *dobtor_ai_chatbot_meeting_minutes*, which
  auto-installs when both this module and *dobtor_ai_chatbot* are present.

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
        'data/note_stage_data.xml',
        'data/transfer_config_data.xml',
        'data/mail_template_data.xml',
        'data/cron_data.xml',
        # Views — 筆記本體（自 dobtor_mail_activity 搬入）先於會議記錄擴充
        'views/note_base_views.xml',
        'views/note_stage_views.xml',
        'views/note_tag_views.xml',
        'views/mail_activity_note_views.xml',
        'views/calendar_event_views.xml',
        'views/note_views.xml',
        'views/note_recording_views.xml',
        'views/note_transcribe_log_views.xml',
        'views/note_transcribe_job_views.xml',
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
            'dobtor_meeting_minutes/static/src/web/**/*',
            'dobtor_meeting_minutes/static/src/scss/**/*',
        ],
        'web.assets_tests': [
            'dobtor_meeting_minutes/static/tests/tours/**/*',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
    'pre_init_hook': '_pre_init_hook',
    'post_init_hook': '_post_init_hook',
}
