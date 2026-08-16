import { describe, expect, test } from "@odoo/hoot";

import { getMindmapTemplates } from "@dobtor_xmind/js/mindmap_templates_data";

describe.current.tags("headless");

/** 空白範本用的假預設資料 —— 編輯器實際傳入的是 `_getDefaultData()`。 */
const FAKE_DEFAULT = { meta: { name: "fake" }, format: "node_tree", data: { id: "root" } };

describe("mindmap templates", () => {
    test("每個範本都有 render-engine 吃得下的結構", () => {
        const templates = getMindmapTemplates(FAKE_DEFAULT);
        expect(templates.length).toBeGreaterThan(10);
        for (const t of templates) {
            expect(typeof t.id).toBe("string");
            expect(t.id).not.toBe("");
            expect(String(t.name)).not.toBe("");
            expect(typeof t.category).toBe("string");
            // jsMind 的 node_tree 契約：meta / format / data.id / data.topic
            expect(t.data.format).toBe("node_tree");
            expect(t.data.data.id).not.toBe(undefined);
        }
    });

    test("範本 id 不重複", () => {
        // 重複的 id 會讓「套用範本」拿到錯的那一份，而畫面上看不出來。
        const ids = getMindmapTemplates(FAKE_DEFAULT).map((t) => t.id);
        expect(ids.length).toBe(new Set(ids).size);
    });

    test("blank 範本原樣使用傳入的預設資料", () => {
        const templates = getMindmapTemplates(FAKE_DEFAULT);
        const blank = templates.find((t) => t.id === "blank");
        expect(blank.data).toBe(FAKE_DEFAULT);
    });

    test("分支節點的 id 在同一份範本內唯一", () => {
        // buildTemplate 用 `node_b_${i}` / `node_t_${i}_${j}` 產生 id；只要編號
        // 邏輯被改壞，重複 id 會讓 jsMind 靜默丟掉節點（樹少一塊但不報錯）。
        for (const t of getMindmapTemplates(FAKE_DEFAULT)) {
            const ids = [];
            const walk = (node) => {
                ids.push(node.id);
                (node.children || []).forEach(walk);
            };
            walk(t.data.data);
            expect(ids.length).toBe(new Set(ids).size);
        }
    });

    test("所有節點都有非空的 topic 文字", () => {
        for (const t of getMindmapTemplates(FAKE_DEFAULT)) {
            const walk = (node) => {
                if (node !== t.data.data || t.id !== "blank") {
                    expect(String(node.topic || "")).not.toBe("");
                }
                (node.children || []).forEach(walk);
            };
            walk(t.data.data);
        }
    });
});
