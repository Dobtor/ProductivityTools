{
    'name': 'Dobtor Approval (BPM 簽核引擎)',
    'version': '18.0.1.3.0',
    'category': 'Productivity',
    'summary': '台灣 BPM 簽核引擎：角色解析、Action 介入、token 執行、mail.activity 橋接、加簽/代理（T0–T6 能力開關）',
    'description': """
Dobtor Approval — BPM 簽核引擎（內含 BPMN 編輯器核心，可獨立設計簽核流程）
=========================================================
- 內建 BPMN 編輯器核心（bpmn-js / node 型別 registry），可獨立安裝後直接設計簽核流程
- 可執行簽核流程（bpmn.executable.process）：forked（複製 XML）獨立延伸
- 簽核人解析引擎（bpmn.role）：HR parent_id / department_manager / job / field / expression …
- Action 介入閘門（bpmn.action.gate）：攔截 → 進 BPMN → 核准回放原 action
- token 執行引擎（bpmn.process.instance + bpmn.token）
- mail.activity 橋接：簽核活動承載、_action_done hook 推進 token
- 加簽（runtime escalation）/ 職務代理（bpmn.delegation）
- T0–T6 能力開關（res.config.settings + ir.config_parameter，預設關閉）

非目標：不提供表單設計器。資料輸入一律使用 Odoo 原生 form view。
""",
    'author': 'Dobtor',
    'website': 'https://www.dobtor.com',
    'license': 'LGPL-3',
    'depends': ['web', 'mail', 'hr'],
    'data': [
        'security/dobtor_approval_security.xml',
        'security/ir.model.access.csv',
        'data/mail_activity_type_data.xml',
        'wizards/bpmn_escalate_wizard_views.xml',
        'wizards/bpmn_lateral_wizard_views.xml',
        'wizards/bpmn_reject_wizard_views.xml',
        'wizards/bpmn_delegate_wizard_views.xml',
        'views/bpmn_process_instance_views.xml',
        'views/bpmn_executable_process_views.xml',
        'views/bpmn_role_views.xml',
        'views/bpmn_action_gate_views.xml',
        'views/bpmn_delegation_views.xml',
        'views/bpmn_activity_link_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
        'views/bpmn_authority_matrix_views.xml',
        'views/dmn_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # bpmn-js / dmn-js 直接打包進模組（vendored，不再 runtime load / CDN）
            'dobtor_approval/static/lib/bpmn-io/bpmn-modeler.production.min.js',
            'dobtor_approval/static/lib/bpmn-io/assets/diagram-js.css',
            'dobtor_approval/static/lib/bpmn-io/assets/bpmn-js.css',
            'dobtor_approval/static/lib/bpmn-io/assets/bpmn.css',
            'dobtor_approval/static/lib/dmn-io/dmn-modeler.production.min.js',
            'dobtor_approval/static/lib/dmn-io/assets/dmn-js-shared.css',
            'dobtor_approval/static/lib/dmn-io/assets/dmn-js-drd.css',
            'dobtor_approval/static/lib/dmn-io/assets/dmn-js-decision-table.css',
            'dobtor_approval/static/lib/dmn-io/assets/dmn-js-decision-table-controls.css',
            'dobtor_approval/static/lib/dmn-io/assets/dmn-js-literal-expression.css',
            'dobtor_approval/static/lib/dmn-io/assets/dmn.css',
            'dobtor_approval/static/src/registry/node_type_registry.js',
            'dobtor_approval/static/src/registry/approval_node_types.js',
            'dobtor_approval/static/src/gate/approval_store.js',
            'dobtor_approval/static/src/gate/form_gate_patch.js',
            'dobtor_approval/static/src/gate/approval_bar.js',
            'dobtor_approval/static/src/gate/approval_bar.xml',
            'dobtor_approval/static/src/gate/approval_bar.scss',
            'dobtor_approval/static/src/gate/form_patches.js',
            'dobtor_approval/static/src/designer/odoo_properties_provider.js',
            'dobtor_approval/static/src/editor/process_editor.js',
            'dobtor_approval/static/src/editor/process_editor.xml',
            'dobtor_approval/static/src/editor/process_editor.scss',
            'dobtor_approval/static/src/components/flow_wizard/flow_wizard.js',
            'dobtor_approval/static/src/components/flow_wizard/flow_wizard_list_controller.js',
            'dobtor_approval/static/src/components/flow_wizard/flow_wizard.xml',
            'dobtor_approval/static/src/components/flow_wizard/flow_wizard.scss',
            'dobtor_approval/static/src/dmn_editor/dmn_editor.js',
            'dobtor_approval/static/src/dmn_editor/dmn_editor.xml',
            'dobtor_approval/static/src/dmn_editor/dmn_editor.scss',
            'dobtor_approval/static/src/fields/method_select.js',
            'dobtor_approval/static/src/fields/method_select.xml',
        ],
    },
    'demo': [
        'data/authority_matrix_demo.xml',
        'data/dmn_demo.xml',
    ],
    'application': True,
    'installable': True,
}
