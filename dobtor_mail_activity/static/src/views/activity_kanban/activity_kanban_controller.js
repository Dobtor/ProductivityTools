/** @odoo-module */

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { setupActivityWeek, applyActivityWeekMethods } from "../activity_week_controller_mixin";
import { ActivityScheduleFormDialog } from "./activity_kanban_schedule_dialog";
import { openActivityWizard, ACTIVITY_WIZARDS } from "@dobtor_mail_activity/utils/activity_actions";

export class ActivityKanbanController extends KanbanController {
    static template = "dobtor_mail_activity.ActivityKanbanView";

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.dialogService = useService("dialog");
        setupActivityWeek(this);
    }

    /**
     * 左上角「New」改開統一建立待辦 wizard（取代 inline 建立）。
     * props.context 來自 searchModel，已含 schedule_current_week / schedule_week_dates。
     */
    createRecord() {
        return openActivityWizard(
            this.actionService,
            ACTIVITY_WIZARDS.create,
            this.props.context || {},
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
     * 已移至 ActivityKanbanHeader，保留作備用
     */
    _updateColumnHeaders() {}
}

applyActivityWeekMethods(ActivityKanbanController);
