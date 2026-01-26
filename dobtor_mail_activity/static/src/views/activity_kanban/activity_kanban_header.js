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
     * @returns {string|null} 日期字串，如果沒有則返回 null
     */
    get columnDate() {
        // 從 group 的 serverValue 取得欄位 key
        const groupKey = this.props.group.serverValue;

        // 週天對應的 schedule_status 值
        const keyToWeekday = {
            'monday': 'Monday',
            'tuesday': 'Tuesday',
            'wednesday': 'Wednesday',
            'thursday': 'Thursday',
            'friday': 'Friday',
            'saturday': 'Saturday',
            'sunday': 'Sunday',
            'waiting': 'Waiting Schedule'
        };

        // 這裡應該從控制器獲取日期資訊，但由於組件分離，
        // 我們使用 DOM 操作在控制器的 _updateColumnHeaders 方法中處理
        return null;
    }
}
