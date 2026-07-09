/** @odoo-module **/

/**
 * Custom list view for xmind.workbook whose "New" button, instead of opening the
 * form, creates a blank workbook and jumps straight into the mind map editor —
 * mirroring the kanban `on_create` behaviour so every create surface is consistent.
 *
 * Bound via `js_class="xmind_workbook_list_open_editor"` on the <list> arch.
 */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

export class XmindNewEditorListController extends ListController {
    /** Override: run the server action that creates the record and returns the
     *  editor client action, rather than the default form/inline create. */
    async createRecord() {
        await this.actionService.doAction("dobtor_xmind.action_new_xmind_editor");
    }
}

registry.category("views").add("xmind_workbook_list_open_editor", {
    ...listView,
    Controller: XmindNewEditorListController,
});
