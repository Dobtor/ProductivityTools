/** @odoo-module */

import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { ActivityKanbanController } from "./activity_kanban_controller";
import { ActivityKanbanRenderer } from "./activity_kanban_renderer";
import { ActivityWeekSearchModel } from "../activity_week_search_model";

export const activityKanbanView = {
    ...kanbanView,
    Controller: ActivityKanbanController,
    Renderer: ActivityKanbanRenderer,
    SearchModel: ActivityWeekSearchModel,
};

registry.category("views").add("activity_kanban", activityKanbanView);
