/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ensureBpmnLib, ensureDmnLib } from "../modeler/lib_loader";
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

/**
 * bpmn_editor — Text 欄位用的 BPMN/DMN 視覺編輯器 widget。
 * 依同筆紀錄的 type_field（diagram_type）決定載入 bpmn-js 或 dmn-js。
 * 函式庫缺檔時優雅降級為「放置說明 + 純文字 XML」。
 */
export class BpmnEditorField extends Component {
    static template = "dobtor_bpmn.BpmnEditorField";
    static props = {
        ...standardFieldProps,
        type_field: { type: String, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.canvasRef = useRef("canvas");
        this.panelRef = useRef("panel");
        this.modeler = null;
        this.state = useState({ ready: false, libMissing: false, error: "" });

        this._diagramType = this._readType();

        onWillStart(async () => {
            const ok =
                this._diagramType === "dmn"
                    ? await ensureDmnLib()
                    : await ensureBpmnLib();
            this.state.libMissing = !ok;
        });

        onMounted(() => this._initModeler());
        onWillUnmount(() => this._destroyModeler());
    }

    _readType() {
        const typeField = this.props.type_field || "diagram_type";
        return this.props.record.data[typeField] || "bpmn";
    }

    get xmlValue() {
        return this.props.record.data[this.props.name] || "";
    }

    get readonly() {
        return this.props.readonly;
    }

    async _initModeler() {
        if (this.state.libMissing) {
            return;
        }
        const Ctor = this._diagramType === "dmn" ? window.DmnJS : window.BpmnJS;
        if (!Ctor || !this.canvasRef.el) {
            this.state.libMissing = true;
            return;
        }
        try {
            const options = { container: this.canvasRef.el };
            if (this._diagramType !== "dmn" && this.panelRef.el) {
                options.propertiesPanel = { parent: this.panelRef.el };
            }
            this.modeler = new Ctor(options);
            await this._importXml(this.xmlValue);
            this.state.ready = true;
        } catch (e) {
            this.state.error = e?.message || String(e);
        }
    }

    async _importXml(xml) {
        if (!this.modeler || !xml) {
            return;
        }
        if (this._diagramType === "dmn") {
            await this.modeler.importXML(xml);
        } else {
            await this.modeler.importXML(xml);
            try {
                this.modeler.get("canvas").zoom("fit-viewport");
            } catch {
                // canvas 尚未就緒，略過
            }
        }
    }

    _destroyModeler() {
        if (this.modeler) {
            try {
                this.modeler.destroy();
            } catch {
                // 忽略銷毀錯誤
            }
            this.modeler = null;
        }
    }

    /** 將目前圖面存回欄位（含 SVG 縮圖，若記錄有 svg 欄位）。 */
    async save() {
        if (!this.modeler) {
            return;
        }
        try {
            const { xml } = await this.modeler.saveXML({ format: true });
            const changes = { [this.props.name]: xml };
            if ("svg" in this.props.record.data && this.modeler.saveSVG) {
                try {
                    const { svg } = await this.modeler.saveSVG();
                    changes.svg = svg;
                } catch {
                    // DMN 多視圖時 saveSVG 可能不適用，略過
                }
            }
            await this.props.record.update(changes);
            this.notification.add(_t("流程圖已套用，請按存檔。"), { type: "success" });
        } catch (e) {
            this.notification.add(_t("儲存流程圖失敗：%s", e?.message || e), {
                type: "danger",
            });
        }
    }
}

export const bpmnEditorField = {
    component: BpmnEditorField,
    displayName: _t("BPMN/DMN 編輯器"),
    supportedTypes: ["text", "html"],
    extractProps: ({ options }) => ({
        type_field: options.type_field || "diagram_type",
    }),
};

registry.category("fields").add("bpmn_editor", bpmnEditorField);
