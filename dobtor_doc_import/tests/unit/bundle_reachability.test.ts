/**
 * bundle_reachability.test.ts — 守住「哪些 TS 真的進得了 build 產物」
 *
 * ☠️ 這支測試存在的理由，是 2026-10-09 整天反覆出現的同一個失效模式：
 *
 *   tools/dist/parse_docx_cli.cjs      被 .gitignore 排除 → engine=ts 從沒運作過
 *   canvas-editor-custom.umd.js        從未掛進 manifest → 瀏覽器端 parser 從沒執行
 *   visual_regression_pipeline.iife.js 沒有任何 script 會建它 → VR 一跑就 exit 2
 *   components/doc_editor/Overlay*.ts  三個 rollup entry 都到不了
 *   .github/workflows/*                寫好了從沒推、schedule 只從預設分支讀
 *
 * 共同點：**存在但不執行，而且不會報錯**。靜態檢查抓不到（檔案都在）、
 * 測試抓不到（測試直接 import 它們，不經 bundle）、人也看不出來。
 *
 * 這支把「可達性」變成一個**會紅的事實**：
 *   - 有東西新變成不可達 → 紅（你剛寫的程式碼進不了任何產物）
 *   - 宣告為不可達的東西變可達 → 也紅（提醒把宣告改掉）
 *
 * 它**不是**要逼人把所有東西接上線。未接的子系統（phase 尚未啟動）本來就該
 * 存在——但要**明確宣告**，而不是靠沒人發現。
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { globSync } from "glob";
import { dirname, resolve } from "node:path";

const MODULE_ROOT = resolve(__dirname, "../..");

/** rollup 的三個入口——產物分別是 UMD bundle、node CLI、VR pipeline。 */
const ENTRIES = [
    "static/src/core/ooxml/index.ts",
    "tools/parse_docx_cli.ts",
    "tools/visual_regression_pipeline.entry.ts",
];

/**
 * 宣告為「不可達且可以不可達」的子系統。
 *
 * 每一條都要寫**為什麼**。這份清單是 2026-10-09 量出來的現況，不是目標。
 */
const DECLARED_UNREACHABLE: { prefix: string; why: string }[] = [
    {
        prefix: "static/src/core/ooxml/worker/",
        why: "Phase 7 效能：Web Worker 解析。規畫書 §5 的 Phase 7 未完成，"
           + "pipeline 目前是同步的。17 檔 / 2,382 行，有 3 支 vitest。",
    },
    {
        prefix: "static/src/core/ooxml/layout/",
        why: "Sprint 277-354 的文繞圖多邊形 layout。活的 layout 是 "
           + "static/src/core/layout/（VR entry 用它的 layoutDocument）。"
           + "16 檔 / 2,413 行，有 15 支 vitest。",
    },
    {
        prefix: "static/src/core/ooxml/font/",
        why: "Phase 2 的 HarfBuzz shaping 與字型鏈。15 檔中**只有 "
           + "FontMetrics.ts 可達**（被 core/layout/FontMetricsAdapter 用），"
           + "其餘 14 檔（ShapingEngine / ShapingFontChain / glyph cache…）"
           + "沒有接上線。活的字型路徑是 core/layout 的 FontMetricsAdapter + "
           + "BrowserTextMetrics。**/dobtor/fonts/* 兩條路由的客戶在這裡面**，"
           + "所以那兩條目前沒有活的消費者。",
    },
    {
        prefix: "static/src/components/doc_editor/",
        why: "Phase 8 Phase 2.2（overlay 絕對定位），規畫書 §5 是 [ ] 未啟動。"
           + "詳見該目錄的 README.md。14 檔 / 2,088 行。",
    },
    {
        prefix: "static/src/core/ooxml/revision/",
        why: "修訂追蹤（接受／拒絕變更）。parser 讀得到 w:ins / w:del，但"
           + "審閱流程沒有接進任何 pipeline。13 檔 / 2,139 行。",
    },
    {
        prefix: "static/src/core/ooxml/export/",
        why: "Phase 6 匯出對稱性（OoxmlWriter）。規畫書標為『選做』。"
           + "2 檔 / 2,297 行。",
    },
    {
        prefix: "static/src/core/font_loader.ts",
        why: "瀏覽器端字型載入（IDB cache → /dobtor/fonts/<family>）。"
           + "唯一引用者是它自己的 vitest。",
    },
    // ☠️ 這裡原本還宣告了 core/cache/layout_cache.ts「不可達」——**錯的**。
    //    我是從「VR entry 的 import 清單裡沒有它」推論的，沒有實際跑可達性；
    //    它其實經由別的檔案被帶進來。這一則測試自己抓到了這個錯誤宣告
    //    （「宣告為不可達的東西不可以已經變成可達」那一項）。
    //    **推論不能代替量測**，連寫這支測試的人也一樣。
];

function resolveImport(fromFile: string, spec: string): string | null {
    const base = resolve(dirname(fromFile), spec);
    for (const ext of ["", ".ts", ".tsx", ".js", ".mjs", "/index.ts"]) {
        const candidate = base + ext;
        try {
            readFileSync(candidate);
            return candidate;
        } catch {
            /* 試下一個後綴 */
        }
    }
    return null;
}

/** 從入口出發，沿相對 import 走出可達集。 */
function reachable(entries: string[]): Set<string> {
    const seen = new Set<string>();
    const stack = entries.map((e) => resolve(MODULE_ROOT, e));
    // ☠️ 兩種形式都要抓：`from './x'` 與 side-effect 的 `import './x'`。
    //    只抓前者會漏掉純副作用的 import（量 reachability 時第一版就漏了）。
    const PATTERN = /(?:from\s+|import\s+)['"](\.[^'"]+)['"]/g;
    while (stack.length) {
        const file = stack.pop()!;
        if (seen.has(file)) continue;
        let text: string;
        try {
            text = readFileSync(file, "utf8");
        } catch {
            continue;
        }
        seen.add(file);
        for (const m of text.matchAll(PATTERN)) {
            const target = resolveImport(file, m[1]);
            if (target) stack.push(target);
        }
    }
    return seen;
}

function relative(abs: string): string {
    return abs.slice(MODULE_ROOT.length + 1).replace(/\\/g, "/");
}

describe("build 產物的可達性", () => {
    const live = new Set([...reachable(ENTRIES)].map(relative));
    const allTs = globSync("static/src/**/*.ts", { cwd: MODULE_ROOT, nodir: true })
        .map((p) => p.replace(/\\/g, "/"));
    const unreachable = allTs.filter((p) => !live.has(p)).sort();
    const declared = (p: string) =>
        DECLARED_UNREACHABLE.find((d) => p.startsWith(d.prefix));

    it("三個 rollup entry 都解析得到（入口打錯會讓整份檢查變成空集）", () => {
        for (const e of ENTRIES) {
            expect(live.has(e), `入口不可達：${e}`).toBe(true);
        }
        expect(live.size).toBeGreaterThan(50);
    });

    it("沒有**未宣告**的不可達檔案", () => {
        const undeclared = unreachable.filter((p) => !declared(p));
        expect(
            undeclared,
            `下列檔案進不了任何 build 產物，而且不在 DECLARED_UNREACHABLE 裡。\n`
            + `這通常意味著「剛寫的程式碼沒有接上線」——那種狀態不會報錯，所以靠`
            + `這一則擋。\n要嘛把它接進某個 entry，要嘛加進宣告清單並寫明為什麼：\n  `
            + undeclared.join("\n  "),
        ).toEqual([]);
    });

    it("宣告為不可達的東西，不可以已經全部接上線（宣告過期）", () => {
        // ☠️ 判準是「該前綴下**完全沒有**不可達的檔案」才算宣告過期。
        //    第一版寫成「只要有一個檔可達就算過期」，結果 ooxml/font/ 被誤判
        //    ——那個目錄 15 檔裡有 1 檔（FontMetrics.ts）是可達的，其餘 14 檔
        //    不是。子系統**部分接線**是常態，不是宣告過期。
        const stale = DECLARED_UNREACHABLE
            .filter((d) => !unreachable.some((p) => p.startsWith(d.prefix)))
            .map((d) => d.prefix);
        expect(
            stale,
            `下列前綴已經被某個 entry 用到了，宣告過期——請從 `
            + `DECLARED_UNREACHABLE 移除：\n  ${stale.join("\n  ")}`,
        ).toEqual([]);
    });

    it("每一條宣告都要有理由（不准只寫前綴）", () => {
        for (const d of DECLARED_UNREACHABLE) {
            expect(d.why.length, `${d.prefix} 的 why 太短`).toBeGreaterThan(20);
        }
    });

    it("記錄現況：可達 / 不可達的檔數（數字變動時這一則會告訴你）", () => {
        // 不鎖死數字——鎖死會讓每次正常增刪都紅。只確認比例沒有失控：
        // 不可達不應該超過總數的 60%（2026-10-09 當下是 84/160 = 52.5%）。
        const ratio = unreachable.length / allTs.length;
        expect(
            ratio,
            `不可達比例 ${(ratio * 100).toFixed(1)}%（${unreachable.length}/${allTs.length}）`
            + `——超過 60% 表示這個模組大半的程式碼都沒有接上線，該停下來決定`
            + `要接還是要刪，而不是繼續加。`,
        ).toBeLessThan(0.6);
    });
});
