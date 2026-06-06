/** @odoo-module **/

/**
 * 前端 Action 介入（DESIGN.md §5.2-A）。
 * Patch FormController 的 object 按鈕點擊：先 RPC check_bpmn_gate；
 * 若該 (model, method, res_id) 有 gate 且未核准 → 攔下，改起簽核實例並提示。
 *
 * 注意：這是 UX 層；後端 _register_hook guard 才是安全底線。
 */
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

patch(FormController.prototype, {
    async beforeExecuteActionButton(clickParams) {
        // 只攔 object 型按鈕、且有方法名、且記錄已存在
        const isObject = clickParams.type === "object";
        const method = clickParams.name;
        const resId = this.model?.root?.resId;
        const resModel = this.model?.root?.resModel;

        if (isObject && method && resId && resModel) {
            let result;
            try {
                result = await rpc("/dobtor_approval/check_bpmn_gate", {
                    model: resModel,
                    method,
                    res_id: resId,
                });
            } catch {
                result = null;
            }
            if (result && result.gated) {
                // 起簽核實例
                let started = null;
                try {
                    started = await rpc("/dobtor_approval/start_gate", {
                        model: resModel,
                        method,
                        res_id: resId,
                    });
                } catch {
                    // 後端 guard 仍會擋，無妨
                }
                const notif = this.env.services?.notification;
                if (notif) {
                    notif.add(
                        _t(
                            "此動作需經簽核。已送出簽核流程「%s」，核准後將自動執行。",
                            (started && started.process_name) || result.process_name
                        ),
                        { type: "warning" }
                    );
                }
                // 阻止原按鈕動作
                return false;
            }
        }
        return super.beforeExecuteActionButton(...arguments);
    },
});
