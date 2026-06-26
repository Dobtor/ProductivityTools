/** @odoo-module */

import { registry } from "@web/core/registry";
import { calendarView } from "@web/views/calendar/calendar_view";
import { CalendarController } from "@web/views/calendar/calendar_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * 活動行事曆 Controller：將「New」/ 點空白時段的建立改走統一建立待辦 wizard
 * (mail.activity.create.wizard)，與其他視圖一致。
 */
export class ActivityCalendarController extends CalendarController {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    createRecord() {
        return this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Create To-do"),
                res_model: "mail.activity.create.wizard",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: this.props.context || {},
            },
            { onClose: () => this.model.load() }
        );
    }
}

export const activityCalendarView = {
    ...calendarView,
    Controller: ActivityCalendarController,
};

registry.category("views").add("activity_calendar", activityCalendarView);
