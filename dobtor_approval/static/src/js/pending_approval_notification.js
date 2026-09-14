/** @odoo-module **/
/**
 * 「已送出簽核」不是錯誤，不要用紅色 traceback 對話框呈現它。
 *
 * ☠★ BpmnPendingApproval 繼承 odoo.exceptions.UserError，但 web client 的
 *    錯誤對話框登記表是用**完整的例外名稱**當 key，不是用 isinstance：
 *
 *        registry.category("error_dialogs")
 *            .add("odoo.exceptions.UserError", WarningDialog)
 *            ...
 *
 *    我們的例外名字是
 *        odoo.addons.dobtor_approval.models.bpmn_guard_mixin.BpmnPendingApproval
 *    ——不在表裡，於是掉進通用的 RPCErrorDialog，使用者看到的是
 *    「Odoo Server Error」加一整段 Python traceback。功能是對的，
 *    但現場只會判定「簽核壞了」，然後要求把簽核關掉。
 *
 *    這是所有「自訂 UserError 子類別」共通的坑：後端看起來很乾淨，
 *    前端全部退化成 traceback。
 *
 * ☠️ 註冊在 error_notifications 而不是 error_dialogs：閘門攔截是**成功**的
 *    結果（單子已經送出去簽了），用警告對話框呈現會讓人以為動作失敗了。
 *    不給 message，讓它用伺服器那一句（裡面有流程名稱）。
 */
import { registry } from "@web/core/registry";

registry.category("error_notifications").add(
    "odoo.addons.dobtor_approval.models.bpmn_guard_mixin.BpmnPendingApproval",
    {
        type: "info",
        sticky: false,
    }
);
