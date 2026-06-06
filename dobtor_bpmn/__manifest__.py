{
    'name': 'Dobtor BPMN (核心·純設計)',
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Odoo 內的 BPMN/DMN 純設計環境（等同 demo.bpmn.io），無執行語意',
    'description': """
Dobtor BPMN — 核心純設計模組
============================
- BPMN 2.0 / DMN 視覺編輯器（bpmn-js / dmn-js）
- 流程設計圖庫（bpmn.diagram）：用途分類 documentation / blueprint / template / executable_src
- 節點型別 registry（供簽核擴充 dobtor_approval 注入新節點）
- 無角色、無簽核、無執行——純設計，可獨立成立為設計/規格工具

非目標：不提供表單設計器。資料輸入一律使用 Odoo 原生 form view。
""",
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/dobtor_bpmn_security.xml',
        'security/ir.model.access.csv',
        'views/bpmn_diagram_category_views.xml',
        'views/bpmn_diagram_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dobtor_bpmn/static/src/registry/node_type_registry.js',
            'dobtor_bpmn/static/src/modeler/lib_loader.js',
            'dobtor_bpmn/static/src/fields/bpmn_editor_field.js',
            'dobtor_bpmn/static/src/fields/bpmn_editor_field.xml',
            'dobtor_bpmn/static/src/fields/bpmn_editor_field.scss',
        ],
    },
    'application': True,
    'installable': True,
}
