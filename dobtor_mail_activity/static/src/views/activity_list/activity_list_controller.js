/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { setupActivityWeek, ActivityWeekMethods } from "../activity_week_controller_mixin";

export class ActivityListController extends ListController {
    static template = "dobtor_mail_activity.ActivityListView";

    setup() {
        super.setup();
        this.actionService = useService("action");
        setupActivityWeek(this);
    }

    /**
     * 更新 model context（List 版：遍歷 flat records）
     */
    _updateModelContext(weekNumber) {
        const currentWeekInfo = this.weekState.weeks.find(w => w.number === weekNumber);
        const dates = currentWeekInfo ? currentWeekInfo.dates : {};

        this.weekDatesState.dates = dates;

        if (this.model.root.config) {
            this.model.root.config.context = {
                ...this.model.root.config.context,
                schedule_current_week: weekNumber,
                schedule_week_dates: dates,
            };
        }

        const records = this.model.root.records || [];
        for (const record of records) {
            if (record.config && record.config.context) {
                record.config.context = {
                    ...record.config.context,
                    schedule_current_week: weekNumber,
                    schedule_week_dates: dates,
                };
            }
        }
    }
}

Object.assign(ActivityListController.prototype, ActivityWeekMethods);
