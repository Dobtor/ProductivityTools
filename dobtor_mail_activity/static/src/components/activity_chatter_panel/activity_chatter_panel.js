/** @odoo-module */

import { Chatter } from "@mail/chatter/web_portal/chatter";

import { Component, useState, useRef } from "@odoo/owl";

import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { useBus } from "@web/core/utils/hooks";

/**
 * ActivityChatterPanel - Side panel for displaying chatter in activity form view
 *
 * Adapted from project_todo's TodoChatterPanel for mail.activity model.
 * Allows toggling chatter visibility via control panel button.
 */
export class ActivityChatterPanel extends Component {
    static template = "dobtor_mail_activity.ActivityChatterPanel";
    static components = { Chatter };
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        this.state = useState({
            displayChatter: this.env.isSmall,
        });
        this.rootRef = useRef("root");
        // Listen for toggle chatter events from control panel
        useBus(this.env.bus, "ACTIVITY:TOGGLE_CHATTER", this.toggleChatter);
    }

    /**
     * Handle chatter visibility toggle
     * @param {CustomEvent} ev - Event containing displayChatter flag
     */
    toggleChatter(ev) {
        this.state.displayChatter = ev.detail.displayChatter;
        this.rootRef.el?.parentElement?.classList.toggle(
            "d-none",
            !this.state.displayChatter
        );
    }
}

export const activityChatterPanel = {
    component: ActivityChatterPanel,
    additionalClasses: [
        "o_activity_chatter",
        "d-none",
        "position-relative",
        "p-0",
        "overflow-y-auto",
    ],
};

registry.category("view_widgets").add("activity_chatter_panel", activityChatterPanel);
