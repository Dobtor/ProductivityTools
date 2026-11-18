// mindmap_sheet_tree.js 的純邏輯測試。
// 執行：node --test dobtor_xmind/tests/node/mindmap_sheet_tree.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const source = await readFile(join(here, "../../static/src/js/mindmap_sheet_tree.js"), "utf8");
if (/^\s*import\s/m.test(source)) {
    throw new Error("mindmap_sheet_tree.js 不再是零相依，這個測試手法失效");
}
const { orderSheets, sheetPath, depthPrefix, flattenTopics } = await import(
    "data:text/javascript;base64," + Buffer.from(source, "utf8").toString("base64"));

const sheets = [
    { id: 5, name: "Idea", sequence: 1, sheet_role: "idea" },
    { id: 2, name: "Sub B", sequence: 30, sheet_role: "sub", parent_sheet_id: 1 },
    { id: 3, name: "Sub A", sequence: 20, sheet_role: "sub", parent_sheet_id: 1 },
    { id: 4, name: "Sub A.1", sequence: 40, sheet_role: "sub", parent_sheet_id: 3 },
    { id: 1, name: "Main", sequence: 50, sheet_role: "main" },
    { id: 9, name: "Orphan", sequence: 60, sheet_role: "sub", parent_sheet_id: 99 },
];

test("main first, subs in tree order, idea sheets last", () => {
    const ordered = orderSheets(sheets);
    assert.deepEqual(ordered.map((s) => [s.name, s.depth]), [
        ["Main", 0], ["Sub A", 1], ["Sub A.1", 2], ["Sub B", 1], ["Orphan", 1], ["Idea", 0],
    ]);
});

test("orderSheets tolerates empty / bad input", () => {
    assert.deepEqual(orderSheets(null), []);
    assert.deepEqual(orderSheets([{ id: 1, name: "x", sheet_role: "idea" }]).length, 1);
});

test("breadcrumb path from main to a nested sub sheet", () => {
    assert.deepEqual(sheetPath(sheets, 4).map((s) => s.name), ["Main", "Sub A", "Sub A.1"]);
    assert.deepEqual(sheetPath(sheets, 1).map((s) => s.name), ["Main"]);
    assert.deepEqual(sheetPath(sheets, 5).map((s) => s.name), ["Idea"]);
    assert.deepEqual(sheetPath(sheets, 9).map((s) => s.name), ["Orphan"]);
    assert.deepEqual(sheetPath(sheets, 404), []);
});

test("sheetPath stops on cycles", () => {
    const cyc = [
        { id: 1, sheet_role: "sub", parent_sheet_id: 2 },
        { id: 2, sheet_role: "sub", parent_sheet_id: 1 },
    ];
    assert.equal(sheetPath(cyc, 1).length, 2);
});

test("depth prefix", () => {
    assert.equal(depthPrefix(0), "");
    assert.equal(depthPrefix(2), "›› ");
});

test("flattenTopics builds a pre-order tree with depth", () => {
    const rows = [
        { id: 3, title: "c", parent_id: [1, "r"], sequence: 2 },
        { id: 1, title: "r", parent_id: false, sequence: 0 },
        { id: 2, title: "b", parent_id: [1, "r"], sequence: 1 },
        { id: 4, title: "b1", parent_id: [2, "b"], sequence: 0 },
    ];
    assert.deepEqual(flattenTopics(rows).map((r) => [r.title, r.depth]),
        [["r", 0], ["b", 1], ["b1", 2], ["c", 1]]);
});
