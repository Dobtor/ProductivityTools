# -*- coding: utf-8 -*-
{
    'name': "dobtor_todolist_project_task_timesheet",
    'summary': """
        project task timesheet
    """,
    'description': """
        project task timesheet
    """,
    'author': "Dobtor SI",
    'website': "http://www.dobtor.com",
    'category': 'todolist',
    'version': '0.1',
    'depends': ['base', 'dobtor_todolist_project_task', 'hr_timesheet', 'sale_timesheet'],
    'data': [
        # 'security/ir.model.access.csv',
        'views/dobtor_todolist_project_task_timesheet_data.xml',
        'views/dobtor_todolist_project_task_timesheet_views.xml',
    ],
}
