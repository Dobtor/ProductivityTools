# -*- coding: utf-8 -*-
{
    'name': 'Advanced Activity Management',
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Advanced activity management system integrating activities, notes, weekly reports and efficiency analytics',
    'description': """
Advanced Activity Management (Productivity Tool)
=================================================
Complete activity management system integrating mail.activity + note.note

Main Features:
--------------
* Note Features
  - Archive mechanism
  - Related display (CRM/Task)
  - Activity integration
  - Hierarchical tags

* Activity Assignment
  - Assignment filters (assigned by me/assigned to me/all)
  - Change assignment with history
  - Unassigned management
  - Priority settings (urgency/importance)
  - Estimated hours

* Activity Execution
  - Planned date management
  - Postpone to next week
  - Completion and timesheet recording
  - Timesheet integration

* Pre-scheduling Management
  - Next week pre-scheduling
  - Week transition mechanism
  - Schedule tracking

* Weekly Report
  - This week plan
  - Previous week variance analysis
  - Self-evaluation suggestions

* Efficiency Analytics
  - Personal efficiency dashboard
  - Team efficiency analysis
  - Estimation accuracy analysis
  - Postponement/completion rate analysis

* Activity Transfer
  - Configurable transfer target models
  - Transfer history tracking
  - Create activity from message
    """,
    'author': 'Dobtor SI',
    'website': 'https://www.dobtor.com',
    'depends': [
        'mail',
        'calendar',
        'portal',
        'hr_timesheet',
        'hr',
        'project',
        'project_todo',
        'crm',
        'sale_crm',
    ],
    'data': [
        # Security
        'security/security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/mail_activity_data.xml',
        'data/mail_activity_transfer_config_data.xml',
        'data/note_data.xml',
        'data/cron_data.xml',
        # Wizards
        'views/wizard_views.xml',
        # Views
        'views/calendar_event_views.xml',
        'views/mail_activity_views.xml',
        'views/mail_message_templates.xml',
        'views/mail_activity_type_views.xml',
        'views/mail_activity_schedule_views.xml',
        'views/mail_activity_transfer_config_views.xml',
        'views/note_tag_views.xml',
        'views/note_stage_views.xml',
        'views/note_views.xml',
        'views/weekly_report_views.xml',
        'views/efficiency_views.xml',
        'views/res_users_views.xml',
        'views/res_company_views.xml',
        'views/res_config_settings_views.xml',
        'views/weekly_schedule_config_views.xml',
        'views/crm_lead_views.xml',
        'views/project_project_views.xml',
        'views/project_todo_override.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # Core (mail extensions)
            'dobtor_mail_activity/static/src/core/**/*',
            # Components
            'dobtor_mail_activity/static/src/components/**/*',
            # Views
            'dobtor_mail_activity/static/src/views/**/*',
            # System integration (patches)
            'dobtor_mail_activity/static/src/web/**/*',
            # Styles
            'dobtor_mail_activity/static/src/scss/**/*',
        ],
        'web.assets_unit_tests': [
            'dobtor_mail_activity/static/tests/**/*',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
    'post_init_hook': '_post_init_hook',
}
