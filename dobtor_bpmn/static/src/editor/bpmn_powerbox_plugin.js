/** @odoo-module **/

/**
 * Rich-text (html) editor "/" power-box plugin: insert an existing BPMN/DMN diagram.
 *
 * Adds one command — 插入流程設計圖 — under a dedicated category placed by sequence
 * BETWEEN the "待辦 / 活動" category (dobtor_mail_activity, seq 5) and the native
 * "結構 / structure" category (seq 10), i.e. seq 8. No hard dependency on
 * dobtor_mail_activity / dobtor_xmind: if those are absent the category simply
 * sits above structure on its own.
 *
 * The command opens a picker of existing bpmn.diagram records; the chosen diagram
 * is inserted as a live, read-only embedded block bound to the whole diagram. The
 * host record (res_model/res_id, captured at insert time) is baked into the block
 * props so the embedded component can register the association on mount.
 */
import { Plugin } from "@html_editor/plugin";
import { _t } from "@web/core/l10n/translation";
import { withSequence } from "@html_editor/utils/resource";
import { renderToElement } from "@web/core/utils/render";
import { BpmnPickerDialog } from "@dobtor_bpmn/editor/bpmn_picker_dialog";

export class BpmnPowerboxPlugin extends Plugin {
    static id = "dobtorBpmnDiagram";
    static dependencies = ["embeddedComponents", "dom", "selection", "history"];

    resources = {
        user_commands: [
            {
                id: "dobtorInsertBpmn",
                title: _t("Insert Process Diagram"),
                description: _t("Embed an existing BPMN/DMN diagram, rendered live"),
                icon: "fa-sitemap",
                run: this.openBpmnPicker.bind(this),
            },
        ],
        // seq 8 → between "待辦/活動"(5) and native "結構"(10).
        powerbox_categories: withSequence(8, {
            id: "bpmn_diagram",
            name: _t("Process Diagram"),
        }),
        powerbox_items: [
            { categoryId: "bpmn_diagram", commandId: "dobtorInsertBpmn" },
        ],
    };

    /** Current host record (may be empty for unsaved / record-less editors). */
    getRecordInfo() {
        return (this.config.getRecordInfo && this.config.getRecordInfo()) || {};
    }

    /** Open the picker; on choice, insert the live embed at the saved cursor. */
    openBpmnPicker() {
        // Remember the cursor: opening the dialog moves focus away from the editor.
        const selection = this.dependencies.selection.getEditableSelection();
        this.services.dialog.add(BpmnPickerDialog, {
            onSelect: (diagramId) => this.insertBpmn(diagramId, selection),
        });
    }

    insertBpmn(diagramId, selection) {
        try {
            this.dependencies.selection.setSelection(selection);
        } catch (e) {
            // Fall back to the current selection if the saved one can't be restored.
        }
        const { resModel, resId } = this.getRecordInfo();
        // resId may arrive as a string; keep the persisted prop a clean Number|false
        // so the embedded component's prop types validate.
        const resIdNum = resId ? Number(resId) || false : false;
        const block = renderToElement("dobtor_bpmn.DiagramBlueprint", {
            embeddedProps: JSON.stringify({
                diagramId,
                resModel: resModel || false,
                resId: resIdNum,
            }),
        });
        this.dependencies.dom.insert(block);
        this.dependencies.history.addStep();
    }
}
