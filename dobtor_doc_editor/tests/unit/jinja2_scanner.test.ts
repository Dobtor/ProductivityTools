/**
 * jinja2_scanner.test.ts — Phase 8 Sprint G
 *
 * 對 scanJinja2Variables / flattenElementsToText 的純函式單測。
 * 涵蓋：
 *   - 主流 + 表格 + 多層巢狀
 *   - 去重 + 出現次數計算
 *   - 變數內空白容錯（`{{name}}` / `{{ name }}` / `{{  name  }}`）
 *   - 帶點路徑（`partner_id.name`）與 `object.` 前綴剝除
 *   - 跳過 control 元素（Sprint E 已註冊欄位不應重複偵測）
 *   - 排序穩定性（次數降冪 → 字母升冪）
 *   - 防禦邊界（null / undefined / 非陣列 main）
 */

import { describe, expect, it } from "vitest";
// 從 OWL 元件資料夾匯入 .js scanner（vitest bundler resolver 支援 .js）
// @ts-expect-error -- 沒附型別宣告，純函式 OK
import { scanJinja2Variables, flattenElementsToText, scanJinja2VariablesWithPositions, scanJinja2VariablesInTables, analyzeScanResults, computeOrphanRecordIds, normalizeMultiCharElements, normalizeMultiCharElementsInTables, findMarkerPositionsInMain, rewriteTdValueWithControls } from "../../static/src/components/doc_editor/jinja2_scanner.js";

/** 把字串展開為 canvas-editor 的單字元 IElement[]（測試 fixture helper） */
function textToElements(text: string) {
    return Array.from(text).map((ch) => ({ value: ch }));
}

describe("scanJinja2Variables", () => {
    it("找到主流的單一變數", () => {
        const data = { main: textToElements("Hello {{ name }} world") };
        expect(scanJinja2Variables(data)).toEqual([
            { varName: "name", occurrences: 1 },
        ]);
    });

    it("user 截圖那 5 個變數場景（去重 + 計次）", () => {
        const text =
            "工程名稱：{{ project_name }}\n" +
            "承包商：{{ contractor }}\n" +
            "估驗日期：{{ estimate_date }}\n" +
            "工程名稱（重複）：{{ project_name }}\n" +
            "金額：{{ amount }}\n" +
            "備註：{{ remark }}";
        const data = { main: textToElements(text) };
        const result = scanJinja2Variables(data);
        // 5 個 unique（project_name 出現 2 次）
        expect(result).toHaveLength(5);
        // project_name 排第一（次數最多）
        expect(result[0]).toEqual({ varName: "project_name", occurrences: 2 });
        // 其餘 4 個各 1 次，按字母排序
        expect(result.slice(1).map((r: any) => r.varName)).toEqual([
            "amount",
            "contractor",
            "estimate_date",
            "remark",
        ]);
    });

    it("變數內空白容錯", () => {
        const data = {
            main: textToElements("{{name}} {{ name }} {{  name  }}"),
        };
        const result = scanJinja2Variables(data);
        expect(result).toEqual([{ varName: "name", occurrences: 3 }]);
    });

    it("帶點路徑變數（partner_id.name）", () => {
        const data = { main: textToElements("{{ partner_id.name }}") };
        const result = scanJinja2Variables(data);
        expect(result).toEqual([
            { varName: "partner_id.name", occurrences: 1 },
        ]);
    });

    it("剝除 `object.` 前綴（與 Sprint E odoo_field_name 對齊）", () => {
        const data = {
            main: textToElements("{{ object.partner_id.name }} 和 {{ partner_id.name }}"),
        };
        const result = scanJinja2Variables(data);
        // 兩個應合併為同一個 `partner_id.name`
        expect(result).toEqual([
            { varName: "partner_id.name", occurrences: 2 },
        ]);
    });

    it("跳過 control 元素（已註冊欄位不重複偵測）", () => {
        const data = {
            main: [
                ...textToElements("Hello "),
                { type: "control", value: "", placeholder: "{{ already_registered }}" },
                ...textToElements(" {{ new_var }}"),
            ],
        };
        const result = scanJinja2Variables(data);
        expect(result).toEqual([{ varName: "new_var", occurrences: 1 }]);
    });

    it("遞迴 table 內 td.value", () => {
        const data = {
            main: [
                {
                    type: "table",
                    trList: [
                        {
                            tdList: [
                                { value: textToElements("欄位 1：{{ field_a }}") },
                                { value: textToElements("欄位 2：{{ field_b }}") },
                            ],
                        },
                        {
                            tdList: [
                                { value: textToElements("欄位 1 重複：{{ field_a }}") },
                            ],
                        },
                    ],
                },
            ],
        };
        const result = scanJinja2Variables(data);
        expect(result).toEqual([
            { varName: "field_a", occurrences: 2 },
            { varName: "field_b", occurrences: 1 },
        ]);
    });

    it("遞迴 list/title 等 valueList", () => {
        const data = {
            main: [
                {
                    type: "title",
                    valueList: textToElements("標題：{{ title_var }}"),
                },
                {
                    type: "list",
                    valueList: textToElements("項目：{{ item_var }}"),
                },
            ],
        };
        const result = scanJinja2Variables(data);
        expect(result.map((r: any) => r.varName).sort()).toEqual([
            "item_var",
            "title_var",
        ]);
    });

    it("同時掃 main / header / footer", () => {
        const data = {
            main: textToElements("{{ main_var }}"),
            header: textToElements("{{ header_var }}"),
            footer: textToElements("{{ footer_var }} {{ header_var }}"),
        };
        const result = scanJinja2Variables(data);
        expect(result).toHaveLength(3);
        // header_var 出現 2 次（header + footer）
        expect(result[0]).toEqual({ varName: "header_var", occurrences: 2 });
    });

    it("沒找到變數時回空陣列", () => {
        const data = { main: textToElements("一段沒有任何變數的純文字") };
        expect(scanJinja2Variables(data)).toEqual([]);
    });

    it("變數內含非法字元（如 |filter）不收", () => {
        const data = {
            main: textToElements("{{ name | upper }} {{ valid_var }}"),
        };
        const result = scanJinja2Variables(data);
        // `name | upper` 不符合純識別字 regex，應不收
        expect(result).toEqual([{ varName: "valid_var", occurrences: 1 }]);
    });

    it("防禦：editorData 為 null / undefined / 空物件", () => {
        expect(scanJinja2Variables(null as any)).toEqual([]);
        expect(scanJinja2Variables(undefined as any)).toEqual([]);
        expect(scanJinja2Variables({})).toEqual([]);
    });

    it("防禦：main 不是陣列", () => {
        expect(scanJinja2Variables({ main: "not an array" } as any)).toEqual([]);
        expect(scanJinja2Variables({ main: null } as any)).toEqual([]);
    });
});

describe("scanJinja2VariablesWithPositions (Sprint H)", () => {
    it("回傳 main 流的逐筆匹配 + 元素索引", () => {
        // "Hi {{ a }} bye" 共 14 字元，每個元素 1 字元
        const main = textToElements("Hi {{ a }} bye");
        const result = scanJinja2VariablesWithPositions(main);
        expect(result).toHaveLength(1);
        expect(result[0].varName).toBe("a");
        expect(result[0].fullMatch).toBe("{{ a }}");
        // "Hi " 佔 0-2，"{{ a }}" 佔 3-9
        expect(result[0].startIdx).toBe(3);
        expect(result[0].endIdx).toBe(9);
    });

    it("多個變數按文件順序回傳（不去重）", () => {
        const main = textToElements("{{ a }} 和 {{ b }} 還有 {{ a }}");
        const result = scanJinja2VariablesWithPositions(main);
        expect(result).toHaveLength(3);
        expect(result.map((r: any) => r.varName)).toEqual(["a", "b", "a"]);
        // 確認位置嚴格遞增
        expect(result[0].endIdx).toBeLessThan(result[1].startIdx);
        expect(result[1].endIdx).toBeLessThan(result[2].startIdx);
    });

    it("跨 control 元素的 match 作廢（不會跨越 unsafe sentinel）", () => {
        const main = [
            ...textToElements("{{ "),
            { type: "control", value: "X", placeholder: "" },
            ...textToElements("name }}"),
        ];
        const result = scanJinja2VariablesWithPositions(main);
        // `{{ ` + control + `name }}` 不應產生 match
        expect(result).toEqual([]);
    });

    it("跨 table 元素的 match 作廢", () => {
        const main = [
            ...textToElements("{{ "),
            { type: "table", trList: [{ tdList: [{ value: textToElements("X") }] }] },
            ...textToElements("a }}"),
        ];
        const result = scanJinja2VariablesWithPositions(main);
        expect(result).toEqual([]);
    });

    it("跨 multi-char value 元素的 match 作廢（無法精確設 range）", () => {
        const main = [
            ...textToElements("{{ "),
            { value: "abc" }, // multi-char value
            ...textToElements(" }}"),
        ];
        const result = scanJinja2VariablesWithPositions(main);
        expect(result).toEqual([]);
    });

    it("complex element 不會打斷其外圍的 match", () => {
        // "ok {{ a }} sep {{ b }} done"
        // 中間夾一個 control 元素在 sep 之後，b 的 match 應該仍然有效
        const main = [
            ...textToElements("ok {{ a }} sep "),
            { type: "control", value: "X" },
            ...textToElements(" {{ b }} done"),
        ];
        const result = scanJinja2VariablesWithPositions(main);
        expect(result).toHaveLength(2);
        expect(result[0].varName).toBe("a");
        expect(result[1].varName).toBe("b");
    });

    it("剝 `object.` 前綴與 Sprint G 對齊", () => {
        const main = textToElements("{{ object.partner_id.name }}");
        const result = scanJinja2VariablesWithPositions(main);
        expect(result).toHaveLength(1);
        expect(result[0].varName).toBe("partner_id.name");
        // fullMatch 不剝（保留原文用於 search）
        expect(result[0].fullMatch).toBe("{{ object.partner_id.name }}");
    });

    it("變數內空白容錯", () => {
        const main = textToElements("{{name}} and {{  spacey  }}");
        const result = scanJinja2VariablesWithPositions(main);
        expect(result.map((r: any) => r.varName)).toEqual(["name", "spacey"]);
    });

    it("帶點路徑變數", () => {
        const main = textToElements("{{ partner_id.name }}");
        const result = scanJinja2VariablesWithPositions(main);
        expect(result).toHaveLength(1);
        expect(result[0].varName).toBe("partner_id.name");
        expect(result[0].startIdx).toBe(0);
        // "{{ partner_id.name }}" 共 21 字元，endIdx = 20
        expect(result[0].endIdx).toBe(20);
    });

    it("變數內含非法字元（如 |filter）不收", () => {
        const main = textToElements("{{ a|upper }} {{ b }}");
        const result = scanJinja2VariablesWithPositions(main);
        expect(result).toHaveLength(1);
        expect(result[0].varName).toBe("b");
    });

    it("沒找到變數時回空陣列", () => {
        const main = textToElements("just plain text no variables");
        expect(scanJinja2VariablesWithPositions(main)).toEqual([]);
    });

    it("防禦：非陣列回空", () => {
        expect(scanJinja2VariablesWithPositions(null as any)).toEqual([]);
        expect(scanJinja2VariablesWithPositions(undefined as any)).toEqual([]);
        expect(scanJinja2VariablesWithPositions({} as any)).toEqual([]);
    });

    it("位置精度可用於 setRange：startIdx..endIdx 的元素串接 = fullMatch", () => {
        const main = textToElements("prefix {{ project_name }} suffix");
        const result = scanJinja2VariablesWithPositions(main);
        expect(result).toHaveLength(1);
        const { startIdx, endIdx, fullMatch } = result[0];
        // 對 mainElements[startIdx..endIdx] 取 value 串起來、應該 = fullMatch
        const reconstructed = main.slice(startIdx, endIdx + 1)
            .map((el: any) => el.value).join("");
        expect(reconstructed).toBe(fullMatch);
    });
});

describe("scanJinja2VariablesInTables (Sprint J)", () => {
    it("找到 table cell 內的變數，含 table/tr/td 座標", () => {
        const main = [
            ...textToElements("前文 "),
            {
                type: "table",
                id: "tbl_1",
                trList: [
                    {
                        tdList: [
                            { value: textToElements("姓名：{{ name }}") },
                            { value: textToElements("公司：{{ company }}") },
                        ],
                    },
                ],
            },
        ];
        const result = scanJinja2VariablesInTables(main);
        expect(result).toHaveLength(2);
        expect(result[0]).toMatchObject({
            varName: "name",
            tableElementIdx: 3,  // "前文 " 佔 3 個 element
            trIdx: 0,
            tdIdx: 0,
            tableId: "tbl_1",
        });
        expect(result[1]).toMatchObject({
            varName: "company",
            tableElementIdx: 3,
            trIdx: 0,
            tdIdx: 1,
            tableId: "tbl_1",
        });
    });

    it("多列多欄 table，座標正確", () => {
        const main = [
            {
                type: "table",
                id: "tbl_x",
                trList: [
                    {
                        tdList: [
                            { value: textToElements("{{ a }}") },
                            { value: textToElements("{{ b }}") },
                        ],
                    },
                    {
                        tdList: [
                            { value: textToElements("{{ c }}") },
                        ],
                    },
                ],
            },
        ];
        const result = scanJinja2VariablesInTables(main);
        expect(result).toHaveLength(3);
        expect(result.map((r: any) => [r.trIdx, r.tdIdx, r.varName])).toEqual([
            [0, 0, "a"],
            [0, 1, "b"],
            [1, 0, "c"],
        ]);
    });

    it("table 無 id 時仍回傳（tableId=null，呼叫者要 fallback）", () => {
        const main = [
            {
                type: "table",
                trList: [{ tdList: [{ value: textToElements("{{ x }}") }] }],
            },
        ];
        const result = scanJinja2VariablesInTables(main);
        expect(result).toHaveLength(1);
        expect(result[0].tableId).toBeNull();
    });

    it("td.value 內含 control 的 match 作廢（複用 main flow 的 sentinel 邏輯）", () => {
        const main = [
            {
                type: "table",
                id: "t1",
                trList: [{
                    tdList: [{
                        value: [
                            ...textToElements("{{ "),
                            { type: "control", value: "X" },
                            ...textToElements("a }}"),
                        ],
                    }],
                }],
            },
        ];
        expect(scanJinja2VariablesInTables(main)).toEqual([]);
    });

    it("非 table 元素跳過、不影響其他 table 處理", () => {
        const main = [
            ...textToElements("nope"),
            { type: "image", value: "" },
            {
                type: "table",
                id: "tt",
                trList: [{ tdList: [{ value: textToElements("{{ ok }}") }] }],
            },
        ];
        const result = scanJinja2VariablesInTables(main);
        expect(result).toHaveLength(1);
        expect(result[0].varName).toBe("ok");
    });

    it("空 / 缺失 trList / tdList 防禦", () => {
        expect(scanJinja2VariablesInTables([])).toEqual([]);
        expect(scanJinja2VariablesInTables([{ type: "table" }])).toEqual([]);
        expect(scanJinja2VariablesInTables([{ type: "table", trList: [] }])).toEqual([]);
        expect(scanJinja2VariablesInTables([{ type: "table", trList: [{}] }])).toEqual([]);
        expect(scanJinja2VariablesInTables([{ type: "table", trList: [{ tdList: [] }] }])).toEqual([]);
        expect(scanJinja2VariablesInTables([{ type: "table", trList: [{ tdList: [{}] }] }])).toEqual([]);
    });

    it("防禦：非陣列回空", () => {
        expect(scanJinja2VariablesInTables(null as any)).toEqual([]);
        expect(scanJinja2VariablesInTables(undefined as any)).toEqual([]);
        expect(scanJinja2VariablesInTables({} as any)).toEqual([]);
    });
});

describe("analyzeScanResults (Sprint Q)", () => {
    it("合併 main + table positions、去重 + 排序 uniqueVars", () => {
        const result = analyzeScanResults({
            scannedAll: [
                { varName: "b", occurrences: 1 },
                { varName: "a", occurrences: 1 },
                { varName: "c", occurrences: 1 },
            ],
            mainPositions: [
                { varName: "b", startIdx: 0, endIdx: 6 },
                { varName: "a", startIdx: 10, endIdx: 16 },
            ],
            tablePositions: [
                { varName: "c", startIdx: 0, endIdx: 6, tableId: "t1" },
            ],
            existingOdooFieldNames: [],
        });
        expect(result.positions).toHaveLength(3);
        expect(result.uniqueVars).toEqual(["a", "b", "c"]);
        expect(result.toCreate).toEqual(["a", "b", "c"]);
        expect(result.cacheHitCount).toBe(0);
        expect(result.skippedCount).toBe(0);
    });

    it("toCreate 過濾掉 existingOdooFieldNames", () => {
        const result = analyzeScanResults({
            scannedAll: [
                { varName: "name", occurrences: 1 },
                { varName: "email", occurrences: 1 },
            ],
            mainPositions: [
                { varName: "name", startIdx: 0, endIdx: 6 },
                { varName: "email", startIdx: 10, endIdx: 16 },
            ],
            tablePositions: [],
            existingOdooFieldNames: ["name"],
        });
        expect(result.uniqueVars).toEqual(["email", "name"]);
        expect(result.toCreate).toEqual(["email"]);
        expect(result.cacheHitCount).toBe(1);
    });

    it("skippedCount = scannedAll 數 − uniqueVars 數 (粗略 list/title proxy)", () => {
        const result = analyzeScanResults({
            scannedAll: [
                { varName: "a", occurrences: 1 },
                { varName: "b", occurrences: 1 },
                { varName: "c", occurrences: 1 },
                { varName: "d", occurrences: 1 },
            ],
            mainPositions: [
                { varName: "a", startIdx: 0, endIdx: 6 },
                { varName: "b", startIdx: 10, endIdx: 16 },
            ],
            tablePositions: [],
            existingOdooFieldNames: [],
        });
        // 4 scanned − 2 replaceable = 2 skipped (c 與 d 可能在 list/title/header)
        expect(result.skippedCount).toBe(2);
    });

    it("uniqueVars 計算只看 positions 不看 scannedAll", () => {
        // scannedAll 含 5 個 var、但 positions 只有 2 個
        const result = analyzeScanResults({
            scannedAll: [
                { varName: "a", occurrences: 1 },
                { varName: "b", occurrences: 1 },
                { varName: "c", occurrences: 1 },
                { varName: "d", occurrences: 1 },
                { varName: "e", occurrences: 1 },
            ],
            mainPositions: [{ varName: "a", startIdx: 0, endIdx: 6 }],
            tablePositions: [{ varName: "b", startIdx: 0, endIdx: 6, tableId: "t" }],
            existingOdooFieldNames: [],
        });
        expect(result.uniqueVars).toEqual(["a", "b"]);
        expect(result.skippedCount).toBe(3);
    });

    it("同一變數在 main + table 重複出現只算一次（dedup）", () => {
        const result = analyzeScanResults({
            scannedAll: [{ varName: "x", occurrences: 3 }],
            mainPositions: [
                { varName: "x", startIdx: 0, endIdx: 6 },
                { varName: "x", startIdx: 10, endIdx: 16 },
            ],
            tablePositions: [
                { varName: "x", startIdx: 0, endIdx: 6, tableId: "t" },
            ],
            existingOdooFieldNames: [],
        });
        expect(result.positions).toHaveLength(3); // 不 dedup positions
        expect(result.uniqueVars).toEqual(["x"]);  // 但 dedup uniqueVars
        expect(result.toCreate).toEqual(["x"]);
    });

    it("空輸入 → 空結果", () => {
        const result = analyzeScanResults({
            scannedAll: [],
            mainPositions: [],
            tablePositions: [],
            existingOdooFieldNames: [],
        });
        expect(result.positions).toEqual([]);
        expect(result.uniqueVars).toEqual([]);
        expect(result.toCreate).toEqual([]);
        expect(result.cacheHitCount).toBe(0);
        expect(result.skippedCount).toBe(0);
    });

    it("防禦：非陣列輸入退化為空陣列", () => {
        const result = analyzeScanResults({
            scannedAll: null as any,
            mainPositions: undefined as any,
            tablePositions: "not array" as any,
            existingOdooFieldNames: { not: "array" } as any,
        });
        expect(result.positions).toEqual([]);
        expect(result.uniqueVars).toEqual([]);
    });
});

describe("computeOrphanRecordIds (Sprint Q)", () => {
    it("回傳在 cache 但不在 controlIds 的 id", () => {
        const cache = [{ id: 1 }, { id: 2 }, { id: 3 }];
        const controlIds = new Set([1, 3]);
        const orphans = computeOrphanRecordIds(cache, controlIds);
        expect(orphans).toEqual(new Set([2]));
    });

    it("空 cache → 空 orphans", () => {
        expect(computeOrphanRecordIds([], new Set([1, 2]))).toEqual(new Set());
    });

    it("空 controlIds → 全部 cache 都是孤兒", () => {
        const cache = [{ id: 10 }, { id: 20 }];
        expect(computeOrphanRecordIds(cache, new Set())).toEqual(new Set([10, 20]));
    });

    it("接受 Array 而非 Set 的 controlIds（自動轉換）", () => {
        const cache = [{ id: 1 }, { id: 2 }, { id: 3 }];
        const orphans = computeOrphanRecordIds(cache, [1]);
        expect(orphans).toEqual(new Set([2, 3]));
    });

    it("cache 含無 id 欄位的元素 → 跳過", () => {
        const cache: any[] = [{ id: 1 }, {}, { id: 3 }, null];
        const orphans = computeOrphanRecordIds(cache, new Set([1]));
        expect(orphans).toEqual(new Set([3]));
    });

    it("防禦：非陣列 cache 回空", () => {
        expect(computeOrphanRecordIds(null as any, new Set([1]))).toEqual(new Set());
        expect(computeOrphanRecordIds(undefined as any, new Set([1]))).toEqual(new Set());
    });

    it("防禦：非 Set/Array controlIds 回 cache 全部（無 id 在空集合中）", () => {
        const cache = [{ id: 1 }, { id: 2 }];
        const orphans = computeOrphanRecordIds(cache, null as any);
        expect(orphans).toEqual(new Set([1, 2]));
    });
});

describe("normalizeMultiCharElements (Sprint T)", () => {
    it("多字元 value 拆成單字元 elements、保留其他屬性", () => {
        const input = [{ value: "Hello", size: 16, color: "#000" }];
        const result = normalizeMultiCharElements(input);
        expect(result).toHaveLength(5);
        expect(result.map((e: any) => e.value)).toEqual(["H", "e", "l", "l", "o"]);
        // 其他屬性 (size/color) 應被 spread 保留
        for (const el of result) {
            expect(el.size).toBe(16);
            expect(el.color).toBe("#000");
        }
    });

    it("單字元 element 原樣回傳", () => {
        const input = [{ value: "x" }, { value: "y" }];
        const result = normalizeMultiCharElements(input);
        expect(result).toEqual(input);
    });

    it("control / table / list / title / valueList / trList 不拆", () => {
        const input = [
            { type: "control", value: "ABC" },           // 不拆
            { type: "table", trList: [] },                // 不拆
            { type: "list", valueList: [] },              // 不拆
            { type: "title", valueList: [{ value: "x" }] }, // 不拆
            { valueList: [{ value: "y" }] },              // 不拆 (僅靠 valueList)
            { trList: [{ tdList: [] }] },                 // 不拆 (僅靠 trList)
        ];
        const result = normalizeMultiCharElements(input);
        expect(result).toEqual(input);
    });

    it("混合：多字元 text + control + 單字元 → 只拆 multi-char text", () => {
        const input = [
            { value: "Hi" },                       // 拆
            { type: "control", value: "X" },       // 不拆
            { value: "z" },                        // 不拆
        ];
        const result = normalizeMultiCharElements(input);
        expect(result.map((e: any) => e.value)).toEqual(["H", "i", "X", "z"]);
    });

    it("含 jinja2 變數的段落被拆成可掃描的單字元", () => {
        const input = [{ value: "Hello {{ name }} world", size: 12 }];
        const result = normalizeMultiCharElements(input);
        // 拆完後 scanJinja2VariablesWithPositions 應該能找到 `{{ name }}`
        const positions = scanJinja2VariablesWithPositions(result);
        expect(positions).toHaveLength(1);
        expect(positions[0].varName).toBe("name");
        expect(positions[0].fullMatch).toBe("{{ name }}");
    });

    it("非陣列防禦", () => {
        expect(normalizeMultiCharElements(null as any)).toEqual([]);
        expect(normalizeMultiCharElements(undefined as any)).toEqual([]);
        expect(normalizeMultiCharElements({} as any)).toEqual([]);
    });

    it("非物件元素原樣帶過", () => {
        const input = [null, undefined, "stringy"];
        const result = normalizeMultiCharElements(input as any);
        expect(result).toEqual(input);
    });
});

describe("normalizeMultiCharElementsInTables (Sprint T)", () => {
    it("遞迴 normalize td.value 內的多字元元素，table 結構保留", () => {
        const input = [
            {
                type: "table",
                id: "t1",
                trList: [
                    {
                        tdList: [
                            { value: [{ value: "Hi" }, { value: "x" }] },
                            { value: [{ value: "{{ name }}" }] },
                        ],
                    },
                ],
            },
        ];
        const result = normalizeMultiCharElementsInTables(input);
        // table 結構保留
        expect(result[0].type).toBe("table");
        expect(result[0].id).toBe("t1");
        // 第一個 td.value: "Hi" 拆成 2 + "x" 保留 = 3 elements
        expect(result[0].trList[0].tdList[0].value).toHaveLength(3);
        expect(result[0].trList[0].tdList[0].value.map((e: any) => e.value))
            .toEqual(["H", "i", "x"]);
        // 第二個 td.value: "{{ name }}" 拆成 10 elements
        expect(result[0].trList[0].tdList[1].value).toHaveLength(10);
        // 拆完後 scanJinja2VariablesInTables 應該能找到 name
        const positions = scanJinja2VariablesInTables(result);
        expect(positions).toHaveLength(1);
        expect(positions[0].varName).toBe("name");
    });

    it("非 table 元素原樣帶過", () => {
        const input = [{ value: "Hello" }, { type: "paragraph", value: "x" }];
        const result = normalizeMultiCharElementsInTables(input);
        expect(result).toEqual(input);
    });

    it("table 無 trList 或無 tdList 防禦", () => {
        expect(normalizeMultiCharElementsInTables([{ type: "table" }])).toEqual([{ type: "table" }]);
        expect(normalizeMultiCharElementsInTables([
            { type: "table", trList: [{ /* no tdList */ }] }
        ])).toEqual([{ type: "table", trList: [{ }] }]);
    });

    it("非陣列防禦", () => {
        expect(normalizeMultiCharElementsInTables(null as any)).toEqual([]);
        expect(normalizeMultiCharElementsInTables(undefined as any)).toEqual([]);
    });
});

describe("flattenElementsToText", () => {
    it("純 text 字元串接", () => {
        expect(flattenElementsToText(textToElements("Hello"))).toBe("Hello");
    });

    it("跳過 control 元素", () => {
        const elements = [
            ...textToElements("A"),
            { type: "control", value: "B" },
            ...textToElements("C"),
        ];
        expect(flattenElementsToText(elements)).toBe("AC");
    });

    it("非陣列 → 空字串", () => {
        expect(flattenElementsToText(null as any)).toBe("");
        expect(flattenElementsToText(undefined as any)).toBe("");
        expect(flattenElementsToText("string" as any)).toBe("");
    });

    it("table 巢狀遞迴", () => {
        const elements = [
            {
                type: "table",
                trList: [
                    {
                        tdList: [
                            { value: textToElements("X") },
                            { value: textToElements("Y") },
                        ],
                    },
                ],
            },
        ];
        expect(flattenElementsToText(elements)).toBe("XY");
    });
});

describe("findMarkerPositionsInMain (Sprint W)", () => {
    it("找到單一 multi-char element 內的 marker", () => {
        // 單一元素：value="專案：__M0__" → marker `__M0__` 在 char 3..9
        const main = [{ value: "專案：__M0__" }];
        expect(findMarkerPositionsInMain(main, "__M0__")).toEqual([
            { startIdx: 3, endIdx: 9 },
        ]);
    });

    it("跨多個 multi-char element 累計 char offset 找到 marker", () => {
        // [專案：(3) ] [__M0__(6)] = 元素邊界 char 3
        const main = [
            { value: "專案：" },
            { value: "__M0__" },
        ];
        expect(findMarkerPositionsInMain(main, "__M0__")).toEqual([
            { startIdx: 3, endIdx: 9 },
        ]);
    });

    it("找到多個 marker 出現", () => {
        const main = [{ value: "__M0__ 與 __M1__" }];
        expect(findMarkerPositionsInMain(main, "__M0__")).toEqual([{ startIdx: 0, endIdx: 6 }]);
        expect(findMarkerPositionsInMain(main, "__M1__")).toEqual([{ startIdx: 9, endIdx: 15 }]);
    });

    it("同 marker 多次出現都回傳", () => {
        const main = [{ value: "A__M__B__M__C" }];
        expect(findMarkerPositionsInMain(main, "__M__")).toEqual([
            { startIdx: 1, endIdx: 6 },
            { startIdx: 7, endIdx: 12 },
        ]);
    });

    it("控制元素以 1 char 占位", () => {
        const main = [
            { value: "A" },
            { type: "control", value: null },
            { value: "B__M__" },
        ];
        // flat 字串：A + (placeholder NUL 1 char) + B__M__ = 8 chars
        // marker `__M__` 起始於 char 3
        expect(findMarkerPositionsInMain(main, "__M__")).toEqual([
            { startIdx: 3, endIdx: 8 },
        ]);
    });

    it("空 input / 空 marker 回傳空陣列", () => {
        expect(findMarkerPositionsInMain([], "__M__")).toEqual([]);
        expect(findMarkerPositionsInMain(null as any, "__M__")).toEqual([]);
        expect(findMarkerPositionsInMain([{ value: "abc" }], "")).toEqual([]);
        expect(findMarkerPositionsInMain([{ value: "abc" }], null as any)).toEqual([]);
    });

    it("marker 不存在回傳空", () => {
        const main = [{ value: "abc def" }];
        expect(findMarkerPositionsInMain(main, "__MISSING__")).toEqual([]);
    });
});

describe("rewriteTdValueWithControls (Sprint X)", () => {
    const mkControl = (varName: string, fieldId: string | number) => ({
        type: "control",
        value: null,
        control: {
            type: "text",
            value: null,
            placeholder: `{{ ${varName} }}`,
            conceptId: String(fieldId),
            deletable: true,
            disabled: false,
        },
    });

    it("拆 multi-char element 內單一 marker → 前段+control", () => {
        const td = [{ value: "__M_a__ 尾巴", size: 20 }];
        const map = new Map([["__M_a__", { fieldId: 7, varName: "a" }]]);
        const { newValue, replaced } = rewriteTdValueWithControls(td, map, mkControl);
        expect(replaced).toBe(1);
        expect(newValue.length).toBe(2);
        expect(newValue[0].type).toBe("control");
        expect(newValue[0].control.conceptId).toBe("7");
        expect(newValue[1].value).toBe(" 尾巴");
    });

    it("拆 marker 在中間 → 前段+control+尾段", () => {
        const td = [{ value: "頭__M_a__尾", size: 20 }];
        const map = new Map([["__M_a__", { fieldId: 7, varName: "a" }]]);
        const { newValue, replaced } = rewriteTdValueWithControls(td, map, mkControl);
        expect(replaced).toBe(1);
        expect(newValue.length).toBe(3);
        expect(newValue[0].value).toBe("頭");
        expect(newValue[1].type).toBe("control");
        expect(newValue[2].value).toBe("尾");
    });

    it("同 element 多個 marker", () => {
        const td = [{ value: "X__M_a__Y__M_b__Z", size: 20 }];
        const map = new Map([
            ["__M_a__", { fieldId: 7, varName: "a" }],
            ["__M_b__", { fieldId: 8, varName: "b" }],
        ]);
        const { newValue, replaced } = rewriteTdValueWithControls(td, map, mkControl);
        expect(replaced).toBe(2);
        expect(newValue.length).toBe(5);
        expect(newValue.map((el: any) => el.type || "text")).toEqual([
            "text", "control", "text", "control", "text",
        ]);
        expect(newValue[1].control.conceptId).toBe("7");
        expect(newValue[3].control.conceptId).toBe("8");
    });

    it("非 text element 原樣保留", () => {
        const ctrlEl = { type: "control", value: null, control: { type: "text", placeholder: "x" } };
        const td = [ctrlEl, { value: "__M_a__", size: 20 }];
        const map = new Map([["__M_a__", { fieldId: 7, varName: "a" }]]);
        const { newValue, replaced } = rewriteTdValueWithControls(td, map, mkControl);
        expect(replaced).toBe(1);
        expect(newValue[0]).toBe(ctrlEl);
        expect(newValue[1].type).toBe("control");
    });

    it("沒 marker 的 element 原樣保留", () => {
        const a = { value: "abc", size: 20 };
        const b = { value: "def", size: 20 };
        const td = [a, b];
        const map = new Map([["__M_x__", { fieldId: 7, varName: "x" }]]);
        const { newValue, replaced } = rewriteTdValueWithControls(td, map, mkControl);
        expect(replaced).toBe(0);
        expect(newValue).toEqual([a, b]);
    });

    it("空 td.value / 空 map / 非 Array 防禦", () => {
        const map = new Map([["__M__", { fieldId: 1, varName: "x" }]]);
        expect(rewriteTdValueWithControls([], map, mkControl).newValue).toEqual([]);
        expect(rewriteTdValueWithControls([{ value: "abc" }], new Map(), mkControl).newValue).toEqual([{ value: "abc" }]);
        expect(rewriteTdValueWithControls(null as any, map, mkControl).newValue).toEqual([]);
    });

    it("保留 text element 的其他樣式屬性", () => {
        const td = [{ value: "X__M_a__Y", size: 24, bold: true, color: "red" }];
        const map = new Map([["__M_a__", { fieldId: 7, varName: "a" }]]);
        const { newValue } = rewriteTdValueWithControls(td, map, mkControl);
        expect(newValue[0]).toEqual({ value: "X", size: 24, bold: true, color: "red" });
        expect(newValue[2]).toEqual({ value: "Y", size: 24, bold: true, color: "red" });
    });
});
