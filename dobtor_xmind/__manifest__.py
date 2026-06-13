# -*- coding: utf-8 -*-
{
    'name': 'Dobtor XMind Editor',
    'version': '18.0.1.0.0',
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
    'depends': ['base', 'web', 'mail', 'project'],
    'data': [
        'security/ir.model.access.csv',
        'security/xmind_security.xml',
        'data/xmind_marker_data.xml',
        'wizard/xmind_import_wizard_views.xml',
        'views/xmind_topic_views.xml',
        'views/xmind_workbook_views.xml',
        'views/project_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dobtor_xmind/static/src/fields/xmind_multi_file_field.js',
            'dobtor_xmind/static/src/fields/xmind_multi_file_field.xml',
            'dobtor_xmind/static/lib/jsmind/jsmind.css',
            'dobtor_xmind/static/lib/jsmind/jsmind.js',
            'dobtor_xmind/static/src/css/mindmap_editor.css',
            'dobtor_xmind/static/src/js/command_stack.js',
            'dobtor_xmind/static/src/js/xmind_features.js',
            'dobtor_xmind/static/src/js/drag_drop_manager.js',
            'dobtor_xmind/static/src/js/relationship_manager.js',
            'dobtor_xmind/static/src/js/mindmap_editor.js',
            'dobtor_xmind/static/src/xml/mindmap_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
