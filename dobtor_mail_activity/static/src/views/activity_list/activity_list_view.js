/** @odoo-module */

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ActivityListController } from "./activity_list_controller";
import { ActivityWeekSearchModel } from "../activity_week_search_model";

export const activityListView = {
    ...listView,
    Controller: ActivityListController,
    SearchModel: ActivityWeekSearchModel,
};

registry.category("views").add("activity_list", activityListView);
