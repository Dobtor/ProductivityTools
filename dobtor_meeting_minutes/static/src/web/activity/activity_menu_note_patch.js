/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ActivityMenu } from "@mail/core/web/activity_menu";
import { useCommand } from "@web/core/commands/command_hook";
import { patch } from "@web/core/utils/patch";

/**
 * 系統匣：Alt+Shift+N 快速新增筆記（命令分類 dobtor-activity 由 dobtor_mail_activity 註冊）。
 */
patch(ActivityMenu.prototype, {
    setup() {
        super.setup(...arguments);
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

    async createNote() {
        await this.env.services.action.doAction({
            type: "ir.actions.act_window",
            name: _t("New Note"),
            res_model: "note.note",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        });
    },
});
