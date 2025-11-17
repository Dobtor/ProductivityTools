# -*- coding: utf-8 -*-
{
    'name': 'XMind Editor',
    'version': '14.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Create and edit XMind mind maps in Odoo',
    'description': """
        XMind Mind Map Editor for Odoo
        ===============================

        Features:
        - Visual mind map editor with drag-and-drop
        - Import/Export .xmind files
        - Hierarchical topic management
        - Notes, markers, and labels support
        - Multiple themes (Robust, Snowbrush, Business)
        - Collaborative editing
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/xmind_marker_data.xml',
        'views/xmind_workbook_views.xml',
        'views/xmind_topic_views.xml',
        'views/menu_views.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dobtor_xmind/static/lib/jsmind/jsmind.css',
            'dobtor_xmind/static/lib/jsmind/jsmind.js',
            'dobtor_xmind/static/src/css/mindmap_editor.css',
            'dobtor_xmind/static/src/js/mindmap_editor.js',
        ],
    },
    'qweb': [
        'static/src/xml/mindmap_templates.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
