/** @odoo-module */

import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { ActivityKanbanHeader } from "./activity_kanban_header";

/**
 * 自訂活動 Kanban Renderer
 * 使用 ActivityKanbanHeader 來顯示工時進度條
 */
export class ActivityKanbanRenderer extends KanbanRenderer {
    static components = {
        ...KanbanRenderer.components,
        KanbanHeader: ActivityKanbanHeader,
    };
}
