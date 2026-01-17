/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class ActivityListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
    }

    /**
     * 批次延期選中的待辦
     */
    async onBatchPostpone() {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            this.notification.add(_t("請先選擇要延期的待辦"), {
                type: "warning",
            });
            return;
        }

        const activityIds = selectedRecords.map(r => r.resId);

        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: _t('批次延期'),
            res_model: 'mail.activity.postpone.wizard',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: {
                default_activity_ids: activityIds,
                active_ids: activityIds,
            },
        });
    }

    /**
     * 批次完成選中的待辦
     */
    async onBatchDone() {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            this.notification.add(_t("請先選擇要完成的待辦"), {
                type: "warning",
            });
            return;
        }

        const activityIds = selectedRecords.map(r => r.resId);

        await this.orm.call(
            'mail.activity',
            'action_done',
            [activityIds],
            { context: { mail_activity_quick_update: true } }
        );

        this.notification.add(_t("已完成 %s 個待辦", activityIds.length), {
            type: "success",
        });

        await this.model.root.load();
    }

    /**
     * 週次快速切換
     */
    async scheduleToWeek(weekNumber) {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            this.notification.add(_t("請先選擇要排程的待辦"), {
                type: "warning",
            });
            return;
        }

        const activityIds = selectedRecords.map(r => r.resId);
        await this.orm.call(
            'mail.activity',
            'action_schedule_to_week',
            [activityIds, weekNumber]
        );

        await this.model.root.load();
    }
}
