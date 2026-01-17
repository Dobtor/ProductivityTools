/** @odoo-module */

import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { ActivityKanbanController } from "./activity_kanban_controller";

export const activityKanbanView = {
    ...kanbanView,
    Controller: ActivityKanbanController,
};

registry.category("views").add("activity_kanban", activityKanbanView);
