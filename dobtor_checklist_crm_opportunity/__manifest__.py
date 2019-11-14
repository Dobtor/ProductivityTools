# -*- coding: utf-8 -*-
{
    'name':
    "dobtor_checklist_crm_opportunity",
    'summary':
    """
        crm opportunity extend feature
    """,
    'description':
    """
        1. crm opportunity has checklist feature
        2. crm opportunity has template feature
    """,
    'author':
    "Dobtor SI",
    'website':
    "http://www.dobtor.com",
    'category':
    'crm',
    'version':
    '0.1',
    'depends': ['crm', 'sale', 'dobtor_checklist_core'],
    'data': [
        'security/ir.model.access.csv',
        'data/reference_model_data.xml',
        'views/dobtor_checklist_crm_opportunity_view.xml',
        'views/setting_crm_lead_view.xml',
    ],
}
