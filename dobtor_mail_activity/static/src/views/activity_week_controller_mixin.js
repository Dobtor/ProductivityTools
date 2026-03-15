/** @odoo-module */

import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { useState, onWillStart, onMounted, useSubEnv } from "@odoo/owl";

/**
 * 在 controller.setup() 中呼叫，設定週次相關的狀態和生命週期。
 *
 * @param {Object} controller - controller instance (this)
 */
export function setupActivityWeek(controller) {
    controller.orm = useService("orm");
    controller.notification = useService("notification");

    controller.weekState = useState({
        weeks: [],
        currentWeek: 0,
        isLoading: true,
    });

    controller.weekDatesState = useState({ dates: {} });
    controller.userHoursState = useState({ dailyTarget: 8, dailyMax: 9 });
    useSubEnv({
        activityWeekDates: controller.weekDatesState,
        activityUserHours: controller.userHoursState,
    });

    controller._baseDomain = null;
    controller.onWeekSelectChange = controller.onWeekSelectChange.bind(controller);

    onWillStart(async () => {
        await Promise.all([
            controller._loadWeekInfo(),
            controller._loadUserHours(),
        ]);
    });

    onMounted(async () => {
        const weekNumber = controller.weekState.currentWeek;
        // Set base domain (strip any existing week conditions)
        controller._baseDomain = controller._filterWeekDomain(controller.props.domain || []);
        // Build week-filtered domain and apply
        const weekDomain = controller._buildWeekDomain(weekNumber);
        controller._updateModelContext(weekNumber);
        await controller.model.root.load({ domain: weekDomain });
        controller.model.notify();
        controller._updateModelContext(weekNumber);
    });
}

/**
 * 週次管理共用方法。使用 Object.assign 加到 controller prototype。
 *
 * 注意：_updateModelContext 未包含在內，因為 Kanban（遍歷 groups）
 * 和 List（遍歷 flat records）的實作不同，需由各 controller 自行定義。
 */
export const ActivityWeekMethods = {
    async _loadWeekInfo() {
        this.weekState.isLoading = true;
        try {
            const weeks = await this.orm.call(
                'mail.activity',
                'get_week_info',
                []
            );
            this.weekState.weeks = weeks;
        } catch (e) {
            console.error('Failed to load week info:', e);
            this.weekState.weeks = [
                { number: -1, name: _t('Last Week'), display_name: _t('Last Week'), key: 'week_prev', count: 0, total_hours: 0, dates: {} },
                { number: 0, name: _t('This Week'), display_name: _t('This Week'), key: 'week0', count: 0, total_hours: 0, dates: {} },
                { number: 1, name: _t('Next Week'), display_name: _t('Next Week'), key: 'week1', count: 0, total_hours: 0, dates: {} },
                { number: 2, name: _t('Week 3'), display_name: _t('Week 3'), key: 'week2', count: 0, total_hours: 0, dates: {} },
                { number: 3, name: _t('Week 4'), display_name: _t('Week 4'), key: 'week3', count: 0, total_hours: 0, dates: {} },
            ];
        }
        this.weekState.isLoading = false;
    },

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

    async selectWeek(weekNumber) {
        if (this.weekState.currentWeek === weekNumber) {
            return;
        }

        this.weekState.currentWeek = weekNumber;

        if (this._baseDomain === null) {
            this._baseDomain = this._filterWeekDomain(this.props.domain || []);
        }

        const weekDomain = this._buildWeekDomain(weekNumber);

        this._updateModelContext(weekNumber);

        await this.model.root.load({ domain: weekDomain });
        this.model.notify();

        this._updateModelContext(weekNumber);

        await this._loadWeekInfo();
    },

    _filterWeekDomain(domain) {
        if (!domain || !domain.length) return [];

        const filtered = [];
        let skipNext = false;

        for (let i = 0; i < domain.length; i++) {
            const item = domain[i];

            if (skipNext) {
                skipNext = false;
                continue;
            }

            if (Array.isArray(item) && item.length === 3) {
                if (item[0] === 'schedule_week_number' || item[0] === 'schedule_status') {
                    if (filtered.length > 0 && filtered[filtered.length - 1] === '|') {
                        filtered.pop();
                    }
                    continue;
                }
            }

            if (item === '|' && i + 2 < domain.length) {
                const next1 = domain[i + 1];
                const next2 = domain[i + 2];
                if (Array.isArray(next1) && Array.isArray(next2)) {
                    if ((next1[0] === 'schedule_status' || next1[0] === 'schedule_week_number') &&
                        (next2[0] === 'schedule_status' || next2[0] === 'schedule_week_number')) {
                        skipNext = true;
                        i++;
                        continue;
                    }
                }
            }

            filtered.push(item);
        }

        return filtered;
    },

    _buildWeekDomain(weekNumber) {
        const weekFilter = [
            '|',
            ['schedule_status', '=', 'waiting'],
            ['schedule_week_number', '=', weekNumber]
        ];

        const baseDomain = this._baseDomain || this._filterWeekDomain(this.props.domain || []);
        if (baseDomain && baseDomain.length) {
            return [...baseDomain, ...weekFilter];
        }
        return weekFilter;
    },

    formatHours(hours) {
        if (!hours) return '';
        return hours.toFixed(1) + _t(' hours');
    },

    async onWeekSelectChange(ev) {
        const weekNumber = parseInt(ev.target.value, 10);
        await this.selectWeek(weekNumber);
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

        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: _t('Batch Postpone'),
            res_model: 'mail.activity.postpone.wizard',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: {
                default_activity_ids: activityIds,
                active_ids: activityIds,
            },
        });
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

    async scheduleToWeek(weekNumber) {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            this.notification.add(_t("Please select activities to schedule first"), {
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
    },
};
