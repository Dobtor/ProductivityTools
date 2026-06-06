/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ensureBpmnLib, ensureDmnLib } from "../modeler/lib_loader";
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

/**
 * BPMN/DMN 全螢幕視覺編輯器（client action，仿 dobtor_xmind 架構）。
 * - 不在 form notebook 內；由設計圖 form header 按鈕 / kanban 卡片開啟。
 * - 文件 metadata 留在 form/kanban；本元件只負責畫布。
 * - 透過 orm service 讀寫紀錄（尊重存取規則），存檔寫回 xml + svg。
 */
export class BpmnEditorAction extends Component {
    static template = "dobtor_bpmn.BpmnEditorAction";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.canvasRef = useRef("canvas");
        this.panelRef = useRef("panel");
        this.modeler = null;

        this.diagramId =
            (this.props.action &&
                this.props.action.params &&
                this.props.action.params.diagram_id) ||
            null;

        this.state = useState({
            ready: false,
            libMissing: false,
            error: "",
            name: "",
            diagramType: "bpmn",
            dirty: false,
            saving: false,
        });

        onWillStart(async () => {
            if (!this.diagramId) {
                this.state.error = _t("缺少設計圖 ID。");
                return;
            }
            const [rec] = await this.orm.read(
                "bpmn.diagram",
                [this.diagramId],
                ["name", "diagram_type", "xml"]
            );
            this._record = rec;
            this.state.name = rec.name || "";
            this.state.diagramType = rec.diagram_type || "bpmn";
            this.state.libMissing = !(this.state.diagramType === "dmn"
                ? await ensureDmnLib()
                : await ensureBpmnLib());
        });

        onMounted(() => this._initModeler());
        onWillUnmount(() => this._destroyModeler());
    }

    async _initModeler() {
        if (this.state.libMissing || this.state.error) {
            return;
        }
        const Ctor = this.state.diagramType === "dmn" ? window.DmnJS : window.BpmnJS;
        if (!Ctor || !this.canvasRef.el) {
            this.state.libMissing = true;
            return;
        }
        try {
            const options = { container: this.canvasRef.el };
            if (this.state.diagramType !== "dmn" && this.panelRef.el) {
                options.propertiesPanel = { parent: this.panelRef.el };
            }
            this.modeler = new Ctor(options);
            const xml = (this._record && this._record.xml) || "";
            if (xml) {
                await this.modeler.importXML(xml);
                try {
                    this.modeler.get("canvas").zoom("fit-viewport");
                } catch {
                    // DMN 多視圖或 canvas 未就緒，略過
                }
            }
            // 監聽變更以標記 dirty
            try {
                this.modeler.on("commandStack.changed", () => {
                    this.state.dirty = true;
                });
            } catch {
                // 某些 dmn-js 視圖無 commandStack，略過
            }
            this.state.ready = true;
        } catch (e) {
            this.state.error = e?.message || String(e);
        }
    }

    _destroyModeler() {
        if (this.modeler) {
            try {
                this.modeler.destroy();
            } catch {
                // 忽略
            }
            this.modeler = null;
        }
    }

    async onSave() {
        if (!this.modeler || this.state.saving) {
            return;
        }
        this.state.saving = true;
        try {
            const { xml } = await this.modeler.saveXML({ format: true });
            const changes = { xml };
            if (this.modeler.saveSVG) {
                try {
                    const { svg } = await this.modeler.saveSVG();
                    changes.svg = svg;
                } catch {
                    // saveSVG 不適用時略過
                }
            }
            await this.orm.write("bpmn.diagram", [this.diagramId], changes);
            this.state.dirty = false;
            this.notification.add(_t("已儲存。"), { type: "success" });
        } catch (e) {
            this.notification.add(_t("儲存失敗：%s", e?.message || e), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }

    async onNameChange(ev) {
        const newName = (ev.target.value || "").trim();
        if (!newName) {
            ev.target.value = this.state.name; // 不允許空名稱，還原
            return;
        }
        if (newName === this.state.name) {
            return;
        }
        this.state.name = newName;
        try {
            await this.orm.write("bpmn.diagram", [this.diagramId], { name: newName });
            this.notification.add(_t("名稱已更新。"), { type: "success" });
        } catch (e) {
            this.notification.add(_t("更新名稱失敗：%s", e?.message || e), {
                type: "danger",
            });
        }
    }

    onBack() {
        this.action.doAction("dobtor_bpmn.action_bpmn_diagram", {
            clearBreadcrumbs: true,
        });
    }
}

registry.category("actions").add("dobtor_bpmn.bpmn_editor", BpmnEditorAction);
