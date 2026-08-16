/** @odoo-module **/

/**
 * 待辦 wizard 的統一開啟入口。
 *
 * 背景：本模組在 views/*.xml 已定義七個 wizard 的 ir.actions.act_window，
 * 但前端各處原本各自手刻等價的 doAction({type:'ir.actions.act_window', …})
 * —— 光是「建立待辦」就散在 7 個檔案。後果是改一個標題要動七處，XML action
 * 上的設定（name、未來可能綁的 view_id）也完全被繞過，等於七個死掉的 record。
 *
 * 這裡改成一律以 XML ID 開啟，XML action 成為單一真實來源。
 */

/** 七個 wizard 的 XML ID（集中定義，避免字串散落各處拼錯）。 */
export const ACTIVITY_WIZARDS = {
    create: "dobtor_mail_activity.action_mail_activity_create_wizard",
    done: "dobtor_mail_activity.action_mail_activity_done_wizard",
    cancel: "dobtor_mail_activity.action_mail_activity_cancel_wizard",
    postpone: "dobtor_mail_activity.action_mail_activity_postpone_wizard",
    transfer: "dobtor_mail_activity.action_mail_activity_transfer_wizard",
    reassign: "dobtor_mail_activity.action_mail_activity_reassign_wizard",
    merge: "dobtor_mail_activity.action_mail_activity_merge_wizard",
};

/**
 * 以彈窗開啟指定的待辦 wizard。
 *
 * @param {object} actionService  action service（useService("action") 取得）
 * @param {string} xmlId          ACTIVITY_WIZARDS 之一
 * @param {object} [context]      額外 context（default_* / active_* 等）
 * @param {object} [options]
 * @param {Function} [options.onClose]  關閉回呼，收到 wizard 回傳的 infos
 * @param {string}   [options.name]     覆寫視窗標題。僅在同一個 wizard 有多種
 *                                      情境、標題需要區分時使用（例如批次延期
 *                                      要顯示「Batch Postpone」而非 XML 上的
 *                                      「Postpone to Next Week」）；不傳則沿用
 *                                      XML action 的名稱。
 * @returns {Promise}
 */
export async function openActivityWizard(actionService, xmlId, context = {}, options = {}) {
    const { name, ...actionOptions } = options;
    if (!name) {
        return actionService.doAction(xmlId, {
            additionalContext: context,
            ...actionOptions,
        });
    }
    // 需要改標題時先載入再覆寫，仍以 XML action 為基礎（target/view_mode/
    // res_model 都沿用它），只換 name。
    const action = await actionService.loadAction(xmlId, context);
    return actionService.doAction(
        { ...action, name },
        { additionalContext: context, ...actionOptions }
    );
}
