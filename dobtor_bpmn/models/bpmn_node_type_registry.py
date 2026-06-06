from odoo import api, models

# 核心標準節點型別（BPMN/DMN 標準元素）。
# 擴充模組（dobtor_approval）以 _inherit 此 AbstractModel、super() 後追加自訂節點。
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


class BpmnNodeTypeRegistry(models.AbstractModel):
    _name = 'bpmn.node.type.registry'
    _description = 'BPMN 節點型別註冊表（擴充注入點）'

    @api.model
    def _get_node_types(self):
        """回傳已註冊的節點型別清單。擴充模組覆寫此方法、super() 後追加。"""
        return list(BASE_NODE_TYPES)
