/** @odoo-module **/

/**
 * 取代 `window.prompt()` 的輸入對話框。
 *
 * 為什麼非換不可 —— 原生 `prompt()`：
 *  - 會凍結 JS 執行緒，自動存檔的計時器與 OWL 的更新一起卡住；
 *  - tour／hoot 一律過不去（原生視窗不在 DOM 裡），所以這些流程完全無法自動測；
 *  - 外觀不隨 Odoo 的 dark/light 與語系走，也無法在對話框裡做驗證；
 *  - Safari 允許使用者勾「不要再顯示」，之後整個功能就靜默失效。
 *
 * 刻意做成多欄位（`fields`）而不是單一輸入框：超連結那個入口原本要連續彈兩次
 * `prompt()`（先網址再標題），使用者按第一個取消還是會被問第二次。做成一次一張
 * 表單，取消就是取消。
 */
import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class MindmapPromptDialog extends Component {
    static template = "dobtor_xmind.MindmapPromptDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        title: { type: String },
        /** [{ name, label, value?, placeholder?, type? }]，type 預設 "text" */
        fields: { type: Array },
        confirmLabel: { type: String, optional: true },
        /** (values) => any；回傳 false 代表不要關閉（驗證失敗） */
        onConfirm: { type: Function },
    };

    setup() {
        // 每個欄位都有固定名稱的 ref（t-ref 用動態字串 "input_" + index），
        // 這裡只需要第一個來自動聚焦。
        this.firstInput = useRef("input_0");
        this.state = useState({
            values: Object.fromEntries(
                this.props.fields.map((f) => [f.name, f.value ?? ""])
            ),
        });
        onMounted(() => {
            const el = this.firstInput.el;
            if (el) {
                el.focus();
                el.select();
            }
        });
    }

    get confirmLabel() {
        return this.props.confirmLabel || _t("Confirm");
    }

    onInput(name, ev) {
        this.state.values[name] = ev.target.value;
    }

    /** Enter 直接送出（單行輸入框的一般預期）。 */
    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onConfirm();
        }
    }

    onConfirm() {
        // onConfirm 明確回傳 false = 驗證未過，保持開啟讓使用者修正。
        if (this.props.onConfirm({ ...this.state.values }) === false) {
            return;
        }
        this.props.close();
    }
}
