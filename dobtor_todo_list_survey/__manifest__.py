# -*- coding: utf-8 -*-
{
    'name': "dobtor_todo_list_survey",
    'summary': """
        1. Todo-list with survey functionality
        2. Management todo-list survey input
        """,
    'description': """
        Todo-list with survey functionality
    """,
    'author': "Dobtor SI",
    'website': "http://www.dobtor.com",
    'category': 'survey',
    'version': '0.1',
    'depends': ['survey', 'dobtor_todo_list_core'],
    'data': [
        'security/ir.model.access.csv',
        'views/todo_list_views.xml',
        'views/history_survey.xml',
    ]
}
