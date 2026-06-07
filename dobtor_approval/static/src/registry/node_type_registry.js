/** @odoo-module **/

/**
 * 節點型別前端註冊表（擴充注入點）。
 * 核心註冊標準 BPMN 元素；其他模組可 import 此物件並 register() 追加自訂節點。
 *
 * 註：目前 process_editor 使用 bpmn-js 原生 palette 與右側硬寫死的 OWL 設定面板，
 * 尚未有 UI 消費端讀此註冊表動態渲染（DESIGN_MODULE_SPLIT §4.1 為預留 roadmap）。
 * 後端的 bpmn.node.type.registry._get_node_types() 才有實際消費端（/dobtor_bpmn/node_types）。
 */
class NodeTypeRegistry {
    constructor() {
        this._types = [];
    }
    register(def) {
        if (!def || !def.id) {
            return;
        }
        // 同 id 覆寫
        const idx = this._types.findIndex((t) => t.id === def.id);
        if (idx >= 0) {
            this._types[idx] = def;
        } else {
            this._types.push(def);
        }
    }
    all() {
        return [...this._types];
    }
    byGroup(group) {
        return this._types.filter((t) => t.group === group);
    }
    clear() {
        this._types = [];
    }
}

export const nodeTypeRegistry = new NodeTypeRegistry();

// 核心標準節點（與後端 BASE_NODE_TYPES 對應，需保持兩端一致）
nodeTypeRegistry.register({ id: "bpmn:StartEvent", label: "開始", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:EndEvent", label: "結束", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:Task", label: "工作", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:UserTask", label: "人工工作", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:ExclusiveGateway", label: "互斥閘道", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:ParallelGateway", label: "並行閘道", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:SequenceFlow", label: "連線", group: "standard" });
