# -*- coding: utf-8 -*-
{
    'name': "dobtor_todolist_crm_opportunity",
    'summary': """
        with crm opportunity template
    """,
    'description': """
        with crm opportunity template
    """,
    'author': "dobtor SI",
    'website': "http://www.dobtor.com",
    'category': 'crm',
    'version': '0.1',
    'depends': ['crm','sale','dobtor_todolist_core'],
    # always loaded
    'data': [
        'views/dobtor_todolist_crm_opportunity_view.xml',
        'views/dobtor_todolist_crm_opportunity_data.xml',
        'views/setting_crm_lead_view.xml',
    ],
}
