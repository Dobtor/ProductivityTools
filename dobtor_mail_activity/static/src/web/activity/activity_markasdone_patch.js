/** @odoo-module **/

import { ActivityMarkAsDone } from "@mail/core/web/activity_markasdone_popover";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";

/**
 * Patch ActivityMarkAsDone - 添加「登錄並繼續」和「延期至下週」按鈕
 *
 * 參考 dobtor_mail_activity.mail_activity_done_wizard_view_form 的按鈕設計
 */
patch(ActivityMarkAsDone.prototype, {
    setup() {
        super.setup(...arguments);
        this.actionService = useService("action");
        this.store = useState(useService("mail.store"));
    },
    /**
     * 登錄並繼續：開啟完成 wizard（僅登錄工時，不完成待辦）
     */
    async onClickLogAndContinue() {
        const { res_id, res_model } = this.props.activity;
        const thread = this.store.Thread.insert({
            model: res_model,
            id: res_id,
        });

        if (this.props.close) {
            this.props.close();
        }

        await new Promise((resolve) => {
            this.actionService.doAction(
                {
                    type: "ir.actions.act_window",
                    name: "Log and Continue",
                    res_model: "mail.activity.done.wizard",
                    view_mode: "form",
                    views: [[false, "form"]],
                    target: "new",
                    context: {
                        default_activity_id: this.props.activity.id,
                    },
                },
                {
                    onClose: resolve,
                }
            );
        });

        this.props.onActivityChanged(thread);
    },

    /**
     * 延期至下週：開啟延期 wizard
     */
    async onClickPostpone() {
        const { res_id, res_model } = this.props.activity;
        const thread = this.store.Thread.insert({
            model: res_model,
            id: res_id,
        });

        if (this.props.close) {
            this.props.close();
        }

        await new Promise((resolve) => {
            this.actionService.doAction(
                {
                    type: "ir.actions.act_window",
                    name: "Postpone to Next Week",
                    res_model: "mail.activity.postpone.wizard",
                    view_mode: "form",
                    views: [[false, "form"]],
                    target: "new",
                    context: {
                        default_activity_id: this.props.activity.id,
                    },
                },
                {
                    onClose: resolve,
                }
            );
        });

        this.props.onActivityChanged(thread);
    },

    /**
     * 轉移：開啟轉移 wizard
     */
    async onClickTransfer() {
        const { res_id, res_model } = this.props.activity;
        const thread = this.store.Thread.insert({
            model: res_model,
            id: res_id,
        });

        if (this.props.close) {
            this.props.close();
        }

        await new Promise((resolve) => {
            this.actionService.doAction(
                {
                    type: "ir.actions.act_window",
                    name: "Transfer",
                    res_model: "mail.activity.transfer.wizard",
                    view_mode: "form",
                    views: [[false, "form"]],
                    target: "new",
                    context: {
                        default_activity_id: this.props.activity.id,
                    },
                },
                {
                    onClose: resolve,
                }
            );
        });

        this.props.onActivityChanged(thread);
    },

    /**
     * 變更指派：開啟重新指派 wizard
     */
    async onClickReassign() {
        const { res_id, res_model } = this.props.activity;
        const thread = this.store.Thread.insert({
            model: res_model,
            id: res_id,
        });

        if (this.props.close) {
            this.props.close();
        }

        await new Promise((resolve) => {
            this.actionService.doAction(
                {
                    type: "ir.actions.act_window",
                    name: "Reassign",
                    res_model: "mail.activity.reassign.wizard",
                    view_mode: "form",
                    views: [[false, "form"]],
                    target: "new",
                    context: {
                        default_activity_id: this.props.activity.id,
                    },
                },
                {
                    onClose: resolve,
                }
            );
        });

        this.props.onActivityChanged(thread);
    },
});
