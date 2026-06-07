/** @odoo-module **/

/**
 * 簽核屬性面板的動態選項提供者（DESIGN_SELF_SERVICE_DESIGNER.md §3.2）。
 * 供 element-template 的 "@rpc:bpmn.role.options" / "@rpc:bpmn.action.options"
 * 動態下拉使用：即時從 Odoo 抓角色 / Action 清單，避免填錯字。
 *
 * 編輯器核心的屬性面板 provider 可呼叫本檔的 resolveRpcChoices()。
 */
import { rpc } from "@web/core/network/rpc";

const _cache = {};

/**
 * 解析 element-template 中 "@rpc:<key>" 形式的 choices。
 * @param {string} rpcKey  例如 "bpmn.role.options"
 * @param {Object} ctx     可選 context（如 {process_id}）
 * @returns {Promise<Array<{name, value}>>}
 */
export async function resolveRpcChoices(rpcKey, ctx = {}) {
    const cacheKey = `${rpcKey}:${JSON.stringify(ctx)}`;
    if (_cache[cacheKey]) {
        return _cache[cacheKey];
    }
    let choices = [];
    try {
        if (rpcKey === "bpmn.role.options") {
            const records = await rpc("/web/dataset/call_kw", {
                model: "bpmn.role",
                method: "search_read",
                args: [ctx.process_id ? [["process_id", "=", ctx.process_id]] : [], ["id", "name"]],
                kwargs: {},
            });
            choices = records.map((r) => ({ name: r.name, value: String(r.id) }));
        } else if (rpcKey === "bpmn.action.options") {
            const records = await rpc("/web/dataset/call_kw", {
                model: "ir.actions.server",
                method: "search_read",
                args: [[["state", "=", "code"]], ["id", "name"]],
                kwargs: { limit: 200 },
            });
            choices = records.map((r) => ({ name: r.name, value: String(r.id) }));
        }
    } catch {
        choices = [];
    }
    _cache[cacheKey] = choices;
    return choices;
}

/** 取得目前公司啟用的能力清單（設計器過濾調色盤用）。 */
export async function getEnabledFeatures() {
    try {
        return await rpc("/dobtor_approval/enabled_features", {});
    } catch {
        return ["wizard", "basic_approval"];
    }
}
