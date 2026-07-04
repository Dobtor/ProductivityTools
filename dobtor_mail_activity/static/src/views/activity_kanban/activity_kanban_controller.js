/** @odoo-module */

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { setupActivityWeek, ActivityWeekMethods } from "../activity_week_controller_mixin";
import { ActivityScheduleFormDialog } from "./activity_kanban_schedule_dialog";

export class ActivityKanbanController extends KanbanController {
    static template = "dobtor_mail_activity.ActivityKanbanView";

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.dialogService = useService("dialog");
        setupActivityWeek(this);
    }

    /** 左上角「New」改開統一建立待辦 wizard（取代 inline 建立）。 */
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
     * 點卡片改開 schedule 表單彈窗（取代整頁導航）。
     * 彈窗自帶官方展開鈕，已覆寫為導向當前 kanban action 的全畫面。
     */
    openRecord(record) {
        const formView = (this.env.config.views || []).find((v) => v[1] === "form");
        this.dialogService.add(ActivityScheduleFormDialog, {
            resModel: this.props.resModel,
            resId: record.resId,
            viewId: formView ? formView[0] : false,
            context: this.props.context,
            expandActionId: this.env.config.actionId,
            onRecordSaved: () => this.model.root.load(),
        });
    }

    /**
     * 更新 model context（Kanban 版：遍歷 groups → list.records）
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

        for (const group of this.model.root.groups || []) {
            if (group.config && group.config.context) {
                group.config.context = {
                    ...group.config.context,
                    schedule_current_week: weekNumber,
                    schedule_week_dates: dates,
                };
            }
            if (group.list && group.list.records) {
                for (const record of group.list.records) {
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
    }

    /**
     * 已移至 ActivityKanbanHeader，保留作備用
     */
    _updateColumnHeaders() {}
}

Object.assign(ActivityKanbanController.prototype, ActivityWeekMethods);
