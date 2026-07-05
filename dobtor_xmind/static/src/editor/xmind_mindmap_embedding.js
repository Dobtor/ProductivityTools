/** @odoo-module **/

/**
 * Live, read-only mind map embedded inside another model's HTML field.
 *
 * Inserted by the "/" power-box command "插入心智圖"; data-embedded="xmindMindmap".
 * The block persists only { workbookId, resModel, resId }; the map itself is always
 * fetched fresh from the backend (/xmind/workbook/<id>/data) at mount, so it stays
 * faithful to the original — same theme, layout, node styling and floating topics —
 * and never goes stale. Rendered with window.OdooMindMap in editable:false mode
 * (no inline edit, no double-click-to-edit), draggable for panning.
 *
 * On mount (when the host record is already saved) it registers the whole-workbook
 * association via xmind.workbook.register_embed so the mind map editor's project bar
 * can list the host records under "關聯物件：...".
 */
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { getEmbeddedProps } from "@html_editor/others/embedded_component_utils";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

export class EmbeddedXmindMindmap extends Component {
    static template = "dobtor_xmind.EmbeddedMindmap";
    static props = {
        host: { type: Object },
        workbookId: { type: [Number, Boolean], optional: true },
        resModel: { type: [String, Boolean], optional: true },
        resId: { type: [Number, Boolean], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.canvasRef = useRef("canvas");
        this.state = useState({ loading: true, error: false, name: "" });
        this._alive = true;
        this._jm = null;

        onWillStart(() => this.load());
        onMounted(() => this._renderMap());
        onWillUnmount(() => {
            this._alive = false;
            this._jm = null;
            // Drop the rendered canvas so any renderer-held DOM/listeners go with it.
            if (this.canvasRef.el) {
                this.canvasRef.el.innerHTML = "";
            }
        });
    }

    get workbookId() {
        return this.props.workbookId || false;
    }

    async load() {
        if (!this.workbookId) {
            this.state.error = _t("No mind map selected.");
            this.state.loading = false;
            return;
        }
        try {
            const result = await rpc(`/xmind/workbook/${this.workbookId}/data`, {});
            if (!this._alive) {
                return;
            }
            if (!result || result.error) {
                this.state.error = _t("Mind map not found or access denied.");
                this.state.loading = false;
                return;
            }
            this._data = result;
            this.state.name = result.name || "";
            this.state.loading = false;
            // Fire-and-forget association registration (host must be saved).
            this._registerEmbed();
        } catch (e) {
            if (this._alive) {
                this.state.error = _t("Failed to load mind map.");
                this.state.loading = false;
            }
        }
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

    /** Instantiate the renderer read-only and show the fetched map faithfully. */
    _renderMap() {
        if (!this._alive || this.state.error || !this._data) {
            return;
        }
        const container = this.canvasRef.el;
        if (!container || !window.OdooMindMap) {
            this.state.error = _t("Mind map renderer not loaded.");
            return;
        }
        const settings = this._data.sheet_settings || {};
        const mindmapData = this._data.mindmap_data;
        if (!mindmapData || !mindmapData.data) {
            this.state.error = _t("This mind map is empty.");
            return;
        }

        // Inject floating topics as flagged root children (mirrors the main editor)
        // so free-floating nodes render at their saved positions.
        const floats = this._data.floating_topics || [];
        if (floats.length && mindmapData.data) {
            if (!mindmapData.data.children) {
                mindmapData.data.children = [];
            }
            for (const ft of floats) {
                if (mindmapData.data.children.some((c) => c.id === ft.id)) {
                    continue;
                }
                mindmapData.data.children.push({
                    id: ft.id || ft.component_id,
                    topic: ft.title,
                    expanded: true,
                    children: [],
                    data: {
                        _isFloatingTopic: true,
                        _ftX: ft.x,
                        _ftY: ft.y,
                        note: ft.note || "",
                        style: ft.style || { background: "#FFFFFF", color: "#303030", fontSize: "13", bold: true },
                        shape: { type: "rounded", fillColor: "#FFFFFF", borderColor: "#558ED5", borderWidth: 2 },
                    },
                });
            }
        }

        const options = {
            container,
            theme: settings.theme || "primary",
            editable: false,
            mode: "full",
            support_html: false,
            view: {
                engine: "canvas",
                hmargin: 60,
                vmargin: 30,
                line_width: 2,
                line_color: "#555",
                draggable: true,
                hide_scrollbars_when_draggable: false,
            },
            layout: {
                hspace: settings.spacing_major || 30,
                vspace: settings.spacing_minor || 8,
                pspace: 13,
            },
            shortcut: { enable: false },
        };

        try {
            this._jm = new window.OdooMindMap(options);
            const layoutMode = settings.layout || "map";
            if (this._jm.layout && this._jm.layout.setLayoutMode) {
                this._jm.layout.setLayoutMode(layoutMode);
            }
            this._jm.show(mindmapData);
        } catch (e) {
            this.state.error = _t("Failed to render mind map.");
        }
    }

    /** Open the full mind map editor for this workbook in a new form view. */
    onOpen() {
        if (!this.workbookId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "xmind.workbook",
            res_id: this.workbookId,
            views: [[false, "form"]],
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
