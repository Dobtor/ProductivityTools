/** @odoo-module */

import { KanbanHeader } from "@web/views/kanban/kanban_header";
import { ActivityColumnProgress } from "./activity_column_progress";

/**
 * 自訂活動 Kanban Header
 * 使用自訂的 ActivityColumnProgress 組件來顯示工時進度條
 */
export class ActivityKanbanHeader extends KanbanHeader {
    static template = "dobtor_mail_activity.ActivityKanbanHeader";
    static components = {
        ...KanbanHeader.components,
        ActivityColumnProgress,
    };

    /**
     * 取得當前週的日期資訊
     * @returns {string|null} 日期字串 (YYYY-MM-DD)，如果沒有則返回 null
     */
    get columnDate() {
        const groupKey = this.props.group.serverValue;
        if (!groupKey || groupKey === 'waiting') {
            return null;
        }
        // 從 env.activityWeekDates 取得日期（由 controller 透過 useSubEnv 提供的響應式狀態）
        const weekDates = this.env.activityWeekDates?.dates;
        if (weekDates && weekDates[groupKey]) {
            return weekDates[groupKey];
        }
        return null;
    }
}
