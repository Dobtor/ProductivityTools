/** @odoo-module **/

/**
 * "Insert diagram" picker dialog.
 *
 * Opened by the "/" power-box command "插入流程設計圖". Lists existing
 * bpmn.diagram records (with a keyword filter) so the user can pick one to embed
 * live into the current HTML field. Pure selection UI — the caller (plugin)
 * inserts the block.
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class BpmnPickerDialog extends Component {
    static template = "dobtor_bpmn.PickerDialog";
    static components = { Dialog };
    static props = {
        close: { type: Function },
        onSelect: { type: Function },
    };

    static LIMIT = 40;

    setup() {
        this.orm = useService("orm");
        this.title = _t("插入流程設計圖");
        this.state = useState({ diagrams: [], loading: true, search: "" });
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
                "bpmn.diagram",
                domain,
                ["id", "name", "diagram_type", "partner_id", "project_id"],
                { limit: BpmnPickerDialog.LIMIT, order: "write_date desc" }
            );
            this.state.diagrams = records;
        } catch (e) {
            this.state.diagrams = [];
        } finally {
            this.state.loading = false;
        }
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.load();
    }

    subtitle(d) {
        const parts = [];
        if (d.partner_id) {
            parts.push(d.partner_id[1]);
        }
        if (d.project_id) {
            parts.push(d.project_id[1]);
        }
        return parts.join(" · ");
    }

    icon(d) {
        return d.diagram_type === "dmn" ? "fa-table" : "fa-sitemap";
    }

    onSelect(d) {
        this.props.onSelect(d.id);
        this.props.close();
    }
}
