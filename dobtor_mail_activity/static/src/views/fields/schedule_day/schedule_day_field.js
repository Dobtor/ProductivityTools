/** @odoo-module */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { SelectionField, selectionField } from "@web/views/fields/selection/selection_field";

const DAY_LABELS = {
    monday: _t("Monday"),
    tuesday: _t("Tuesday"),
    wednesday: _t("Wednesday"),
    thursday: _t("Thursday"),
    friday: _t("Friday"),
    saturday: _t("Saturday"),
    sunday: _t("Sunday"),
};

export class ScheduleDayField extends SelectionField {
    static template = "dobtor_mail_activity.ScheduleDayField";

    get string() {
        const scheduleStatus = this.props.record.data[this.props.name];

        // If waiting or false, show standard label
        if (scheduleStatus === "waiting" || scheduleStatus === false) {
            return super.string;
        }

        // If it's a day value and planned_date exists, show "DayLabel mm/dd"
        const plannedDate = this.props.record.data.planned_date;
        if (plannedDate && DAY_LABELS[scheduleStatus]) {
            // planned_date is a luxon DateTime object from Odoo's Date field
            const dayLabel = DAY_LABELS[scheduleStatus].toString();
            const dateStr = plannedDate.toFormat("MM/dd");
            return `${dayLabel} ${dateStr}`;
        }

        // Fallback to standard label
        return super.string;
    }

    get badgeClass() {
        const scheduleStatus = this.props.record.data[this.props.name];
        if (scheduleStatus === "waiting" || scheduleStatus === false) {
            return "text-bg-secondary";
        }
        return "text-bg-info";
    }
}

export const scheduleDayField = {
    ...selectionField,
    component: ScheduleDayField,
    displayName: _t("Schedule Day"),
};

registry.category("fields").add("schedule_day", scheduleDayField);
