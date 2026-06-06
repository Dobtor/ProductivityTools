# -*- coding: utf-8 -*-
"""向核心 bpmn.node.type.registry 註冊簽核專屬節點型別 — DESIGN_MODULE_SPLIT.md §4.2。

核心 dobtor_bpmn 提供 AbstractModel bpmn.node.type.registry，方法 _get_node_types()
回傳 list[dict]。此處 _inherit + super() 後追加簽核節點（approvalTask / odooActionTask /
conditionGateway 等），讓核心編輯器後端解析能認得這些節點。

每個 dict 契約：{id, label, group, bpmn_type, moddle_props}
"""
from odoo import models

# 簽核擴充節點型別定義
APPROVAL_NODE_TYPES = [
    {
        'id': 'odoo:approvalTask',
        'label': '簽核任務',
        'group': 'odoo',
        'bpmn_type': 'bpmn:UserTask',
        'moddle_props': ['odoo:roleRef', 'odoo:approvalMode', 'odoo:allowEscalation'],
    },
    {
        'id': 'odoo:cosignTask',
        'label': '會簽任務',
        'group': 'odoo',
        'bpmn_type': 'bpmn:UserTask',
        'moddle_props': ['odoo:roleRef', 'odoo:approvalMode'],
    },
    {
        'id': 'odoo:odooActionTask',
        'label': '執行 Odoo 動作',
        'group': 'odoo',
        'bpmn_type': 'bpmn:ServiceTask',
        'moddle_props': ['odoo:serverAction', 'odoo:boundMethod'],
    },
    {
        'id': 'odoo:conditionGateway',
        'label': '條件分歧',
        'group': 'odoo',
        'bpmn_type': 'bpmn:ExclusiveGateway',
        'moddle_props': ['odoo:condition'],
    },
    {
        'id': 'odoo:parallelGateway',
        'label': '平行會簽',
        'group': 'odoo',
        'bpmn_type': 'bpmn:ParallelGateway',
        'moddle_props': [],
    },
]


class BpmnNodeTypeRegistry(models.AbstractModel):
    _inherit = 'bpmn.node.type.registry'

    def _get_node_types(self):
        types = super()._get_node_types()
        # 以 id 去重後追加（避免核心已宣告同 id 時重複）
        existing_ids = {t.get('id') for t in types}
        for nt in APPROVAL_NODE_TYPES:
            if nt['id'] not in existing_ids:
                types.append(nt)
        return types
