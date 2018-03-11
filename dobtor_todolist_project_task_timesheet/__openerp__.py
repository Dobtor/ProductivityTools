# -*- coding: utf-8 -*-
{
    'name': "dobtor_todolist_project_task_timesheet",

    'summary': """
        Short (1 phrase/line) summary of the module's purpose, used as
        subtitle on modules listing or apps.openerp.com""",

    'description': """
        Long description of module's purpose
    """,

    'author': "Steven, www.dobtor.com",
    'website': "www.dobtor.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/openerp/addons/base/module/module_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'dobtor_todolist_project_task', 'sale_timesheet'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/dobtor_todolist_project_task_timesheet_data.xml',
        'views/dobtor_todolist_project_task_timesheet_views.xml',
        'views/templates.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}