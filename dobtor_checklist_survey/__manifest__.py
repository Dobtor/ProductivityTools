# -*- coding: utf-8 -*-
{
    'name': "dobtor_checklist_survey",
    'summary': """
        1. checklist with survey functionality
        2. Management checklist survey input
        """,
    'description': """
        checklist with survey functionality
    """,
    'author': "Dobtor SI",
    'website': "http://www.dobtor.com",
    'category': 'survey',
    'version': '0.1',
    'depends': ['survey', 'dobtor_checklist_core'],
    'data': [
        'security/ir.model.access.csv',
        'views/checklist_views.xml',
        'views/history_survey.xml',
    ]
}
