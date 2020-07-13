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
        'security/ir_rule.xml',
        'data/todo_type_data.xml',
        'views/ir_attachment_view.xml',
        'views/todo_list_tree_view.xml',
        'views/dobtor_todo_list_core_view.xml',
        'data/subscription_template.xml',
        'views/configuration.xml',
        'views/todo_list_type_view.xml',
    ],
    'installable':
    True,
}
