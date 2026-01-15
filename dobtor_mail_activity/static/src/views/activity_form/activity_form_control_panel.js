/** @odoo-module */

import { onMounted, useEffect } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { ControlPanel } from "@web/search/control_panel/control_panel";

/**
 * ActivityFormControlPanel - Control panel with chatter toggle for activity form
 *
 * Adapted from project_todo's TodoFormControlPanel.
 * Features:
 * - Toggle button to show/hide chatter panel
 * - Persists chatter state in localStorage
 * - Auto-shows chatter when coming from activity view
 */
export class ActivityFormControlPanel extends ControlPanel {
    static template = "dobtor_mail_activity.ActivityFormControlPanel";

    setup() {
        super.setup();

        // React to screen size changes
        useEffect(
            (isSmall) => {
                if (isSmall && !this.state.displayChatter) {
                    this.toggleChatter();
                }
            },
            () => [this.env.isSmall]
        );

        onMounted(() => {
            // Check if coming from activity view and toggle chatter accordingly
            const isFromActivityView =
                router.current.actionStack?.[
                    router.current.actionStack?.length - 1
                ]?.view_type === "activity";

            if (
                !this.env.isSmall &&
                !this.state.displayChatter &&
                (isFromActivityView ||
                    JSON.parse(
                        browser.localStorage.getItem("isActivityChatterOpened")
                    ))
            ) {
                this.toggleChatter();
            }
        });
    }

    /**
     * Toggle chatter visibility and persist state
     * @param {MouseEvent} ev - Click event (optional)
     */
    toggleChatter(ev) {
        this.state.displayChatter = !this.state.displayChatter;
        if (ev) {
            // Only persist when user explicitly toggles
            browser.localStorage.setItem(
                "isActivityChatterOpened",
                this.state.displayChatter
            );
        }
        // Notify chatter panel of visibility change
        this.env.bus.trigger("ACTIVITY:TOGGLE_CHATTER", {
            displayChatter: this.state.displayChatter,
        });
    }
}
