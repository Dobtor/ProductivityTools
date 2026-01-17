/** @odoo-module */

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class ActivityKanbanController extends KanbanController {
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

        // 開啟批次延期 wizard
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

        // 快速完成（不開啟 wizard）
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
     * @param {number} weekNumber - 目標週次 (-1=上週, 0=本週, 1=下週, ...)
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

        const weekNames = {
            '-1': _t('上週'),
            '0': _t('本週'),
            '1': _t('下週'),
            '2': _t('第三週'),
            '3': _t('第四週'),
        };
        const weekName = weekNames[String(weekNumber)] || _t('指定週次');

        this.notification.add(_t("已將 %s 個待辦排程至%s", activityIds.length, weekName), {
            type: "success",
        });

        await this.model.root.load();
    }

    /**
     * 排程至本週
     */
    async scheduleToThisWeek() {
        await this.scheduleToWeek(0);
    }

    /**
     * 排程至下週
     */
    async scheduleToNextWeek() {
        await this.scheduleToWeek(1);
    }

    /**
     * 排程至第三週
     */
    async scheduleToWeek2() {
        await this.scheduleToWeek(2);
    }

    /**
     * 排程至第四週
     */
    async scheduleToWeek3() {
        await this.scheduleToWeek(3);
    }

    /**
     * 開啟新增待辦表單
     */
    async onCreateActivity() {
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: _t('新增待辦'),
            res_model: 'mail.activity',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: this.props.context,
        });
    }
}
