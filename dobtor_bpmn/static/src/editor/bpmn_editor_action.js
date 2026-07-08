/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { Pager } from "@web/core/pager/pager";
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

/**
 * BPMN/DMN 全螢幕視覺編輯器（client action，仿 dobtor_xmind 架構）。
 * - 不在 form notebook 內；由設計圖 form header 按鈕 / kanban 卡片開啟。
 * - 文件 metadata 留在 form/kanban；本元件只負責畫布。
 * - 透過 orm service 讀寫紀錄（尊重存取規則），存檔寫回 xml + svg。
 *
 * 兩種掛載方式：
 *  1) client action：props.action.params.diagram_id（可編輯，含工具列/屬性面板/專案列）。
 *  2) 唯讀嵌入（HTML 欄位 "/" 插入）：props.diagramId + props.readonly=true。唯讀時隱藏
 *     工具列/面板/專案列、畫布不可互動，僅忠實呈現圖面（同一 bpmn-js/dmn-js 管線）。
 */
export class BpmnEditorAction extends Component {
    static template = "dobtor_bpmn.BpmnEditorAction";
    static components = { AutoComplete, Pager };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.canvasRef = useRef("canvas");
        this.panelRef = useRef("panel");
        this.modeler = null;

        // 唯讀嵌入以 props.diagramId 帶入；client action 走 action.params.diagram_id。
        this.readonly = !!this.props.readonly;
        this.diagramId =
            this.props.diagramId ||
            (this.props.action &&
                this.props.action.params &&
                this.props.action.params.diagram_id) ||
            null;
        // 重整後 diagram_id 由 URL 取回會是字串（"5"），轉回 int 供 ORM 使用。
        if (this.diagramId) {
            this.diagramId = parseInt(this.diagramId, 10) || null;
        }

        this.state = useState({
            ready: false,
            libMissing: false,
            error: "",
            name: "",
            diagramType: "bpmn",
            dirty: false,
            saving: false,
            // 專案列（可編輯專案/客戶 + 顯示關聯物件）
            partnerId: false,
            partnerName: "",
            projectId: false,
            projectName: "",
            embedsLabel: "",
            // 標題後的多標籤欄位：[{id, name, color}]
            tags: [],
            // 右上角 pager（在所有可讀設計圖之間翻頁，write_date desc）
            pagerTotal: 0,
            pagerOffset: 0,
        });
        // pager 記錄清單（非 reactive；offset/total 進 state 驅動 Pager 重繪）
        this.pagerIds = [];

        onWillStart(async () => {
            if (!this.diagramId) {
                this.state.error = _t("缺少設計圖 ID。");
                return;
            }
            await this._loadRecord();
            if (!this.readonly) {
                await this._loadPager();
            }
        });

        onMounted(() => {
            // Persist diagram_id into the action's controller state so a browser
            // refresh reopens the SAME diagram. On refresh Odoo feeds the URL state
            // back as action.params, and action_service rebuilds the URL from this
            // controller state — so writing here (not a bare router.pushState, which
            // gets wiped) makes the id land in the URL and survive refresh.
            if (this.diagramId && !this.readonly && this.props.updateActionState) {
                this.props.updateActionState({ diagram_id: this.diagramId });
            }
            this._initModeler();
        });
        onWillUnmount(() => this._destroyModeler());
    }

    async _loadEmbeds() {
        try {
            const names = await this.orm.call("bpmn.diagram", "get_embed_names", [
                [this.diagramId],
            ]);
            this.state.embedsLabel = (names || []).join("、");
        } catch (e) {
            this.state.embedsLabel = "";
        }
    }

    // ===== 標題後的多標籤欄位（bpmn.diagram.tag，可搜尋新增/即時建立/移除）=====

    async _loadTags(tagIds) {
        if (!tagIds.length) {
            this.state.tags = [];
            return;
        }
        try {
            const recs = await this.orm.read("bpmn.diagram.tag", tagIds, ["name", "color"]);
            this.state.tags = recs.map((r) => ({ id: r.id, name: r.name, color: r.color || 0 }));
        } catch (e) {
            this.state.tags = [];
        }
    }

    get tagSources() {
        const selected = this.state.tags.map((t) => t.id);
        return [
            {
                options: async (request) => {
                    const term = (request || "").trim();
                    let results = [];
                    try {
                        results = await this.orm.call("bpmn.diagram.tag", "name_search", [], {
                            name: term,
                            args: [["id", "not in", selected]],
                            operator: "ilike",
                            limit: 8,
                        });
                    } catch (e) {
                        results = [];
                    }
                    const opts = results.map(([id, name]) => ({ label: name, id }));
                    // 無完全相符 → 提供即時建立新標籤選項。
                    const exact = results.some(
                        ([, n]) => (n || "").toLowerCase() === term.toLowerCase()
                    );
                    if (term && !exact) {
                        opts.push({ label: _t('建立「%s」', term), id: false, create: true, term });
                    }
                    return opts;
                },
            },
        ];
    }

    async onSelectTag(option) {
        try {
            let id = option.id;
            if (option.create) {
                const created = await this.orm.call("bpmn.diagram.tag", "name_create", [
                    option.term,
                ]);
                id = created && created[0];
            }
            if (!id) {
                return;
            }
            if (this.state.tags.some((t) => t.id === id)) {
                return; // 已存在，忽略
            }
            await this.orm.write("bpmn.diagram", [this.diagramId], { tag_ids: [[4, id]] });
            let name = option.label;
            let color = 0;
            try {
                const [t] = await this.orm.read("bpmn.diagram.tag", [id], ["name", "color"]);
                name = t.name;
                color = t.color || 0;
            } catch (e) {
                // 讀取顏色/名稱失敗不阻斷；沿用選項標籤。
            }
            this.state.tags.push({ id, name, color });
        } catch (e) {
            this.notification.add(_t("新增標籤失敗：%s", e?.message || e), { type: "danger" });
        }
    }

    async removeTag(tagId) {
        try {
            await this.orm.write("bpmn.diagram", [this.diagramId], { tag_ids: [[3, tagId]] });
            this.state.tags = this.state.tags.filter((t) => t.id !== tagId);
        } catch (e) {
            this.notification.add(_t("移除標籤失敗：%s", e?.message || e), { type: "danger" });
        }
    }

    async _initModeler() {
        if (this.state.libMissing || this.state.error) {
            return;
        }
        const Ctor = this.state.diagramType === "dmn" ? window.DmnJS : window.BpmnJS;
        if (!Ctor || !this.canvasRef.el) {
            this.state.libMissing = true;
            return;
        }
        try {
            const options = { container: this.canvasRef.el };
            // 唯讀嵌入不掛屬性面板（模板已移除 panel），此處 panelRef.el 為 null 自然略過。
            if (this.state.diagramType !== "dmn" && this.panelRef.el) {
                options.propertiesPanel = { parent: this.panelRef.el };
            }
            this.modeler = new Ctor(options);
            const xml = (this._record && this._record.xml) || "";
            if (xml) {
                await this.modeler.importXML(xml);
                try {
                    this.modeler.get("canvas").zoom("fit-viewport");
                } catch {
                    // DMN 多視圖或 canvas 未就緒，略過
                }
            }
            if (!this.readonly) {
                // 監聽變更以標記 dirty（唯讀不追蹤，畫布亦已 pointer-events:none）
                try {
                    this.modeler.on("commandStack.changed", () => {
                        this.state.dirty = true;
                    });
                } catch {
                    // 某些 dmn-js 視圖無 commandStack，略過
                }
            }
            this.state.ready = true;
        } catch (e) {
            this.state.error = e?.message || String(e);
        }
    }

    _destroyModeler() {
        if (this.modeler) {
            try {
                this.modeler.destroy();
            } catch {
                // 忽略
            }
            this.modeler = null;
        }
    }

    async onSave() {
        if (!this.modeler || this.state.saving || this.readonly) {
            return;
        }
        this.state.saving = true;
        try {
            const { xml } = await this.modeler.saveXML({ format: true });
            const changes = { xml };
            if (this.modeler.saveSVG) {
                try {
                    const { svg } = await this.modeler.saveSVG();
                    changes.svg = svg;
                } catch {
                    // saveSVG 不適用時略過
                }
            }
            await this.orm.write("bpmn.diagram", [this.diagramId], changes);
            this.state.dirty = false;
            this.notification.add(_t("已儲存。"), { type: "success" });
        } catch (e) {
            this.notification.add(_t("儲存失敗：%s", e?.message || e), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }

    async onNameChange(ev) {
        const newName = (ev.target.value || "").trim();
        if (!newName) {
            ev.target.value = this.state.name; // 不允許空名稱，還原
            return;
        }
        if (newName === this.state.name) {
            return;
        }
        this.state.name = newName;
        try {
            await this.orm.write("bpmn.diagram", [this.diagramId], { name: newName });
            this.notification.add(_t("名稱已更新。"), { type: "success" });
        } catch (e) {
            this.notification.add(_t("更新名稱失敗：%s", e?.message || e), {
                type: "danger",
            });
        }
    }

    // ===== 專案列：可編輯專案 / 客戶（AutoComplete 名稱搜尋 + 直接寫回）=====

    _nameSearchSource(model, domain = []) {
        return [
            {
                options: async (request) => {
                    const term = (request || "").trim();
                    let results = [];
                    try {
                        results = await this.orm.call(model, "name_search", [], {
                            name: term,
                            args: domain,
                            operator: "ilike",
                            limit: 8,
                        });
                    } catch (e) {
                        results = [];
                    }
                    return results.map(([id, name]) => ({ label: name, id }));
                },
            },
        ];
    }

    get partnerSources() {
        return this._nameSearchSource("res.partner");
    }

    get projectSources() {
        // 有選客戶時再選專案 → 專案清單限縮為該客戶的專案。
        const domain = this.state.partnerId
            ? [["partner_id", "=", this.state.partnerId]]
            : [];
        return this._nameSearchSource("project.project", domain);
    }

    async _writeField(field, value) {
        try {
            await this.orm.write("bpmn.diagram", [this.diagramId], { [field]: value });
        } catch (e) {
            this.notification.add(_t("更新失敗：%s", e?.message || e), { type: "danger" });
        }
    }

    // 客戶只在「無專案」時可編輯（有專案時客戶由專案帶入且唯讀）。
    async onSelectPartner(option) {
        if (this.state.projectId) {
            return;
        }
        this.state.partnerId = option.id;
        this.state.partnerName = option.label;
        await this._writeField("partner_id", option.id);
    }

    async clearPartner() {
        if (this.state.projectId) {
            return;
        }
        this.state.partnerId = false;
        this.state.partnerName = "";
        await this._writeField("partner_id", false);
    }

    async onSelectProject(option) {
        this.state.projectId = option.id;
        this.state.projectName = option.label;
        await this._writeField("project_id", option.id);
        // 有專案 → 客戶＝專案客戶（後端已強制），讀回反映到畫面（專案無客戶則清空）。
        await this._refreshPartnerFromProject(option.id);
    }

    /** 從專案帶出客戶到本地狀態（顯示用；資料庫值由後端 write 強制一致）。 */
    async _refreshPartnerFromProject(projectId) {
        try {
            const [proj] = await this.orm.read("project.project", [projectId], ["partner_id"]);
            const p = proj && proj.partner_id;
            this.state.partnerId = (p && p[0]) || false;
            this.state.partnerName = (p && p[1]) || "";
        } catch (e) {
            // 讀取失敗不阻斷；資料庫值仍由後端保持一致。
        }
    }

    async clearProject() {
        // 清除專案不動客戶（保留現值，回到可自由編輯）。
        this.state.projectId = false;
        this.state.projectName = "";
        await this._writeField("project_id", false);
    }

    /** Breadcrumb gear: open this diagram's form view (customer/project/state/…). */
    onOpenForm() {
        if (!this.diagramId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bpmn.diagram",
            res_id: this.diagramId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** Breadcrumb text / switcher list button: back to the diagram list view (with
     *  its search panel & filters). viewType forces the list over the action's
     *  default kanban. */
    onOpenList() {
        this.action.doAction("dobtor_bpmn.action_bpmn_diagram", { viewType: "list" });
    }

    // ===== 記錄載入 / 右上角 pager（在可讀設計圖之間翻頁）=====

    /** Read this.diagramId into state (name/type/xml/專案/客戶/標籤/嵌入). Reusable by
     *  onWillStart and pager navigation. */
    async _loadRecord() {
        const fields = ["name", "diagram_type", "xml"];
        if (!this.readonly) {
            fields.push("partner_id", "project_id", "tag_ids");
        }
        const [rec] = await this.orm.read("bpmn.diagram", [this.diagramId], fields);
        if (!rec) {
            // 翻頁到已被刪除 / 失去權限的設計圖：優雅呈現，勿讓 undefined 拋錯。
            this.state.error = _t("找不到設計圖（可能已被刪除或無存取權限）。");
            return;
        }
        this._record = rec;
        this.state.name = rec.name || "";
        this.state.diagramType = rec.diagram_type || "bpmn";
        if (!this.readonly) {
            this.state.partnerId = (rec.partner_id && rec.partner_id[0]) || false;
            this.state.partnerName = (rec.partner_id && rec.partner_id[1]) || "";
            this.state.projectId = (rec.project_id && rec.project_id[0]) || false;
            this.state.projectName = (rec.project_id && rec.project_id[1]) || "";
            await this._loadTags(rec.tag_ids || []);
            await this._loadEmbeds();
        }
        // bpmn-js / dmn-js 皆已隨 dobtor_approval 打包（bundled），不需 runtime load。
        this.state.libMissing = this.state.diagramType === "dmn"
            ? !window.DmnJS
            : !window.BpmnJS;
    }

    /** Fetch the id set the pager walks: all readable diagrams, newest-edited first. */
    async _loadPager() {
        try {
            this.pagerIds = await this.orm.search("bpmn.diagram", [], {
                order: "write_date desc",
            });
        } catch {
            this.pagerIds = [];
        }
        this._syncPagerOffset();
    }

    _syncPagerOffset() {
        const idx = this.pagerIds.indexOf(this.diagramId);
        this.state.pagerTotal = this.pagerIds.length;
        this.state.pagerOffset = idx >= 0 ? idx : 0;
    }

    /** Pager onUpdate → open the diagram at the new 0-based offset (limit=1). */
    onPagerUpdate({ offset }) {
        const newId = this.pagerIds[offset];
        if (newId) {
            this._navigateToRecord(newId);
        }
    }

    /** Switch the editor to another diagram in place (no full action re-dispatch):
     *  teardown modeler → swap id → sync URL → reload record → re-init modeler. */
    async _navigateToRecord(newId) {
        if (!newId || newId === this.diagramId || this.readonly) {
            return;
        }
        if (this.state.dirty &&
            !window.confirm(_t("有未儲存的變更，切換將捨棄。是否繼續？"))) {
            return;
        }
        this._destroyModeler();
        this.diagramId = newId;
        this.state.dirty = false;
        this.state.ready = false;
        this.state.error = "";
        if (this.props.updateActionState) {
            this.props.updateActionState({ diagram_id: newId });
        }
        await this._loadRecord();
        this._syncPagerOffset();
        this._initModeler();
    }
}

registry.category("actions").add("dobtor_bpmn.bpmn_editor", BpmnEditorAction);
