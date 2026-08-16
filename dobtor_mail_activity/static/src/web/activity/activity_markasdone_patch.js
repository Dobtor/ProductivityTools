/** @odoo-module **/

import { ActivityMarkAsDone } from "@mail/core/web/activity_markasdone_popover";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { useState } from "@odoo/owl";
import {
    openActivityWizard,
    ACTIVITY_WIZARDS,
} from "@dobtor_mail_activity/utils/activity_actions";

/**
 * Patch ActivityMarkAsDone — 在原生「標示完成」popover 加上本模組的動作：
 * 登錄並繼續 / 延期 / 轉移 / 取消 / 變更指派。
 *
 * 五個動作的流程完全相同（關 popover → 開 wizard → 等關閉 → 通知 thread 刷新），
 * 故收斂到 _openActivityWizard()；wizard 本身一律以 XML action 開啟
 * （見 utils/activity_actions.js），標題只在語意確實不同時才覆寫。
 */
patch(ActivityMarkAsDone.prototype, {
    setup() {
        super.setup(...arguments);
        this.actionService = useService("action");
        this.store = useState(useService("mail.store"));
    },

    /**
     * 開啟針對目前這筆待辦的 wizard，關閉後通知 chatter 刷新。
     *
     * @param {string} wizardKey ACTIVITY_WIZARDS 的鍵
     * @param {string} [name]    標題覆寫（僅在同一 wizard 有不同語意時使用）
     */
    async _openActivityWizard(wizardKey, name) {
        const { id, res_id, res_model } = this.props.activity;
        // 先取得 thread：popover 關閉後 props 可能失效，故在關閉前取好
        const thread = this.store.Thread.insert({ model: res_model, id: res_id });

        if (this.props.close) {
            this.props.close();
        }

        await new Promise((resolve) =>
            openActivityWizard(
                this.actionService,
                ACTIVITY_WIZARDS[wizardKey],
                { default_activity_id: id },
                { onClose: resolve, ...(name ? { name } : {}) }
            )
        );

        this.props.onActivityChanged(thread);
    },

    /** 登錄並繼續：開完成 wizard，但只登錄工時、不完成待辦 —— 與「完成」語意不同，故覆寫標題。 */
    onClickLogAndContinue() {
        return this._openActivityWizard("done", _t("Log and Continue"));
    },

    /** 延期至下週 */
    onClickPostpone() {
        return this._openActivityWizard("postpone");
    },

    /** 轉移到其他文件 */
    onClickTransfer() {
        return this._openActivityWizard("transfer");
    },

    /** 取消待辦（需填原因） */
    onClickCancelActivity() {
        return this._openActivityWizard("cancel");
    },

    /** 變更指派對象 */
    onClickReassign() {
        return this._openActivityWizard("reassign");
    },
});
