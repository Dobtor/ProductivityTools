# -*- coding: utf-8 -*-
{
    'name':
    "Dobtor Todo list Core",
    'version':
    '1.0',
    'description':
    'Dobtor todo list core',
    'author':
    'Dobtor SI',
    'website':
    'http://www.dobtor.com',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/ir_attachment_view.xml',
        'views/todo_list_tree_view.xml',
        'views/dobtor_todo_list_core_view.xml',
        'data/subscription_template.xml',
        'views/configuration.xml',
    ],
    'installable':
    True,
}
