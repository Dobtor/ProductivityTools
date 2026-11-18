/** @odoo-module **/

/**
 * Editable project/customer bar for the mind map editor.
 *
 * The MindmapEditor itself is an imperative (non-reactive) component that mounts
 * jsMind into a raw DOM ref, so we isolate all reactive UI (AutoComplete widgets)
 * inside this small self-contained child. Its internal state changes re-render ONLY
 * this component — never the parent — so the canvas is never disturbed.
 *
 * Mirrors the BPMN editor's project bar behaviour:
 *   - 客戶 (customer) editable via AutoComplete only when NO project is linked;
 *     when a project is linked the customer is read-only text ("（由專案帶入）").
 *   - 專案 (project) editable via AutoComplete; project search is narrowed to the
 *     chosen customer's projects (有選客戶時再選專案).
 *   - Selecting a project writes it and pulls the customer from that project
 *     (backend enforces partner = project's customer, empty clears it).
 * Create / sync / open-project stay as parent callbacks (they need to save the
 * whole mind map first); after those, the parent calls our exposed reload().
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";

export class MindmapProjectBar extends Component {
    static template = "dobtor_xmind.MindmapProjectBar";
    static components = { AutoComplete };
    static props = {
        workbookId: { type: [Number, Boolean], optional: true },
        onOpenProject: { type: Function, optional: true },
        onProjectChanged: { type: Function, optional: true },
        registerApi: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            partnerId: false,
            partnerName: "",
            projectId: false,
            projectName: "",
            embeds: [],
        });
        // Let the parent refresh us after it creates/syncs a project.
        if (this.props.registerApi) {
            this.props.registerApi({ reload: () => this.load() });
        }
        onWillStart(() => this.load());
    }

    get workbookId() {
        return this.props.workbookId || false;
    }

    async load() {
        if (!this.workbookId) {
            return;
        }
        try {
            const [rec] = await this.orm.read(
                "xmind.workbook",
                [this.workbookId],
                ["partner_id", "project_id"]
            );
            this.state.partnerId = (rec.partner_id && rec.partner_id[0]) || false;
            this.state.partnerName = (rec.partner_id && rec.partner_id[1]) || "";
            this.state.projectId = (rec.project_id && rec.project_id[0]) || false;
            this.state.projectName = (rec.project_id && rec.project_id[1]) || "";
        } catch (e) {
            // Non-fatal: leave the bar empty if the workbook can't be read.
        }
        try {
            const names = await this.orm.call("xmind.workbook", "get_embed_names", [
                [this.workbookId],
            ]);
            this.state.embeds = names || [];
        } catch (e) {
            this.state.embeds = [];
        }
    }

    get embedsLabel() {
        return (this.state.embeds || []).join("、");
    }

    // ===== 名稱搜尋來源 =====
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
                    // ★ 記錄 id 放在 resId：Odoo 18 AutoComplete.makeOption 會把 option.id 蓋成內部流水號，
                    //   讀 option.id 會寫入不相干的記錄（例：選 A 專案卻連到 id 恰好等於流水號的 B 專案）。
                    let options = results.map(([id, name]) => ({ label: name, resId: id }));
                    if (model === "project.project" && options.length) {
                        options = await this._markLinkedProjects(options);
                    }
                    return options;
                },
            },
        ];
    }

    /**
     * 一個專案只能連一張心智圖：已被其他心智圖連結的專案在下拉選單標出是哪一張，
     * 使用者選之前就知道（選了仍會由後端擋下並說明原因）。
     */
    async _markLinkedProjects(options) {
        let links = [];
        try {
            links = await this.orm.searchRead(
                "xmind.workbook",
                [
                    ["project_id", "in", options.map((o) => o.resId)],
                    ["id", "!=", this.workbookId],
                ],
                ["project_id", "name"],
                { context: { active_test: false } }
            );
        } catch (e) {
            return options;
        }
        const byProject = {};
        for (const wb of links) {
            byProject[wb.project_id[0]] = wb.name;
        }
        return options.map((o) =>
            byProject[o.resId]
                ? { ...o, label: _t("%(project)s (linked to mind map: %(map)s)", { project: o.label, map: byProject[o.resId] }) }
                : o
        );
    }

    /**
     * AutoComplete 的 placeholder 是**元件 prop**（運算式），不是 HTML 屬性 ——
     * Odoo 的翻譯抽取器不會看它，直接在模板裡寫字串等於永遠不可翻譯。
     * 走 getter 回傳 _t()，字串才會進 .po。
     */
    get partnerPlaceholder() {
        return _t("Search customers…");
    }

    get projectPlaceholder() {
        return _t("Search projects…");
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
            await this.orm.write("xmind.workbook", [this.workbookId], { [field]: value });
            return true;
        } catch (e) {
            // RPC 錯誤的 e.message 只是「Odoo Server Error」，真正的說明在 e.data.message。
            const msg = (e && e.data && e.data.message) || (e && e.message) || String(e);
            this.notification.add(_t("Update failed: %s", msg), { type: "danger" });
            return false;
        }
    }

    // 客戶只在「無專案」時可編輯（有專案時客戶由專案帶入且唯讀）。
    async onSelectPartner(option) {
        if (this.state.projectId) {
            return;
        }
        this.state.partnerId = option.resId;
        this.state.partnerName = option.label;
        await this._writeField("partner_id", option.resId);
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
        const prevId = this.state.projectId;
        const prevName = this.state.projectName;
        this.state.projectId = option.resId;
        this.state.projectName = option.label;
        if (!(await this._writeField("project_id", option.resId))) {
            // 寫入失敗（例如專案已連到別張心智圖）→ 畫面回到原本的專案，不要顯示成已連結。
            this.state.projectId = prevId;
            this.state.projectName = prevName;
            return;
        }
        const [proj] = await this.orm.read("project.project", [option.resId], ["display_name"]).catch(() => [null]);
        if (proj) {
            this.state.projectName = proj.display_name;
        }
        // 有專案 → 客戶＝專案客戶（後端已強制），讀回反映到畫面（專案無客戶則清空）。
        await this._refreshPartnerFromProject(option.resId);
        this._notifyParent();
    }

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
        this._notifyParent();
    }

    /** Keep the parent's projectInfo fresh (used by its sync warning / open guard). */
    _notifyParent() {
        if (this.props.onProjectChanged) {
            this.props.onProjectChanged(
                this.state.projectId
                    ? { id: this.state.projectId, name: this.state.projectName }
                    : null
            );
        }
    }

    onOpenProject() {
        this.props.onOpenProject && this.props.onOpenProject();
    }
}
