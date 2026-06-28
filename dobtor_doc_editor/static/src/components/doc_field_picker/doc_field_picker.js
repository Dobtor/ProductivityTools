/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

/**
 * DocFieldPickerDialog — OWL Dialog 欄位選擇器。
 * 從 Powerbox 觸發，顯示目前文件可用的 Odoo 欄位，選取後插入游標位置。
 */
export class DocFieldPickerDialog extends Component {
    static template = "dobtor_doc_editor.DocFieldPickerDialog";
    static components = { Dialog };
    static props = {
        modelName: { type: String, optional: true },
        docId: { type: Number, optional: true },
        onInsert: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.state = useState({
            fields: [],
            loading: true,
            error: null,
            search: "",
            expanded: new Set(),
        });

        onWillStart(async () => {
            await this._loadFields();
        });
    }

    async _loadFields() {
        if (!this.props.modelName) {
            this.state.loading = false;
            this.state.error = _t("此文件未設定目標 Model，無法列出欄位。");
            return;
        }
        try {
            const fields = await rpc("/dobtor_doc/fields", {
                model_name: this.props.modelName,
                doc_id: this.props.docId || null,
            });
            this.state.fields = fields;
        } catch (e) {
            this.state.error = e.message || _t("載入欄位失敗");
        } finally {
            this.state.loading = false;
        }
    }

    get filteredFields() {
        const q = this.state.search.trim().toLowerCase();
        if (!q) return this.state.fields;
        return this.state.fields.filter(f =>
            f.name.toLowerCase().includes(q) ||
            (f.label || "").toLowerCase().includes(q)
        );
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    toggleExpand(fieldName) {
        if (this.state.expanded.has(fieldName)) {
            this.state.expanded.delete(fieldName);
        } else {
            this.state.expanded.add(fieldName);
        }
        // 觸發重新渲染
        this.state.expanded = new Set(this.state.expanded);
    }

    insertField(expression, label, fieldInfo) {
        // 第三個參數 fieldInfo 對新 caller 提供完整欄位資訊（含中文 label/type/relation）。
        // 既有 caller 只看前兩個參數，向下相容。
        this.props.onInsert(expression, label, fieldInfo);
        this.props.close();
    }

    insertSubField(parentField, sub) {
        const expr = `{{ object.${parentField.name}.${sub.name} }}`;
        const label = `${parentField.name}.${sub.name}`;
        // 子欄位 fieldInfo 帶上父欄位中文 label 串接，便於 alias token 使用
        const fieldInfo = {
            ...sub,
            path: label,
            displayLabel: `${parentField.label}-${sub.label || sub.name}`,
        };
        this.insertField(expr, label, fieldInfo);
    }
}
