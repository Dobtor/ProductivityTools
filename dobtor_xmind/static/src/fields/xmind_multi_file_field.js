/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, useState } from "@odoo/owl";

/**
 * xmind_multi_file — self-contained multi-file upload widget for dobtor_xmind.
 *
 * Uses a native <input type="file" multiple> so multi-selection works
 * regardless of the stock many2many_binary widget's deployed-version
 * behaviour. All selected files are read with FileReader into base64 and
 * stored as a JSON array [{name, data}] on a Text field; the import wizard
 * parses that JSON and batch-creates workbooks (no ir.attachment residue).
 */
export class XmindMultiFileField extends Component {
    static template = "dobtor_xmind.XmindMultiFileField";
    static props = { ...standardFieldProps };

    setup() {
        this.notification = useService("notification");
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
        // Track names already chosen (previously + within this selection) so
        // duplicate filenames are skipped rather than imported twice.
        const existing = new Set(this.state.files.map((f) => f.name));
        const skipped = [];
        for (const file of fileList) {
            if (existing.has(file.name)) {
                skipped.push(file.name);
                continue;
            }
            try {
                const data = await this._readAsBase64(file);
                this.state.files.push({ name: file.name, data });
                existing.add(file.name);
            } catch {
                // skip a single file that failed to read
            }
        }
        // Clear the input so the same file(s) can be re-selected
        ev.target.value = "";
        if (skipped.length) {
            this.notification.add(
                _t("Skipped duplicate file name(s): %s", skipped.join(", ")),
                { type: "warning" }
            );
        }
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

export const xmindMultiFileField = {
    component: XmindMultiFileField,
    displayName: _t("Multi-file Upload"),
    supportedTypes: ["text"],
};

registry.category("fields").add("xmind_multi_file", xmindMultiFileField);
