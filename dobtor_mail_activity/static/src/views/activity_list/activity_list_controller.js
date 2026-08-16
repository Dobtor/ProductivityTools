/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { setupActivityWeek, applyActivityWeekMethods } from "../activity_week_controller_mixin";
import { openActivityWizard, ACTIVITY_WIZARDS } from "@dobtor_mail_activity/utils/activity_actions";

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
}

applyActivityWeekMethods(ActivityListController);
