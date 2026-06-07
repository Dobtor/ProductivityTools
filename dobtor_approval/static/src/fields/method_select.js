/** @odoo-module **/
// Copyright 2026 Dobtor Systems Integration — License LGPL-3
/**
 * bpmn_method_select — Char 欄位 widget：依同筆記錄的「目標模型」欄位，
 * RPC scan_model_actions 取該模型可攔截的按鈕/方法，渲染為下拉選單（中文 string），
 * 取代手打方法名。保留「手動輸入」後路與既有值。
 *
 * 用法：<field name="method_name" widget="bpmn_method_select"
 *              options="{'model_field': 'model_name'}"/>
 *   model_field：同筆記錄中代表目標模型的欄位（char 模型技術名 或 m2o ir.model）。
 */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";

export class MethodSelectField extends Component {
    static template = "dobtor_approval.MethodSelectField";
    static props = { ...standardFieldProps, modelField: { type: String, optional: true } };
    static defaultProps = { modelField: "model_name" };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ options: [], manual: false });
        onWillStart(() => this._load(this._model(this.props)));
        onWillUpdateProps((np) => {
            if (this._model(np) !== this._model(this.props)) {
                this._load(this._model(np));
            }
        });
    }

    _model(props) {
        const v = props.record.data[props.modelField];
        // model_name(char) → 字串；model_id(m2o) → [id, name]
        if (typeof v === "string") return v;
        return (v && v[1]) || "";
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get valueKnown() {
        return this.state.options.some((o) => o.name === this.value);
    }

    async _load(model) {
        if (!model) {
            this.state.options = [];
            return;
        }
        try {
            this.state.options = await this.orm.call(
                "bpmn.executable.process", "scan_model_actions", [model]);
        } catch {
            this.state.options = [];
        }
    }

    onSelect(ev) {
        const v = ev.target.value;
        if (v === "__manual__") {
            this.state.manual = true;
            return;
        }
        this.state.manual = false;
        this.props.record.update({ [this.props.name]: v });
    }

    onManualInput(ev) {
        this.props.record.update({ [this.props.name]: ev.target.value });
    }

    backToSelect() {
        this.state.manual = false;
    }
}

export const methodSelectField = {
    component: MethodSelectField,
    displayName: "BPMN 攔截方法選擇",
    supportedTypes: ["char"],
    extractProps: ({ options }) => ({ modelField: (options && options.model_field) || "model_name" }),
};

registry.category("fields").add("bpmn_method_select", methodSelectField);
