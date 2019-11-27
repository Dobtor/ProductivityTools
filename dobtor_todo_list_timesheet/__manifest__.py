# -*- coding: utf-8 -*-
{
    'name': "dobtor_todo_list_timesheet",
    'summary': """
        project task timesheet
    """,
    'description': """
        project task timesheet
    """,
    'author': "Dobtor SI",
    'website': "http://www.dobtor.com",
    'version': '0.1',
    'depends': ['base', 'dobtor_todo_list_project_task', 'hr_timesheet', 'sale_timesheet'],
    'data': [
        # 'security/ir.model.access.csv',
        'data/dobtor_timesheet_data.xml',
        'views/dobtor_todo_list_project_task_timesheet_views.xml',
    ],
}
