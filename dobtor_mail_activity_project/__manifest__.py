# -*- coding: utf-8 -*-
{
    'name': 'Advanced Activity Management - Project & Timesheet',
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Project link and timesheet logging for Advanced Activity Management',
    'description': """
Bridge between dobtor_mail_activity and Project / Timesheets
============================================================
Installed automatically when Project and Timesheets are installed.

* Project field on activities (relation diagram, customer fallback)
* Log time into timesheets when completing an activity
* "Log Time" afterwards (also for completed activities) once a project is linked
* Default timesheet project per company
* Hides project_todo's own To-do app (dobtor_mail_activity provides one)
    """,
    'author': 'Dobtor SI',
    'website': 'https://www.dobtor.com',
    'depends': [
        'dobtor_mail_activity',
        'project',
        'project_todo',
        'hr_timesheet',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/transfer_config_data.xml',
        'views/mail_activity_views.xml',
        'views/mail_activity_timesheet_views.xml',
        'views/res_company_views.xml',
        'views/res_config_settings_views.xml',
        'views/project_todo_override.xml',
    ],
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
