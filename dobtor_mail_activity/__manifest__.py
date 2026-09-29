# -*- coding: utf-8 -*-
{
    'name': 'Advanced Activity Management',
    'version': '18.0.3.0.0',
    'category': 'Productivity',
    'summary': 'Advanced activity management: activities, weekly reports and efficiency analytics',
    'description': """
Advanced Activity Management (Productivity Tool)
=================================================
Complete activity management system built on mail.activity

Main Features:
--------------
* Notes (note.note) now live in dobtor_meeting_minutes, which depends on
  this module and adds the activity ↔ note integration.

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
        'hr',
        # 不相依 project / hr_timesheet / crm / sale_crm / project_todo。
        # 專案與工時整合 → dobtor_mail_activity_project（auto_install）
        # CRM／銷售整合   → dobtor_mail_activity_crm（auto_install）
    ],
    'data': [
        # Security
        'security/security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/mail_activity_data.xml',
        'data/mail_activity_transfer_config_data.xml',
        'data/cron_data.xml',
        # Wizards
        'views/wizard_views.xml',
        'views/mail_activity_create_wizard_views.xml',
        # Views
        'views/mail_activity_views.xml',
        'views/mail_message_templates.xml',
        'views/mail_activity_type_views.xml',
        'views/mail_activity_schedule_views.xml',
        'views/mail_activity_transfer_config_views.xml',
        'views/weekly_report_views.xml',
        'views/efficiency_views.xml',
        'views/res_users_views.xml',
        'views/res_config_settings_views.xml',
        'views/weekly_schedule_config_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # Vendored 邏輯圖渲染器（window.OdooMindMap，自 dobtor_xmind 複製，
            # 零 import 自足），供關聯圖 widget 使用。需先於 widget 載入。
            'dobtor_mail_activity/static/lib/mindmap/jsmind.css',
            'dobtor_mail_activity/static/lib/mindmap/jsmind.js',
            # Core (mail extensions)
            'dobtor_mail_activity/static/src/core/**/*',
            # Shared utilities
            'dobtor_mail_activity/static/src/utils/**/*',
            # Views
            'dobtor_mail_activity/static/src/views/**/*',
            # System integration (patches)
            'dobtor_mail_activity/static/src/web/**/*',
            # Rich text editor integration (powerbox / embedded activity list)
            'dobtor_mail_activity/static/src/editor/**/*',
            # Styles
            'dobtor_mail_activity/static/src/scss/**/*',
        ],
        # Tour（僅測試時載入）：週次選擇器與搜尋 facet 的共存驗證，
        # 這條路徑純前端資料流，Python 測不到。
        'web.assets_tests': [
            'dobtor_mail_activity/static/tests/tours/**/*',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
}
