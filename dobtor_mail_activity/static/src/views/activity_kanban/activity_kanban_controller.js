/** @odoo-module */

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { useState, onWillStart, onMounted, useSubEnv } from "@odoo/owl";

export class ActivityKanbanController extends KanbanController {
    static template = "dobtor_mail_activity.ActivityKanbanView";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        // 週次選擇器狀態
        this.weekState = useState({
            weeks: [],
            currentWeek: 0,
            isLoading: true,
        });

        // 週次日期狀態（透過 subEnv 傳遞給子元件，如 ActivityKanbanHeader）
        this.weekDatesState = useState({ dates: {} });
        useSubEnv({ activityWeekDates: this.weekDatesState });

        // 基礎 domain（排除週次篩選）
        this._baseDomain = null;

        // 綁定方法
        this.onWeekSelectChange = this.onWeekSelectChange.bind(this);

        onWillStart(async () => {
            await this._loadWeekInfo();
        });

        onMounted(() => {
            this._updateModelContext(this.weekState.currentWeek);
        });
    }

    /**
     * 載入週次資訊
     */
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
                { number: -1, name: _t('Last Week'), key: 'week_prev', count: 0, total_hours: 0, dates: {} },
                { number: 0, name: _t('This Week'), key: 'week0', count: 0, total_hours: 0, dates: {} },
                { number: 1, name: _t('Next Week'), key: 'week1', count: 0, total_hours: 0, dates: {} },
                { number: 2, name: _t('Week 3'), key: 'week2', count: 0, total_hours: 0, dates: {} },
                { number: 3, name: _t('Week 4'), key: 'week3', count: 0, total_hours: 0, dates: {} },
            ];
        }
        this.weekState.isLoading = false;
    }

    /**
     * 選擇週次並套用篩選
     */
    async selectWeek(weekNumber) {
        if (this.weekState.currentWeek === weekNumber) {
            return;
        }

        this.weekState.currentWeek = weekNumber;

        // 儲存基礎 domain
        if (this._baseDomain === null) {
            this._baseDomain = this._filterWeekDomain(this.props.domain || []);
        }

        // 建立包含週次篩選的 domain
        const weekDomain = this._buildWeekDomain(weekNumber);

        // 將目前週次寫入 model root config context，供 load() 傳播給新建的 groups/records
        this._updateModelContext(weekNumber);

        // 重新載入資料（groups/records 會從 root config context 繼承週次資訊）
        await this.model.root.load({ domain: weekDomain });
        this.model.notify();

        // load() 後再次更新，確保所有新建的 groups/records 都有正確的 context
        this._updateModelContext(weekNumber);

        // 重新載入週次資訊
        await this._loadWeekInfo();
    }

    /**
     * 更新 model context 以傳遞目前週次給後端
     */
    _updateModelContext(weekNumber) {
        const currentWeekInfo = this.weekState.weeks.find(w => w.number === weekNumber);
        const dates = currentWeekInfo ? currentWeekInfo.dates : {};

        // 更新響應式狀態，讓 ActivityKanbanHeader 自動重新渲染
        this.weekDatesState.dates = dates;

        // 更新 root config context，使 load() 時自動傳播到新建的 groups/records
        if (this.model.root.config) {
            this.model.root.config.context = {
                ...this.model.root.config.context,
                schedule_current_week: weekNumber,
                schedule_week_dates: dates,
            };
        }

        // 同步更新已存在的 groups 和 records（供立即拖曳使用）
        for (const group of this.model.root.groups || []) {
            if (group.config && group.config.context) {
                group.config.context = {
                    ...group.config.context,
                    schedule_current_week: weekNumber,
                    schedule_week_dates: dates,
                };
            }
            // 更新 group 下所有 record 的 context
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
     * 過濾掉週次相關的 domain 條件
     */
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

            // 檢查是否為週次相關條件
            if (Array.isArray(item) && item.length === 3) {
                if (item[0] === 'schedule_week_number' || item[0] === 'schedule_status') {
                    // 如果前一個是 '|'，也要移除
                    if (filtered.length > 0 && filtered[filtered.length - 1] === '|') {
                        filtered.pop();
                    }
                    continue;
                }
            }

            // 檢查是否為 '|' 且後面兩個都是週次相關
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
    }

    /**
     * 建立週次篩選 domain
     */
    _buildWeekDomain(weekNumber) {
        // 週次篩選：顯示該週的排程或等待排程的項目
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
    }

    /**
     * 更新欄位標題加入日期（已改由 ActivityKanbanHeader 透過 group context 直接顯示）
     * 此方法保留作為備用，不再做 DOM 操作
     */
    _updateColumnHeaders() {
        // 日期顯示已移至 ActivityKanbanHeader 元件，
        // 透過 group.context.schedule_week_dates 取得日期資訊
    }

    /**
     * 取得週次按鈕的 CSS class
     */
    getWeekButtonClass(week) {
        if (week.number === this.weekState.currentWeek) {
            return 'btn btn-sm btn-primary me-1';
        }
        return 'btn btn-sm btn-outline-secondary me-1';
    }

    /**
     * 格式化工時顯示
     */
    formatHours(hours) {
        if (!hours) return '';
        return hours.toFixed(1) + _t(' hours');
    }

    /**
     * 取得週次的日期範圍顯示
     */
    getWeekDateRange(week) {
        if (week.start_date && week.end_date) {
            return `${week.start_date} ~ ${week.end_date}`;
        }
        return '';
    }

    /**
     * 週次選擇器變更事件
     */
    async onWeekSelectChange(ev) {
        const weekNumber = parseInt(ev.target.value, 10);
        await this.selectWeek(weekNumber);
    }

    /**
     * 批次延期選中的待辦
     */
    async onBatchPostpone() {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            this.notification.add(_t("Please select activities to postpone first"), {
                type: "warning",
            });
            return;
        }

        const activityIds = selectedRecords.map(r => r.resId);

        // Open batch postpone wizard
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
    }

    /**
     * 批次完成選中的待辦
     */
    async onBatchDone() {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            this.notification.add(_t("Please select activities to complete first"), {
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

        this.notification.add(_t("Completed %s activities", activityIds.length), {
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

        const weekNames = {
            '-1': _t('Last Week'),
            '0': _t('This Week'),
            '1': _t('Next Week'),
            '2': _t('Week 3'),
            '3': _t('Week 4'),
        };
        const weekName = weekNames[String(weekNumber)] || _t('Specified Week');

        this.notification.add(_t("Scheduled %s activities to %s", activityIds.length, weekName), {
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
            name: _t('New Activity'),
            res_model: 'mail.activity',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: this.props.context,
        });
    }
}
