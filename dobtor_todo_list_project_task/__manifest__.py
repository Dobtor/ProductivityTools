# -*- coding: utf-8 -*-
{
    "name": "Dobtor Todo List Project Task",
    'summary': """
        Project Template
    """,
    'description': """
        *Dobtor Todo list project task bridge
        *Project Template
    """,
    'author': "Dobtor SI",
    'website': "http://www.dobtor.com",
    'category': 'project',
    'version': '0.1',
    'depends': [
        'project',
        'analytic',
        'dobtor_project_core',
        'dobtor_todo_list_core'
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/analytic_account.xml',
        'views/dobtor_todo_list_project_task.xml',
        'data/subscription_template.xml',
        'views/project_template_view.xml',
        'views/task_type.xml',
    ],
}
