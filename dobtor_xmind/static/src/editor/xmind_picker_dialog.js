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
import { orderSheets, depthPrefix } from "@dobtor_xmind/js/mindmap_sheet_tree";

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
        // 第二步：選分頁（預設主圖）。只有一張分頁時直接插入。
        this.state = useState({ workbooks: [], loading: true, search: "",
                                picked: null, sheets: [], sheetId: false });
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

    async onSelect(wb) {
        let sheets = [];
        try {
            sheets = await this.orm.searchRead("xmind.sheet", [["workbook_id", "=", wb.id]],
                ["id", "name", "sequence", "sheet_role", "parent_sheet_id"]);
        } catch {
            sheets = [];
        }
        sheets = orderSheets(sheets.map((s) => ({
            ...s, parent_sheet_id: s.parent_sheet_id && s.parent_sheet_id[0] })));
        if (sheets.length <= 1) {
            this.props.onSelect(wb.id, false);
            this.props.close();
            return;
        }
        const main = sheets.find((s) => s.sheet_role === "main") || sheets[0];
        Object.assign(this.state, { picked: wb, sheets, sheetId: main.id });
    }

    sheetLabel(sheet) {
        return depthPrefix(sheet.depth || 0) + sheet.name;
    }

    get sheetStepLabel() {
        return _t("Sheet to show");
    }

    onSheetSelect(ev) {
        this.state.sheetId = parseInt(ev.target.value, 10) || false;
    }

    onBack() {
        Object.assign(this.state, { picked: null, sheets: [], sheetId: false });
    }

    onInsertSheet() {
        const main = this.state.sheets.find((s) => s.sheet_role === "main");
        // 選主圖就不寫死分頁 id：主圖之後換了，嵌入也跟著顯示新的主圖
        const sheetId = main && main.id === this.state.sheetId ? false : this.state.sheetId;
        this.props.onSelect(this.state.picked.id, sheetId);
        this.props.close();
    }
}
