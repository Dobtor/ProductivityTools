/** @odoo-module */

import { Component, useRef, onWillUnmount, useState, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * 需求二/三/五：待辦「專案關聯」向右邏輯圖欄位小工具。
 *
 * 重用 vendored 的 window.OdooMindMap（logic_right 佈局）唯讀顯示 FK 關聯樹：
 * - 有 project → 專案為根，展開屬於該專案的 CRM/任務/… 紀錄
 * - 否則有 partner → 客戶為根，展開屬於該客戶的紀錄（需求五縮小 res 範圍）
 * 點節點 → 回填 res_model_id/res_id（等同建立待辦與該文件的關聯）。
 * 右上角工具列：縮放(+/−/適應視窗)、展開一層/收合一層、眼睛(顯示/隱藏各
 * res_name 底下「未完成」待辦)。節點 +/- 為原生個別展收。畫面自動 fit、
 * 視窗大小變動時重新 fit；佈局引擎確保節點不碰撞。
 */
export class ActivityRelationDiagramField extends Component {
    static template = "dobtor_mail_activity.ActivityRelationDiagram";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.containerRef = useRef("diagram");
        this.state = useState({
            loading: false,
            empty: false,
            level: 1,
            showActivities: false,
        });
        this.jm = null;
        this._maxDepth = 0;
        this._resizeObserver = null;
        this._resizeTimer = null;
        this._renderSeq = 0;

        // 相關欄位變動（project/partner/res）時重載邏輯圖
        useEffect(
            () => {
                this.renderTree();
                return () => this.destroyMap();
            },
            () => [this._depKey()]
        );
        onWillUnmount(() => this.destroyMap());
    }

    get record() {
        return this.props.record;
    }

    /** 眼睛鈕標題（用 getter 回 _t，讓翻譯抽取器可擷取；t-att-title 內字面字串不會被抽取）。 */
    get eyeTitle() {
        return this.state.showActivities
            ? _t("Collapse all to-dos")
            : _t("Expand all to-dos");
    }

    _depKey() {
        // 主要依 project/partner 決定是否重載。res_model/res_id 通常是本 widget 點
        // 節點回填的「輸出」，納入依賴會使點節點回填觸發 useEffect → 整張圖
        // teardown+重新 RPC，遺失展開/縮放狀態，故一般情形不納入。
        // 例外：「無專案且無客戶」時，res 是唯一決定樹根的「輸入」，若不納入，外部
        // （如改 target_ref）變更 res 後圖不會刷新 → 顯示 stale 舊根。此情形下樹極
        // 簡（僅該文件 + 待辦），teardown 重載成本低，故納入 res 以正確反映變更。
        const d = this.record.data;
        const proj = (d.project_id && d.project_id[0]) || false;
        const partner = (d.partner_id && d.partner_id[0]) || false;
        const key = [proj, partner];
        if (!proj && !partner) {
            key.push((d.res_model_id && d.res_model_id[0]) || false, d.res_id || false);
        }
        return key.join("|");
    }

    destroyMap() {
        // 卸下視窗大小監聽
        if (this._resizeObserver) {
            try {
                this._resizeObserver.disconnect();
            } catch (e) {
                // ignore
            }
            this._resizeObserver = null;
        }
        if (this._resizeTimer) {
            clearTimeout(this._resizeTimer);
            this._resizeTimer = null;
        }
        // 先讓渲染器移除自身掛在 document 上的 mousemove/mouseup 監聽（防洩漏），
        // 再清空容器。每次 FK 變更 re-render 都會 new 一個，未 destroy 會累積監聽。
        if (this.jm && typeof this.jm.destroy === "function") {
            try {
                this.jm.destroy();
            } catch (e) {
                // 渲染器已部分卸載時忽略
            }
        }
        if (this.containerRef.el) {
            this.containerRef.el.innerHTML = "";
        }
        this.jm = null;
    }

    /** 視窗/容器大小變動時，去抖後重新 fit（自動適應視窗大小）。 */
    _observeResize() {
        if (typeof ResizeObserver === "undefined" || !this.containerRef.el) {
            return;
        }
        this._resizeObserver = new ResizeObserver(() => {
            if (this._resizeTimer) {
                clearTimeout(this._resizeTimer);
            }
            this._resizeTimer = setTimeout(() => {
                if (!this.jm) {
                    return;
                }
                // 先 refresh 重量測（容器由 0→實寬時節點尺寸才正確），再 fit。
                if (this.jm.view && this.jm.view.refresh) {
                    this.jm.view.refresh();
                }
                if (typeof this.jm.fitToContainer === "function") {
                    this.jm.fitToContainer();
                }
            }, 120);
        });
        this._resizeObserver.observe(this.containerRef.el);
    }

    async renderTree() {
        // 序號防競態：若 await 期間依賴又變（觸發新一輪 renderTree），舊的這輪
        // 在 await 後直接中止，避免建立第二個 OdooMindMap 而洩漏其 document 監聽。
        const token = ++this._renderSeq;
        this.destroyMap();
        const d = this.record.data;
        const projectId = d.project_id ? d.project_id[0] : false;
        const partnerId = d.partner_id ? d.partner_id[0] : false;
        const resModel = d.res_model || false;
        const resId = d.res_id || false;

        if (!projectId && !partnerId && !(resModel && resId)) {
            this.state.empty = true;
            return;
        }

        this.state.loading = true;
        let tree;
        try {
            tree = await this.orm.call("mail.activity", "get_relation_tree", [
                projectId,
                partnerId,
                resModel,
                resId,
            ]);
        } catch (e) {
            if (token !== this._renderSeq) {
                return;
            }
            this.state.loading = false;
            this.notification.add(_t("Failed to load the relation diagram."), {
                type: "danger",
            });
            return;
        }
        if (token !== this._renderSeq) {
            return; // 已被較新的一輪取代
        }
        this.state.loading = false;

        const hasChildren =
            tree && tree.data && tree.data.children && tree.data.children.length;
        this.state.empty = !hasChildren;
        if (!this.containerRef.el || !hasChildren) {
            return;
        }
        if (typeof window.OdooMindMap === "undefined") {
            this.notification.add(_t("Diagram library is not loaded."), {
                type: "danger",
            });
            return;
        }

        this.jm = new window.OdooMindMap({
            container: this.containerRef.el,
            editable: false,
            view: { line_color: "#9aa4b2", line_width: 1, draggable: false },
            layout: { mode: "logic_right", hspace: 30, vspace: 8, pspace: 13 },
            shortcut: { enable: false },
        });
        this.jm.add_event_listener((type, data) => {
            // type 1 + 有 node 且無 evt(expand/collapse) → 節點選取
            if (type === 1 && data && data.node && data.evt === undefined) {
                this.onNodeSelect(data.node);
            }
        });
        // 預設展開 客戶→專案→res_name（結構節點的 expanded 旗標已設）；渲染完成
        // 後把「未完成待辦」下拉清單注入各記錄節點的 DOM，再 refresh 重量測 + fit。
        this.jm.show(tree, () => {
            this._injectTodoLists();
            if (this.jm && typeof this.jm.view?.refresh === "function") {
                this.jm.view.refresh();
            }
            if (this.jm && typeof this.jm.fitToContainer === "function") {
                this.jm.fitToContainer();
            }
        });
        this._computeMaxDepth();
        // 結構預設全展開（樹的 expanded 旗標已設）；level 起點設為最深，
        // 使「收合一層」由全展開往回收。待辦群組另由眼睛 icon 控制。
        this.state.level = this._maxDepth + 1;
        this.state.showActivities = false;
        this._observeResize();
    }

    _computeMaxDepth() {
        let max = 0;
        const nodes = this.jm && this.jm.mind ? this.jm.mind.nodes : {};
        for (const id in nodes) {
            max = Math.max(max, nodes[id]._depth || 0);
        }
        this._maxDepth = max;
    }

    /** 逐層套用展開：depth < level 的結構節點展開，其餘收合（root 恆展開）。
     * 待辦清單是節點內 DOM（非圖節點），不受逐層控制，由眼睛 icon 管理。 */
    _applyLevel(level) {
        if (!this.jm || !this.jm.mind) {
            return;
        }
        const nodes = this.jm.mind.nodes;
        for (const id in nodes) {
            const n = nodes[id];
            const expanded = n.isroot || (n._depth || 0) < level;
            n.expanded = expanded;
            if (n._expander) {
                n._expander.textContent = expanded ? "−" : "+";
            }
        }
        this.jm.view.refresh();
    }

    onExpandLevel() {
        this.state.level = Math.min(this.state.level + 1, this._maxDepth + 1);
        this._applyLevel(this.state.level);
    }

    onCollapseLevel() {
        this.state.level = Math.max(this.state.level - 1, 1);
        this._applyLevel(this.state.level);
    }

    // ===== 縮放（按鈕）=====
    onZoomIn() {
        if (this.jm && this.jm.zoomIn) {
            this.jm.zoomIn();
        }
    }

    onZoomOut() {
        if (this.jm && this.jm.zoomOut) {
            this.jm.zoomOut();
        }
    }

    /** 適應視窗：自動縮放/置中使全圖填滿容器。 */
    onZoomFit() {
        if (this.jm && this.jm.fitToContainer) {
            this.jm.fitToContainer();
        }
    }

    /** 眼睛 icon（總開關）：一次展開/收合所有節點內的待辦下拉清單。 */
    onToggleActivities() {
        if (!this.jm || !this.jm.mind) {
            return;
        }
        this.state.showActivities = !this.state.showActivities;
        this._setAllTodos(this.state.showActivities);
    }

    // ===== 節點內「未完成待辦」下拉清單（level-down/up）=====

    /** level-down（收合態，點了展開）/ level-up（展開態，點了收合）SVG。 */
    _levelIcon(open) {
        return open
            ? '<svg class="o_ard_ic" viewBox="0 0 16 16"><path d="M3 12 H10 V7" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10 4 l-2.4 3 h4.8 z" fill="currentColor"/></svg>'
            : '<svg class="o_ard_ic" viewBox="0 0 16 16"><path d="M3 4 H10 V9" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10 12 l-2.4 -3 h4.8 z" fill="currentColor"/></svg>';
    }

    /** 把每個帶 data.todos 的記錄節點，於其 DOM box 內注入切換鈕 + 隱藏清單。 */
    _injectTodoLists() {
        if (!this.jm || !this.jm.mind) {
            return;
        }
        const nodes = this.jm.mind.nodes;
        for (const id in nodes) {
            const n = nodes[id];
            const todos = n.data && n.data.todos;
            const el = n._el;
            if (!todos || !todos.length || !el || el.dataset.ardTodos === "1") {
                continue;
            }
            el.dataset.ardTodos = "1";
            n._todosOpen = false;
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "o_ard_todo_toggle";
            btn.innerHTML = this._levelIcon(false);
            btn.title = _t("Show open to-dos (%s)", todos.length);
            btn.addEventListener("click", (ev) => {
                ev.stopPropagation();
                this._toggleNodeTodos(n);
            });
            el.insertBefore(btn, el.firstChild);
            const list = this._buildTodoList(todos);
            el.appendChild(list);
            n._todoListEl = list;
            n._todoBtnEl = btn;
        }
    }

    _buildTodoList(todos) {
        const box = document.createElement("div");
        box.className = "o_ard_todos";
        box.style.display = "none";
        for (const t of todos) {
            const row = document.createElement("div");
            row.className = "o_ard_todo";
            const dot = document.createElement("span");
            dot.className = "o_ard_dot " + (t.severity || "ok");
            const txt = document.createElement("span");
            txt.className = "o_ard_todo_txt";
            txt.textContent = t.label || "";
            row.appendChild(dot);
            row.appendChild(txt);
            if (t.deadline) {
                const when = document.createElement("span");
                when.className = "o_ard_todo_when";
                when.textContent = t.deadline;
                row.appendChild(when);
            }
            row.addEventListener("click", (ev) => {
                ev.stopPropagation();
                this._openActivity(t.activity_id);
            });
            box.appendChild(row);
        }
        return box;
    }

    /** 單一節點展/收：切換清單顯示 → refresh 重量測（兄弟自動下移、不碰撞）。
     * 不強制 fit，避免展開單一節點就把整圖縮放/置中（跳動）；使用者可自行縮放/
     * 平移。總開關（眼睛）與視窗變動才會 fit。 */
    _toggleNodeTodos(n) {
        n._todosOpen = !n._todosOpen;
        if (n._todoListEl) {
            n._todoListEl.style.display = n._todosOpen ? "" : "none";
        }
        if (n._todoBtnEl) {
            n._todoBtnEl.innerHTML = this._levelIcon(n._todosOpen);
        }
        // 眼睛總開關狀態與實際 DOM 同步：全部開才顯示為「已展開」
        this._syncEyeState();
        if (this.jm.view && this.jm.view.refresh) {
            this.jm.view.refresh();
        }
    }

    /** 依實際各節點清單開合，同步眼睛 icon 的 state.showActivities。 */
    _syncEyeState() {
        if (!this.jm || !this.jm.mind) {
            return;
        }
        const nodes = this.jm.mind.nodes;
        let total = 0;
        let open = 0;
        for (const id in nodes) {
            const n = nodes[id];
            if (!n._todoListEl) {
                continue;
            }
            total += 1;
            if (n._todosOpen) {
                open += 1;
            }
        }
        this.state.showActivities = total > 0 && open === total;
    }

    /** 總開關：一次設定所有節點待辦清單的展/收。 */
    _setAllTodos(show) {
        const nodes = this.jm.mind.nodes;
        for (const id in nodes) {
            const n = nodes[id];
            if (!n._todoListEl) {
                continue;
            }
            n._todosOpen = show;
            n._todoListEl.style.display = show ? "" : "none";
            if (n._todoBtnEl) {
                n._todoBtnEl.innerHTML = this._levelIcon(show);
            }
        }
        if (this.jm.view && this.jm.view.refresh) {
            this.jm.view.refresh();
        }
        if (this.jm.fitToContainer) {
            this.jm.fitToContainer();
        }
    }

    _openActivity(activityId) {
        if (!activityId) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "mail.activity",
            res_id: activityId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    async onNodeSelect(nodeId) {
        const node = this.jm && this.jm.get_node(nodeId);
        if (!node || !node.data) {
            return;
        }
        if (!node.data.res_model || !node.data.res_id) {
            return; // 群組節點無 res，不可回填
        }
        const { res_model, res_id } = node.data;
        try {
            const models = await this.orm.searchRead(
                "ir.model",
                [["model", "=", res_model]],
                ["id", "name"],
                { limit: 1 }
            );
            if (!models.length) {
                return;
            }
            await this.record.update({
                res_model_id: [models[0].id, models[0].name],
                res_id: res_id,
            });
            this.notification.add(_t("Linked related document: %s", node.topic), {
                type: "success",
            });
        } catch (e) {
            this.notification.add(_t("Failed to link the selected document."), {
                type: "danger",
            });
        }
    }
}

export const activityRelationDiagramField = {
    component: ActivityRelationDiagramField,
    supportedTypes: ["boolean"],
    // 讓 widget 自足：不論 arch 是否列出這些欄位，皆抓取並在變動時反應。
    fieldDependencies: [
        { name: "project_id", type: "many2one" },
        { name: "partner_id", type: "many2one" },
        { name: "res_id", type: "integer" },
        { name: "res_model", type: "char" },
    ],
};

registry.category("fields").add("activity_relation_diagram", activityRelationDiagramField);
