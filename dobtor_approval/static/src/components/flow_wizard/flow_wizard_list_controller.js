/** @odoo-module **/
// Copyright 2026 Dobtor Systems Integration
// License LGPL-3
/**
 * FlowWizardListController — 在簽核流程定義 list 上方加「精靈建立」按鈕，
 * 經 dialog service 把 FlowWizardDialog 開在 list 之上（保留清單脈絡）。
 *
 * 透過 list 視圖 js_class="bpmn_executable_process_list" 套用。
 */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { FlowWizardDialog } from "./flow_wizard";

export class FlowWizardListController extends ListController {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
    }

    openFlowWizard() {
        this.dialog.add(FlowWizardDialog, {});
    }
}

registry.category("views").add("bpmn_executable_process_list", {
    ...listView,
    Controller: FlowWizardListController,
    buttonTemplate: "dobtor_approval.FlowWizardListView.Buttons",
});
