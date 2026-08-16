/** @odoo-module **/

/**
 * 關聯邏輯圖：節點內「未完成待辦」下拉清單的 DOM 覆蓋層。
 *
 * 為什麼是手刻 DOM 而非 OWL 子元件：清單必須插進 vendored 渲染器
 * （window.OdooMindMap）自己產生的節點 box 內，那些 box 不在 OWL 的控制範圍，
 * 無法以 t-component 掛載。
 *
 * 既然逃不掉手刻，就把它整個關進這個類別，好處是：
 *   - 所有 addEventListener 都登記在 _listeners，dispose() 一次移除，
 *     不再依賴「容器 innerHTML 被清空 → 監聽隨節點被 GC」這種間接保證；
 *   - 開合狀態集中在此，欄位元件只需要呼叫 toggleAll() / dispose()；
 *   - 邏輯圖欄位本體回到純 OWL，只剩渲染與工具列。
 */
import { _t } from "@web/core/l10n/translation";

/** level-down（收合態，點了展開）/ level-up（展開態，點了收合）SVG。 */
function levelIcon(open) {
    return open
        ? '<svg class="o_ard_ic" viewBox="0 0 16 16"><path d="M3 12 H10 V7" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10 4 l-2.4 3 h4.8 z" fill="currentColor"/></svg>'
        : '<svg class="o_ard_ic" viewBox="0 0 16 16"><path d="M3 4 H10 V9" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10 12 l-2.4 -3 h4.8 z" fill="currentColor"/></svg>';
}

export class RelationDiagramTodoOverlay {
    /**
     * @param {object} options
     * @param {() => object} options.getMindMap 取得目前的 OdooMindMap 實例
     * @param {(activityId: number) => void} options.onOpenActivity 點待辦列的回呼
     * @param {(allOpen: boolean) => void} options.onStateChange 開合狀態變動回呼
     */
    constructor({ getMindMap, onOpenActivity, onStateChange }) {
        this.getMindMap = getMindMap;
        this.onOpenActivity = onOpenActivity;
        this.onStateChange = onStateChange;
        /** @type {Array<[EventTarget, string, Function]>} */
        this._listeners = [];
        /** @type {Map<string, {node: object, list: HTMLElement, btn: HTMLElement, open: boolean}>} */
        this._entries = new Map();
    }

    /** 集中登記監聽，供 dispose() 一次移除。 */
    _on(target, type, handler) {
        target.addEventListener(type, handler);
        this._listeners.push([target, type, handler]);
    }

    _nodes() {
        const jm = this.getMindMap();
        return jm && jm.mind ? jm.mind.nodes : {};
    }

    _refresh() {
        const jm = this.getMindMap();
        if (jm && jm.view && jm.view.refresh) {
            jm.view.refresh();
        }
    }

    /** 把每個帶 data.todos 的記錄節點，於其 DOM box 內注入切換鈕 + 隱藏清單。 */
    inject() {
        const nodes = this._nodes();
        for (const id in nodes) {
            const node = nodes[id];
            const todos = node.data && node.data.todos;
            const el = node._el;
            if (!todos || !todos.length || !el || this._entries.has(id)) {
                continue;
            }
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "o_ard_todo_toggle";
            btn.innerHTML = levelIcon(false);
            btn.title = _t("Show open to-dos (%s)", todos.length);
            this._on(btn, "click", (ev) => {
                ev.stopPropagation();
                this.toggle(id);
            });
            el.insertBefore(btn, el.firstChild);

            const list = this._buildList(todos);
            el.appendChild(list);
            this._entries.set(id, { node, list, btn, open: false });
        }
    }

    _buildList(todos) {
        const box = document.createElement("div");
        box.className = "o_ard_todos";
        box.style.display = "none";
        for (const todo of todos) {
            const row = document.createElement("div");
            row.className = "o_ard_todo";

            const dot = document.createElement("span");
            dot.className = "o_ard_dot " + (todo.severity || "ok");
            row.appendChild(dot);

            const txt = document.createElement("span");
            txt.className = "o_ard_todo_txt";
            txt.textContent = todo.label || "";
            row.appendChild(txt);

            if (todo.deadline) {
                const when = document.createElement("span");
                when.className = "o_ard_todo_when";
                when.textContent = todo.deadline;
                row.appendChild(when);
            }

            this._on(row, "click", (ev) => {
                ev.stopPropagation();
                this.onOpenActivity(todo.activity_id);
            });
            box.appendChild(row);
        }
        return box;
    }

    /**
     * 單一節點展/收。不強制 fit —— 展開單一節點就把整圖縮放/置中會造成跳動；
     * 使用者可自行縮放平移，只有總開關與視窗變動才 fit。
     */
    toggle(id) {
        const entry = this._entries.get(id);
        if (!entry) {
            return;
        }
        entry.open = !entry.open;
        entry.list.style.display = entry.open ? "" : "none";
        entry.btn.innerHTML = levelIcon(entry.open);
        this._notifyState();
        this._refresh();
    }

    /** 總開關：一次設定所有節點清單的展/收。 */
    toggleAll(show) {
        for (const entry of this._entries.values()) {
            entry.open = show;
            entry.list.style.display = show ? "" : "none";
            entry.btn.innerHTML = levelIcon(show);
        }
        this._notifyState();
        this._refresh();
    }

    /** 全部展開才回報「已展開」，讓眼睛 icon 與實際 DOM 一致。 */
    _notifyState() {
        const total = this._entries.size;
        let open = 0;
        for (const entry of this._entries.values()) {
            if (entry.open) {
                open += 1;
            }
        }
        this.onStateChange(total > 0 && open === total);
    }

    /** 移除所有監聽與內部參照。DOM 節點本身由圖表容器清空時一併消失。 */
    dispose() {
        for (const [target, type, handler] of this._listeners) {
            target.removeEventListener(type, handler);
        }
        this._listeners = [];
        this._entries.clear();
    }
}
