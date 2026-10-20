// mindmap_ai_hooks.js 的純邏輯測試（不需要瀏覽器、OWL 或 Odoo）。
// 執行：node --test dobtor_xmind/tests/node/mindmap_ai_hooks.test.mjs
//
// 為什麼不放在 static/tests：那個目錄整個被 web.assets_unit_tests 收進 hoot 套件，
// 放一支 node 用的 .mjs 進去會被打包器當成資源檔。
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const source = await readFile(join(here, "../../static/src/js/mindmap_ai_hooks.js"), "utf8");
if (/^\s*import\s/m.test(source)) {
    throw new Error("mindmap_ai_hooks.js 不再是零相依，這個測試手法失效（該修的是相依，不是斷言）");
}
const mod = await import("data:text/javascript;base64," + Buffer.from(source, "utf8").toString("base64"));
const { AiPreview, PREVIEW_FLAG, hasPreviewNodes, isPreviewNode, planPreview, previewId, stripPreviewNodes } = mod;

// ---------------------------------------------------------------- 假的 jm
function fakeEl() {
    const classes = new Set();
    const attrs = {};
    return {
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
        },
        setAttribute: (k, v) => { attrs[k] = v; },
        removeAttribute: (k) => { delete attrs[k]; },
        _classes: classes,
        _attrs: attrs,
    };
}

/** 模仿 OdooMindMap：節點存在 nodes{}，get_data 會把「所有」節點（含預覽）匯出。 */
function fakeJm(tree) {
    const nodes = {};
    const calls = [];
    const build = (json, parent) => {
        const n = {
            id: json.id, topic: json.topic, data: json.data || {}, parent,
            children: [], expanded: json.expanded !== false, _el: fakeEl(),
        };
        nodes[n.id] = n;
        (json.children || []).forEach((c) => n.children.push(build(c, n)));
        return n;
    };
    const root = build(tree, null);
    const jm = {
        calls,
        view: { refresh: () => calls.push("refresh") },
        get_node: (id) => nodes[id] || null,
        add_node(parentId, id, topic, data) {
            calls.push(["add_node", id]);
            const parent = nodes[parentId];
            if (!parent) return null;
            const n = { id, topic, data: data || {}, parent, children: [], expanded: true, _el: fakeEl() };
            parent.children.push(n);
            nodes[id] = n;
            return n;
        },
        remove_node(id) {
            calls.push(["remove_node", id]);
            const n = nodes[id];
            if (!n) return false;
            if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1);
            const drop = (x) => { x.children.forEach(drop); delete nodes[x.id]; };
            drop(n);
            return true;
        },
        expand_node(id) { calls.push(["expand", id]); nodes[id].expanded = true; },
        collapse_node(id) { calls.push(["collapse", id]); nodes[id].expanded = false; },
        get_data() {
            const ex = (n) => ({ id: n.id, topic: n.topic, expanded: n.expanded, data: n.data, children: n.children.map(ex) });
            return { meta: { name: root.topic }, format: "node_tree", data: ex(root) };
        },
    };
    return jm;
}

const TREE = {
    id: "root", topic: "Root", data: {},
    children: [
        { id: "a", topic: "A", data: {}, children: [{ id: "a1", topic: "A1", data: {}, children: [] }] },
        { id: "b", topic: "B", expanded: false, data: {}, children: [{ id: "b1", topic: "B1", data: {}, children: [] }] },
        { id: "c", topic: "C", data: {}, children: [] },
    ],
};
const ids = (tree) => {
    const out = [];
    const walk = (n) => { out.push(n.id); (n.children || []).forEach(walk); };
    walk(tree.data);
    return out;
};

// ------------------------------------------------------------------ 測試
test("previewId 不可能與真節點撞號", () => {
    assert.match(previewId("x"), /^ai_preview__/);
    assert.notEqual(previewId("a"), "a");
});

test("planPreview：temp_id 串接、略過不存在的節點與未知 op", () => {
    const exists = (id) => ["root", "a", "b", "c"].includes(id);
    const { actions, skipped } = planPreview([
        { op: "add", parent_id: "root", temp_id: "n1", title: "N1", index: 0 },
        { op: "add", parent_id: "n1", temp_id: "n2", title: "N2" },
        { op: "add", parent_id: "ghost", temp_id: "n3", title: "X" },
        { op: "rename", id: "a", title: "A!" },
        { op: "rename", id: "zzz", title: "no" },
        { op: "set_note", id: "c", note: "hello" },
        { op: "move", id: "c", new_parent_id: "n1", index: 0 },
        { op: "delete", id: "a" },
    ], exists);
    assert.deepEqual(actions.map((a) => a.type), ["add", "add", "rename", "note", "move"]);
    assert.equal(actions[1].parent, previewId("n1"), "子節點的 parent 要指到預覽節點");
    assert.equal(actions[4].parent, previewId("n1"));
    assert.deepEqual(skipped.map((s) => s.index), [2, 4, 7]);
});

test("stripPreviewNodes：移除預覽節點與其子孫，不改輸入", () => {
    const tree = {
        meta: { name: "x" }, format: "node_tree",
        data: {
            id: "root", topic: "R", data: {}, children: [
                { id: "a", topic: "A", data: {}, children: [] },
                { id: "p", topic: "P", data: { [PREVIEW_FLAG]: "add" }, children: [
                    { id: "p2", topic: "P2", data: {}, children: [] }] },
            ],
        },
    };
    const before = JSON.stringify(tree);
    const out = stripPreviewNodes(tree);
    assert.equal(JSON.stringify(tree), before, "輸入不得被修改");
    assert.deepEqual(ids(out), ["root", "a"]);
    assert.equal(out.format, "node_tree");
    assert.ok(hasPreviewNodes(tree));
    assert.ok(!hasPreviewNodes(out));
});

test("enter：新增綠底暫時節點、改名／備註只加標記、搬移產生幽靈節點", () => {
    const jm = fakeJm(TREE);
    const p = new AiPreview(jm);
    const res = p.enter([
        { op: "add", parent_id: "root", temp_id: "n1", title: "新", index: 0 },
        { op: "rename", id: "a", title: "A 改名" },
        { op: "set_note", id: "c", note: "備註" },
        { op: "move", id: "c", new_parent_id: "a", index: 0 },
    ]);
    assert.equal(res.applied, 4);
    assert.ok(p.active);
    const added = jm.get_node(previewId("n1"));
    assert.equal(added.data[PREVIEW_FLAG], "add");
    assert.ok(added._el._classes.has("xmind-ai-add"));
    assert.equal(jm.get_node("root").children[0].id, previewId("n1"), "index=0 要排第一");
    assert.ok(jm.get_node("a")._el._classes.has("xmind-ai-rename"));
    assert.equal(jm.get_node("a")._el._attrs["data-ai-new"], "A 改名");
    assert.equal(jm.get_node("a").topic, "A", "改名預覽不可改動節點資料");
    assert.ok(jm.get_node("c")._el._classes.has("xmind-ai-moving"));
    const ghost = jm.get_node("a").children.find((n) => isPreviewNode(n));
    assert.equal(ghost.data[PREVIEW_FLAG], "ghost");
    assert.equal(ghost.topic, "C");
});

test("★ 預覽節點不會被序列化進存檔（get_data → stripPreviewNodes 後與原樹相同）", () => {
    const jm = fakeJm(TREE);
    const before = ids(jm.get_data());
    const p = new AiPreview(jm);
    p.enter([
        { op: "add", parent_id: "root", temp_id: "n1", title: "新" },
        { op: "add", parent_id: "n1", temp_id: "n2", title: "新的子" },
        { op: "move", id: "c", new_parent_id: "a" },
    ]);
    const raw = jm.get_data();
    assert.ok(hasPreviewNodes(raw), "前提：預覽期間 get_data 確實含有暫時節點（所以一定要過濾）");
    assert.ok(ids(raw).length > before.length);
    // 編輯器存檔路徑：stripPreviewNodes(get_data(...))
    assert.deepEqual(ids(stripPreviewNodes(raw)), before);
    assert.ok(!hasPreviewNodes(stripPreviewNodes(raw)));
});

test("exit：畫面回到進入前的樣子（節點、標記、收合狀態）", () => {
    const jm = fakeJm(TREE);
    const snapshot = JSON.stringify(jm.get_data());
    const p = new AiPreview(jm);
    // 在收合的 b 底下新增 → 預覽需暫時展開 b
    p.enter([
        { op: "add", parent_id: "b", temp_id: "n1", title: "藏在收合底下" },
        { op: "rename", id: "a", title: "x" },
        { op: "move", id: "c", new_parent_id: "a" },
    ]);
    assert.equal(jm.get_node("b").expanded, true, "預覽期間 b 暫時展開");
    p.exit();
    assert.ok(!p.active);
    assert.equal(JSON.stringify(jm.get_data()), snapshot, "exit 之後資料必須與進入前完全相同");
    assert.equal(jm.get_node("b").expanded, false, "b 要回到收合");
    assert.equal(jm.get_node("a")._el._classes.size, 0);
    assert.equal(jm.get_node("c")._el._classes.size, 0);
    assert.deepEqual(jm.get_node("a")._el._attrs, {});
});

test("重複 enter 不會疊加；exit 可重複呼叫", () => {
    const jm = fakeJm(TREE);
    const p = new AiPreview(jm);
    const ops = [{ op: "add", parent_id: "root", temp_id: "n1", title: "新" }];
    p.enter(ops);
    p.enter(ops);
    const count = jm.get_node("root").children.filter(isPreviewNode).length;
    assert.equal(count, 1);
    p.exit();
    p.exit();
    assert.equal(jm.get_node("root").children.length, 3);
});

test("預覽期間通知 busy，結束後解除（編輯器據此忽略 jsMind 事件）", () => {
    const jm = fakeJm(TREE);
    const log = [];
    const p = new AiPreview(jm, { setBusy: (b) => log.push(b), afterChange: () => log.push("after") });
    p.enter([{ op: "add", parent_id: "root", temp_id: "n1", title: "新" }]);
    assert.deepEqual(log, [true, false, "after"]);
    log.length = 0;
    p.exit();
    assert.deepEqual(log, [true, false, "after"]);
});

test("不碰復原堆疊：整個流程只用到 jm 的低階 API", () => {
    const jm = fakeJm(TREE);
    new AiPreview(jm).enter([{ op: "add", parent_id: "root", temp_id: "n1", title: "新" }]);
    const used = new Set(jm.calls.map((c) => (Array.isArray(c) ? c[0] : c)));
    for (const name of used) {
        assert.ok(["add_node", "remove_node", "expand", "collapse", "refresh"].includes(name), name);
    }
});
