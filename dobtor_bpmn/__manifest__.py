{
    'name': 'Dobtor BPMN (流程設計圖庫)',
    'version': '18.0.2.2.0',
    'category': 'Productivity',
    'summary': 'BPMN/DMN 流程設計圖庫，疊在 dobtor_approval 編輯器核心之上，可將設計圖交給簽核引擎',
    'description': """
Dobtor BPMN — 流程設計圖庫（依賴 dobtor_approval 編輯器核心）
============================
- 流程設計圖庫（bpmn.diagram）：用途分類 documentation / blueprint / template / executable_src
- 重用 dobtor_approval 內建的 BPMN 2.0 / DMN 視覺編輯器（bpmn-js / dmn-js）
- 設計圖可一鍵「建立簽核流程」，複製 XML 至 dobtor_approval 的可執行簽核流程（forked）
- 無角色、無簽核、無執行——純設計，作為設計/規格工具

非目標：不提供表單設計器。資料輸入一律使用 Odoo 原生 form view。
""",
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['dobtor_approval', 'project'],
    'data': [
        'security/dobtor_bpmn_security.xml',
        'security/ir.model.access.csv',
        'views/bpmn_diagram_category_views.xml',
        'views/bpmn_diagram_views.xml',
        'wizards/bpmn_diagram_import_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dobtor_bpmn/static/src/editor/bpmn_editor_action.js',
            'dobtor_bpmn/static/src/editor/bpmn_editor_action.xml',
            'dobtor_bpmn/static/src/editor/bpmn_editor_action.scss',
            'dobtor_bpmn/static/src/fields/bpmn_multi_file_field.js',
            'dobtor_bpmn/static/src/fields/bpmn_multi_file_field.xml',
            'dobtor_bpmn/static/src/views/bpmn_kanban.scss',
            # HTML editor "/" power-box — insert an existing BPMN/DMN diagram live
            # into any model's rich-text field (faithful, read-only render).
            'dobtor_bpmn/static/src/editor/bpmn_picker_dialog.js',
            'dobtor_bpmn/static/src/editor/bpmn_picker_dialog.xml',
            'dobtor_bpmn/static/src/editor/bpmn_diagram_embedding.js',
            'dobtor_bpmn/static/src/editor/bpmn_diagram_embedding.xml',
            'dobtor_bpmn/static/src/editor/bpmn_diagram_blueprint.xml',
            'dobtor_bpmn/static/src/editor/bpmn_powerbox_plugin.js',
            'dobtor_bpmn/static/src/editor/html_field_bpmn_patch.js',
        ],
    },
    'application': True,
    'installable': True,
}
