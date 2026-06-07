/** @odoo-module **/
// Copyright 2026 Dobtor Systems Integration — License LGPL-3
/**
 * DmnEditor — DMN 決策編輯器（client action 'dmn_editor'）。
 *
 * 掛載 dmn-js DmnModeler（DRD + 決策表 + literal 三檢視，native UI），
 * 右側為 Odoo 變數綁定面板（DMN 變數 ⇄ 單據欄位，白名單）。
 * 儲存：saveXML → dmn.definitions.save_dmn_xml（重建 shadow）+ set_bindings。
 * 風格比照 process_editor。
 */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

const MODEL = "dmn.definitions";

export class DmnEditor extends Component {
    static template = "dobtor_approval.DmnEditor";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.canvasRef = useRef("canvas");
        this.modeler = null;

        this.definitionsId =
            (this.props.action && this.props.action.params &&
                this.props.action.params.definitions_id) || null;

        this.SOURCE_KINDS = [
            { value: "record_field", label: _t("單據欄位") },
            { value: "applicant", label: _t("申請人") },
            { value: "instance_ctx", label: _t("流程實例變數") },
            { value: "constant", label: _t("常數") },
        ];

        this.state = useState({
            loading: true,
            libMissing: false,
            error: "",
            name: "",
            stateLabel: "",
            version: 0,
            bindings: [],
            saving: false,
        });
        this._xml = "";

        onWillStart(async () => {
            // dmn-js 已隨模組打包（manifest web.assets_backend），不需 runtime load
            this.state.libMissing = !window.DmnJS;
            try {
                const data = await this.orm.call(MODEL, "get_dmn_data", [[this.definitionsId]]);
                this.state.name = data.name;
                this.state.version = data.version;
                this.state.stateLabel = data.state;
                this.state.bindings = (data.bindings || []).map((b) => ({ ...b }));
                this._xml = data.xml;
            } catch (e) {
                this.state.error = e?.message?.data?.message || e?.message || String(e);
            }
            this.state.loading = false;
        });

        onMounted(() => this._initCanvas());
        onWillUnmount(() => this._destroy());
    }

    async _initCanvas() {
        if (this.state.libMissing || this.state.error || !window.DmnJS) {
            if (!window.DmnJS) this.state.libMissing = true;
            return;
        }
        try {
            this.modeler = new window.DmnJS({ container: this.canvasRef.el });
            await this.modeler.importXML(this._xml || "");
        } catch (e) {
            this.state.error = e?.message || String(e);
        }
    }

    _destroy() {
        if (this.modeler) {
            try {
                this.modeler.destroy();
            } catch {
                /* noop */
            }
            this.modeler = null;
        }
    }

    // ---- 綁定面板 ----
    addBinding() {
        this.state.bindings.push({
            variable: "", source_kind: "record_field",
            record_field: "", instance_key: "", constant_value: "",
        });
    }

    removeBinding(idx) {
        this.state.bindings.splice(idx, 1);
    }

    // ---- 儲存 / 發佈 / 試算 ----
    async _saveXml() {
        if (!this.modeler) return true;
        try {
            const { xml } = await this.modeler.saveXML({ format: true });
            await this.orm.call(MODEL, "save_dmn_xml", [[this.definitionsId], xml]);
            await this.orm.call(MODEL, "set_bindings", [
                [this.definitionsId],
                this.state.bindings.map((b) => ({ ...b })),
            ]);
            return true;
        } catch (e) {
            this.notification.add(
                _t("儲存失敗：%s", e?.message?.data?.message || e?.message || e),
                { type: "danger", sticky: true }
            );
            return false;
        }
    }

    async onSave() {
        this.state.saving = true;
        if (await this._saveXml()) {
            this.notification.add(_t("已儲存決策。"), { type: "success" });
        }
        this.state.saving = false;
    }

    async onPublish() {
        if (!(await this._saveXml())) return;
        try {
            await this.orm.call(MODEL, "action_publish", [[this.definitionsId]]);
            this.notification.add(_t("決策集已發佈。"), { type: "success" });
            this.state.stateLabel = "published";
        } catch (e) {
            this.notification.add(
                _t("發佈失敗：%s", e?.message?.data?.message || e?.message || e),
                { type: "danger", sticky: true }
            );
        }
    }

    async onPreview() {
        if (!(await this._saveXml())) return;
        const act = await this.orm.call(MODEL, "action_open_preview", [[this.definitionsId]]);
        this.action.doAction(act);
    }

    onBack() {
        this.action.doAction("dobtor_approval.action_dmn_definitions", {
            clearBreadcrumbs: true,
        });
    }
}

registry.category("actions").add("dmn_editor", DmnEditor);
