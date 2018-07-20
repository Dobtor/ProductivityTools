# -*- coding: utf-8 -*-
{
    'name': "dobtor_crm_opportunity_template",

    'summary': """
        crm opportunity template""",

    'description': """
        crm opportunity template
    """,
    'author': "dobtor SI",
    'website': "http://www.dobtor.com",
    'category': 'crm',
    'version': '0.1',
    'depends': ['dobtor_todolist_crm_opportunity'],
    'data': [
        # 'security/ir.model.access.csv',
        'views/views.xml',
        'views/templates.xml',
    ],
}
