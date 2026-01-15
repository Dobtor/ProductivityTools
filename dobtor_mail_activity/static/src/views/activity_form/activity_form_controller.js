/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { FormController } from "@web/views/form/form_controller";

/**
 * ActivityFormController - Form controller for mail.activity
 *
 * Limits the action menu to specific actions relevant for activities:
 * - duplicate: Create a copy of the activity
 * - delete: Remove the activity
 */
export class ActivityFormController extends FormController {
    /**
     * Override action menu items to limit available actions
     * @returns {Object} Filtered action menu items
     */
    get actionMenuItems() {
        const actionToKeep = ["duplicate", "delete"];
        const menuItems = super.actionMenuItems;

        // Filter actions to only keep relevant ones
        const filteredActions =
            menuItems.action?.filter((action) =>
                actionToKeep.includes(action.key)
            ) || [];

        // Add custom actions if needed
        const activityData = this.model.root.data;

        // Add postpone action if activity is active
        if (activityData.activity_state === "active") {
            filteredActions.push({
                description: _t("延期"),
                callback: async () => {
                    await this.model.action.doAction({
                        type: "ir.actions.act_window",
                        name: _t("延期活動"),
                        res_model: "mail.activity.postpone.wizard",
                        view_mode: "form",
                        views: [[false, "form"]],
                        target: "new",
                        context: {
                            default_activity_ids: [this.model.root.resId],
                        },
                    });
                },
            });

            filteredActions.push({
                description: _t("轉移"),
                callback: async () => {
                    await this.model.action.doAction({
                        type: "ir.actions.act_window",
                        name: _t("轉移活動"),
                        res_model: "mail.activity.transfer.wizard",
                        view_mode: "form",
                        views: [[false, "form"]],
                        target: "new",
                        context: {
                            default_activity_id: this.model.root.resId,
                        },
                    });
                },
            });
        }

        menuItems.action = filteredActions;
        menuItems.print = []; // Remove print menu
        return menuItems;
    }
}
