/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * 輕量公司 autocomplete：輸入文字 → name_search 既有公司（is_company=True）；
 * 可選既有，或以輸入文字直接新增。選定後呼叫 props.onSelect(idOrName)。
 *   - 既有：onSelect(<int id>)
 *   - 新增：onSelect(<string name>)
 */
export class CompanyAutocomplete extends Component {
    static template = "dobtor_messaging_base.CompanyAutocomplete";
    static props = {
        onSelect: { type: Function },
        placeholder: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ query: "", results: [], open: false, loading: false });
    }

    get placeholder() {
        return this.props.placeholder || _t("Add a company…");
    }

    async onInput(ev) {
        const query = ev.target.value;
        this.state.query = query;
        if (!query.trim()) {
            this.state.results = [];
            this.state.open = false;
            return;
        }
        this.state.loading = true;
        try {
            const res = await this.orm.call("res.partner", "name_search", [], {
                name: query,
                args: [["is_company", "=", true]],
                limit: 8,
            });
            this.state.results = res.map(([id, name]) => ({ id, name }));
        } catch {
            this.state.results = [];
        }
        this.state.loading = false;
        this.state.open = true;
    }

    onFocus() {
        if (this.state.query.trim()) {
            this.state.open = true;
        }
    }

    onBlur() {
        // 延遲關閉，讓 mousedown 選項先觸發
        setTimeout(() => (this.state.open = false), 150);
    }

    get canCreate() {
        const q = this.state.query.trim();
        if (!q) {
            return false;
        }
        return !this.state.results.some(
            (r) => (r.name || "").toLowerCase() === q.toLowerCase()
        );
    }

    pick(company) {
        this.props.onSelect(company.id);
        this._reset();
    }

    create() {
        const name = this.state.query.trim();
        if (name) {
            this.props.onSelect(name);
        }
        this._reset();
    }

    _reset() {
        this.state.query = "";
        this.state.results = [];
        this.state.open = false;
    }
}
