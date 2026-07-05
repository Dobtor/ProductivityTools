/** @odoo-module **/

/**
 * Rich-text (html) editor "/" power-box plugin: insert an existing mind map.
 *
 * Adds one command — 插入心智圖 — under a dedicated category placed by sequence
 * BETWEEN the "待辦 / 活動" category (dobtor_mail_activity, seq 5) and the native
 * "結構 / structure" category (seq 10), i.e. seq 7. No hard dependency on
 * dobtor_mail_activity: if that module is absent the category simply sits above
 * structure on its own.
 *
 * The command opens a picker of existing xmind.workbook records; the chosen mind
 * map is inserted as a live, read-only embedded block bound to the whole workbook.
 * The host record (res_model/res_id, captured at insert time) is baked into the
 * block props so the embedded component can register the association on mount.
 */
import { Plugin } from "@html_editor/plugin";
import { _t } from "@web/core/l10n/translation";
import { withSequence } from "@html_editor/utils/resource";
import { renderToElement } from "@web/core/utils/render";
import { XmindPickerDialog } from "@dobtor_xmind/editor/xmind_picker_dialog";

export class XmindPowerboxPlugin extends Plugin {
    static id = "dobtorXmindMindmap";
    static dependencies = ["embeddedComponents", "dom", "selection", "history"];

    resources = {
        user_commands: [
            {
                id: "dobtorInsertMindmap",
                title: _t("Insert Mind Map"),
                description: _t("Embed an existing mind map, rendered live"),
                icon: "fa-sitemap",
                run: this.openMindmapPicker.bind(this),
            },
        ],
        // seq 7 → between "待辦/活動"(5) and native "結構"(10).
        powerbox_categories: withSequence(7, {
            id: "xmind_mindmap",
            name: _t("Mind Map"),
        }),
        powerbox_items: [
            { categoryId: "xmind_mindmap", commandId: "dobtorInsertMindmap" },
        ],
    };

    /** Current host record (may be empty for unsaved / record-less editors). */
    getRecordInfo() {
        return (this.config.getRecordInfo && this.config.getRecordInfo()) || {};
    }

    /** Open the picker; on choice, insert the live embed at the saved cursor. */
    openMindmapPicker() {
        // Remember the cursor: opening the dialog moves focus away from the editor.
        const selection = this.dependencies.selection.getEditableSelection();
        this.services.dialog.add(XmindPickerDialog, {
            onSelect: (workbookId) => this.insertMindmap(workbookId, selection),
        });
    }

    insertMindmap(workbookId, selection) {
        try {
            this.dependencies.selection.setSelection(selection);
        } catch (e) {
            // Fall back to the current selection if the saved one can't be restored.
        }
        const { resModel, resId } = this.getRecordInfo();
        // resId may arrive as a string; keep the persisted prop a clean Number|false
        // so the embedded component's prop types validate.
        const resIdNum = resId ? Number(resId) || false : false;
        const block = renderToElement("dobtor_xmind.MindmapBlueprint", {
            embeddedProps: JSON.stringify({
                workbookId,
                resModel: resModel || false,
                resId: resIdNum,
            }),
        });
        this.dependencies.dom.insert(block);
        this.dependencies.history.addStep();
    }
}
