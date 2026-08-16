# -*- coding: utf-8 -*-
{
    'name': 'Dobtor Mind Map',
    'version': '18.0.3.0.0',
    'category': 'Productivity',
    'summary': 'Visual Mind Map Editor',
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
    'depends': ['base', 'web', 'mail', 'project', 'dobtor_project'],
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
            # 自帶 Open Sans（取代原本執行期注入的 Google Fonts CDN link）。
            # 必須排在用到該字型的樣式之前。
            'dobtor_xmind/static/lib/fonts/open_sans.css',
            'dobtor_xmind/static/lib/jsmind/jsmind.css',
            'dobtor_xmind/static/lib/jsmind/jsmind.js',
            'dobtor_xmind/static/src/css/mindmap_editor.css',
            'dobtor_xmind/static/src/js/command_stack.js',
            'dobtor_xmind/static/src/js/xmind_features.js',
            'dobtor_xmind/static/src/js/drag_drop_manager.js',
            'dobtor_xmind/static/src/js/relationship_manager.js',
            'dobtor_xmind/static/src/js/mindmap_project_bar.js',
            'dobtor_xmind/static/src/views/list_open_editor.js',
            'dobtor_xmind/static/src/js/mindmap_pager.js',
            'dobtor_xmind/static/src/js/mindmap_search.js',
            'dobtor_xmind/static/src/js/mindmap_templates_data.js',
            'dobtor_xmind/static/src/js/mindmap_prompt_dialog.js',
            'dobtor_xmind/static/src/js/mindmap_context_menu.js',
            'dobtor_xmind/static/src/js/mindmap_sheet_tabs.js',
            'dobtor_xmind/static/src/xml/mindmap_sheet_tabs.xml',
            'dobtor_xmind/static/src/xml/mindmap_prompt_dialog.xml',
            'dobtor_xmind/static/src/js/mindmap_editor.js',
            'dobtor_xmind/static/src/xml/mindmap_templates.xml',
            # Pre-fill the "Schedule Activity" wizard summary from the clicked node.
            'dobtor_xmind/static/src/js/activity_popover_summary_patch.js',
            # Gantt toolbar integration (dobtor_project) — create/open mind map.
            'dobtor_xmind/static/src/js/gantt_mindmap_button.js',
            'dobtor_xmind/static/src/xml/gantt_mindmap_button.xml',
            # HTML editor "/" power-box — insert an existing mind map live into any
            # model's rich-text field.
            'dobtor_xmind/static/src/editor/xmind_picker_dialog.js',
            'dobtor_xmind/static/src/editor/xmind_picker_dialog.xml',
            'dobtor_xmind/static/src/editor/xmind_mindmap_embedding.js',
            'dobtor_xmind/static/src/editor/xmind_mindmap_embedding.xml',
            'dobtor_xmind/static/src/editor/xmind_mindmap_blueprint.xml',
            'dobtor_xmind/static/src/editor/xmind_powerbox_plugin.js',
            'dobtor_xmind/static/src/editor/html_field_xmind_patch.js',
        ],
        # 端到端 tour（跑在真的瀏覽器裡，由 tests/test_sheet_tour.py 驅動）
        'web.assets_tests': [
            'dobtor_xmind/static/tests/tours/mindmap_sheet_tour.js',
        ],
        # hoot 單元測試。tours/ 要排除 —— 那是 assets_tests 的東西，
        # 混進來會在單元測試環境裡註冊 tour 而拖慢並污染結果。
        'web.assets_unit_tests': [
            'dobtor_xmind/static/tests/**/*',
            ('remove', 'dobtor_xmind/static/tests/tours/**/*'),
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
