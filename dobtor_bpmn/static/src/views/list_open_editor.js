/** @odoo-module **/

/**
 * Custom list view for bpmn.diagram whose "New" button, instead of opening the
 * form, creates a blank diagram and jumps straight into the visual editor —
 * mirroring the kanban `on_create` behaviour so every create surface is consistent.
 *
 * Bound via `js_class="bpmn_diagram_list_open_editor"` on the <list> arch.
 */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

export class BpmnNewEditorListController extends ListController {
    /** Override: run the server action that creates the record and returns the
     *  editor client action, rather than the default form/inline create. */
    async createRecord() {
        await this.actionService.doAction("dobtor_bpmn.action_new_bpmn_editor");
    }
}

registry.category("views").add("bpmn_diagram_list_open_editor", {
    ...listView,
    Controller: BpmnNewEditorListController,
});
