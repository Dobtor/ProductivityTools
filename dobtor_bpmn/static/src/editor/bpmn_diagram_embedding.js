/** @odoo-module **/

/**
 * Live, read-only BPMN/DMN diagram embedded inside another model's HTML field.
 *
 * Inserted by the "/" power-box command "插入流程設計圖"; data-embedded="bpmnDiagram".
 * The block persists only { diagramId, resModel, resId }. It mounts the FULL
 * BpmnEditorAction component in read-only mode, so the diagram is rendered through
 * the exact same bpmn-js / dmn-js pipeline as the real editor — a faithful render,
 * always fresh from the DB, never stale, and non-editable (no toolbar/panel/project
 * bar, no save, canvas made non-interactive).
 *
 * On mount (host record already saved) it registers the whole-diagram association
 * via bpmn.diagram.register_embed so the editor's project bar can list the host
 * records under "關聯物件：...".
 */
import { Component, onWillStart, useState } from "@odoo/owl";
import { getEmbeddedProps } from "@html_editor/others/embedded_component_utils";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { BpmnEditorAction } from "@dobtor_bpmn/editor/bpmn_editor_action";

export class EmbeddedBpmnDiagram extends Component {
    static template = "dobtor_bpmn.EmbeddedDiagram";
    static components = { BpmnEditorAction };
    static props = {
        host: { type: Object },
        diagramId: { type: [Number, Boolean], optional: true },
        resModel: { type: [String, Boolean], optional: true },
        resId: { type: [Number, Boolean], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ name: "", missing: false });

        onWillStart(async () => {
            if (!this.diagramId) {
                this.state.missing = true;
                return;
            }
            try {
                const recs = await this.orm.read("bpmn.diagram", [this.diagramId], ["name"]);
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

    get diagramId() {
        return this.props.diagramId || false;
    }

    /** Props for the read-only BpmnEditorAction sub-component. */
    get editorProps() {
        return { diagramId: this.diagramId, readonly: true };
    }

    /** Register the whole-diagram ↔ host-record association (idempotent). */
    async _registerEmbed() {
        const { resModel, resId } = this.props;
        if (!resModel || !resId) {
            return;
        }
        try {
            await this.orm.call("bpmn.diagram", "register_embed", [
                this.diagramId,
                resModel,
                resId,
            ]);
        } catch (e) {
            // Non-fatal: the diagram still renders even if the link can't be recorded.
        }
    }

    get emptyLabel() {
        return _t("Diagram not found or access denied.");
    }

    /** Open the full (editable) visual editor — the same client action the app
     *  uses everywhere (bpmn.diagram.action_open_editor). */
    onOpen() {
        if (!this.diagramId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.client",
            tag: "dobtor_bpmn.bpmn_editor",
            params: { diagram_id: this.diagramId },
            target: "current",
        });
    }
}

export const bpmnDiagramEmbedding = {
    name: "bpmnDiagram",
    Component: EmbeddedBpmnDiagram,
    getProps: (host) => ({ host, ...getEmbeddedProps(host) }),
};

// Read-only display reuses the same component (it is already non-editable).
export const readonlyBpmnDiagramEmbedding = bpmnDiagramEmbedding;
