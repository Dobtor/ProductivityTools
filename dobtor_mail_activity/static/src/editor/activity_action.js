/** @odoo-module **/

/**
 * 用 orm.call 取回的 act_window 是「未經 clean_action」的原始 dict——
 * 只帶 view_mode、沒有 views。Odoo 18 client 端 _preprocessAction 對
 * ir.actions.act_window 會執行 `action.views.map(...)`，views 為 undefined 時
 * 會丟 "Cannot read properties of undefined (reading 'map')"。
 *
 * 這裡補上 views（由 view_mode/view_id 推導），讓直接 doAction 原始 dict 也安全。
 */
export function ensureActionViews(action) {
    if (action && action.type === "ir.actions.act_window" && !action.views) {
        const mode = action.view_mode ? action.view_mode.split(",")[0] : "form";
        const viewId = Array.isArray(action.view_id) ? action.view_id[0] : false;
        action.views = [[viewId, mode]];
    }
    return action;
}
