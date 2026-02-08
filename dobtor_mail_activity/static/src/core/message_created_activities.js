/** @odoo-module **/

import { Message } from "@mail/core/common/message";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { useState, onMounted } from "@odoo/owl";

/**
 * 擴展 Message 組件，在訊息標題後顯示已建立的待辦事項
 */
patch(Message.prototype, {
    setup() {
        super.setup();

        this.orm = useService("orm");
        this.actionService = useService("action");

        // 儲存已建立的待辦
        this.createdActivitiesState = useState({
            activities: [],
            loaded: false,
            loading: false,
        });

        onMounted(() => {
            this.loadCreatedActivities();
        });
    },

    /**
     * 載入此訊息建立的待辦事項
     */
    async loadCreatedActivities() {
        const message = this.props.message;
        if (!message || !message.id || this.createdActivitiesState.loading) {
            return;
        }

        this.createdActivitiesState.loading = true;

        try {
            const activities = await this.orm.call(
                "mail.message",
                "get_created_activities",
                [[message.id], true]  // include_archived = true
            );
            this.createdActivitiesState.activities = activities || [];
            this.createdActivitiesState.loaded = true;
        } catch (e) {
            console.warn("Failed to load created activities:", e);
            this.createdActivitiesState.activities = [];
            this.createdActivitiesState.loaded = true;
        } finally {
            this.createdActivitiesState.loading = false;
        }
    },

    /**
     * 點擊待辦事項時開啟
     */
    async onClickCreatedActivity(activity) {
        try {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "mail.activity",
                res_id: activity.id,
                views: [[false, "form"]],
                target: "current",
                context: { active_test: false },
            });
        } catch (e) {
            console.error("Failed to open activity:", e);
        }
    },

    /**
     * 轉移待辦事項至其他文件
     */
    async onTransferCreatedActivity(ev, activity) {
        ev.stopPropagation();
        try {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                name: "Transfer Activity",
                res_model: "mail.activity.transfer.wizard",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_activity_id: activity.id,
                    default_source_model: activity.res_model,
                    default_source_id: activity.res_id,
                },
            });
        } catch (e) {
            console.error("Failed to open transfer wizard:", e);
        }
    },

    /**
     * 重新載入待辦（建立新待辦後調用）
     */
    async reloadCreatedActivities() {
        this.createdActivitiesState.loaded = false;
        this.createdActivitiesState.activities = [];
        await this.loadCreatedActivities();
    },
});
