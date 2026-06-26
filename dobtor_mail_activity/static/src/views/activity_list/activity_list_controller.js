/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { setupActivityWeek, ActivityWeekMethods } from "../activity_week_controller_mixin";

export class ActivityListController extends ListController {
    static template = "dobtor_mail_activity.ActivityListView";

    setup() {
        super.setup();
        this.actionService = useService("action");
        setupActivityWeek(this);
    }

    /**
     * 活動清單的「New」改走統一建立待辦 wizard（取代 inline 建立）。
     * 沿用視圖 context（無目標文件 → wizard 顯示 target 輸入）。
     */
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
            { onClose: () => this.model.root.load() }
        );
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
