/** @odoo-module **/

/**
 * Live, read-only mind map embedded inside another model's HTML field.
 *
 * Inserted by the "/" power-box command "插入心智圖"; data-embedded="xmindMindmap".
 * The block persists only { workbookId, resModel, resId }. It mounts the FULL
 * MindmapEditor component in read-only mode, so the map is rendered through the
 * exact same pipeline as the real editor — faithful theme, layout, node styling,
 * markers, labels, images, floating topics, AND overlays (relationships,
 * boundaries, summaries, callouts) — always fresh from the DB, never stale, and
 * non-editable (no toolbar/sidebar/status bar, no autosave, no keyboard/drag).
 *
 * On mount (host record already saved) it registers the whole-workbook association
 * via xmind.workbook.register_embed so the editor's project bar can list the host
 * records under "關聯物件：...".
 */
import { Component, onWillStart, useState } from "@odoo/owl";
import { getEmbeddedProps } from "@html_editor/others/embedded_component_utils";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { MindmapEditor } from "@dobtor_xmind/js/mindmap_editor";

export class EmbeddedXmindMindmap extends Component {
    static template = "dobtor_xmind.EmbeddedMindmap";
    static components = { MindmapEditor };
    static props = {
        host: { type: Object },
        workbookId: { type: [Number, Boolean], optional: true },
        resModel: { type: [String, Boolean], optional: true },
        resId: { type: [Number, Boolean], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ name: "", missing: false });

        onWillStart(async () => {
            if (!this.workbookId) {
                this.state.missing = true;
                return;
            }
            try {
                const recs = await this.orm.read("xmind.workbook", [this.workbookId], ["name"]);
                if (recs && recs.length) {
                    this.state.name = recs[0].name || "";
                } else {
                    this.state.missing = true;
                }
            } catch (e) {
                this.state.missing = true;
            }
            this._registerEmbed();
        });
    }

    get workbookId() {
        return this.props.workbookId || false;
    }

    /** Props for the read-only MindmapEditor sub-component. */
    get editorProps() {
        return { workbookId: this.workbookId, readonly: true };
    }

    /** Register the whole-workbook ↔ host-record association (idempotent). */
    async _registerEmbed() {
        const { resModel, resId } = this.props;
        if (!resModel || !resId) {
            return;
        }
        try {
            await this.orm.call("xmind.workbook", "register_embed", [
                this.workbookId,
                resModel,
                resId,
            ]);
        } catch (e) {
            // Non-fatal: the map still renders even if the link can't be recorded.
        }
    }

    get emptyLabel() {
        return _t("Mind map not found or access denied.");
    }

    /** Open the full (editable) mind map editor — the same client action the app
     *  uses everywhere (xmind.workbook.action_open_editor). */
    onOpen() {
        if (!this.workbookId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.client",
            tag: "dobtor_xmind.mindmap_editor",
            params: { workbook_id: this.workbookId },
            target: "current",
        });
    }
}

export const xmindMindmapEmbedding = {
    name: "xmindMindmap",
    Component: EmbeddedXmindMindmap,
    getProps: (host) => ({ host, ...getEmbeddedProps(host) }),
};

// Read-only display reuses the same component (it is already non-editable).
export const readonlyXmindMindmapEmbedding = xmindMindmapEmbedding;
