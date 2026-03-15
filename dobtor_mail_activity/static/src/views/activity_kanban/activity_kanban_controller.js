/** @odoo-module */

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { setupActivityWeek, ActivityWeekMethods } from "../activity_week_controller_mixin";

export class ActivityKanbanController extends KanbanController {
    static template = "dobtor_mail_activity.ActivityKanbanView";

    setup() {
        super.setup();
        this.actionService = useService("action");
        setupActivityWeek(this);
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

    getWeekButtonClass(week) {
        if (week.number === this.weekState.currentWeek) {
            return 'btn btn-sm btn-primary me-1';
        }
        return 'btn btn-sm btn-outline-secondary me-1';
    }

    getWeekDateRange(week) {
        if (week.start_date && week.end_date) {
            return `${week.start_date} ~ ${week.end_date}`;
        }
        return '';
    }

    async scheduleToThisWeek() {
        await this.scheduleToWeek(0);
    }

    async scheduleToNextWeek() {
        await this.scheduleToWeek(1);
    }

    async scheduleToWeek2() {
        await this.scheduleToWeek(2);
    }

    async scheduleToWeek3() {
        await this.scheduleToWeek(3);
    }

    async onCreateActivity() {
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: _t('New Activity'),
            res_model: 'mail.activity',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: this.props.context,
        });
    }
}

Object.assign(ActivityKanbanController.prototype, ActivityWeekMethods);
