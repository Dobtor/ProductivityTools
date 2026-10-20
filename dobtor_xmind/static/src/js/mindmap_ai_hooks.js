/** @odoo-module **/

/**
 * 編輯器的「外部預覽／重載」掛鉤所需的純邏輯。
 *
 * ★ 本檔**零 import**（不碰 OWL、不碰 jsMind 全域）：這樣才能在沒有瀏覽器的環境用
 *   node 直接測。需要 DOM／jsMind 的部分一律透過建構子傳進來的 `jm` 物件。
 * ★ 本模組不知道「誰」會呼叫它 —— 編輯器只是把自己登記到
 *   `registry.category("dobtor_xmind.bridge")`，外部元件（例如 AI 助理面板）想用就來取。
 *
 * 預覽的鐵律（任何一條破了，預覽就會變成「偷偷改了使用者的圖」）：
 *   1. 預覽節點只存在於畫面：一律帶 `data._aiPreview`，**不進 commandStack**。
 *   2. 預覽節點**不得被序列化進存檔**：編輯器存檔前先 `exit()`，並再用
 *      `stripPreviewNodes()` 過濾一次；後端 `_upsert_jsmind_node` 還有第三道。
 *   3. 預覽期間 jsMind 的事件一律忽略（`add_node` 會發出和「選取」同型的事件，
 *      不擋的話側邊欄會彈出來、`selectedNode` 會指到暫時節點）。
 *   4. `exit()` 之後畫面必須回到進入前的樣子（含收合／展開狀態）。
 */

export const PREVIEW_FLAG = "_aiPreview";
const ID_PREFIX = "ai_preview__";

/** 預覽節點在畫布上的 id。加前綴是為了不可能與真節點（uuid／node_…）撞號。 */
export function previewId(tempId) {
    return ID_PREFIX + String(tempId);
}

export function isPreviewNode(node) {
    return !!(node && node.data && node.data[PREVIEW_FLAG]);
}

/**
 * 從 jm.get_data('node_tree') 的樹裡拿掉所有預覽節點（連同子孫）。
 * 不修改輸入；回傳新的樹（節點物件淺拷貝，`data` 共用）。
 */
export function stripPreviewNodes(tree) {
    if (!tree || typeof tree !== "object") {
        return tree;
    }
    const walk = (node) => {
        const out = { ...node };
        if (Array.isArray(node.children)) {
            out.children = node.children.filter((c) => !isPreviewNode(c)).map(walk);
        }
        return out;
    };
    return { ...tree, data: tree.data ? walk(tree.data) : tree.data };
}

/** 樹中是否還有預覽節點（給測試與存檔守衛用）。 */
export function hasPreviewNodes(tree) {
    const walk = (node) =>
        isPreviewNode(node) || (node.children || []).some((c) => walk(c));
    return !!(tree && tree.data && walk(tree.data));
}

/**
 * 把一串 ops 轉成預覽動作。純函式：不碰畫布。
 *
 * @param {Array} ops  提案的 ops（已由後端驗證過；這裡仍只信任到「能畫」的程度）
 * @param {(id:string)=>boolean} exists  真節點是否存在於目前畫布
 * @returns {{actions:Array, skipped:Array}}
 */
export function planPreview(ops, exists) {
    const actions = [];
    const skipped = [];
    const temps = new Set();
    const resolve = (id) => (temps.has(id) ? previewId(id) : id);
    (ops || []).forEach((op, index) => {
        const kind = op && op.op;
        if (kind === "add") {
            const parent = resolve(op.parent_id);
            if (!temps.has(op.parent_id) && !exists(op.parent_id)) {
                skipped.push({ index, reason: "parent_missing" });
                return;
            }
            const temp = op.temp_id || `auto_${index}`;
            temps.add(temp);
            actions.push({
                type: "add", id: previewId(temp), parent, title: String(op.title || ""),
                index: Number.isInteger(op.index) ? op.index : null,
            });
        } else if (kind === "rename" || kind === "set_note") {
            if (!exists(op.id)) {
                skipped.push({ index, reason: "node_missing" });
                return;
            }
            actions.push({
                type: kind === "rename" ? "rename" : "note", id: op.id,
                text: String(kind === "rename" ? op.title || "" : op.note || ""),
            });
        } else if (kind === "move") {
            const parent = resolve(op.new_parent_id);
            if (!exists(op.id) || (!temps.has(op.new_parent_id) && !exists(op.new_parent_id))) {
                skipped.push({ index, reason: "node_missing" });
                return;
            }
            actions.push({
                type: "move", id: op.id, ghost: previewId(`move_${index}_${op.id}`), parent,
                index: Number.isInteger(op.index) ? op.index : null,
            });
        } else {
            skipped.push({ index, reason: "unsupported_op" });
        }
    });
    return { actions, skipped };
}

/**
 * 在一個 jm（OdooMindMap 實例）上套用／撤除預覽。
 *
 * @param {Object} jm   需要：get_node, add_node, remove_node, expand_node, collapse_node,
 *                      view.refresh（選用）
 * @param {Object} [hooks]
 * @param {(busy:boolean)=>void} [hooks.setBusy]  預覽期間通知編輯器「忽略 jsMind 事件」
 * @param {()=>void} [hooks.afterChange]          畫面變動後（重畫特徵層）
 */
export class AiPreview {
    constructor(jm, hooks = {}) {
        this.jm = jm;
        this.hooks = hooks;
        this.active = false;
        this._added = [];       // 暫時節點 id（依加入順序）
        this._marks = [];       // [{el, cls, attr}]
        this._expanded = [];    // 進入前被收合、預覽時暫時展開的節點 id
        this._arrows = [];      // [{from, to}]
        this._arrowSvg = null;
    }

    enter(ops) {
        this.exit();
        const { actions, skipped } = planPreview(ops, (id) => !!this.jm.get_node(id));
        this._busy(true);
        try {
            this.active = true;
            for (const action of actions) {
                if (action.type === "add") {
                    this._addNode(action.parent, action.id, action.title, "add", action.index);
                } else if (action.type === "rename") {
                    this._mark(action.id, "xmind-ai-rename", "data-ai-new", action.text);
                } else if (action.type === "note") {
                    this._mark(action.id, "xmind-ai-note", "data-ai-note", action.text);
                } else if (action.type === "move") {
                    const node = this.jm.get_node(action.id);
                    this._addNode(action.parent, action.ghost, node ? node.topic : "", "ghost", action.index);
                    this._mark(action.id, "xmind-ai-moving", null, null);
                    this._arrows.push({ from: action.id, to: action.ghost });
                }
            }
            this._refresh();
            this._drawArrows();
        } finally {
            this._busy(false);
        }
        this._afterChange();
        return { applied: actions.length, skipped };
    }

    exit() {
        if (!this.active) {
            return;
        }
        this._busy(true);
        try {
            // 後加入的先拿掉（子孫先於祖先），remove_node 本身也會帶走子孫
            for (const id of this._added.slice().reverse()) {
                if (this.jm.get_node(id)) {
                    this.jm.remove_node(id);
                }
            }
            for (const { el, cls, attr } of this._marks) {
                if (el && el.classList) {
                    el.classList.remove(cls);
                }
                if (el && attr && el.removeAttribute) {
                    el.removeAttribute(attr);
                }
            }
            for (const id of this._expanded) {
                if (this.jm.get_node(id)) {
                    this.jm.collapse_node(id);
                }
            }
            if (this._arrowSvg && this._arrowSvg.parentNode) {
                this._arrowSvg.parentNode.removeChild(this._arrowSvg);
            }
            this._refresh();
        } finally {
            this._added = [];
            this._marks = [];
            this._expanded = [];
            this._arrows = [];
            this._arrowSvg = null;
            this.active = false;
            this._busy(false);
        }
        this._afterChange();
    }

    // ---- 內部 ----
    _busy(value) {
        if (this.hooks.setBusy) {
            this.hooks.setBusy(value);
        }
    }

    _afterChange() {
        if (this.hooks.afterChange) {
            this.hooks.afterChange();
        }
    }

    _refresh() {
        if (this.jm.view && typeof this.jm.view.refresh === "function") {
            this.jm.view.refresh();
        }
    }

    _addNode(parentId, id, title, kind, index) {
        const parent = this.jm.get_node(parentId);
        if (!parent) {
            return;
        }
        if (parent.expanded === false && !isPreviewNode(parent)) {
            this.jm.expand_node(parentId);
            this._expanded.push(parentId);
        }
        const node = this.jm.add_node(parentId, id, title, { [PREVIEW_FLAG]: kind });
        if (!node) {
            return;
        }
        this._added.push(id);
        if (index !== null && index !== undefined && Array.isArray(parent.children)) {
            const from = parent.children.indexOf(node);
            if (from > -1) {
                parent.children.splice(from, 1);
                parent.children.splice(Math.min(index, parent.children.length), 0, node);
            }
        }
        const el = node._el;
        if (el && el.classList) {
            el.classList.add("xmind-ai-preview", kind === "ghost" ? "xmind-ai-ghost" : "xmind-ai-add");
        }
    }

    _mark(id, cls, attr, value) {
        const node = this.jm.get_node(id);
        const el = node && node._el;
        if (!el || !el.classList) {
            return;
        }
        el.classList.add(cls);
        if (attr && el.setAttribute) {
            el.setAttribute(attr, value);
        }
        this._marks.push({ el, cls, attr });
    }

    /** 搬移的箭頭：原節點 → 幽靈節點。純視覺、盡力而為（失敗不影響預覽本體）。 */
    _drawArrows() {
        try {
            const world = this.jm.view && this.jm.view.world;
            if (!world || !this._arrows.length || typeof document === "undefined") {
                return;
            }
            const NS = "http://www.w3.org/2000/svg";
            const svg = document.createElementNS(NS, "svg");
            svg.setAttribute("class", "xmind-ai-arrows");
            svg.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;overflow:visible;pointer-events:none;z-index:50;";
            const defs = document.createElementNS(NS, "defs");
            defs.innerHTML = '<marker id="xmind-ai-arrowhead" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#0E7490"/></marker>';
            svg.appendChild(defs);
            const centre = (node) => ({
                x: (node._x || 0) + (node._w || 0) / 2,
                y: (node._y || 0) + (node._h || 0) / 2,
            });
            for (const { from, to } of this._arrows) {
                const a = this.jm.get_node(from);
                const b = this.jm.get_node(to);
                if (!a || !b) {
                    continue;
                }
                const p = centre(a);
                const q = centre(b);
                const path = document.createElementNS(NS, "path");
                const mx = (p.x + q.x) / 2;
                path.setAttribute("d", `M${p.x},${p.y} C${mx},${p.y} ${mx},${q.y} ${q.x},${q.y}`);
                path.setAttribute("stroke", "#0E7490");
                path.setAttribute("stroke-width", "2");
                path.setAttribute("stroke-dasharray", "6,4");
                path.setAttribute("fill", "none");
                path.setAttribute("marker-end", "url(#xmind-ai-arrowhead)");
                svg.appendChild(path);
            }
            world.appendChild(svg);
            this._arrowSvg = svg;
        } catch (error) {
            // 箭頭只是輔助說明
        }
    }
}
