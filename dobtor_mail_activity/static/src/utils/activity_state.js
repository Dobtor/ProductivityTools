/** @odoo-module **/

/**
 * 依待辦排程狀態回傳 Bootstrap 文字（與可選邊框）色彩 class，
 * 比照原生列表視圖的時鐘著色：逾期=紅、今天=黃、已排程=綠。
 *
 * 集中此對映，供內嵌清單、膠囊、選擇對話框、工具列時鐘共用。
 *
 * @param {string} state  'overdue' | 'today' | 'planned' | ...
 * @param {{active?: boolean, withBorder?: boolean, mutedDefault?: boolean}} [opts]
 *        active：待辦是否仍作用中（false → 灰）；
 *        withBorder：是否一併回傳對應的 border-* class；
 *        mutedDefault：未知/無狀態時回傳灰（true）或綠（false，預設）。
 * @returns {string}
 */
export function activityStateClass(
    state,
    { active = true, withBorder = false, mutedDefault = false } = {}
) {
    const pick = (text, border) => (withBorder ? `${text} ${border}` : text);
    if (!active) {
        return pick("text-muted", "border-secondary");
    }
    switch (state) {
        case "overdue":
            return pick("text-danger", "border-danger");
        case "today":
            return pick("text-warning", "border-warning");
        case "planned":
            return pick("text-success", "border-success");
        default:
            return mutedDefault
                ? pick("text-muted", "border-secondary")
                : pick("text-success", "border-success");
    }
}
