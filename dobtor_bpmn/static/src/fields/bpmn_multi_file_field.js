/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";
import { Component, useState } from "@odoo/owl";

/**
 * bpmn_multi_file — 多檔上傳 widget（不依賴 stock many2many_binary 的版本行為）。
 * 用原生 <input type="file" multiple> 一次讀入所有選取檔案，存成 JSON
 * 陣列 [{name, data(base64)}] 寫回 Text 欄位；後端精靈解析後批次建立設計圖。
 */
export class BpmnMultiFileField extends Component {
    static template = "dobtor_bpmn.BpmnMultiFileField";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ files: this._parse() });
    }

    _parse() {
        try {
            return JSON.parse(this.props.record.data[this.props.name] || "[]");
        } catch {
            return [];
        }
    }

    get readonly() {
        return this.props.readonly;
    }

    _readAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const result = reader.result || "";
                resolve(String(result).split(",")[1] || "");
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    async onChange(ev) {
        const fileList = Array.from(ev.target.files || []);
        for (const file of fileList) {
            try {
                const data = await this._readAsBase64(file);
                this.state.files.push({ name: file.name, data });
            } catch {
                // 略過讀取失敗的單一檔案
            }
        }
        // 清掉 input 值，讓使用者可再次選取（含同名檔）
        ev.target.value = "";
        await this._save();
    }

    remove(index) {
        this.state.files.splice(index, 1);
        this._save();
    }

    clearAll() {
        this.state.files = [];
        this._save();
    }

    async _save() {
        await this.props.record.update({
            [this.props.name]: JSON.stringify(this.state.files),
        });
    }
}

export const bpmnMultiFileField = {
    component: BpmnMultiFileField,
    displayName: _t("多檔上傳"),
    supportedTypes: ["text"],
};

registry.category("fields").add("bpmn_multi_file", bpmnMultiFileField);
