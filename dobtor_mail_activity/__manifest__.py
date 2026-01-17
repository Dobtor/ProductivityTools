# -*- coding: utf-8 -*-
{
    'name': '生產力工具',
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': '整合待辦管理、筆記本、週報告與效率分析的生產力工具',
    'description': """
生產力工具 (Productivity Tool)
==============================
整合 mail.activity + note.note 的完整生產力管理系統

主要功能：
---------
* 筆記本功能
  - 封存機制
  - 關聯顯示（CRM/Task）
  - 待辦整合
  - 階層式標籤

* 代辦指派
  - 指派篩選（我指派的/被委任的/所有的）
  - 更改指派與歷史記錄
  - 未指派管理
  - 優先級設定（時間性/重要性）
  - 預估工時

* 代辦執行
  - 計畫日期管理
  - 延至下週功能
  - 完成與工時記錄
  - 工時表整合

* 預排管理
  - 下週預排
  - 週轉換機制
  - 排程追蹤

* 週報告
  - 本週計畫
  - 前週差異分析
  - 自評建議

* 效率分析
  - 個人效率儀表板
  - 團隊效率分析
  - 預估準確度分析
  - 延期/完成率分析

* 待辦轉移
  - 可配置的轉移目標模型
  - 轉移歷史追蹤
  - 從訊息建立待辦
    """,
    'author': 'Dobtor SI',
    'website': 'https://www.dobtor.com',
    'depends': [
        'mail',
        'hr_timesheet',
        'hr',
        'project',
        'project_todo',
        'crm',
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
        'views/mail_activity_views.xml',
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
}
