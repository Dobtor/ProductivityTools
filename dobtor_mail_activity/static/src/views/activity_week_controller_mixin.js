/** @odoo-module */

import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { useState, onWillStart, useSubEnv } from "@odoo/owl";
import { openActivityWizard, ACTIVITY_WIZARDS } from "@dobtor_mail_activity/utils/activity_actions";

/**
 * 在 controller.setup() 中呼叫，接上週次選擇器與批次操作。
 *
 * 週次的狀態與 domain/context 注入都住在 ActivityWeekSearchModel（見同層
 * activity_week_search_model.js）；Controller 只負責畫那條選單並轉呼叫。
 *
 * @param {Object} controller - controller instance (this)
 */
export function setupActivityWeek(controller) {
    controller.orm = useService("orm");
    controller.notification = useService("notification");

    // 週次狀態的擁有者是 ActivityWeekSearchModel（reactive）；在這裡 useState()
    // 訂閱，讓它的變動只重繪本 controller（而非 WithSearch → 多餘的 model.load）。
    controller.weekState = useState(controller.env.searchModel.weekState);

    controller.userHoursState = useState({ dailyTarget: 8, dailyMax: 9 });
    useSubEnv({
        // kanban 欄位標題用；來源是 searchModel，切週次時由它更新
        activityWeekDates: useState(controller.env.searchModel.weekDatesState),
        activityUserHours: controller.userHoursState,
    });

    controller.onWeekSelectChange = controller.onWeekSelectChange.bind(controller);

    onWillStart(() => controller._loadUserHours());
}

/**
 * 週次／批次操作的共用方法掛到 controller prototype。
 *
 * 用 Object.defineProperties（複製 property descriptor）而非 Object.assign，
 * 這樣日後在 ActivityWeekMethods 加 getter 也不會被求值成靜態值。
 */
export function applyActivityWeekMethods(ControllerClass) {
    Object.defineProperties(
        ControllerClass.prototype,
        Object.getOwnPropertyDescriptors(ActivityWeekMethods)
    );
}

export const ActivityWeekMethods = {
    async _loadUserHours() {
        try {
            const result = await this.orm.read(
                'res.users',
                [user.userId],
                ['weekly_committed_hours'],
            );
            if (result.length) {
                const weekly = result[0].weekly_committed_hours || 40;
                const daily = weekly / 5;
                this.userHoursState.dailyTarget = daily;
                this.userHoursState.dailyMax = daily * 1.125;
            }
        } catch (e) {
            // Fallback to defaults (8/9)
        }
    },

    async onWeekSelectChange(ev) {
        const raw = ev.target.value;
        const weekNumber = raw === 'all' ? 'all' : parseInt(raw, 10);
        await this.env.searchModel.selectWeek(weekNumber);
    },

    async onBatchPostpone() {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            this.notification.add(_t("Please select activities to postpone first"), {
                type: "warning",
            });
            return;
        }

        const activityIds = selectedRecords.map(r => r.resId);

        await openActivityWizard(
            this.actionService,
            ACTIVITY_WIZARDS.postpone,
            { default_activity_ids: activityIds, active_ids: activityIds },
            { name: _t('Batch Postpone') }
        );
    },

    /** 合併：多選 → 指定主待辦 → 其餘併入並封存。 */
    async onBatchMerge() {
        const selectedRecords = this.model.root.selection;
        if (selectedRecords.length < 2) {
            this.notification.add(_t("Select at least two activities to merge"), {
                type: "warning",
            });
            return;
        }

        const activityIds = selectedRecords.map(r => r.resId);

        await openActivityWizard(
            this.actionService,
            ACTIVITY_WIZARDS.merge,
            {
                default_activity_ids: activityIds,
                active_model: 'mail.activity',
                active_ids: activityIds,
            }
        );
    },

    async onBatchDone() {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            this.notification.add(_t("Please select activities to complete first"), {
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

        this.notification.add(_t("Completed %s activities", activityIds.length), {
            type: "success",
        });

        await this.model.root.load();
    },
};
