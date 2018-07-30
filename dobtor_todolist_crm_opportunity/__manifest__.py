# -*- coding: utf-8 -*-
{
    'name': "dobtor_todolist_crm_opportunity",
    'summary': """
        crm opportunity extend freature
    """,
    'description': """
        1. crm opportunity has todolist freature
        2. crm opportunity has template freature
    """,
    'author': "dobtor SI",
    'website': "http://www.dobtor.com",
    'category': 'crm',
    'version': '0.1',
    'depends': ['crm','sale','dobtor_todolist_core'],
    'data': [
        'views/dobtor_todolist_crm_opportunity_view.xml',
        'views/dobtor_todolist_crm_opportunity_data.xml',
        'views/setting_crm_lead_view.xml',
    ],
}
