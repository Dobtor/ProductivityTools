import { describe, expect, test } from "@odoo/hoot";

import { MindmapEditor } from "@dobtor_xmind/js/mindmap_editor";
import { MINDMAP_FILTERS } from "@dobtor_xmind/js/mindmap_search";
import { RelationshipManager } from "@dobtor_xmind/js/relationship_manager";

describe.current.tags("headless");

/**
 * 這裡直接對 prototype 上的方法用 `.call()`，不去掛載整個編輯器。
 *
 * 理由：要測的是純狀態邏輯，而 MindmapEditor 是把自訂 render engine 掛在原生
 * DOM 上的命令式 god-component，掛起來需要一整套 service、一個真的畫布與一次
 * RPC。用假的 `this` 反而能精準釘住「這段邏輯讀了哪些狀態」——多讀了別的東西，
 * 測試就會壞。
 */
function callWith(method, ctx) {
    return MindmapEditor.prototype[method].call(ctx);
}

/** 假的 jsMind：只需要 get_node()。 */
function fakeJm(existingIds) {
    const set = new Set(existingIds);
    return { get_node: (id) => (set.has(id) ? { id, data: {} } : null) };
}

describe("_pruneFloatingTopics", () => {
    test("節點還在的浮動主題原樣保留", () => {
        const ctx = {
            jm: fakeJm(["a", "b"]),
            floatingTopics: [{ id: "a" }, { id: "b" }],
        };
        callWith("_pruneFloatingTopics", ctx);
        expect(ctx.floatingTopics.map((f) => f.id)).toEqual(["a", "b"]);
    });

    test("節點已被移除的浮動主題會被丟掉", () => {
        // 這就是「刪掉的浮動主題以空白標題復活」那個 bug 的成因：畫布上的節點
        // 被 onDelete / onCutTopic / AddNodeCommand.undo 拿掉了，但這份影子陣列
        // 沒人動，存檔時就照著殘留項寫回一筆（連 title 都沒有）。
        const ctx = {
            jm: fakeJm(["a"]),
            floatingTopics: [{ id: "a" }, { id: "gone" }],
        };
        callWith("_pruneFloatingTopics", ctx);
        expect(ctx.floatingTopics.map((f) => f.id)).toEqual(["a"]);
    });

    test("全部都不見時清成空陣列", () => {
        const ctx = { jm: fakeJm([]), floatingTopics: [{ id: "x" }, { id: "y" }] };
        callWith("_pruneFloatingTopics", ctx);
        expect(ctx.floatingTopics).toEqual([]);
    });

    test("還沒有 jm 時不動作也不丟例外", () => {
        // onMounted 之前、或 _initJsMind 失敗時會走到這裡。
        const ctx = { jm: null, floatingTopics: [{ id: "a" }] };
        expect(() => callWith("_pruneFloatingTopics", ctx)).not.toThrow();
        expect(ctx.floatingTopics.length).toBe(1);
    });

    test("空陣列時直接返回", () => {
        const ctx = {
            jm: { get_node: () => { throw new Error("不該被呼叫"); } },
            floatingTopics: [],
        };
        expect(() => callWith("_pruneFloatingTopics", ctx)).not.toThrow();
    });
});

describe("MINDMAP_FILTERS", () => {
    const byKey = Object.fromEntries(MINDMAP_FILTERS.map((f) => [f.key, f.predicate]));

    test("每個篩選條件都有 key / label / predicate", () => {
        for (const f of MINDMAP_FILTERS) {
            expect(typeof f.key).toBe("string");
            expect(String(f.label)).not.toBe("");
            expect(typeof f.predicate).toBe("function");
        }
        const keys = MINDMAP_FILTERS.map((f) => f.key);
        expect(keys.length).toBe(new Set(keys).size);
    });

    test("linked / unassigned", () => {
        expect(byKey.linked({ taskId: 7 })).toBe(true);
        expect(byKey.linked({})).toBe(false);
        expect(byKey.unassigned({})).toBe(true);
        expect(byKey.unassigned({ assignees: [] })).toBe(true);
        expect(byKey.unassigned({ assignees: [1] })).toBe(false);
    });

    test("done / open 互為補集", () => {
        for (const d of [{}, { taskInfo: {} }, { taskInfo: { progress: 0 } },
                         { taskInfo: { progress: 50 } }, { taskInfo: { progress: 100 } }]) {
            expect(byKey.done(d)).toBe(!byKey.open(d));
        }
    });

    test("overdue：只比日期，截止「今天」不算逾期", () => {
        const day = 24 * 60 * 60 * 1000;
        const iso = (offsetDays) => new Date(Date.now() + offsetDays * day).toISOString();

        expect(byKey.overdue({ taskInfo: { end: iso(-1), progress: 0 } })).toBe(true);
        // 今天到期 → 不算逾期
        expect(byKey.overdue({ taskInfo: { end: iso(0), progress: 0 } })).toBe(false);
        expect(byKey.overdue({ taskInfo: { end: iso(1), progress: 0 } })).toBe(false);
        // 已完成的不算逾期，即使日期已過
        expect(byKey.overdue({ taskInfo: { end: iso(-5), progress: 100 } })).toBe(false);
        // 沒有截止日就不算逾期
        expect(byKey.overdue({})).toBe(false);
        expect(byKey.overdue({ taskInfo: {} })).toBe(false);
    });

    test("has_deadline", () => {
        expect(byKey.has_deadline({ taskInfo: { end: "2026-01-01" } })).toBe(true);
        expect(byKey.has_deadline({ taskInfo: {} })).toBe(false);
        expect(byKey.has_deadline({})).toBe(false);
    });
});

describe("關連線的端點可見性", () => {
    const proto = RelationshipManager.prototype;
    const visible = { offsetParent: {}, offsetWidth: 120 };
    const collapsed = { offsetParent: null, offsetWidth: 120 };   // display:none

    test("_isEndpointVisible 認得收合／零寬度／不存在的端點", () => {
        expect(proto._isEndpointVisible(visible)).toBe(true);
        expect(proto._isEndpointVisible(collapsed)).toBe(false);
        expect(proto._isEndpointVisible({ offsetParent: {}, offsetWidth: 0 })).toBe(false);
        expect(proto._isEndpointVisible(null)).toBe(false);
        expect(proto._isEndpointVisible(undefined)).toBe(false);
    });

    test("syncVisibility：端點被收合的線要整條收起來", () => {
        // 這是修掉的舊行為：收合分支後，節點的 offsetLeft/offsetWidth 變成 0，
        // 關連線端點被算到 (0,0)，畫布左上角會出現一條射向角落的殘線。
        const ctx = {
            _isEndpointVisible: proto._isEndpointVisible,
            relationships: [
                { group: { style: {} }, sourceElement: visible, targetElement: visible },
                { group: { style: {} }, sourceElement: collapsed, targetElement: visible },
                { group: null, sourceElement: null, targetElement: null },
            ],
        };
        proto.syncVisibility.call(ctx);
        expect(ctx.relationships[0].group.style.display).toBe("");
        expect(ctx.relationships[1].group.style.display).toBe("none");
        // 沒有 group 的（尚未繪製）要跳過而不是丟例外
        expect(ctx.relationships[2].group).toBe(null);
    });
});
