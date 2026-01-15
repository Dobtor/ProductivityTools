/** @odoo-module */

import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { ActivityFormController } from "./activity_form_controller";
import { ActivityFormControlPanel } from "./activity_form_control_panel";

/**
 * ActivityFormView - Custom form view for mail.activity
 *
 * Extends standard form view with:
 * - Custom controller with limited action menu
 * - Control panel with chatter toggle button
 */
export const activityFormView = {
    ...formView,
    Controller: ActivityFormController,
    ControlPanel: ActivityFormControlPanel,
};

registry.category("views").add("activity_form", activityFormView);
