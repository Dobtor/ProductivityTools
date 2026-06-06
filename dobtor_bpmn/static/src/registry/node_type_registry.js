/** @odoo-module **/

/**
 * 節點型別前端註冊表。
 * 核心註冊標準 BPMN 元素；擴充模組（dobtor_approval）import 此物件並 register() 追加簽核節點。
 * 編輯器的調色盤 / 屬性面板 / element-templates 讀此註冊表動態渲染。
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

// 核心標準節點（與後端 BASE_NODE_TYPES 對應）
nodeTypeRegistry.register({ id: "bpmn:StartEvent", label: "開始", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:EndEvent", label: "結束", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:UserTask", label: "人工工作", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:ExclusiveGateway", label: "互斥閘道", group: "standard" });
nodeTypeRegistry.register({ id: "bpmn:ParallelGateway", label: "並行閘道", group: "standard" });
