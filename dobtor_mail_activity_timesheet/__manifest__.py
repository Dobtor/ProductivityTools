# -*- coding: utf-8 -*-
{
    'name': 'Advanced Activity Management - Timesheet & CRM Bridge',
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Timesheet integration and CRM/Project/Sales workflow for Advanced Activity Management',
    'description': """
Advanced Activity Management - Timesheet & CRM Bridge
=====================================================
Auto-installing bridge between ``dobtor_mail_activity`` and the
CRM / Project / Sales / Timesheet stack. Installs automatically only when
both the core module and the full stack are present, so the core module
stays installable on a minimal Odoo (mail only).

Adds back the integration features that genuinely cannot be configuration
driven (typed relations, foreign-model UI, fields added to foreign models):

* Timesheet integration
  - ``account.analytic.line.activity_id`` linkage
  - ``mail.activity.actual_hours`` recomputed from linked timesheets
  - Timesheet tab on the activity form
  - Activity completion creates timesheet entries (done wizard)
  - Company default timesheet project setting

* CRM / Project / Sales workflow
  - ``crm.lead.project_id`` + auto-fill default project + timesheet migration
  - Sales order confirmation writes the project back to the lead
  - Project smart button to related leads
  - Replaces the project_todo menu action with "My Activities"
    """,
    'author': 'Dobtor SI',
    'website': 'https://www.dobtor.com',
    'depends': [
        'dobtor_mail_activity',
        'hr_timesheet',
        'crm',
        'sale_crm',
        'project',
        'project_todo',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/crm_lead_views.xml',
        'views/project_project_views.xml',
        'views/mail_activity_timesheet_views.xml',
        'views/project_todo_override.xml',
    ],
    'installable': True,
    # 當核心模組與整個 CRM/專案/銷售/工時堆疊都安裝時自動安裝；
    # 缺任一依賴則不安裝，核心模組仍可獨立輕量安裝。
    'auto_install': True,
    'application': False,
    'license': 'LGPL-3',
    'post_init_hook': '_post_init_hook',
}
