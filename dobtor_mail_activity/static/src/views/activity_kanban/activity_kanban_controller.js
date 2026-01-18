/** @odoo-module */

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { useState, onWillStart, onMounted, onPatched } from "@odoo/owl";

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

        // 基礎 domain（排除週次篩選）
        this._baseDomain = null;

        // 綁定方法
        this.onWeekSelectChange = this.onWeekSelectChange.bind(this);

        onWillStart(async () => {
            await this._loadWeekInfo();
        });

        onMounted(() => {
            this._updateColumnHeaders();
        });

        onPatched(() => {
            this._updateColumnHeaders();
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
                { number: -1, name: '上週', key: 'week_prev', count: 0, total_hours: 0, dates: {} },
                { number: 0, name: '本週', key: 'week0', count: 0, total_hours: 0, dates: {} },
                { number: 1, name: '下週', key: 'week1', count: 0, total_hours: 0, dates: {} },
                { number: 2, name: '第三週', key: 'week2', count: 0, total_hours: 0, dates: {} },
                { number: 3, name: '第四週', key: 'week3', count: 0, total_hours: 0, dates: {} },
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

        // 重新載入資料
        await this.model.root.load({ domain: weekDomain });
        this.model.notify();

        // 重新載入週次資訊
        await this._loadWeekInfo();

        // 更新欄位標題
        this._updateColumnHeaders();
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
     * 更新欄位標題加入日期
     */
    _updateColumnHeaders() {
        if (!this.weekState.weeks.length) return;

        const currentWeekInfo = this.weekState.weeks.find(w => w.number === this.weekState.currentWeek);
        if (!currentWeekInfo) return;

        const dates = currentWeekInfo.dates || {};

        // 週天對應的 schedule_status 值
        const titleToKey = {
            '週一': 'monday',
            '週二': 'tuesday',
            '週三': 'wednesday',
            '週四': 'thursday',
            '週五': 'friday',
            '週六': 'saturday',
            '週日': 'sunday',
            '等待排程': 'waiting'
        };

        // 延遲執行以確保 DOM 已更新
        setTimeout(() => {
            const groups = document.querySelectorAll('.o_kanban_group');
            groups.forEach(col => {
                const headerTitle = col.querySelector('.o_kanban_header_title');
                const header = headerTitle?.querySelector('.o_column_title');

                if (!header) return;

                // 移除舊的日期標記
                const oldDateInfo = header.querySelector('.week-date-info');
                if (oldDateInfo) {
                    oldDateInfo.remove();
                }

                // 取得 group key
                let groupKey = '';
                const dataId = col.dataset.id || '';
                if (dataId) {
                    groupKey = String(dataId).toLowerCase();
                }
                if (!groupKey || !dates[groupKey]) {
                    const titleText = header.textContent.trim();
                    groupKey = titleToKey[titleText] || '';
                }

                // 加入日期資訊（插入到標題元素內部）
                if (groupKey && dates[groupKey]) {
                    const dateSpan = document.createElement('span');
                    dateSpan.className = 'week-date-info';
                    // 顯示完整日期 YYYY-MM-DD
                    const dateStr = dates[groupKey];
                    dateSpan.textContent = ' ' + dateStr;
                    header.appendChild(dateSpan);
                }
            });
        }, 100);
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
        return hours.toFixed(1) + _t('小時');
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
