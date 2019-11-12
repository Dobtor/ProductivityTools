# -*- coding: utf-8 -*-
{
    'name':
    "Dobtor Check list Core",
    'version':
    '1.0',
    'description':
    'Dobtor check list core',
    'author':
    'Dobtor SI',
    'website':
    'http://www.dobtor.com',
    'depends': ['base', 'mail'],
    'data': [
        'views/ir_attachment_view.xml',
        'views/checklist_tree_view.xml',
        'views/dobtor_checklist_core_view.xml',
        'data/subscription_template.xml',
        'views/configuration.xml',
    ],
    'installable':
    True,
}
