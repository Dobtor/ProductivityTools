/** @odoo-module **/

/**
 * 分頁樹的純邏輯（零相依，tests/node/mindmap_sheet_tree.test.mjs 直接載入測試）。
 *
 * 分頁資料來自 /xmind/workbook/<id>/sheets：
 *   { id, name, sequence, sheet_role: 'main'|'sub'|'idea', parent_sheet_id,
 *     anchor_component_id, anchor_topic_title }
 */

/**
 * 分頁列的顯示順序：主圖 → 子圖（依樹狀、同層依 sequence）→ 發想頁。
 * 每筆多一個 depth（主圖／發想頁 0，子圖 1..3）。
 * 找不到上層的子圖（資料不一致）接在樹的後面，depth 1，不會消失。
 */
export function orderSheets(sheets) {
    const list = Array.isArray(sheets) ? sheets : [];
    const bySeq = (a, b) => (a.sequence || 0) - (b.sequence || 0) || a.id - b.id;
    const childrenOf = new Map();
    for (const sheet of list) {
        if (sheet.sheet_role === "sub" && sheet.parent_sheet_id) {
            if (!childrenOf.has(sheet.parent_sheet_id)) {
                childrenOf.set(sheet.parent_sheet_id, []);
            }
            childrenOf.get(sheet.parent_sheet_id).push(sheet);
        }
    }
    const result = [];
    const placed = new Set();
    const walk = (sheet, depth) => {
        if (placed.has(sheet.id)) {
            return;
        }
        placed.add(sheet.id);
        result.push({ ...sheet, depth });
        for (const child of (childrenOf.get(sheet.id) || []).slice().sort(bySeq)) {
            walk(child, depth + 1);
        }
    };
    for (const main of list.filter((s) => s.sheet_role === "main").sort(bySeq)) {
        walk(main, 0);
    }
    for (const sub of list.filter((s) => s.sheet_role === "sub").sort(bySeq)) {
        if (!placed.has(sub.id)) {
            walk(sub, 1);
        }
    }
    for (const other of list.filter((s) => !placed.has(s.id)).sort(bySeq)) {
        walk(other, 0);
    }
    return result;
}

/**
 * 從主圖到指定分頁的路徑（含兩端）。不是子圖時只有它自己。
 * 遇到環或斷掉的上層就停。
 */
export function sheetPath(sheets, sheetId) {
    const byId = new Map((sheets || []).map((s) => [s.id, s]));
    const path = [];
    const seen = new Set();
    let current = byId.get(sheetId);
    while (current && !seen.has(current.id)) {
        seen.add(current.id);
        path.unshift(current);
        current = current.sheet_role === "sub" ? byId.get(current.parent_sheet_id) : null;
    }
    return path;
}

/** 分頁列上的縮排前綴：每一層一個「›」。 */
export function depthPrefix(depth) {
    return depth > 0 ? "›".repeat(depth) + " " : "";
}

/**
 * 主題清單（xmind.topic search_read：id、title、parent_id、sequence）排成樹狀
 * 先序，每筆帶 depth；供「移到分頁／掛到主題」的主題挑選器使用。
 */
export function flattenTopics(rows) {
    const list = Array.isArray(rows) ? rows : [];
    const parentOf = (r) => (Array.isArray(r.parent_id) ? r.parent_id[0] : r.parent_id) || false;
    const ids = new Set(list.map((r) => r.id));
    const kids = new Map();
    for (const r of list) {
        const p = parentOf(r);
        const key = p && ids.has(p) ? p : 0;
        if (!kids.has(key)) {
            kids.set(key, []);
        }
        kids.get(key).push(r);
    }
    const order = (a, b) => (a.sequence || 0) - (b.sequence || 0) || a.id - b.id;
    const out = [];
    const seen = new Set();
    const walk = (r, depth) => {
        if (seen.has(r.id)) {
            return;
        }
        seen.add(r.id);
        out.push({ ...r, depth });
        for (const c of (kids.get(r.id) || []).slice().sort(order)) {
            walk(c, depth + 1);
        }
    };
    for (const r of (kids.get(0) || []).slice().sort(order)) {
        walk(r, 0);
    }
    return out;
}
