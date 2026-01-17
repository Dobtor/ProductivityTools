/** @odoo-module */

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class WeekSelector extends Component {
    static template = "dobtor_mail_activity.WeekSelector";
    static props = {
        onWeekSelect: { type: Function, optional: true },
        currentWeek: { type: Number, optional: true },
        showStats: { type: Boolean, optional: true },
    };
    static defaultProps = {
        currentWeek: 0,
        showStats: true,
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            weeks: [],
            selectedWeek: this.props.currentWeek,
            isLoading: true,
        });

        onWillStart(async () => {
            await this.loadWeekInfo();
        });
    }

    /**
     * 載入週次資訊
     */
    async loadWeekInfo() {
        this.state.isLoading = true;
        try {
            const weeks = await this.orm.call(
                'mail.activity',
                'get_week_info',
                []
            );
            this.state.weeks = weeks;
        } catch (e) {
            console.error('Failed to load week info:', e);
            this.state.weeks = [];
        }
        this.state.isLoading = false;
    }

    /**
     * 選擇週次
     */
    selectWeek(weekNumber) {
        this.state.selectedWeek = weekNumber;
        if (this.props.onWeekSelect) {
            this.props.onWeekSelect(weekNumber);
        }
    }

    /**
     * 取得週次項目的 CSS class
     */
    getWeekClass(week) {
        const classes = ['o_week_item', 'p-2', 'rounded', 'cursor-pointer', 'text-center'];

        if (week.number === this.state.selectedWeek) {
            classes.push('bg-primary', 'text-white', 'shadow-sm');
        } else {
            classes.push('bg-light', 'border');
        }

        // 本週加粗
        if (week.number === 0) {
            classes.push('fw-bold');
        }

        // 上週淡化
        if (week.number < 0) {
            classes.push('opacity-75');
        }

        return classes.join(' ');
    }

    /**
     * 取得週次徽章的 CSS class
     */
    getBadgeClass(week) {
        if (week.count === 0) {
            return 'bg-secondary';
        } else if (week.count <= 3) {
            return 'bg-success';
        } else if (week.count <= 7) {
            return 'bg-warning text-dark';
        } else {
            return 'bg-danger';
        }
    }

    /**
     * 開啟指定週次的待辦列表
     */
    async openWeekActivities(weekNumber) {
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: _t('週待辦'),
            res_model: 'mail.activity',
            view_mode: 'kanban,list,form',
            domain: [
                ['active', '=', true],
                ['schedule_week_number', '=', weekNumber],
            ],
            context: {
                search_default_my_activities: 1,
            },
        });
    }
}
