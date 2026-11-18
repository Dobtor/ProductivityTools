/** @odoo-module **/

/**
 * 子心智圖相關的對話框：
 *  - SubSheetCreateDialog：「建立子心智圖」—— 每顆選取的主題一列（可改分頁名、
 *    可取消勾選），模式 延伸／拆出，新分頁版面。
 *  - SheetTopicPickerDialog：挑「分頁 ＋ 主題」—— 「移到分頁…」（目標分頁＋
 *    父主題，預設中心主題）與分頁右鍵「掛到主題…」（只列主圖／子圖的主題）共用。
 *
 * 純選擇 UI：真正的伺服器呼叫由編輯器在 onConfirm 裡做（它負責先存檔、
 * 之後重新載入分頁與清掉復原堆疊）。
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { depthPrefix } from "@dobtor_xmind/js/mindmap_sheet_tree";

export function getSubSheetLayouts() {
    return [
        { id: "logic_right", name: _t("Logic Chart (Right)") },
        { id: "map", name: _t("Mind Map") },
        { id: "tree_right", name: _t("Tree Chart (Right)") },
        { id: "org_chart_down", name: _t("Org Chart (Down)") },
        { id: "timeline_horizontal", name: _t("Timeline - Horizontal") },
        { id: "fishbone_left", name: _t("Fishbone (Head Right)") },
    ];
}

export class SubSheetCreateDialog extends Component {
    static template = "dobtor_xmind.SubSheetCreateDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        /** [{ key, title, hasChildren, existing: {id, name} | null }] */
        topics: { type: Array },
        /** ({ mode, layout, rows: [{key, name, existing}] }) => void */
        onConfirm: { type: Function },
    };

    setup() {
        this.title = _t("Create Sub Mind Map");
        this.layouts = getSubSheetLayouts();
        this.state = useState({
            rows: this.props.topics.map((t) => ({
                key: t.key,
                title: t.title,
                name: t.title,
                checked: true,
                hasChildren: !!t.hasChildren,
                existing: t.existing || null,
            })),
            mode: "extend",
            layout: "logic_right",
        });
    }

    existingLabel(row) {
        return _t("Already has the sheet “%s”, it will be opened", row.existing.name);
    }

    /** 「拆出」只有在至少一顆（要新建的）主題有子主題時才有意義。 */
    get canSplit() {
        return this.state.rows.some((r) => r.checked && !r.existing && r.hasChildren);
    }

    get canConfirm() {
        return this.state.rows.some((r) => r.checked);
    }

    get confirmLabel() {
        return this.state.rows.some((r) => r.checked && !r.existing) ? _t("Create") : _t("Open");
    }

    onConfirm() {
        const rows = this.state.rows.filter((r) => r.checked);
        if (!rows.length) {
            return;
        }
        this.props.onConfirm({
            mode: this.canSplit ? this.state.mode : "extend",
            layout: this.state.layout,
            rows: rows.map((r) => ({ key: r.key, name: (r.name || "").trim() || r.title,
                                     existing: r.existing })),
        });
        this.props.close();
    }
}

export class SheetTopicPickerDialog extends Component {
    static template = "dobtor_xmind.SheetTopicPickerDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        title: { type: String },
        /** 已排序的分頁（orderSheets 的結果） */
        sheets: { type: Array },
        defaultSheetId: { type: [Number, Boolean], optional: true },
        /** 'move'：可選父主題，預設中心主題；'attach'：必須選一顆非中心主題 */
        mode: { type: String },
        /** (sheetId) => Promise<[{id, title, depth, component_id}]>（已排成樹狀） */
        loadTopics: { type: Function },
        /** 不可選的主題 component_id（例如正在搬移的子樹） */
        disabledKeys: { type: Array, optional: true },
        help: { type: String, optional: true },
        confirmLabel: { type: String, optional: true },
        /** ({ sheetId, topicId }) => void；topicId 為 false 代表中心主題 */
        onConfirm: { type: Function },
    };

    setup() {
        const first = this.props.defaultSheetId || (this.props.sheets[0] && this.props.sheets[0].id);
        this.state = useState({ sheetId: first || false, topics: [], topicId: false, loading: true });
        onWillStart(() => this.loadTopics());
    }

    sheetLabel(sheet) {
        return depthPrefix(sheet.depth || 0) + sheet.name;
    }

    topicIndent(topic) {
        return "padding-left: " + (8 + 16 * (topic.depth || 0)) + "px";
    }

    isDisabled(topic) {
        if (this.props.mode === "attach" && !topic.depth) {
            return true;   // 中心主題不能當錨點
        }
        return (this.props.disabledKeys || []).includes(topic.component_id);
    }

    async loadTopics() {
        this.state.loading = true;
        this.state.topicId = false;
        try {
            this.state.topics = this.state.sheetId
                ? await this.props.loadTopics(this.state.sheetId)
                : [];
        } finally {
            this.state.loading = false;
        }
    }

    onSheetChange(ev) {
        this.state.sheetId = parseInt(ev.target.value, 10) || false;
        this.loadTopics();
    }

    selectTopic(topic) {
        if (!this.isDisabled(topic)) {
            this.state.topicId = topic.id;
        }
    }

    isSelected(topic) {
        if (this.state.topicId) {
            return this.state.topicId === topic.id;
        }
        return this.props.mode === "move" && !topic.depth;
    }

    get canConfirm() {
        if (!this.state.sheetId || this.state.loading) {
            return false;
        }
        return this.props.mode === "move" || !!this.state.topicId;
    }

    get confirmText() {
        return this.props.confirmLabel || _t("Confirm");
    }

    get emptyLabel() {
        return _t("This sheet has no topic.");
    }

    onConfirm() {
        if (!this.canConfirm) {
            return;
        }
        this.props.onConfirm({ sheetId: this.state.sheetId, topicId: this.state.topicId || false });
        this.props.close();
    }
}
