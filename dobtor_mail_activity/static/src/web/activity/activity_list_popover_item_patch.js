/** @odoo-module **/

import { ActivityListPopoverItem } from "@mail/core/web/activity_list_popover_item";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

/**
 * Patch ActivityListPopoverItem - 添加轉移按鈕
 *
 * 在 Chatter 活動列表的每個活動項目中加入「Transfer」按鈕，
 * 讓用戶可以直接將活動轉移到其他文件。
 */
patch(ActivityListPopoverItem.prototype, {
    setup() {
        super.setup(...arguments);
        this.actionService = useService("action");
        this.ormService = useService("orm");
    },

    get hasTransferButton() {
        const activity = this.props.activity;
        return activity.state !== "done" && activity.can_write;
    },

    async onClickTransfer() {
        const activity = this.props.activity;
        const action = await this.ormService.call(
            "mail.activity",
            "action_transfer_activity",
            [[activity.id]]
        );
        await this.actionService.doAction(action, {
            onClose: () => {
                this.props.onActivityChanged?.();
            },
        });
    },
});
