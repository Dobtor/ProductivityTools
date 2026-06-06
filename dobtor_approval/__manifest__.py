{
    'name': 'Dobtor Approval (BPM 簽核引擎)',
    'version': '18.0.1.1.0',
    'category': 'Productivity',
    'summary': '台灣 BPM 簽核引擎：角色解析、Action 介入、token 執行、mail.activity 橋接、加簽/代理（T0–T6 能力開關）',
    'description': """
Dobtor Approval — BPM 簽核引擎（擴充 dobtor_bpmn 核心純設計）
=========================================================
- 可執行簽核流程（bpmn.executable.process）：linked / forked 兩種延伸模式
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
    'depends': ['dobtor_bpmn', 'mail', 'hr'],
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
    ],
    'assets': {
        'web.assets_backend': [
            'dobtor_approval/static/src/registry/approval_node_types.js',
            'dobtor_approval/static/src/gate/form_gate_patch.js',
            'dobtor_approval/static/src/designer/odoo_properties_provider.js',
            'dobtor_approval/static/src/editor/process_editor.js',
            'dobtor_approval/static/src/editor/process_editor.xml',
            'dobtor_approval/static/src/editor/process_editor.scss',
        ],
    },
    'application': True,
    'installable': True,
}
