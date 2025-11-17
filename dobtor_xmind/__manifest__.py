# -*- coding: utf-8 -*-
{
    'name': 'Dobtor XMind Editor',
    'version': '14.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Visual Mind Map Editor with XMind 2 Features',
    'description': '''
        Complete mind mapping solution with advanced editing features:
        - Undo/Redo system (Command Pattern)
        - Multiple layout algorithms
        - Topic styling and theming
        - Markers, icons, and labels
        - Relationship lines
        - Notes and attachments
        - Import/Export .xmind files
        - Drag-and-drop reorganization
    ''',
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'data/xmind_marker_data.xml',
        'views/xmind_topic_views.xml',
        'views/xmind_workbook_views.xml',
        'views/menu_views.xml',
        'views/templates.xml',
    ],
    # Note: Assets are defined in views/templates.xml for Odoo 14 compatibility
    # The 'assets' key is only supported in Odoo 15+
    'qweb': [
        'static/src/xml/mindmap_templates.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
