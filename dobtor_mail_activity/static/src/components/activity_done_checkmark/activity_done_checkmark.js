/** @odoo-module */

import { useState, onRendered, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import {
    StateSelectionField,
    stateSelectionField,
} from "@web/views/fields/state_selection/state_selection_field";

/**
 * ActivityDoneCheckmark - Widget for toggling activity done state
 *
 * Adapted from project_todo's TodoDoneCheckmark for mail.activity model.
 * Handles activity_state field with values: 'active', 'done', 'cancelled'
 */
export class ActivityDoneCheckmark extends StateSelectionField {
    static template = "dobtor_mail_activity.ActivityDoneCheckmark";
    static props = {
        ...stateSelectionField.component.props,
        viewType: { type: String },
    };

    setup() {
        super.setup();
        // State for managing done checkmark appearance
        this.stateDone = useState({
            isDone: false, // Determines checkmark appearance, updated on mouse leave
            notReloadState: false, // Prevents checkmark change during form re-render
        });

        onMounted(() => {
            // For mail.activity, activity_state can be: 'active', 'done', 'cancelled'
            const fieldValue = this.props.record.data[this.props.name];
            // Store the previous non-done state for toggle back
            this.notDoneState = fieldValue === "done" ? "active" : fieldValue;
        });

        onRendered(() => {
            if (!this.stateDone.notReloadState) {
                this.stateDone.isDone =
                    this.props.record.data[this.props.name] === "done";
            }
        });
    }

    /**
     * Update done state appearance when mouse leaves
     * @private
     * @param {MouseEvent} ev
     */
    actualizeDoneState(ev) {
        this.stateDone.notReloadState = false;
    }

    /**
     * Freeze done state appearance when mouse enters
     * @private
     * @param {MouseEvent} ev
     */
    freezeDoneState(ev) {
        this.stateDone.notReloadState = true;
    }

    /**
     * Toggle the activity done state
     * @private
     * @param {MouseEvent} ev
     */
    async onDoneToggled(ev) {
        const currentValue = this.props.record.data[this.props.name];
        const newValue =
            currentValue !== "done" ? "done" : this.notDoneState;

        if (["kanban", "list"].includes(this.props.viewType)) {
            // For kanban/list views, use parent's updateRecord for proper refresh
            await super.updateRecord(newValue);
        } else {
            // For form view, update the record directly
            await this.props.record.update({
                [this.props.name]: newValue,
            });
        }
    }
}

export const activityDoneCheckmark = {
    ...stateSelectionField,
    component: ActivityDoneCheckmark,
    extractProps: (fieldInfo, dynamicInfo) => {
        const props = stateSelectionField.extractProps(fieldInfo, dynamicInfo);
        props.viewType = fieldInfo.viewType;
        return props;
    },
};

registry.category("fields").add("activity_done_checkmark", activityDoneCheckmark);
