/** @odoo-module **/

/**
 * "Insert mind map" picker dialog.
 *
 * Opened by the "/" power-box command "插入心智圖". Lists existing xmind.workbook
 * records (with a keyword filter) so the user can pick one to embed live into the
 * current HTML field. Pure selection UI — the caller (plugin) inserts the block.
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class XmindPickerDialog extends Component {
    static template = "dobtor_xmind.PickerDialog";
    static components = { Dialog };
    static props = {
        close: { type: Function },
        onSelect: { type: Function },
    };

    static LIMIT = 40;

    setup() {
        this.orm = useService("orm");
        this.title = _t("Insert a Mind Map");
        this.state = useState({ workbooks: [], loading: true, search: "" });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const domain = [];
        const term = (this.state.search || "").trim();
        if (term) {
            domain.push(["name", "ilike", term]);
        }
        try {
            const records = await this.orm.searchRead(
                "xmind.workbook",
                domain,
                ["id", "name", "partner_id", "project_id"],
                { limit: XmindPickerDialog.LIMIT, order: "write_date desc" }
            );
            this.state.workbooks = records;
        } catch (e) {
            this.state.workbooks = [];
        } finally {
            this.state.loading = false;
        }
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.load();
    }

    subtitle(wb) {
        const parts = [];
        if (wb.partner_id) {
            parts.push(wb.partner_id[1]);
        }
        if (wb.project_id) {
            parts.push(wb.project_id[1]);
        }
        return parts.join(" · ");
    }

    onSelect(wb) {
        this.props.onSelect(wb.id);
        this.props.close();
    }
}
