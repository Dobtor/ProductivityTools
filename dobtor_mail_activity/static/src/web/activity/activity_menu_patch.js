/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ActivityMenu } from "@mail/core/web/activity_menu";
import { useCommand } from "@web/core/commands/command_hook";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { openActivityWizard, ACTIVITY_WIZARDS } from "@dobtor_mail_activity/utils/activity_actions";

// Register activity command category for command palette
registry.category("command_categories").add("dobtor-activity", {}, { sequence: 105 });

/**
 * Patch ActivityMenu to add quick actions for activities
 *
 * Features:
 * - Alt+Shift+A: Quick create new activity
 * （Alt+Shift+N 新增筆記在 dobtor_meeting_minutes）
 */
patch(ActivityMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.actionService = useService("action");

        // Global hotkey Alt+Shift+A: Add new activity
        useCommand(
            _t("New Activity"),
            () => {
                document.body.click(); // Close command palette
                this.createActivity();
            },
            {
                category: "dobtor-activity",
                hotkey: "alt+shift+a",
                global: true,
            }
        );
    },

    /**
     * Create a new activity via quick action
     */
    async createActivity() {
        // 統一走「建立待辦」wizard（無目標文件 → 顯示 target 輸入）
        await openActivityWizard(this.actionService, ACTIVITY_WIZARDS.create, {
            default_activity_user_id: user.userId,
        });
    },
});
