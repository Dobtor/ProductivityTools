# -*- coding: utf-8 -*-
{
    'name': 'Advanced Activity Management - CRM',
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': 'CRM lead ↔ project link for Advanced Activity Management',
    'description': """
Bridge between dobtor_mail_activity_project and CRM / Sales
===========================================================
Installed automatically when CRM and Sales (sale_crm) are installed together
with the Project bridge.

* Project on CRM leads (create a project from a lead, tasks / timesheets smart buttons)
* Confirming a sales order writes the project back to its opportunity
* Activities on a lead log time into the lead's project
    """,
    'author': 'Dobtor SI',
    'website': 'https://www.dobtor.com',
    'depends': [
        'dobtor_mail_activity_project',
        'crm',
        'sale_crm',
    ],
    'data': [
        'views/crm_lead_views.xml',
        'views/project_project_views.xml',
    ],
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
