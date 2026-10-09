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
 * 它**不是**要逼人把所有東西接上線。未接的子系統本來就該存在——但要**明確宣告**，
 * 而不是靠沒人發現。
 *
 * ── 為什麼宣告要按「軸」分類（2026-10-09 ADR-034）──────────────────────────
 *
 * 第一版宣告寫的是「Phase N 未啟動」。那個分類法害我在範圍收斂時犯了一個錯：
 * 我用「1:1 Word 匯入」這條線判定 Overlay / CanvasEditor測量 / revision
 * 「不需要」，然後 git rm 掉。**但那三個不是匯入軸的東西**——它們是
 * 「提昇 dobtor_doc_editor 編輯能力」那條軸的資產，用匯入軸的尺量它們，
 * 量出來當然是 0 分。
 *
 * 所以每一條宣告現在都必須寫明它屬於哪一軸，以及**啟動條件**：
 *
 *   import    匯入軸——docx → IElement 的 1:1 重現。要接上線，缺的要補。
 *   editor    編輯器軸——沿用來提昇 dobtor_doc_editor 的編輯能力。
 *   frozen    已凍結——條件不成立（缺前置能力），寫清楚條件、不刪不接。
 *   tooling   開發工具——不該進出貨 bundle，它的消費者是測試或量測腳本。
 *   declined  已評估、決定不接——寫清楚是誰在什麼依據下決定的。
 *
 * 下次稽核請**按軸讀**：看到 editor 軸的檔案不可達，那是正常的，不要拿
 * 匯入軸的理由去刪它。
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

/** 子系統屬於哪一條軸——見檔頭。 */
type Axis = "import" | "editor" | "frozen" | "tooling" | "declined";

/**
 * 宣告為「不可達且可以不可達」的子系統。
 *
 * 每一條都要寫 axis（哪一軸）、why（為什麼現在不可達）、activation（什麼條件
 * 下才該接上線）。這份清單是 2026-10-09 **量出來**的現況，不是目標。
 *
 * ☠️ 不要用別的軸的理由刪掉某一軸的資產——那正是 ADR-034 要防的事。
 */
const DECLARED_UNREACHABLE: {
    prefix: string;
    axis: Axis;
    why: string;
    activation: string;
}[] = [
    // ────────────────────────── 匯入軸（import）──────────────────────────
    {
        prefix: "static/src/core/ooxml/layout/",
        axis: "import",
        why: "Sprint 277-354 的文繞圖多邊形 layout（16 檔 / 2,413 行，15 支 "
           + "vitest）。活的 layout 是 static/src/core/layout/（12 檔 / 4,485 "
           + "行，VR entry 用它的 layoutDocument）。兩套並存，新的那套沒有接。",
        activation: "要接的地方是**比對用管線**（VR），不是匯入管線——"
           + "engine=ts 完全不呼叫 layoutDocument，所以這套排版做到完美，"
           + "編輯器畫面也不會變。條件：VR 出現 Word 文繞圖的 fixture 且"
           + "現行 core/layout 量不出來。",
    },
    {
        prefix: "static/src/core/ooxml/font/Shaping",
        axis: "import",
        why: "HarfBuzz WASM shaping（ShapingEngine / ShapingFontChain）。"
           + "字寬決定換行位置，所以它對 1:1 重現是有效果的。"
           + "活的字型路徑是 core/layout 的 FontMetricsAdapter + "
           + "BrowserTextMetrics（量測用近似值）。",
        activation: "條件：VR 量到的差異可歸因於字寬誤差。接法是讓 "
           + "FontMetricsAdapter 走 ShapingEngine。代價是 ~400KB WASM，"
           + "要 lazy。",
    },
    {
        prefix: "static/src/core/ooxml/font/index.ts",
        axis: "import",
        why: "font/ 的 barrel。它 re-export 整個目錄，而目錄裡大部分還沒接線，"
           + "所以 barrel 自己也不可達。",
        activation: "目錄內任一子系統接上線時，barrel 自然就可達了。",
    },
    {
        prefix: "static/src/core/font_loader.ts",
        axis: "import",
        why: "瀏覽器端字型載入（IDB cache → /dobtor/fonts/<family>）。"
           + "唯一引用者是它自己的 vitest 與 ShapingFontChain.ts。"
           + "☠️ 連帶後果：**/dobtor/fonts/* 那兩條 auth='public' 路由"
           + "（155 行、12 則測試）目前沒有活的消費者**——路由活著、客戶沒接。",
        activation: "跟 ooxml/font/Shaping 同一個條件，它們是同一條相依鏈。",
    },

    // ───────────────────────── 編輯器軸（editor）─────────────────────────
    {
        prefix: "static/src/components/doc_editor/",
        axis: "editor",
        why: "overlay 絕對定位（14 檔 / 2,088 行）。**量過**：DocumentNode / "
           + "IElement 在這 14 檔裡出現 0 次，只吃 Rect{x,y,w,h} / Bounds / "
           + "AlignGuide，import 只有目錄內 5 支自己人——也就是說它跟 ooxml "
           + "parser 沒有耦合，是獨立的幾何運算層。"
           + "核心的 doc.template.field **已經有** pos_x / pos_y / width / "
           + "height（help 寫「overlay 模式專用」）。缺的只有一層 UI。",
        activation: "最可沿用的一塊。規畫書 Phase 8 Phase 2.2 條件是「Phase "
           + "2.1 實測明確不滿意才啟動」——擋在這裡的是**產品判斷**，"
           + "不是技術缺口。詳見該目錄的 README.md。",
    },
    {
        prefix: "static/src/core/ooxml/font/CanvasEditor",
        axis: "editor",
        why: "把真實字型度量橋接進 canvas-editor（11 檔）。對編輯器有直接"
           + "效果：字寬準 → 換行準。相依鏈 CanvasEditor* → TextMeasureProxy "
           + "→ ShapingEngine。",
        activation: "條件：編輯器換行與 Word 不一致且已歸因到字寬。"
           + "風險：它 patch 第三方（canvas-editor）內部——"
           + "CanvasEditorPatchProbe.ts 存在就是因為有這個風險。"
           + "另需真字型（/dobtor/fonts/* 與 font_loader.ts 都在但沒接）。",
    },
    {
        prefix: "static/src/core/ooxml/font/TextMeasureProxy.ts",
        axis: "editor",
        why: "CanvasEditor* 與 ShapingEngine 之間的那一層 proxy。"
           + "單獨列出來是因為它的名字不以 CanvasEditor 開頭，"
           + "但它只有 CanvasEditor* 這一組客戶。",
        activation: "同 ooxml/font/CanvasEditor。",
    },

    // ───────────────────────── 已凍結（frozen）──────────────────────────
    {
        prefix: "static/src/core/ooxml/revision/",
        axis: "frozen",
        why: "修訂追蹤審閱（接受／拒絕變更，13 檔 / 2,139 行）。"
           + "**量過**：DocumentNode 出現 38 次、IElement 出現 0 次"
           + "——它完全長在 parser 的 AST 上，而編輯器吃的是 IElement。",
        activation: "離可用最遠的一塊，要三件前置條件**同時**成立："
           + "(1) IElement → DocumentNode 的反向 mapper（不存在）；"
           + "(2) 編輯器本身會產生 w:ins / w:del（canvas-editor 不會）；"
           + "(3) 有人要這個功能。"
           + "三件都不成立之前不要動它，也不要因為它不可達就刪它。",
    },

    // ───────────────────────── 開發工具（tooling）─────────────────────────
    {
        prefix: "static/src/core/ooxml/export/",
        axis: "tooling",
        why: "OoxmlWriter（2 檔 / 2,297 行）。☠️ 我原本判它『可刪』是**錯的**"
           + "——它是 65 支測試的 round-trip oracle："
           + "AST → write → unzip → re-parse → 驗證資訊沒丟。"
           + "它是**證明 parser 真的留住了 Word 資訊**的工具。",
        activation: "不該進出貨 bundle，它的消費者是測試。"
           + "這一條永遠不會『接上線』，不要再把它當孤兒。",
    },

    // ───────────────────── 已評估、決定不接（declined）─────────────────────
    {
        prefix: "static/src/core/ooxml/worker/",
        axis: "declined",
        why: "Web Worker 平行解析（17 檔 TS + 1 支 node entry / 2,477 行）。"
           + "☠️ **它自己的檔頭就寫了不該做**：Sprint 197 final audit 判定"
           + "「不建議」（cost/benefit marginal、cache 五連發已經 ~10x warm "
           + "path 加速、真實文件只有 20-50 頁），是 explicit OVERRIDE 之下"
           + "做出來的 SPIKE-only；第一個 sprint 就寫明「不啟動真實 Worker"
           + "（structured clone of AST 的 Map/class 風險未解）」。"
           + "三個 dispatcher 全部是 PROBE / spike / 不啟動。"
           + "之後 Sprint 307/312/317/322 又在這個地基上疊了 pool、"
           + "load balancer、circuit breaker、health monitor 四輪。",
        activation: "**決定：不接**（2026-10-09，使用者指示「留在 "
           + "dobtor_doc_import，先不接」）。留著是因為它有 51 支測試、"
           + "刪掉會一併失去那些測試記錄的設計意圖。"
           + "真要接的前置條件是先解掉 structured clone："
           + "已驗證 AST 滿是 Map（FontTable / StyleMap / NumberingMap / "
           + "headers），parse_docx_cli.ts 就得用 replacer 處理它們。",
    },
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
    // ☠️ 排除 *.d.ts。宣告檔是 ambient 型別，**本質上不會被 import**
    //    （FontMetrics.ts 寄託 opentype.js 的那一份就是這樣），把它算進
    //    「必須可達」的集合是分類錯誤——這一則真的在我加
    //    static/src/core/types/opentype.d.ts 時紅了。
    //    這**不是漏洞**：TypeScript 禁止宣告檔裝實作，所以沒有人
    //    能利用 .d.ts 藏一段「存在但不執行」的執行期程式碼。
    const allTs = globSync("static/src/**/*.ts", { cwd: MODULE_ROOT, nodir: true })
        .map((p) => p.replace(/\\/g, "/"))
        .filter((p) => !p.endsWith(".d.ts"));
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

    it("每一條宣告都要標軸，而且要寫啟動條件（ADR-034）", () => {
        // ☠️ 這一則是上一次收斂犯錯的直接補救：沒有軸，下一個人就會拿
        //    匯入軸的尺去量編輯器軸的資產，量出 0 分然後刪掉它。
        const AXES = ["import", "editor", "frozen", "tooling", "declined"];
        for (const d of DECLARED_UNREACHABLE) {
            expect(AXES, `${d.prefix} 的 axis 不合法：${d.axis}`).toContain(d.axis);
            expect(
                d.activation.length,
                `${d.prefix} 沒寫啟動條件——「什麼情況下才該接上線」是這份清單`
                + `最重要的資訊，缺了它下次稽核就只能重新推論一遍。`,
            ).toBeGreaterThan(20);
        }
    });

    it("宣告清單裡的前綴不可以互相包含（避免歸錯軸還沒人發現）", () => {
        // font/ 底下刻意拆成 Shaping（匯入軸）/ CanvasEditor（編輯器軸）/
        // TextMeasureProxy（編輯器軸）/ index.ts 四條。拆得這麼細就必須擋住
        // 「有人圖方便加一條 font/ 把四條全蓋掉」——那會讓軸別資訊消失。
        const prefixes = DECLARED_UNREACHABLE.map((d) => d.prefix);
        const overlaps: string[] = [];
        for (const a of prefixes) {
            for (const b of prefixes) {
                if (a !== b && b.startsWith(a)) overlaps.push(`${a} ⊃ ${b}`);
            }
        }
        expect(
            overlaps,
            `下列宣告互相包含，較寬的那條會把較窄的軸別資訊蓋掉：\n  `
            + overlaps.join("\n  "),
        ).toEqual([]);
    });

    it("每一條宣告都真的蓋到至少一個檔案（不准留空殼宣告）", () => {
        // 「宣告過期」那一則擋的是「全部接上線了」；這一則擋的是
        // 「檔案被刪了但宣告還在」——兩種過期的形狀不一樣。
        const allTsSet = new Set(allTs);
        const empty = DECLARED_UNREACHABLE
            .filter((d) => ![...allTsSet].some((p) => p.startsWith(d.prefix)))
            .map((d) => d.prefix);
        expect(
            empty,
            `下列前綴底下已經沒有任何 .ts 檔了（檔案刪了、宣告沒清）：\n  `
            + empty.join("\n  "),
        ).toEqual([]);
    });

    it("記錄現況：可達 / 不可達的檔數（數字變動時這一則會告訴你）", () => {
        // 不鎖死數字——鎖死會讓每次正常增刪都紅。只確認比例沒有失控：
        // 不可達不應該超過總數的 60%（2026-10-09 當下是 78/154 = 50.6%）。
        const ratio = unreachable.length / allTs.length;
        expect(
            ratio,
            `不可達比例 ${(ratio * 100).toFixed(1)}%（${unreachable.length}/${allTs.length}）`
            + `——超過 60% 表示這個模組大半的程式碼都沒有接上線，該停下來決定`
            + `要接還是要刪，而不是繼續加。`,
        ).toBeLessThan(0.6);
    });
});
