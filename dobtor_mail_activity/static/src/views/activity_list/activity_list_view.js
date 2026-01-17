/** @odoo-module */

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ActivityListController } from "./activity_list_controller";

export const activityListView = {
    ...listView,
    Controller: ActivityListController,
};

registry.category("views").add("activity_list", activityListView);
