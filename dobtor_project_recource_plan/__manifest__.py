# -*- coding: utf-8 -*-
{
    'name':
    "Dobtor Project Resource Plan",
    'summary':
    """
        Dobtor Project Resource Plan""",
    'description':
    """
        Dobtor Project Resource Plan
    """,
    'author':
    "Dobtor SI",
    'website':
    "http://www.dobtor.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/12.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category':
    'Project',
    'version':
    '12.0.1',

    # any module necessary for this one to work correctly
    'depends': ['dobtor_todo_list_project_task'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/plan_view.xml',
        'views/plan_request.xml',
        'views/views.xml',
        'views/project_task.xml',
        'wizard/todo_user_wizards.xml',
        'wizard/project_task_resource_plan.xml',
    ],
}