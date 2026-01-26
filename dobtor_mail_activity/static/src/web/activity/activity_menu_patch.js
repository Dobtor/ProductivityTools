/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ActivityMenu } from "@mail/core/web/activity_menu";
import { useCommand } from "@web/core/commands/command_hook";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";

// Register activity command category for command palette
registry.category("command_categories").add("dobtor-activity", {}, { sequence: 105 });

/**
 * Patch ActivityMenu to add quick actions for activities
 *
 * Features:
 * - Alt+Shift+A: Quick create new activity
 * - Alt+Shift+N: Quick create new note
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

        // Global hotkey Alt+Shift+N: Add new note
        useCommand(
            _t("New Note"),
            () => {
                document.body.click(); // Close command palette
                this.createNote();
            },
            {
                category: "dobtor-activity",
                hotkey: "alt+shift+n",
                global: true,
            }
        );
    },

    /**
     * Create a new activity via quick action
     */
    async createActivity() {
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: _t("New Activity"),
            res_model: "mail.activity",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_user_id: this.store.self?.userId,
                // Use module's custom form view if available
                form_view_ref: "dobtor_mail_activity.mail_activity_view_form_quick",
            },
        });
    },

    /**
     * Create a new note via quick action
     */
    async createNote() {
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: _t("New Note"),
            res_model: "note.note",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        });
    },
});
