/** @odoo-module **/

/**
 * 向核心 dobtor_bpmn 編輯器註冊簽核專屬節點型別（積木）。
 * 契約：@dobtor_bpmn/registry/node_type_registry 匯出 nodeTypeRegistry，
 * 提供 register(def) / all()。本檔載入時 register 簽核積木。
 *
 * DESIGN_MODULE_SPLIT.md §4.1、DESIGN_SELF_SERVICE_DESIGNER.md §3.1。
 */
import { nodeTypeRegistry } from "@dobtor_bpmn/registry/node_type_registry";

// element-template：簽核任務（只露業務欄位，隱藏 BPMN 術語）
const APPROVAL_TASK_TEMPLATE = {
    name: "簽核任務",
    id: "dobtor.approval_task",
    appliesTo: ["bpmn:UserTask"],
    properties: [
        {
            label: "簽核對象",
            type: "Dropdown",
            binding: { type: "property", name: "odoo:roleRef" },
            choices: "@rpc:bpmn.role.options",
        },
        {
            label: "簽核方式",
            type: "Dropdown",
            binding: { type: "property", name: "odoo:approvalMode" },
            choices: [
                { name: "任一人核准即過", value: "any" },
                { name: "全部核准(會簽)", value: "all" },
                { name: "依序簽核", value: "sequential" },
            ],
        },
        {
            label: "允許主管自行往上加簽",
            type: "Boolean",
            binding: { type: "property", name: "odoo:allowEscalation" },
        },
    ],
};

const ODOO_ACTION_TEMPLATE = {
    name: "執行 Odoo 動作",
    id: "dobtor.odoo_action_task",
    appliesTo: ["bpmn:ServiceTask"],
    properties: [
        {
            label: "綁定動作",
            type: "Dropdown",
            binding: { type: "property", name: "odoo:serverAction" },
            choices: "@rpc:bpmn.action.options",
        },
    ],
};

const APPROVAL_NODE_DEFS = [
    {
        id: "odoo:approvalTask",
        label: "簽核任務",
        group: "odoo",
        appliesTo: "bpmn:UserTask",
        moddle: "odoo:roleRef",
        feature: "basic_approval",
        template: APPROVAL_TASK_TEMPLATE,
    },
    {
        id: "odoo:cosignTask",
        label: "會簽任務",
        group: "odoo",
        appliesTo: "bpmn:UserTask",
        moddle: "odoo:approvalMode",
        feature: "cosign",
        template: APPROVAL_TASK_TEMPLATE,
    },
    {
        id: "odoo:odooActionTask",
        label: "執行 Odoo 動作",
        group: "odoo",
        appliesTo: "bpmn:ServiceTask",
        moddle: "odoo:serverAction",
        feature: "action_gate",
        template: ODOO_ACTION_TEMPLATE,
    },
    {
        id: "odoo:conditionGateway",
        label: "條件分歧",
        group: "odoo",
        appliesTo: "bpmn:ExclusiveGateway",
        moddle: "odoo:condition",
        feature: "conditional",
    },
    {
        id: "odoo:parallelGateway",
        label: "平行會簽",
        group: "odoo",
        appliesTo: "bpmn:ParallelGateway",
        moddle: "",
        feature: "parallel_gw",
    },
];

// 容錯：核心 registry 尚未提供 register 時不致整包報錯
if (nodeTypeRegistry && typeof nodeTypeRegistry.register === "function") {
    for (const def of APPROVAL_NODE_DEFS) {
        nodeTypeRegistry.register(def);
    }
}

export { APPROVAL_NODE_DEFS };
