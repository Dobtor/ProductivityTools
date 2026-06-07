# -*- coding: utf-8 -*-
"""BPMN 節點型別註冊表（編輯器核心 + 簽核擴充）。

反轉依賴後，編輯器核心移入本模組（dobtor_approval）：
- BASE_NODE_TYPES + AbstractModel `bpmn.node.type.registry` 提供標準 BPMN/DMN 節點。
- 同檔以 _inherit + super() 追加簽核專屬節點（approvalTask / odooActionTask /
  conditionGateway 等），讓後端解析認得這些節點。

每個 dict 契約：{id, label, group, bpmn_type, moddle_props}
其他模組可 _inherit 此 AbstractModel、super() 後追加自訂節點。
"""
from odoo import api, models

# 核心標準節點型別（BPMN/DMN 標準元素）。
BASE_NODE_TYPES = [
    {'id': 'bpmn:StartEvent', 'label': '開始', 'group': 'standard',
     'bpmn_type': 'bpmn:StartEvent', 'moddle_props': []},
    {'id': 'bpmn:EndEvent', 'label': '結束', 'group': 'standard',
     'bpmn_type': 'bpmn:EndEvent', 'moddle_props': []},
    {'id': 'bpmn:Task', 'label': '工作', 'group': 'standard',
     'bpmn_type': 'bpmn:Task', 'moddle_props': []},
    {'id': 'bpmn:UserTask', 'label': '人工工作', 'group': 'standard',
     'bpmn_type': 'bpmn:UserTask', 'moddle_props': []},
    {'id': 'bpmn:ExclusiveGateway', 'label': '互斥閘道(XOR)', 'group': 'standard',
     'bpmn_type': 'bpmn:ExclusiveGateway', 'moddle_props': []},
    {'id': 'bpmn:ParallelGateway', 'label': '並行閘道(AND)', 'group': 'standard',
     'bpmn_type': 'bpmn:ParallelGateway', 'moddle_props': []},
    {'id': 'bpmn:SequenceFlow', 'label': '連線', 'group': 'standard',
     'bpmn_type': 'bpmn:SequenceFlow', 'moddle_props': []},
]

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
    _name = 'bpmn.node.type.registry'
    _description = 'BPMN 節點型別註冊表（擴充注入點）'

    @api.model
    def _get_node_types(self):
        """回傳已註冊的節點型別清單。擴充模組覆寫此方法、super() 後追加。"""
        types = list(BASE_NODE_TYPES)
        # 以 id 去重後追加簽核節點
        existing_ids = {t.get('id') for t in types}
        for nt in APPROVAL_NODE_TYPES:
            if nt['id'] not in existing_ids:
                types.append(nt)
        return types
