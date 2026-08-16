/** @odoo-module */

import { registry } from "@web/core/registry";
import { calendarView } from "@web/views/calendar/calendar_view";
import { CalendarController } from "@web/views/calendar/calendar_controller";
import { CalendarModel } from "@web/views/calendar/calendar_model";
import { useService } from "@web/core/utils/hooks";
import { openActivityWizard, ACTIVITY_WIZARDS } from "@dobtor_mail_activity/utils/activity_actions";

/**
 * 唯讀展示模型：停用事件拖曳/縮放（改期一律走排程 form / 拖曳卡 / 延期，
 * 避免在行事曆上跨週移動或改動 date_deadline 形成後門）。
 * popover 的「Edit」按鈕不受影響，仍可開排程表單。
 */
export class ActivityCalendarModel extends CalendarModel {
    get canEdit() {
        return false;
    }
}

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
        return openActivityWizard(
            this.actionService,
            ACTIVITY_WIZARDS.create,
            this.props.context || {},
            { onClose: () => this.model.load() }
        );
    }
}

export const activityCalendarView = {
    ...calendarView,
    Controller: ActivityCalendarController,
    Model: ActivityCalendarModel,
};

registry.category("views").add("activity_calendar", activityCalendarView);
