/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { FormController } from "@web/views/form/form_controller";
import { openActivityWizard, ACTIVITY_WIZARDS } from "@dobtor_mail_activity/utils/activity_actions";

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
        if (activityData.activity_status === "active") {
            filteredActions.push({
                description: _t("Postpone"),
                callback: async () => {
                    await openActivityWizard(
                        this.actionService,
                        ACTIVITY_WIZARDS.postpone,
                        { default_activity_id: this.model.root.resId }
                    );
                },
            });

            filteredActions.push({
                description: _t("Transfer"),
                callback: async () => {
                    await openActivityWizard(
                        this.actionService,
                        ACTIVITY_WIZARDS.transfer,
                        { default_activity_id: this.model.root.resId }
                    );
                },
            });

            // 改排週次（保持原星期幾搬到目標週）。
            // 清單/看板是透過 binding 的 ir.actions.server 進入 ⚙️ 選單，但本表單
            // 覆寫了 actionMenuItems 只留 duplicate/delete，binding 進不來，
            // 故沿用本檔既有的「自行 push」模式補上，兩邊行為一致。
            // 與「延期」不同：延期會清空計畫日期並要求填原因，這裡只換週。
            for (const [description, method] of [
                [_t("Move to Previous Week"), "action_schedule_to_week_prev"],
                [_t("Move to This Week"), "action_schedule_to_week0"],
                [_t("Move to Next Week"), "action_schedule_to_week1"],
            ]) {
                filteredActions.push({
                    description,
                    callback: async () => {
                        // 先存檔：方法會寫 planned_date/schedule_status，
                        // 未存的髒值會在後續 reload 時遺失
                        await this.model.root.save();
                        const action = await this.orm.call(
                            "mail.activity",
                            method,
                            [[this.model.root.resId]]
                        );
                        await this.actionService.doAction(action);
                    },
                });
            }
        }

        menuItems.action = filteredActions;
        menuItems.print = []; // Remove print menu
        return menuItems;
    }
}
