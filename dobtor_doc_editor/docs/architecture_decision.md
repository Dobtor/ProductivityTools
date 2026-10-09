# Architecture Decision Records — dobtor_doc_editor Track B

**建立日期**：2026-04-21
**最後彙整**：2026-05-17（Sprint 118 — §0 索引 + §0.5 規畫書 §3 對映 + ADR-021）
**適用範圍**：Track B（Canvas OOXML 完整渲染引擎），Phase 0 架構基準
**狀態**：Phase 0 確定，Phase 1+ 執行中持續更新

---

## 0. ADR 索引（Sprint 118 彙整）

23 個 ADR。編號 004-007 為歷史保留缺口（早期 numbering、無 ADR 文件）。

| # | 主題 | Sprint / Phase | 一句話 |
|---|---|---|---|
| 001 | canvas-editor 修改策略 | Phase 0 | npm build pipeline + patch-package，rollup 打 UMD |
| 002 | OOXML Parser 架構 | Phase 0 | 獨立 TypeScript 模組、Parser/Renderer 解耦 |
| 003 | Golden File 測試策略 | Phase 0 | LibreOffice headless 當 reference renderer + pixelmatch |
| 004-007 | （歷史缺口） | — | 早期未編 ADR 文件、僅留 audit doc |
| 008 | Phase A + B Exit Report | Sprint 0-2 | Build 鏈通電 + 6 stub Parser + 183 unit tests |
| 009 | Phase D Exit Report | — | （詳見 §ADR-009） |
| 010 | Phase E Exit Report | — | Backend 並行通道 |
| 011 | Phase F.1+F.2+F.3 Exit Report | 2026-05-06 | 視覺基線 Pipeline 建立 |
| 012 | Phase 4 Exit Report | 2026-05-06 | Style/Theme/Border 補完、diff% 未動 |
| 013 | 轉路線 A | Sprint 50 | 商業化先行 + Phase 7 效能優化 |
| 014 | FontMetricsAdapter | Sprint 62 | 用 LibreOffice 系統 fallback fonts 對齊 metric anchor |
| 015 | Portal lazy load font | Sprint 64b | Strategy B 為 production font 供應 |
| 016 | `fill_template` PDF graceful fallback | Sprint 70 | 紀律 #11 第一應用 |
| 017 | `doc_zip_guard.py` 設計 | Sprint 71 | 純記憶體運算、避開 filesystem（紀律 #11 例外） |
| 018 | CONTRIBUTING.md 補完 | Sprint 67 | Phase 0 唯一未完項收口 |
| 019 | `run_backend_tests.sh` | Sprint 72 | 統一 21 個 backend tests、紀律 #13 候選 |
| 020 | Autonomous docs sprint 範式 | Sprint 73-74 | glossary + retro 是有實質產出的 sprint |
| **021** | **Portal cross-company collaboration by collaborator_ids** | **Sprint 117** | **不加 company filter、collaborator_ids 即 explicit access grant、配合 lock-in test 防回歸** |
| 022 | 後台 UI 擴充為範本欄位拖曳建構器 | Phase 8 | （本文件已有 §ADR-022，先前漏列於索引） |
| **023** | **報表管線（藥丸／快照）與 QWeb 轉換器** | **2026-09～10** | **範本＋綁定取代「每張報表一支程式」；轉換器只轉不搬；標記與取值分離；失敗策略逐層明寫** |
| **024** | **型別→格式只有一份表、欄位標籤走欄位定義、模型自備值、附頁** | **2026-10-08** | **對照 report_extend_bf 的 `bf_` 引用設計；格式規則收斂到渲染層，標籤取 `fields_get` 的 string，整合者用 `doc_report_values()` 而不是擴白名單** |
| **025** | **記錄這一側的三個約定方法（自備附頁、附頁開關、範本覆寫）＋「轉成列印範本」入口** | **2026-10-08** | **對照 report_extend_bf 的 `bf.extend`：綁定管不到的事交給記錄自己說；精靈的入口搬到報表與 qweb 範本上** |
| **026** | **前後端都分層（render 六層、doc_editor 四層）** | **2026-10-08～09** | **拆的理由不是檔案太大，是每一層的不變量沒有地方可寫；驗證靠「成員逐一比對 + 程式碼行多重集」而不是靠測試** |
| **027** | **HTML → content_json 只處理自己的子集，`noupdate` 資料靠 migration** | **2026-10-09** | **對任意 HTML 不可靠（需要瀏覽器端的 executeSetHTML），但對我們自己寫的 12 個標籤可靠；資料檔是 noupdate，改 XML 到不了既有庫** |
| **028** | ~~CI 分兩層~~ **撤回：不做 GitHub Actions CI** | **2026-10-09** | 專案決定當天撤回；撤回前量到的三個前提留在 ADR 本文（schedule 只從預設分支讀、paths 要含 workflow 自己、第一次執行就紅在檢查自己）|
| **029** | **移除未出貨的 TS OOXML 子系統** | **2026-10-09** | 76k 行測試＋33k 行原始碼＋82MB fixture 不產生 production 行為；回退 tag `doc-editor-before-ts-removal` |
| **030** | **授權 LGPL-3 → OPL-1** | **2026-10-09** | Dobtor 統一政策；depends 全 LGPL-3 核心（無 AGPL）、自有檔案零授權標頭、隨附第三方皆寬鬆式（JSZip 雙授權選 MIT）|
| **031** | **移除模組內的 Claude Code hooks** | **2026-10-09** | 573 行、4 支 hook；它要求的三層 SOP 與 sprint artifact 都已不存在，且實測已不生效。紀律本身保留在 CONTRIBUTING §5 |
| **032** | **取回 TS OOXML 子系統＋補上從未接上的兩條線** | **2026-10-09** | CLI 產物進版控（`!tools/dist/`）、bundle 掛進 manifest 並加瀏覽器端消費者；三道守門員都驗過會紅 |
| **033** | **檔案匯入拆成 dobtor_doc_import** | **2026-10-09** | 核心 0 行 TS / 36 條路由；新模組 33,076 行 TS、3,059 則 vitest、82MB fixture、5 條路由。跨模組介面只有四個 |

---

## 0.5 規畫書 §3 架構總圖 ↔ ADR 對映（Sprint 118 彙整）

規畫書 §3「架構總圖」列 6 層（Owl Component / Importer / Layer 1-6）。對應 ADR 落地紀錄：

| 規畫書層次 | 職責 | 主要 ADR |
|---|---|---|
| Owl Component（doc_editor.js）| AutoSave / Leader Election / 欄位變數 | ADR-001（容器整合 + UMD build）|
| Layer 1 Package | jszip / ContentTypes / Relationships / Parts 索引 | ADR-002（OOXML 模組結構含 package/）|
| Layer 2 OOXML AST Parser | document/styles/numbering/theme/settings/fontTable/footnotes/headers* | ADR-002、ADR-008（Phase A+B 完整 parser）、ADR-012（Style/Theme/Border） |
| Layer 3 Style Resolver | docDefaults → theme → basedOn → direct → flatten | ADR-008（StyleResolver/ThemeResolver）、ADR-012 |
| Layer 4 Layout Engine | Text shaping / line breaking / pagination / table / float / multi-col / footnote | ADR-014（FontMetricsAdapter 走進 metric anchor）、ADR-013（Sprint 50 轉路線）、Phase 3 audit docs（sprint34-49）|
| Layer 5 Canvas Renderer | DPR / 虛擬化 / 字型載入 / glyph 快取 / 游標選取 | ADR-015（portal lazy load font）、ADR-001（canvas-editor fork 保留 cursor/IME）|
| Layer 6 Interaction | IME / hit-testing / Undo-Redo / Copy-Paste | ADR-001（保留 canvas-editor 基礎設施段）|
| 横切：產品化 | CI / Zip guard / Portal ACL / Backend tests | ADR-016 / 017 / 018 / 019 / 020 / 021 |

橫切的 security / portal / ops 議題（ADR-016 起）不對映單一 §3 層，屬規畫書 §Phase 4.5 產品化基礎建設範疇。

---

## ADR-001：canvas-editor 修改策略 — npm Build Pipeline + patch-package

### 背景

Track B 需要對 `@hufe921/canvas-editor` 的核心模組進行深度修改：

- **Layout Engine**（`editor/core/draw/`）：完全不支援 Word 表格模型
- **Table Renderer**：不計算 gridSpan / vMerge
- **Section/Page 管理**：單節架構，不支援多節 sectPr
- **Text Shaping Pipeline**：使用 `ctx.measureText()`，精度不足
- **Float Manager**：無浮動元素管理

**Phase 0 發現**：canvas-editor 目前以 **UMD bundle 形式 vendor 在 `static/src/lib/canvas_editor/`**，
並非透過 npm 安裝，`patch-package` 的前提條件（npm node_modules）不存在。
直接修改 minified UMD（方案 A）更不可行——無法在混淆程式碼上實作複雜的 AST Parser。

評估方案：

| 方案 | 說明 | 可行性 |
|------|------|--------|
| A. 直接修改 vendor UMD | 最簡單 | ❌ minified 程式碼無法實作 Parser / Layout Engine |
| B. 完整 fork npm 倉庫 | 乾淨但獨立 | ⚠️ 需維護獨立 repo，upstream 更新難合併 |
| **C. 模組內 npm pipeline + patch-package** | **版控追蹤 diff，build 出新 UMD** | **✅ 推薦** |

### 決策：在模組根目錄建立 npm Build Pipeline

**架構**：
1. `dobtor_doc_editor/package.json` — 宣告 `@hufe921/canvas-editor` 為 npm dependency
2. `patch-package` 修改 node_modules 內的 canvas-editor 原始碼，diff 存入 `patches/`
3. **Rollup**（非 Vite）將我們的 OOXML TypeScript Parser + 修改後的 canvas-editor 打包成一個 UMD
4. 輸出 `static/src/lib/canvas_editor/canvas-editor-custom.umd.js`，由 Odoo 靜態資源系統載入

> **為何選 Rollup 而非 Vite**：我們要的是 library bundle（UMD 格式），不是 web app 開發伺服器。
> Rollup 輕量、專為 library 設計，Vite 底層 production build 本身也是用 Rollup。

**Git 追蹤策略**：

| 項目 | 追蹤方式 |
|------|---------|
| `package.json` / `package-lock.json` | ✅ 進 git |
| `static/src/core/ooxml/**/*.ts`（我們的原始碼）| ✅ 進 git |
| `patches/*.patch`（canvas-editor 修改 diff）| ✅ 進 git |
| `static/src/lib/canvas_editor/canvas-editor-custom.umd.js`（build 產出）| ✅ 進 git（Odoo 需要靜態檔案）|
| `node_modules/`                         | ❌ `.gitignore` |

### Build Pipeline 設定檔

詳見專案根目錄的 `package.json`、`rollup.config.js`、`tsconfig.json`。

### 日常工作流程

```bash
# 初始設定（只需一次）
cd e:/work/system/addons/dobtor_doc_editor
npm install

# 修改 canvas-editor 後記錄 patch
npx patch-package @hufe921/canvas-editor

# 重新 build（修改 OOXML Parser 或 patch 後執行）
npm run build:frontend

# 監聽模式（開發中使用）
npm run build:watch
```

### patch 目錄結構

```
patches/
└── @hufe921+canvas-editor+0.9.128.patch   # canvas-editor 修改 diff（自動產生）
```

### 注意事項

- canvas-editor 升版時（0.9.128 → 新版），需重新 `npm install`、套用 patch、確認衝突
- **不需替換的模組**（保留原始）：IME 處理、游標 hit-testing、Undo/Redo、Copy/Paste、基本 Canvas 渲染基礎設施
- build 產出的 `canvas-editor-custom.umd.js` 要同步更新 `__manifest__.py` 的靜態資源參照

---

## ADR-002：OOXML Parser 設計 — 獨立 TypeScript 模組

### 背景

canvas-editor 目前走 `mammoth.js → HTML → canvas-editor 內部格式` 的轉換路徑，在複雜表格（gridSpan/vMerge）、多節頁面、浮動圖片上嚴重失真。

需要一個能直接解析 OOXML（`.docx` ZIP 結構）並輸出精確 AST 的 Parser，作為 Track B 的資料層。

### 決策：獨立 TypeScript 模組，輸出標準 AST

**模組位置**：`static/src/core/ooxml/`

**核心原則**：Parser 與 Renderer 完全解耦——Parser 只負責將 OOXML 轉為 AST，不接觸任何 Canvas API。

### 模組結構

```
static/src/core/ooxml/
├── index.ts                  # 主入口：OoxmlParser class
├── package/
│   ├── PackageReader.ts      # ZIP 解包，[Content_Types].xml, _rels/ 解析
│   └── PartResolver.ts       # 部件路徑解析（相對 → 絕對）
├── units/
│   └── Units.ts              # EMU → px, twips → pt, half-pt → pt
├── styles/
│   ├── StyleResolver.ts      # styles.xml 繼承鏈（docDefaults → style → direct format）
│   └── ThemeResolver.ts      # theme/theme1.xml 色彩/字型映射
├── document/
│   ├── DocumentParser.ts     # word/document.xml 主解析器
│   ├── ParagraphParser.ts    # <w:p> → ParagraphNode
│   ├── RunParser.ts          # <w:r> → RunNode（含 rPr 格式）
│   └── FieldParser.ts        # fldChar / instrText → FieldNode（PAGE, DATE 等）
├── table/
│   ├── TableParser.ts        # <w:tbl> → TableNode（含 gridCol 計算）
│   ├── RowParser.ts          # <w:tr> → RowNode（含 tblHeader, cantSplit）
│   ├── CellParser.ts         # <w:tc> → CellNode（含 gridSpan, vMerge 解析）
│   └── GridResolver.ts       # 計算每個 Cell 的 (gridCol, gridSpan, rowSpan)
├── numbering/
│   └── NumberingResolver.ts  # numbering.xml → lvl 格式 + lvlRestart 支援
├── section/
│   └── SectionParser.ts      # sectPr → SectionNode（頁面尺寸、頁距、多欄）
├── drawing/
│   ├── InlineDrawingParser.ts  # <wp:inline> → InlineImageNode
│   └── AnchorDrawingParser.ts  # <wp:anchor> → FloatImageNode（含位置/繞排策略）
├── header-footer/
│   └── HeaderFooterParser.ts   # header1.xml / footer1.xml（奇偶頁/首頁）
└── ast/
    └── types.ts              # 完整 AST 型別定義（所有 Node 介面）
```

### AST 型別設計原則

```typescript
// ast/types.ts（節錄關鍵型別）

/** 文件根節點 */
interface DocumentNode {
  type: 'document';
  sections: SectionNode[];
  styles: StyleMap;
  numbering: NumberingMap;
}

/** 表格節點（含已解算的 grid 資訊） */
interface TableNode {
  type: 'table';
  grid: number[];          // 每欄寬度（EMU）
  rows: RowNode[];
  style?: string;          // tblStyle 引用
}

/** 儲存格節點（gridSpan / rowSpan 已計算） */
interface CellNode {
  type: 'cell';
  gridCol: number;         // 起始 grid column（0-indexed，累計 gridSpan 後）
  gridSpan: number;        // 橫向佔格數
  rowSpan: number;         // 縱向佔格數（由 vMerge 推算）
  isContinuation: boolean; // true = 此格是上方 vMerge 的延續（渲染時跳過）
  content: ParagraphNode[];
  borders: CellBorders;
}

/** 行高度量介面（Phase 1 預留，Phase 2 由 HarfBuzz WASM 實作） */
interface LineMetrics {
  ascender: number;    // 字型 ascender（pt）
  descender: number;   // 字型 descender（pt）
  lineGap: number;     // 字型建議行距（pt）
  // 注意：不依賴 ctx.measureText()，由字型檔案直接讀取
  // Phase 1 暫用 ctx.measureText() 佔位，但必須透過此介面封裝
  // 確保 Phase 2 引入 HarfBuzz WASM 時 Layout Engine 無需重寫
}
```

### GridResolver 演算法（vMerge 核心）

vMerge 的欄位索引不能用一般陣列索引，因為 gridSpan 會打亂對應關係。必須累計 grid 位置：

```typescript
// GridResolver.ts（虛擬碼）
// 注意：需要兩次 pass
// Pass 1：掃描所有 vMerge=restart 的 Cell，計算各自的 rowSpan
// Pass 2：根據 Pass 1 結果，標記所有 isContinuation = true 的 Cell

function resolveGrid(rows: RawRow[]): ResolvedRow[] {
  const pendingMerge: Map<number, number> = new Map(); // gridCol → 剩餘 rowSpan

  return rows.map(row => {
    let gridCol = 0;
    const cells = row.rawCells.map(rawCell => {
      // 跳過被 vMerge 佔用的 grid 位置
      while ((pendingMerge.get(gridCol) ?? 0) > 0) {
        pendingMerge.set(gridCol, pendingMerge.get(gridCol)! - 1);
        gridCol++;
      }

      const span = rawCell.gridSpan ?? 1;
      const isStart = rawCell.vMerge === 'restart';
      const isContinuation = rawCell.vMerge === 'continue';

      if (isStart) {
        for (let i = 0; i < span; i++) {
          pendingMerge.set(gridCol + i, /* rowSpan 由 Pass 1 計算 */ 0);
        }
      }

      const resolved = { gridCol, gridSpan: span, isContinuation };
      gridCol += span;
      return resolved;
    });
    return { cells };
  });
}
```

---

## ADR-003：Golden File 測試策略 — LibreOffice + pixelmatch

### 背景

Track B 的目標是 A- 級還原度（pixelmatch diff < 5%）。需要一個自動化的基準測試機制，在每次修改 Renderer 後量化還原度是否進步或退步。

### 決策：LibreOffice 作為 Ground Truth，pixelmatch 作為量化工具

**流程**：

```
DOCX fixture
    │
    ├─ LibreOffice headless ──→ PNG（Ground Truth / golden）  ← 在 Docker 執行
    │                                 │
    └─ canvas-editor render ──→ PNG ──┴──→ pixelmatch ──→ diff%  ← 在本機執行
                                                           │
                                              diff < 5%  ✅ Pass
                                              diff ≥ 5%  ❌ Fail（輸出 diff image）
```

### 執行環境分工（重要）

| 腳本 | 執行環境 | 原因 |
|------|---------|------|
| `generate_golden.sh`（LibreOffice）| **Docker 容器**（system-odoo）| 已有 `/usr/bin/soffice` + Noto CJK |
| `compare_fixtures.js`（Puppeteer）| **本機 Windows**（開發者機器）| Puppeteer 在無 GUI 的 Docker 容器執行需要 X11 / Xvfb / sandbox 權限，維護成本極高；本機有 Chrome，開箱即用 |

> **不要在 Docker 容器中跑 Puppeteer。** 即使勉強跑起來，也需要 `--no-sandbox`
> 與一堆 X11 依賴庫，每次容器重建都要重新設定。

### 腳本位置

```
tests/
├── fixtures/
│   ├── 01_simple/
│   │   ├── *.docx
│   │   └── golden/          ← LibreOffice 產生的 PNG（進 git）
│   ├── 02_std_table/ ...
│   └── ...
└── scripts/
    ├── generate_golden.sh   ← 在 Docker 執行：生成 golden PNG
    ├── compare_fixtures.js  ← 在本機執行：pixelmatch 比對
    └── report.html          ← 自動產生的視覺化報告
```

### Step 1：generate_golden.sh（Docker 執行）

```bash
#!/usr/bin/env bash
# 執行方式：docker exec system-odoo bash /addons/dobtor_doc_editor/tests/scripts/generate_golden.sh

set -e
FIXTURES_DIR="$(cd "$(dirname "$0")/../fixtures" && pwd)"

find "$FIXTURES_DIR" -name "*.docx" | while read -r docx; do
  dir=$(dirname "$docx")
  golden_dir="$dir/golden"
  mkdir -p "$golden_dir"

  echo "Generating golden: $(basename "$docx")"
  soffice --headless --convert-to png \
    --outdir "$golden_dir" "$docx" 2>/dev/null

  echo "  → $golden_dir/$(basename "${docx%.docx}").png"
done

echo "Done."
```

**多頁文件注意**：LibreOffice 對多頁 DOCX 輸出多個 PNG（`name_1.png`, `name_2.png`...），比對腳本需逐頁對應。

### Step 2：compare_fixtures.js（本機執行）

```javascript
// compare_fixtures.js
// 執行環境：本機 Node.js（非 Docker）
// 依賴：npm install puppeteer pixelmatch pngjs glob

const pixelmatch = require('pixelmatch');
const { PNG } = require('pngjs');
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const glob = require('glob');

const THRESHOLD = 0.05;  // 5% 為 Pass/Fail 邊界
const FIXTURES = glob.sync('tests/fixtures/**/*.docx');

async function renderDocxWithCanvasEditor(page, docxPath) {
  // 重要：等待字型載入完成後再截圖
  // 流程：
  // 1. document.fonts.ready — 等待所有 CSS @font-face 載入
  // 2. window.__canvasEditorReady — 等待 canvas-editor 渲染完成後設置的旗標
  //
  // canvas-editor 渲染完成後，需在程式碼中執行：
  //   window.__canvasEditorReady = true;
  // 否則 Puppeteer 可能在字型尚未載入時截圖，導致 CJK 字型退回 Arial，diff 爆表

  await page.goto(`http://localhost:10003/test-fixture?path=${encodeURIComponent(docxPath)}`);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => window.__canvasEditorReady === true, { timeout: 10000 });

  return page.screenshot({ encoding: 'binary' });
}

async function runComparison() {
  const browser = await puppeteer.launch();
  const results = [];

  for (const docxPath of FIXTURES) {
    const goldenPath = path.join(
      path.dirname(docxPath), 'golden',
      path.basename(docxPath, '.docx') + '.png'
    );
    if (!fs.existsSync(goldenPath)) {
      console.warn(`⚠️  No golden for: ${docxPath}`);
      continue;
    }

    const page = await browser.newPage();
    const renderedBuffer = await renderDocxWithCanvasEditor(page, docxPath);
    await page.close();

    const golden = PNG.sync.read(fs.readFileSync(goldenPath));
    const rendered = PNG.sync.read(Buffer.from(renderedBuffer));
    const diff = new PNG({ width: golden.width, height: golden.height });

    const numDiff = pixelmatch(
      golden.data, rendered.data, diff.data,
      golden.width, golden.height,
      { threshold: 0.1 }
    );
    const diffRatio = numDiff / (golden.width * golden.height);

    // 輸出 diff image（供人工檢視）
    if (diffRatio >= THRESHOLD) {
      const diffPath = goldenPath.replace('.png', '_diff.png');
      fs.writeFileSync(diffPath, PNG.sync.write(diff));
    }

    results.push({
      fixture: path.relative('tests/fixtures', docxPath),
      diffRatio,
      pass: diffRatio < THRESHOLD,
    });
  }

  await browser.close();
  printReport(results);
}

function printReport(results) {
  console.log('\n=== Canvas-Editor 還原度報告 ===\n');
  results.forEach(r => {
    const icon = r.pass ? '✅' : '❌';
    console.log(`${icon} ${r.fixture.padEnd(50)} ${(r.diffRatio * 100).toFixed(1)}%`);
  });
  const passed = results.filter(r => r.pass).length;
  console.log(`\n${passed}/${results.length} 通過（目標：全部 < 5%）`);
}

runComparison().catch(console.error);
```

### `window.__canvasEditorReady` 旗標約定

在 `doc_editor.js` 的渲染完成回呼中，需設定此旗標：

```javascript
// doc_editor.js（Phase 1 實作 Renderer 時加入）
editor.on('rendered', () => {
  window.__canvasEditorReady = true;
});
```

> **字型問題的根因**：`document.fonts.ready` 只等待 CSS `@font-face` 宣告的字型。
> canvas-editor 透過 Canvas 2D `ctx.font` 指定字型時，瀏覽器在第一次實際繪製前
> 不保證字型已載入。必須等 canvas-editor 的 `rendered` 事件（實際繪製完成後），
> 才能確保 CJK 字型不退回 Arial。

### 目標還原度（Phase 別）

| Phase | 目標 diff% | 瓶頸 |
|-------|------------|------|
| Phase 0 基準（現況）| ~40-60%（估計）| 表格跑版、字距誤差 |
| Phase 1 完成後 | ~20-30% | Parser 正確，Renderer 仍用舊路徑 |
| Phase 2 完成後 | ~10-15% | HarfBuzz WASM 改善行高精度 |
| Phase 3 完成後 | **< 5%** | Layout Engine + TableLayout 完整 |

### 注意事項

1. **Golden PNG 進 git**：42 份 fixture × 平均 200KB ≈ 8MB，可接受
2. **字型一致性**：LibreOffice（Docker）與 canvas-editor（本機）需使用相同字型（Noto CJK），否則比對無意義
3. **跨頁 vMerge 的測試重點**：`03_complex_table/` 的多頁估驗表格是此問題的關鍵 fixture

---

## Phase 0 完成條件

| 條件 | 狀態 |
|------|------|
| 42 份 fixture DOCX 收集完成 | ✅ |
| `capability_audit.md` 完成（含兩個隱藏大魔王）| ✅ |
| `architecture_decision.md` 完成（本文件）| ✅ |
| `generate_golden.sh` 建立並執行，golden PNG 進 git | ❌ |
| `compare_fixtures.js` 建立，可輸出基準 diff% | ❌ |
| patch-package 安裝並建立 `patches/` 目錄 | ❌ |

**Phase 0 → Phase 1 的進入條件**：上表全部 ✅

---

## 附錄：Phase 1 開始前的自我檢查清單

- [ ] `LineMetrics` 介面的欄位定義是否涵蓋 Phase 2 HarfBuzz 的需求？
- [ ] `CellNode.isContinuation` 是否足以讓 Phase 3 TableLayout 處理跨頁 vMerge（連續渲染 + border 省略）？
- [ ] `SectionNode` 是否記錄了 headerReference / footerReference（奇偶頁/首頁切換）？
- [ ] `FloatImageNode` 的位置模型是否能表達 Word 所有 anchor 定位模式（絕對位置 / 相對欄 / 相對頁）？
- [ ] `window.__canvasEditorReady` 旗標約定是否已在 `doc_editor.js` 中預留？

---

## ADR-008：Phase A + Phase B Exit Report（2026-05-05）

### 範圍

Phase A（Sprint 0 通電）與 Phase B（Sprint 1-2 Parser 全套補完）合併報告。

### 已完成

#### Phase A — Build 鏈通電

- ✅ `OoxmlParser.ts` orchestrator 實作（取代 Sprint 1 throw stub）
- ✅ 6 個 stub Parser 最小可運行版（StyleResolver / NumberingResolver / SectionParser / HeaderFooterParser / TableParser + GridResolver / DrawingParser）
- ✅ `make verify` 等價（`npx tsc --noEmit` + `npm run build:frontend` + bundle 檢查）全綠
- ✅ Bundle 產出：`static/src/lib/canvas_editor/canvas-editor-custom.umd.js`（126KB after Phase B）
- ✅ Phase A smoke 整合測試：47 tests，41 fixture 全部 OoxmlParser.parse() 不 throw
- ✅ Golden PNG 產出：126 張 PNG 跨 6 類 fixture（`generate_golden.sh` 在 WSL host 跑通）

#### Phase B — Parser 全套完整

| 模組 | 狀態 | Unit Tests | 範圍 |
|------|------|-----------|------|
| StyleResolver | ✅ 完整 | 12 | docDefaults + basedOn 多層 + flatten + 巢狀 indent 合併 |
| NumberingResolver | ✅ 完整 | 25 | abstractNum/num + 9 層 ilvl + numFmt 全套（CJK chineseCounting/japaneseCounting/taiwaneseCounting/iroha/aiueo）+ lvlOverride |
| SectionParser | ✅ 完整 | 14 | pgSz/pgMar/headerRefs/footerRefs/cols + 多 section 切分（DocumentParser.walkBodyAsSections） |
| HeaderFooterParser | ✅ 完整 | 6 | 重用 DocumentParser.parseBodyContent，破碎 XML 降級 |
| TableParser | ✅ 完整 | 14 | tblGrid + tblPr + tcPr 全套（tcW/tcBorders/shd/tcMar/vAlign/noWrap/textDirection）+ trPr |
| GridResolver | ✅ 完整 | 11 | vMerge 兩 pass 演算法 + 14 欄送審管制風格 fixture 通過 + 鏈中斷 + 孤兒 continue 邊界 |
| DrawingParser | ✅ 完整 | 11 | wp:inline + wp:anchor 完整 posH/posV/wrapType（5 種）+ 接入 ParagraphParser |

**測試數**：183 個（12 test files）全綠。

### 關鍵設計決策（Phase A+B 期間）

#### ADR-008.1：DocumentParser ↔ TableParser 循環依賴

**問題**：DocumentParser 走訪 body 需要 TableParser 解析 `<w:tbl>`；TableParser 解析 cell 內容需要 DocumentParser 走訪段落。

**解法**：lazy getter + 反向 this 注入。
- `TableParser` 接受可選 `DocumentParser` 建構子參數；不傳則 first-use 時 `new DocumentParser(this)`。
- `DocumentParser` 接受可選 `TableParser` 建構子參數；同理 lazy 建立反向實例。
- `OoxmlParser` 統一持有兩者的 instance，避免重複實例化。

**參考**：[`OoxmlParser.ts`](../static/src/core/ooxml/OoxmlParser.ts)
> ⚠️ 上面這個路徑已不存在（ADR-029 整批移除）：`git show doc-editor-before-ts-removal:dobtor_doc_editor/static/src/core/ooxml/OoxmlParser.ts`

#### ADR-008.2：cell.content 限定 ParagraphNode[]（暫）

**問題**：AST `CellNode.content: ParagraphNode[]` 不支援巢狀表格。

**權宜**：TableParser cell 解析時 filter `.parseBodyContent(tc)` 結果為 ParagraphNode only。

**未來**：Phase B.5+ 可改 AST 為 `CellNode.content: BlockNode[]` + 對應更新 TableParser 與測試。

#### ADR-008.3：降級優於 throw

所有 stub 在 Phase A 期間以「回空集合 / 預設值」降級，不 throw `NotImplemented`。

**理由**：確保任一 Phase 中途中斷時，OoxmlParser.parse() 仍能跑出有效 DocumentNode（即便部分屬性缺失）。Build 鏈與整合測試永遠可執行。

#### ADR-008.4：`parseParagraphProps` / `parseRunProps` 暴露為 named export

`StyleResolver` 與 `NumberingResolver` 解析 `<w:pPr>` / `<w:rPr>` 的需求等同於 `ParagraphParser`，因此把這兩個函式從 ParagraphParser 內部 private 升級為 named export。避免重造同樣的 attribute walker。

### 已知限制（Phase A+B 不修，留 Phase C+ / 後續 Sprint）

- TableParser cell.content 仍為 ParagraphNode[]（巢狀表格降級）
- StyleResolver `<w:tblStylePr>` 條件樣式（15 種：firstRow/lastRow/etc.）未支援（需 TableParser 做樣式套用，留 Phase B+）
- ECMA-376 17.4.65 邊框衝突解決優先級表未實作（Phase 3 Layout Engine）
- DrawingParser `<wp:effectExtent>` 與 `<a:srcRect>` 裁切未解析（Renderer 階段需要）
- HeaderFooterParser 偶數頁 / 首頁不同節邏輯未支援（規劃 Phase 3）
- GridResolver 不同 gridSpan 跨列 vMerge（罕見邊界）以「精確 gridCol 匹配」處理

### Bundle / 測試指標

| 指標 | Phase A 結束 | Phase B 結束 |
|------|-------------|-------------|
| TypeScript 嚴格 type check | ✅ pass | ✅ pass |
| rollup build | ✅ 89KB | ✅ 126KB |
| 測試數量 | 92 | 183 |
| Fixture 解析無 throw | 41/41 | 41/41 |
| Golden PNG 產出 | 126 張 | 126 張（同） |
| OOXML 元素白名單覆蓋 | — | 392 unique 元素 |

### 下個 Phase 進入條件（Phase D）

- [x] Build 鏈通電
- [x] Parser 全套通過
- [x] AST 完整對應 OOXML 結構
- [ ] canvas-editor fork 策略文件（Phase C，2026-05-05 完成）
- [ ] HarfBuzz WASM 整合可行性 spike（Phase D 第一週決策關卡）


---

## ADR-009：Phase D Exit Report（2026-05-05）

### 範圍

Phase D（Sprint 2-3 加速）：mapper / HarfBuzz / 端到端整合測試 / CLI tool 全套交付。

### 已完成

| Sub-phase | 模組 | 行數 | 測試 |
|---|---|---|---|
| D.1 | ToCanvasEditor mapper | ~330 | 20 unit |
| D.2 | ShapingEngine + FontMetrics + HarfBuzz spike | ~270 | 13 unit |
| D.3 | E2E mapper integration + fixture stats | — | 47 integration |
| D.4 | docs/phase_d_e2e_report.md + 本 ADR | — | — |

**測試總數**：284（從 Phase B+ 結束的 224 增加 60 個）。
**Bundle 體積**：151KB（Phase B+ 136KB → +15KB 為 ToCanvasEditor）。
**font/ 模組刻意不入主 bundle**（rollup tree-shaking + `index.ts` 不 re-export）。

### 關鍵決策

#### ADR-009.1：HarfBuzz 整合**可行**但**暫不接入主流程**

Spike 5/5 全綠，WASM 在 Node + vitest 可正常運作。**踩坑**：vitest 的 dynamic import 把 CJS module-as-Promise 包成 Module namespace，導致 `await import()` throw `Method Promise.prototype.then called on incompatible receiver [object Module]`。**解法**：用 `createRequire(import.meta.url)` 直接取 CJS module.exports 再 await（此 pattern 寫進 ShapingEngine.loadHb 與 HarfBuzzSpike.test.ts）。

#### ADR-009.2：font/ 模組不接到 OoxmlParser 主流程的設計理由

1. canvas-editor Renderer 用 Browser `ctx.measureText()`，接 HarfBuzz 必須 fork 該 Renderer → 屬 Phase 6+
2. Bundle 體積：harfbuzzjs WASM ~200KB，接到 main bundle 會大幅 inflate
3. font/ 純粹預備 Phase 6 自寫 Layout Engine 用，提前驗證可行性

**決策**：`static/src/core/ooxml/index.ts` 不 re-export font/。需要時 Phase 6 直接 `import { ShapingEngine } from '../font/ShapingEngine'`，rollup tree-shake 不影響主 bundle。

#### ADR-009.3：監造會議記錄 fixture 內容**整份在表格 cell 內**

E2E mapper integration 第一版測試誤以為 `elements.map(e=>e.value).join('')` 能抽出全部文字，但 .docx 的 31KB 文字內容**全部位於 single 34-row table 內**，平面 traverse 抓不到。**修正**：`flattenText` helper 遞迴抽出 `valueList` + `trList[].tdList[].value` 內容。這個經驗也適用於 ChienYi 多數工程文件（自主檢查表、缺失改善表等都是 form-style，主內容在 cell 內）。

#### ADR-009.4：未做 pixelmatch e2e diff

規劃 Phase D.3 含 pixelmatch vs LibreOffice golden 的視覺差異測試，本次未做：
- 需要 puppeteer + canvas-editor headless 渲染環境（CI 工程量 ~1 天）
- 需要 canvas-editor 實際在瀏覽器中跑（vitest node 環境跑不了）
- pixelmatch 結果只能驗證「視覺一致性」，但 mapper 結構正確性已透過 47 個 integration test 驗證

**Defer 路徑**：留待 Phase F（規劃 §6.2 Visual Regression Pipeline）做完整 visual regression。

### 已知限制（Phase D 不修，留 Phase E/F+）

- ShapingEngine 不在 OoxmlParser 主流程：font/ 模組獨立可用
- canvas-editor 浮動圖片繞排：mapper 暫降為 inline image（Phase 6 Layout Engine fork 才能正確繞排）
- 列表編號：mapper 暫不映射 numId/ilvl 到 canvas-editor 的 listType/listStyle 系統
- Tab stops（pPr.tabs）：canvas-editor 的 type=tab 不接位置陣列，當作純 `\t` 字元

### Phase E 進入條件

- [x] Mapper 全套通過（41/41 fixture）
- [x] CLI tool 可呼叫（parse_docx_cli.ts 已寫，rollup CLI bundle 待 Phase E 補）
- [x] Backend 並行通道有明確介面（Python subprocess.run + JSON IPC）


---

## ADR-010：Phase E Exit Report — Backend 並行通道（2026-05-05）

### 範圍

`doc_controller.py` 的 `/dobtor_doc/import` route 加 `engine` 參數，讓使用者可選擇傳統 LibreOffice 路徑或本模組 TS OOXML Parser 路徑。Phase E 目標是把 Phase B/D 累積的 Parser 能力送進 Odoo 真實流程，讓 chichi 與同事可以實機比對兩條路徑的輸出。

### 已完成

| 子項 | 狀態 |
|---|---|
| `tools/parse_docx_cli.ts` Node CLI | ✅ Phase D.3 已寫；Phase E 補 DOMParser 注入（@xmldom/xmldom） |
| `rollup.cli.config.js` + `tsconfig.cli.json`：CLI bundle 為 CJS | ✅ 138KB 自含 bundle，container 內 Node 18 正常跑 |
| `_ts_parse_docx_to_elements()` Python wrapper | ✅ subprocess.run + 30s timeout + 失敗降級 None |
| `/dobtor_doc/import?engine=ts\|libreoffice\|both` route | ✅ 三模式齊備；ODT 自動降級 LibreOffice（無 TS 路徑） |
| `engine=both` 模式內含 audit 比對 log | ✅ 回傳 `{ html, elements, audit }` 給前端比對 |
| 前端 `importViaTsEngine(file)` | ✅ doc_editor.js 加新 method；用 canvas-editor `executeSetValue({main: elements})` 餵 IElement[] |
| `@xmldom/xmldom` 從 devDeps 移到 dependencies | ✅ CLI 自含 bundle，CI / production 環境都能跑 |
| Odoo 升級 SOP（兩步驟） | ✅ `docker exec ... -u dobtor_doc_editor` + `docker restart` 全綠 |
| Container 內 CLI runtime 驗證 | ✅ `docker exec odoo18 node /mnt/extra-addons/.../parse_docx_cli.cjs` 對 fixture 跑出 262KB JSON |

### 關鍵設計決策

#### ADR-010.1：Subprocess 而非 Pyodide / native binding

**決策**：Python `subprocess.run(['node', cli_path, ...])` 把 .docx 寫暫存檔再呼 CLI。

**為何**：
1. **隔離性**：Node process crash 不影響 Odoo worker
2. **無 Python 綁定**：不需要 Pyodide / wasmtime-py 等實驗性整合
3. **timeout 可控**：subprocess 有 30s timeout，防止惡意大檔卡住 worker
4. **Container 內 Node 已就緒**：`docker exec odoo18 which node` → /usr/bin/node 18.19.1

**代價**：
- 每次解析開 process 有 ~50–100ms cold start cost（小檔不顯著，大量併發時要注意）
- 序列化 JSON 從 stdout 改為檔案 I/O（簡化 buffer 處理）

**後續優化**（如有需要）：跑 long-lived Node daemon + Unix socket IPC，省 cold start。Phase F 才考慮。

#### ADR-010.2：`engine=both` audit 模式

提供使用者**安全切換**機制：兩條路徑都跑，回傳 `audit: { ts_element_count, lo_html_len, lo_fallback }`。
chichi 可在 `?engine=both` 觀察兩端輸出規模、判斷 TS 路徑成熟度，再決定何時把預設改為 `engine=ts`。

不在 controller 自動做 diff（diff 是視覺工程，需要 e2e renderer），但 audit log 提供量化線索。

#### ADR-010.3：`engine=ts` 失敗自動降級為 LibreOffice

**邏輯**：當 `engine=ts` 但 `_ts_parse_docx_to_elements()` 回 None（CLI 未 build / Node 不在 PATH / subprocess timeout / 解析失敗），controller 自動 fallback 到 LibreOffice 路徑。使用者收到正常結果，audit 含 `ts_failed: True`。

**理由**：避免 chichi 切換 engine 後突然「沒結果」造成上線 regression。LibreOffice 路徑永遠是穩定後備。

#### ADR-010.4：前端不自動切換、提供顯式 method

doc_editor.js 加 `importViaTsEngine(file)`，但**沒**自動取代 `_handleImportFile`。

**為何**：
- `_handleImportFile` 既有流程含「上傳模板 + 偵測 Jinja 變數」邏輯，與 import 預覽不同職責
- TS 路徑的渲染品質還未經 chichi 的 fixture 全集驗證
- 暴露顯式 method 讓 chichi 可在 DevTools 跑 `window._docEditor.importViaTsEngine(file)` 比對，再決定何時推進到 UI button

### 端到端驗證

```bash
# Container 內 CLI
docker exec odoo18 node /mnt/extra-addons/dobtor_doc_editor/tools/dist/parse_docx_cli.cjs \
  /mnt/extra-addons/dobtor_doc_editor/tests/fixtures/01_simple/03.1120815-監造會議記錄.docx \
  /tmp/out.json
# → OK: parsed ... → /tmp/out.json (mode=elements, 262444 bytes)

# 模組升級（Phase E controller 與前端同時生效）
docker exec odoo18 odoo -c /etc/odoo/odoo.conf -d odoo18_dev -u dobtor_doc_editor --stop-after-init
docker restart odoo18

# Web 端驗證（DevTools console）
# 1. 開 Odoo 的 dobtor_doc_editor 編輯器
# 2. 在 console: window._docEditor.importViaTsEngine(<File>)
#    → result.success = true, elementCount = N
# 3. 比對 canvas-editor 渲染 vs 原 .docx
```

### 已知限制

- **大檔（>5MB）效能**：subprocess 30s timeout 可能不夠；長期應走 daemon 或 worker
- **TS Parser 範圍仍受 Phase B+D 限制**：不支援 footnote / endnote / OMML / SmartArt / 追蹤修訂等（已在 ADR-008/009 標記）
- **ODT 不走 TS 路徑**：本模組 OoxmlParser 只支援 .docx；ODT 自動降級 LibreOffice
- **Audit log 沒永久存**：目前只在 response 回傳，未寫進 ir.logging。未來 chichi 評估時可加 hook 收集

### 下個 Phase（Phase F+，本次不做）

| 項目 | 理由 |
|---|---|
| 視覺 diff（pixelmatch）e2e | 需 puppeteer + canvas-editor headless render（規劃 §6.2 Visual Regression Pipeline） |
| Layout Engine 自寫（Knuth-Plass / 跨頁表格） | 規劃 Phase 3，3-4 個月 |
| HarfBuzz 接到 canvas-editor Renderer | 需 fork canvas-editor Renderer pipeline |
| Footnote / OMML / 追蹤修訂 / SmartArt | 規劃 Phase 1.9 + Phase 5，分階段做 |

### 進入 Phase F 的條件

- [x] Backend 並行通道可用（engine=ts/both 上線）
- [x] Frontend 可餵 IElement[]（importViaTsEngine 寫好）
- [x] CLI 在 container 內驗證跑通
- [x] chichi + 同事驗證至少 5 份 fixture，比較 TS vs LibreOffice 渲染差異 — **此項已被 Phase F 自動化 pipeline 取代**（見 ADR-011）


---

## ADR-011：Phase F.1+F.2+F.3 Exit Report — 視覺基線 Pipeline 建立（2026-05-06）

### 範圍

Phase F（規劃 §6.2 Visual Regression Pipeline）：建立 puppeteer + pixelmatch e2e pipeline，對全 42 份 fixture .docx 執行視覺基線測量，產出 `docs/baseline_diff_report.md` 量化「Phase E 結束時」的渲染還原度。

### 已完成

| 子項 | 狀態 |
|---|---|
| F.1 Odoo Clean Layout 測試路由 `/dobtor_doc_editor/test` | ✅ doc_controller.py:1224 |
| F.1 JSON-RPC 資料端點 `/dobtor_doc_editor/test_data` | ✅ doc_controller.py:1255 |
| F.1 test_layout.xml + test_harness.js（無 Owl，純 IIFE） | ✅ |
| F.1 window.__canvasEditorReady ready flag 約定 | ✅ test_harness.js:setReadyFlag |
| F.2 puppeteer + pixelmatch + pngjs + glob 安裝 | ✅ package.json devDeps |
| F.2 compare_fixtures.cjs login flow（POST /web/session/authenticate） | ✅ |
| F.2 多頁 page comparison（每頁 canvas[data-index] 對應 golden N） | ✅ |
| F.2 DPI 尺寸對齊（1240 raw vs 1241 golden，nearest-neighbor scale） | ✅ |
| F.3 Markdown report writer + JSON dump | ✅ |
| F.3 baseline_diff_report.md 觀察與瓶頸分類 | ✅ |

### 量化結果（baseline）

| 維度 | 值 |
|------|-----|
| 全 fixture mean diff% | **15.0%** |
| 中位數 | 13.3% |
| 最佳 | 1.7%（02_std_table 簽到表）|
| 最差 | 30.0%（02_std_table 週報）|
| 表現最佳類別 | 06_template（2.9%）/ 05_header_footer（3.8%）|
| 表現最差類別 | 04_with_image（26.5%）/ 03_complex_table（22.6%）|

### 關鍵設計決策

#### ADR-011.1：test 路由與 import 路由分離

`/dobtor_doc/import` 是 production flow（form upload + LibreOffice fallback）。
`/dobtor_doc_editor/test` 是 dev/QA flow（伺服器讀 fixture path + TS engine only）。

**為何分離**：
- import 路由的 fixture path 是上傳 multipart，test 路由是 server-side 路徑（fixtures 屬於 module artifacts）
- import 路由有 LibreOffice fallback；test 路由要求 TS engine pure（fallback 會混淆 baseline）
- import 路由 `auth='user'`（多帳號 session）；test 路由也 `auth='user'` 但目的是 admin debug

#### ADR-011.2：test_harness.js 不走 Owl Component

doc_editor.js 是完整 Owl Component（AutoSave / Offline / Leader Election）。test_harness.js 是純 IIFE：
- test 頁面是 clean HTML（無 Odoo backend webclient），Owl runtime 沒載入
- 單一目的：fetch elements → boot canvas-editor → 設 ready flag
- 不需要 AutoSave / contentChange listener；不應引入 Component lifecycle 複雜度

#### ADR-011.3：ready flag 用 MutationObserver + 雙 rAF + fonts.ready

canvas-editor v0.9.128 沒暴露 `rendered` event。採三段條件 AND：
1. `MutationObserver` 偵測 `<canvas>` 元素出現
2. `document.fonts.ready` Promise resolve
3. `requestAnimationFrame × 2` 確保下一幀 pixel 已上 GPU

5 秒 timeout fallback 防止 puppeteer 卡死（保險）。

#### ADR-011.4：分頁不一致以 N=min(golden, rendered) 比對

實機觀察：canvas-editor 多數 fixture 比 golden 多 1–3 頁（page split 演算法不同）。

**處理**：
- 取 N = min(goldenPages.length, renderedPages.length) 比對前 N 頁
- 多餘頁不計入 diff%（避免「沒對應」拉爆數字）
- report 註明「rendered 多 X 頁」provide 後續 Phase 3 分頁引擎工作的目標 fixture

#### ADR-011.5：1px 尺寸差用 nearest-neighbor scale

raw canvas = 1240×1754（A4 at 150 DPI 精算 ≈1240.157）
golden PNG = 1241×1754/1755（pdftoppm rounded up）

差異 < 0.1%，但 pixelmatch 要求尺寸完全一致。fit() 函式做 nearest-neighbor 縮放，所有 fixture 標 `*` warning。實際 diff% 不會被此影響（雙方都用同一畫素網格比對）。

更精確的做法：未來改用 pdftoppm `-rx 1240 -ry 1754` 強制尺寸；或 force canvas raw width = 1241 via canvas-editor config。Phase 4 不做。

### 主要瓶頸分類（用於 Phase 4+ 路線圖）

報告 `docs/baseline_diff_report.md` 的「瓶頸分類」表列出所有 fixture diff% 的根因：

| 瓶頸 | 貢獻 | 解 Phase |
|------|------|---------|
| 分頁位置不同 | 30–40% | Phase 3.2 自寫分頁引擎（不在本計畫） |
| 字型 measureText 精度 | 10–20% | Phase 2 / 6 接 HarfBuzz |
| 浮動圖片渲染 | 25%（限 04 類）| Phase 3.4 Float/Wrap |
| **邊框衝突未解決** | 5–10% | **Phase 4.3（本計畫）** |
| **Theme color 未解析** | 2–5% | **Phase 4.1（本計畫）** |
| **條件樣式未套用** | 3–5% | **Phase 4.2（本計畫）** |

Phase 4 攻擊「邊框 + theme + 條件樣式」三線，預估全 fixture 平均 diff% 從 15.0% 下降至 9–12%。

### 已知限制

- **尺寸 1px 差**：fit() 縮放掩蓋；不影響趨勢但小數點位 noise 會 ±0.3pp
- **分頁不一致**：本 baseline 不修，Phase 3 才改攻
- **單一 DEVICE_SCALE_FACTOR=1.5625**：未對單一 fixture 校準；環境變數可覆寫
- **WSL 字型 vs production 字型**：WSL 上跑 Noto CJK，production Linux container 不同；影響 ~5pp diff%
- **probe_dom.cjs 是一次性除錯腳本**：保留檔案不刪（給未來 canvas-editor 升級時 re-probe DOM 結構用）

### Phase 4 進入條件

- [x] Visual baseline 全 41 fixture 量化
- [x] Pipeline 可重跑（compare_fixtures.cjs --json-out + --md-out）
- [x] ADR-011 紀錄 baseline 設計決策與限制
- [x] 主要瓶頸分類，Phase 4 預期改進量明確


---

## ADR-012：Phase 4 Exit Report — Style/Theme/Border 完整補完，但 diff% 未動（2026-05-06）

### 範圍

Phase 4（規劃 §5 Phase 4 Style & Theme 完整 + ADR-010 next phase 列出的三項 audit 缺口）：
- Phase 4.1：ThemeResolver + colorResolver — 解析 word/theme/theme1.xml，把 themeColor/themeTint/themeShade reference 在 parser 階段 eager 解析為具體 hex
- Phase 4.2：TableStyleApplicator — 套用 w:tblStyle 與 w:tblStylePr 條件樣式（13 種：firstRow/lastRow/band/corner 等）到 row/cell 內每段段落+run
- Phase 4.3：BorderConflictResolver — 實作 ECMA-376 §17.4.65 邊框衝突解決（cell own vs table inside/outside），adjacent cell 兩側邊界協調

### 已完成（parser-level 100% 交付）

| 模組 | 行數 | 測試 |
|------|------|------|
| ThemeResolver.ts | 230 | 19 unit |
| colorResolver.ts | 50 | 共享 |
| TableStyleApplicator.ts | 220 | 16 unit |
| BorderConflictResolver.ts | 230 | 14 unit |

**測試總數**：333（從 Phase F.3 結束的 284 增加 49 個）。
**Bundle 體積**：UMD 184KB（+33KB）/ CLI 433KB（+30KB）。
**Odoo 模組升級**：兩步驟 SOP 全綠。
**TypeScript strict**：clean。

### 量化 diff% 改進：**未達預期**

對 baseline 重跑 compare_fixtures.cjs 後：

| 維度 | Baseline | Phase 4 | Delta |
|------|----------|---------|-------|
| 全 fixture mean | 15.00% | 15.00% | **+0.009pp** |
| Median | 13.30% | 13.30% | 0.000pp |
| Worst | 30.00% | 30.00% | 0.000pp |

**40/42 fixture 0.00pp delta；2/42 微幅 +0.15-0.24pp regression（雜訊範圍，皆 04_with_image 類別）。**

baseline 報告原預估 Phase 4 可下降 –3 ~ –6pp。**未達標**。

### 為什麼 Phase 4 改不動 diff%（核心發現）

#### ADR-012.1：canvas-editor renderer 是真正的瓶頸

Phase 4 三大模組都正確改動 AST，**但 canvas-editor renderer 不消化新增屬性**：

1. **BorderConflictResolver**：cell.props.borders 已是 ECMA 17.4.65 正解，但 ToCanvasEditor mapper 將 cell 映射為 canvas-editor 的 `td` 物件後，canvas-editor 用自己的 border defaults，不採用 effective borders
2. **TableStyleApplicator**：條件樣式 apply 到段落 / run 是正確的，但 canvas-editor IElement 對部分屬性（行距 / 字距 / 段距 / 條件式 fontFamily 切換）的呈現有自己的規則
3. **ThemeResolver**：themeColor → hex 解析正確，但 ChienYi fixture 集合**極少用 themeColor reference**（多直接寫 hex），所以這項解析能力沒被觸發

#### ADR-012.2：fixture 集合特性與 Phase 4 不匹配

ChienYi 工程文件的特性：
- 表格樣式以「直接寫 cell 屬性」為主，少用 tblStylePr 條件樣式
- 顏色多為直接 hex（黑、紅、藍），少用 theme reference
- 結果：Phase 4 改進的「正確性」對這些 fixture 不顯著

對「典型 Office 商業模板」（含豐富 theme + tblStylePr 的範本）效益會更大，但本次 fixture 集不展示這層差異。

#### ADR-012.3：Phase 4 改動的 真正價值

雖然視覺基線沒動，**Phase 4 的價值在「為下個 Phase（fork canvas-editor / 自寫 Renderer）打前置基礎」**：
- 沒有 ThemeResolver，未來 Renderer 拿到的 RunProps.color 仍是「accent1」字串而非 hex
- 沒有 BorderConflictResolver，未來 Renderer 必須自己再算一次邊框衝突
- 沒有 TableStyleApplicator，條件樣式必須在 Renderer 階段重新套用一次

**結論**：parser-level 工作已飽和。下個 Phase 必須直接攻擊 renderer。

### 真正動 diff% 的下個 Phase（規劃指向）

| 工作 | 估計 diff% 改進 | 工程量 | 規劃對應 |
|------|---------------|--------|---------|
| Fork canvas-editor + 自寫 PageSplit Engine | **–10 ~ –15pp** | 3-4 個月 | Phase 3.2 |
| HarfBuzz 接 canvas-editor Renderer | –3 ~ –5pp | 1-2 個月 | Phase 2 / 6 |
| Float / Wrap 圖文繞排（限 04_with_image 類）| –10 ~ –15pp（該類） | 2-3 個月 | Phase 3.4 |
| 自寫 Border Renderer 用 Phase 4.3 結果 | –1 ~ –3pp | 1 週（前置已備）| Phase 3.3 |

從 15% 降到 5%（A- 級）需 4-6 個月 fork canvas-editor 工程。**Phase 4 是必要前提，但不是充分條件**。

### 關鍵設計決策

#### ADR-012.4：themeColor → hex 用 RGB 線性近似（非 HSL luminance）

ECMA-376 §17.18.97 定義 themeTint/themeShade 為 HSL luminance 修改（lumMod / lumOff）。Phase 4.1 用 RGB 線性近似：
- tint：`rgb' = rgb * (1 - t/255) + 255 * (t/255)`
- shade：`rgb' = rgb * (1 - s/255)`

差異：對中等飽和度色（accent1 = 4F81BD）兩種演算法 Δ ≈ ±5 RGB。視覺差異 < 5%。fixture 集合中極少用 themeTint/Shade，誤差影響無感知。

未來若需要嚴格規格相容（Word 來回 round-trip）才升級為 HSL 版本。

#### ADR-012.5：themeColor eager resolve 而非 lazy

Parser 階段把 themeColor → hex 寫回 RunProps.color。代價：
- 失去原 themeColor 識別（無法 round-trip 回原 themeColor reference）
- AST 簡單（color 始終是 hex）

權衡：
- mapper / renderer 不用知道 ThemeMap 概念
- Phase 6 export 對稱性可重新匯出為實際 hex（多數使用者不需要 round-trip 為 themeColor reference）

#### ADR-012.6：TableStyleApplicator mutates AST（不引入新欄位）

對 cell.content 的 paragraph.props 與 run.props 做 mutation（merge in-place）。沒在 CellNode/RowNode 加 effectiveStyleProps 欄位。

理由：
- mapper / renderer 不用做二段查詢（先看 row.effective，再看 paragraph.explicit）
- explicit 屬性仍永遠優先（mergeProps order 確保）
- 缺點：失去「explicit vs from-style」的識別，但 Phase 4 沒有需要這層識別的下游消費者

#### ADR-012.7：BorderConflictResolver 在 TableParser 內 mutate

resolveTableBorders 直接 mutate cell.props.borders。理由與 ADR-012.6 相同：
- 渲染端只需「effective borders」一份結果
- pre-Phase 4 cell.props.borders 是「raw」，post-Phase 4 是「resolved」；這是有意義的升級

#### ADR-012.8：visual baseline pipeline 是 Phase 4 結果無感知的根本原因

Phase 4 改的「正確性」屬於 AST 層；視覺基線比的是渲染後 PNG。中間隔了 ToCanvasEditor mapper + canvas-editor renderer 兩道過濾，前述 ADR-012.1 ~ .3 都是這兩道濾鏡造成的「parser 改進透明化」。

修法：fork canvas-editor 把 mapper 輸出的精確 props 餵進渲染（Phase 6+ 工作）。

### 已知限制

- **Phase 4.1 themeColor RGB 線性近似** vs Word HSL 演算法精確版（誤差 < 5%）
- **TableStyleApplicator mutation 不可逆**：原始 explicit-vs-from-style 區分丟失
- **BorderConflictResolver 不處理 row borders**（trPr.tcBorders）— Word 中極少出現
- **vMerge 跨頁 border 抑制**：Phase 4.3 不處理 cross-page rendering（屬 Phase 3.2 分頁引擎範圍）
- **canvas-editor renderer 沒消化新精確 props**：證明 visual baseline pipeline 設計正確（量化能立刻顯示無變化），下個 Phase 攻 renderer

### 進入下一階段（Phase 6 / canvas-editor Renderer Fork）的條件

- [x] AST 層級「結構正確」+「樣式正確」+「邊框正確」全部到位
- [x] 49 個 Phase 4 測試全綠 + 既有 284 測試零 regression
- [x] visual baseline pipeline 可即時量化下個 Phase 改動的真實效益
- [x] ADR-012 紀錄 Phase 4 達標未顯效的真實原因 + 下個 Phase 路線圖
- [ ] **Phase 6**：fork canvas-editor，把 ToCanvasEditor mapper 接到 fork 後的 Renderer，讓 effective borders / effective conditional styles 真正寫入 Canvas — **此項屬下個獨立 Plan，不在本計畫範圍**

---

## ADR-013：Sprint 50 — 轉路線 A（商業化先行 + Phase 7 效能優化）

**日期**：2026-05-15
**狀態**：已落地（Sprint 50-58 cache 五連發 + Sprint 56-59 perf 微優化）

### 背景

Sprint 28-49 連 22 個 sprint 攻 VR mean 收斂、到 0.0749（A- 級 mean ≤ 0.10）。商業化已可用。Sprint 50 決策點：繼續壓 mean（路線 B）vs 商業化先行（路線 A）？

### 決策

走路線 A：商業化先行 + Phase 7 效能優化。Sprint 50 加四段 timing（parse/layout/preload/render）建立 perf baseline。

### 揭示

**parse 占 60.7% 為主要瓶頸；render 29.3%、preload 8.1%、layout 僅 1.8%**。反直覺：parse 成本由 **XML 結構複雜度** 主導，不是檔案大小（42KB 監造表 187ms > 1860KB 週報 147ms）。

### 後果

- Sprint 51-54 AST cache 五連發、Sprint 56 ImageBitmap、Sprint 58 LayoutCache：full-warm 從 cold 12150ms → warm 1346ms（**7.01× speedup**）
- VR mean 不變（cache opt-in、預設不啟用）
- 揭示「單執行緒 render 邊際遞減」（Sprint 59 path coalescing ≈ 0 收益）

---

## ADR-014：Sprint 62 — FontMetricsAdapter 用 LibreOffice 系統 fallback fonts 對齊 goldens metric anchor

**日期**：2026-05-16
**狀態**：已落地 + Sprint 65 promote default-on

### 背景

Sprint 60-61 揭示鏈：
- Sprint 60 OffscreenCanvas probe：技術可行（puppeteer 4/4 features）但 Sprint 61 建議 pivot HarfBuzz
- Sprint 61 BrowserTextMetrics（Chrome `measureText`）：**negative result，VR +0.0013 退化**。**揭示 goldens = LibreOffice render anchor**、Sprint 28 經驗值 1.15em 反而比 Chrome real metric 更接近 LO

### 決策

不用 Chrome metric、用 LO 系統 fallback fonts（DroidSansFallback / LiberationSerif）作為 FontMetricsAdapter 的 metric source。

### 揭示（Sprint 14 nodeModuleStub 47-sprint 隱性 blocker）

Sprint 62 初測 VR 0.0749 完全不動。Diagnostic probe 揭示：**Sprint 14 引入的 `nodeModuleStub` 故意把 opentype.js 排除在 IIFE 外、所有 `registerFont` silent fail → adapter 永遠空、47 sprints 來沒人發現**。

修復 = FontMetrics.ts 改用 ESM `import * as opentypeNs from "opentype.js"`、bundle +80KB。修復後 VR 0.0749 → **0.0732（-2.3% 改善）**。

### 後果

- VR mean -1.7% 首次命中（Sprint 50-62 第一次）
- Sprint 65 promote `--font-metrics` 為 VR default-on（mechanical commit）
- 紀律 #5 揭示：「vitest 通過不保證 IIFE bundle 同 code 也 work」

---

## ADR-015：Sprint 64b — Strategy B（portal lazy load + IDB cache）為 production font 供應

**日期**：2026-05-16
**狀態**：infrastructure 落地（誠實定位）+ Sprint 69 修為 candidate fallback

### 背景

Sprint 62-63 揭示「VR 命中 -1.7% 但 production user 看不到、production 走 canvas-editor 不是自家 pipeline」。Sprint 64 audit 列三選項：

| 選項 | 描述 | 評估 |
|---|---|---|
| A | Bundle Noto Sans CJK 進 IIFE | +5-10MB bundle、不可接受 |
| B | Portal lazy load + IDB cache | +backend endpoint + frontend module，可接受 |
| C | 依賴 user OS 字型 | 跨平台不一致、不可接受 |

### 決策

走 Strategy B。Backend `/dobtor/fonts/<family>` + Frontend `FontLoader` (IDB cache + silent fallback)。

### 揭示

開工前 grep `doc_editor.js` 發現 production 走 `window["canvas-editor"].Editor` — Sprint 60-65 audit 假設 production 走自家 pipeline 是錯的。**Sprint 64b 誠實定位為「未來 migrate 準備 infrastructure」、不是「立即啟用 production -1.7%」**。

→ 紀律 #8：架構發現的 sprint 也要記下來。

### Sprint 69 後續

Sprint 69 HttpCase runtime test 揭示 `FONT_PATH_MAP` 寫死的 droid/liberation 在 odoo18 container 內**不存在** → dead code。修為 candidate fallback chain（WSL host + container 跨環境兼容）。

→ ADR-015 後續：紀律 #11（controller filesystem 必須 cross-check production 環境）。

---

## ADR-016：Sprint 70 — `fill_template` PDF graceful fallback（紀律 #11 第一應用）

**日期**：2026-05-16
**狀態**：已落地

### 背景

Sprint 69 揭示紀律 #11。Sprint 70 audit `doc_controller.py` 14 處 filesystem 互動：
- 12 處設計上 graceful（`if not shutil.which: return None`）
- 1 處 dead-but-graceful（`_lo_convert_to_html`）
- **1 處明確 broken**：`fill_template` PDF 路徑（line 1085 註解誤宣稱「`/usr/bin/soffice` 已確認存在」、實際 odoo18 container 無 libreoffice）

### 決策

不擴 container 字型（保持 minimal），改加 graceful fallback：
- `if not shutil.which('soffice')` → 回結構化 error + `fallback: 'docx'`
- `try/except (CalledProcessError, TimeoutExpired, FileNotFoundError)` catch all subprocess errors
- 修錯誤註解（紀律 #11 延伸：assumes-X 註解必須伴隨 runtime check）

### 後果

- user 從 500 拿到結構化 error
- 廠商可選擇擴 container（加 libreoffice 套件）或維持 docx-only export
- 紀律 #11 從揭示變成 **第一應用實例**

---

## ADR-017：Sprint 71 — `doc_zip_guard.py` 設計上避開 filesystem（紀律 #11 例外）

**日期**：2026-05-16

### 背景

Sprint 71 audit `doc_zip_guard.py`：**設計乾淨、無 filesystem 互動**（全程 `io.BytesIO`、無 `extractall` / `tempfile` / `os.path`）。紀律 #11 不適用。

### 揭示

**「無 filesystem 互動」是好設計、不是缺少 audit point**。紀律 #11 的應用優先級 = filesystem-heavy controller > in-memory model。

### 後續

補 3 個邊界 test（單檔 ratio bomb / 小檔不誤判 / 常數一致性）；揭示紀律 #12（test class 必須 explicit tag、否則 silent skip）。

---

## ADR-018：Sprint 67 — CONTRIBUTING.md 補完（Phase 0 唯一未完項）

**日期**：2026-05-16

### 背景

規畫書 §0.5 Phase 0 完成度 95%、唯一未完項 = CONTRIBUTING.md（§附錄 A `[ ]` 項從 Sprint 33 拖到 Sprint 67）。

### 決策

走 autonomous 路徑做 §附錄 A `[ ]` 項。CONTRIBUTING.md 10 章 / 13KB / **Sprint 紀律 8 條（從 Sprint 57-64b audit 萃取）**。

### 揭示

- 紀律 #7 延伸：mechanical commit 不只 code change、也適用 docs/process commit
- 紀律 #9（候選）：§附錄 A `[ ]` 項是 autonomous sprint 優先選擇

---

## ADR-019：Sprint 72 — `run_backend_tests.sh` 統一 21 個 Odoo backend tests

**日期**：2026-05-16

### 背景

Sprint 64b/66/68/69/71 加了 21 個 Odoo backend tests、無統一觸發。每次跑要記憶 `--test-tags=...` + `--http-port=8169` + `-u dobtor_doc_editor` 一長串 docker exec 命令。

### 決策

不上 GitHub Actions CI（CI 跑 Odoo runtime scope 大）、加 `tests/scripts/run_backend_tests.sh` 給 user 手動觸發 + 環境變數覆寫（ODOO_DB / HTTP_PORT / etc）。

### 後果

- 21 tests 一鍵跑（font_serve 12 + zip_guard 9）
- 紀律 #13 候選：backend test 必須有「定期被跑」機制才算真實 coverage
- Sprint 76+ CI 工程 Odoo container 鋪路

---

## ADR-020：Sprint 73-74 — autonomous docs sprint 範式（glossary + retro）

**日期**：2026-05-16

### 背景

Sprint 67 揭示 autonomous docs sprint 候選。Sprint 73 走 glossary（85 條術語）、Sprint 74 走 retro（Sprint 50-72 23 個 sprint 橫向回顧）。

### 決策

文件 sprint 也是有實質產出的 sprint、不是「無 code 變動 = 浪費」。retro 揭示「紀律生成節奏 1.77 sprint / 條」、「Sprint 60-62 三步揭示鏈是最大 inflection」。

### 後果

- glossary 把 23 sprint 累積的 85 個術語固化、新貢獻者 onboarding 時間縮短
- retro 把隱性收益曲線顯式化、未來 sprint 用「分布缺什麼」校準方向
- 紀律 #14 候選：規畫書 / audit doc / CONTRIBUTING / glossary 必須在每個重要 sprint 之後同步

---

## ADR-021：Sprint 117 — Portal cross-company collaboration by collaborator_ids（不加 company filter）

**日期**：2026-05-17

### 背景

Sprint 78 Finding B 揭示 `rule_doc_document_portal` 與 `rule_doc_document_company` 形成不對稱：

- group_doc_editor：collab rule + company rule AND 合用、跨公司被擋
- group_doc_portal：只有 collab rule、跨公司可讀寫

Sprint 78 audit 評為 medium、需 user 確認業務流程。Sprint 117 autonomous 收口時、讀 `security/doc_groups.xml` `group_doc_portal` 設計目的註解：「**讓 ChienYi 承包商 / 業主代表能線上編輯被授權的文件**」。

### 決策：保留現狀（不加 company filter）+ lock-in 4 test + 註解永久化

| 選項 | 評估 |
|---|---|
| 加 company filter（default-secure） | break ChienYi 承包商 / 業主代表跨公司編輯流程；admin 須改用多 company_ids 操作繁瑣 |
| **保留 + lock-in test + 設計文件化** | 設計意圖明示、test fail 強迫讀 rationale、可逆 |

選後者。`collaborator_ids` 是 explicit access grant、足以承擔授權邊界；admin 誤邀屬「業務流程紀律」、不是 access control 漏洞。

### 後果

- `tests/test_security.py` 新增 `TestPortalCrossCompanyCollaboration` × 4：
  - `test_portal_can_read_cross_company_invited_doc`（lock-in）
  - `test_portal_can_write_cross_company_invited_doc`（lock-in）
  - `test_portal_cannot_read_uninvited_cross_company_doc`（sanity）
  - `test_portal_search_includes_cross_company_invited`（sanity）
- `security/doc_security.xml` 註解擴 11 行、永久化決策、引用本 ADR / Sprint 117 audit
- backend 27 → 31 passed
- 揭示紀律 #18 子原則：「待 user 決策」候選的 autonomous 收口必須讀原始設計意圖（group / model 註解）後才決、不能憑 default-secure 直覺加邊界
- 可逆性：若 ChienYi 未來改為跨公司協作 disallow by default、移除 lock-in assertion + 加 company filter 即可、Sprint N_portal_company_rule_reversal.md 紀錄

### 參考

- 完整 rationale：[docs/sprint117_portal_company_rule_closure.md](sprint117_portal_company_rule_closure.md)
- Sprint 78 原始 audit：[docs/sprint78_acl_record_rules_audit.md](sprint78_acl_record_rules_audit.md) §2.3

---

## ADR-022：DocEditor 後台 UI 擴充為範本欄位拖曳建構器（Phase 8 Template UI Builder）

**日期**：2026-05-19

### 背景

User 提供 `test-risen.dobtor.com/.../esign_configure` 介面截圖，要求 `dobtor_doc_editor` 後台 `ir.actions.client` 全螢幕編輯器的視覺靠攏該圖（三欄式 + 欄位工具列 + 簽約人 chip + 右側 inspector），並新增「可拖曳欄位放到文件上做範本」功能。

此方向與規劃書原 scope（docx 1:1 高保真匯入、Phase 0-7 全部 docx 匯入相關，無電子簽章 phase）明確衝突，且與 Sprint 90-109 revert 教訓表面相似（同一張參考圖、相同方向）。

差異點：Sprint 90-109 是 **Claude 誤判**使用者意圖、未確認 scope 即批次執行 20 sprint。本次 user 明確認知衝突、明確認知 revert 教訓後仍決定推進——屬紀律 #18 的「user 認可或修改規畫書」合法路徑。

### 決策：正式擴張規劃書 scope，加入 Phase 8 Template UI Builder

| 選項 | 評估 |
|---|---|
| 拒絕、維持 scope（user 須另開模組） | user 已明確選擇改造既有 `ir.actions.client`、否決另開模組 |
| Strategy A：新建 doc_sign_builder 並存舊 DocEditor | Sprint 90-109 已試、被認定「助長順便做」、20 sprint 浪費可 revert 但仍是浪費 |
| **Strategy B：直接改 DocEditor**（本次選擇） | 失敗成本可見、會更謹慎；滿足 user「改造後台 ir.actions.client」明確要求 |

選 Strategy B，並用 **增量交付 + 條件啟動** 控制風險：
- Phase 1（視覺風格靠攏）：~1 週、無新 model，4 個檔案改動。
- Phase 2.1（inline control 拖曳）：~1 週、新增 `doc.template.signer` + `doc.template.field` model，用 canvas-editor 原生 control API；control 會被序列化回 docx，與原規劃書 docx 匯入體系一致。
- Phase 2.2（overlay 絕對定位）：~3-4 週、**僅當 Phase 2.1 實測明確不滿意才啟動**，不預設動工。

### 後果

- 規劃書 `dobtor_doc_editor_高保真匯入開發規劃.md` 第 0.2 節 Phase 完成度表追加「Phase 8 Template UI Builder | 0%」。
- `docs/sprint90_to_109_revert.md` 結尾追加「2026-05-19 後續」段，紀錄本次重啟與上次的差別。
- 紀律 #18 補充案例：紀律 #18 不是「禁止 scope 擴張」，而是「scope 擴張須走 user 認可或修改規畫書流程」；本 ADR 是流程合規範例。
- VR mean target、Phase 進度條須重新校準（Phase 8 工時不計入 docx 匯入 phase）。
- 可逆性：若 Phase 8 後續再被推翻，因走 Strategy B（直接改 DocEditor）、回滾需手動 diff 還原；不像 Sprint 90-109 可 byte-identical revert。這是 Strategy B 明知接受的代價。

### 參考

- 計畫檔：[/home/chichi/.claude/plans/mnt-d-work-odoo18-docker-addons-dobtor-sharded-sedgewick.md](/home/chichi/.claude/plans/mnt-d-work-odoo18-docker-addons-dobtor-sharded-sedgewick.md)
- Sprint 90-109 revert：[docs/sprint90_to_109_revert.md](sprint90_to_109_revert.md)
- 紀律 #18 出處：規劃書 [§6.5 18 條開發紀律](../dobtor_doc_editor_高保真匯入開發規劃.md#65-18-條開發紀律)


---

## ADR-023：報表管線（藥丸／快照）與 QWeb 轉換器

**日期**：2026-09～2026-10
**狀態**：已落地（`doc.render.mixin` / `doc.report` / `doc.qweb.converter`）

### 問題

ChienYi 以外的客戶要的是「單據」：同一份版面套不同記錄印出來。既有的
`doc.document` 是「一份文件一筆記錄」，套不到這個需求；而 Odoo 原生報表要
改版面就得改 XML，使用者碰不到。

### 決策

1. **範本 + 綁定**：`doc.template`（版面，含藥丸）＋ `doc.report`（把範本綁到
   `ir.actions.report`）。綁定存在時接管 `_render_qweb_html`，不存在就完全
   不影響原生。
2. **藥丸分兩類，語意不可混**：
   - **取值**（`record` / `line` / `group` / `running` / `taxTotals` / `image`
     / `page` / `html` / `i18n`）——會變成內容
   - **標記**（`repeat` / `condition` / `column` / `format` / `groupHeader`
     / `groupFooter`）——設計期的宣告，**絕對不印**；各自的 pass 吃掉它，
     攤平時再保險地丟一次（`_MARKER_SOURCES`）
3. **標記放哪裡就決定作用範圍**：表格列內＝整列、段落裡＝整段。理由是
   canvas-editor 的元素串列是扁平的，只有「列」與「`\n` 切出的段落」是可靠
   的邊界；任意區塊的起訖標記會被使用者編輯時拆散。
4. **失敗策略逐層明寫，而且不一致是故意的**：
   - 條件求值失敗 → **當真**（寧可多印；少印會被當成資料問題，追不到渲染層）
   - 條件式格式求值失敗 → **不套用**（格式套錯比沒套上難追）
   - 取值求值失敗 → 空字串（一個壞欄位不該讓整份文件產不出來）
   - 分組的分隔判斷失敗 → 當成「不是分隔點」（退化成不分組，比印出 N 個
     空組好看）
5. **沙箱只開一道窄門**：底線開頭的方法一律擋，白名單
   （`_SAFE_REPORT_METHODS`）逐筆讀過實作確認唯讀才加，呼叫走
   `report_helper()`。`_generate_qr_code` 刻意不收——它會回寫
   `qr_code_method`，也就是印一張 PDF 會改資料。
6. **轉換器只轉不搬**：`doc.qweb.converter` 把原生 arch 轉成範本，原生報表
   不動（見 [scope_decision.md](scope_decision.md) §7）。唯一會「猜」的地方
   是改寫規則表，猜完一定拿樣本記錄試算一遍；認不出來的寫法原樣保留並標成
   待確認，**不猜**。

### 後果

- 36 張原生報表全部轉得出來、34 張有內容（剩 2 張是版面預覽，本來就沒內容）
- 覆蓋範圍、刻意不支援的項目、量測方法：
  [qweb_converter_coverage.md](qweb_converter_coverage.md)
- 代價：快照管線的 pass 順序變成一條不可對調的鏈（`_snapshot_content_json`
  的註解是權威），每加一個新 pass 都要說清楚它為什麼在那個位置

---

## ADR-024：型別→格式只有一份表、欄位標籤走欄位定義、模型自備值、附頁

**日期**：2026-10-08
**狀態**：已實作
**起因**：對照 `report_extend_bf`（py3o/ODT 的報表模組）的「引用設計」。
它在範本裡寫 `o.bf_<欄位>` 就自動依型別格式化、寫 `o.bf_label_<欄位>` 就得到
欄位標籤，兩者都由一個 attribute-lookup hook 在**渲染時**依欄位定義決定。

### 問題

我們的格式規則有**五份**，互不相交，而且沒有一份在渲染層：

| 位置 | 涵蓋 |
|---|---|
| `doc_qweb_converter._auto_format` | monetary / float / integer / date / datetime |
| `doc_editor.js _metaForModelField` | selection（限頂層）/ monetary |
| `doc_editor.js _metaForLineField` | monetary |
| `doc_editor.js onInsertGroupSubtotal` | monetary；其餘固定兩位小數 |
| `fields._expr_for`（已退場的 alias） | date / datetime / selection / many2one |

渲染層只有兩個「看輸出長相」的事後修正（`_RECORDSET_REPR_RE`、
`rendered in ('False','None')`）。實際症狀全是靜默的：

- 轉換器不補 selection → `t-field="o.state"` 印 `done` 而不是「完成」
  （`stock` 的 `report_stockpicking_operations` 與 `report_stock_reception`）
- 編輯器左欄拖一個 date 進去印 `2026-10-08 00:00:00`、float 印 `100.0`
  ——**同一個欄位，走轉換器對、手工拉錯**
- 巢狀 selection（「客戶-狀態」）印代碼，三份判斷都只處理頂層
- **每一個 float 都印兩位小數**。原本寫 `getattr(field, 'digits', None)` 再判
  `isinstance(tuple)`，而 Odoo 的 `Field` **根本沒有 `digits` 屬性**（只有
  `_digits` 與 `get_digits(env)`）——所以那句永遠回 None、永遠退回兩位。
  註解寫著「float 看 digits」，實際上從來沒看過。影響兩種欄位：digits 是
  tuple 的（`partner_latitude` 是 (10,7)）、以及 digits 是 decimal.precision
  名字的（`product_uom_qty`；本機設定剛好是 2，客戶改成 3 位就會印錯）

### 決定

1. **型別→格式只有一份表**：`RenderFields._type_format_expression`，在渲染層。
   藥丸只要帶 `path`，格式就是對的。優先序：明寫的 `expression` > `meta.format`
   > 型別預設。轉換器與編輯器都呼叫它，編輯器**不再**自己寫型別判斷。
   - 轉換器只套數字與日期（`numeric_only=True`）。那組範圍是已經量過保真度
     （漏印 2 / 4）的現狀；原生 QWeb 對 `t-out` 的數字其實也不格式化，要不要
     分 `t-field` / `t-out` 是另一件事，要連著重新量才能動。
   - selection / 關聯欄位改成讓藥丸只帶 `path`，由渲染層處理——同一條路同時
     照顧手工做的範本。
   - **boolean 刻意不在表裡**：原生 QWeb 對布林沒有 field converter
     （`True` 印 "True"、`False` 印空白）。放進去會讓轉換的報表與原生不一致。
     要方框的範本（自主檢查表）明寫 `checkmark(object.x)`。
2. **欄位標籤藥丸**（`source='fieldLabel'`）：文字取 `fields_get()['string']`，
   跟著渲染語言走。表頭的「品名／數量／單價」就是欄位標籤，而 Odoo 的 .po
   早就翻好了；走 i18n 藥丸等於請使用者把 Odoo 的翻譯再抄一遍、每個語言一次，
   之後兩邊各自漂移。`labelModel` 要明講，因為表頭那顆藥丸放在重複列**外面**，
   求值記錄是主記錄，推斷不出明細的模型。
3. **模型自備值**（`doc_report_values()` → 範本用 `data.<鍵>`）：
   `_SAFE_REPORT_METHODS` 那份白名單是給**別人家的**方法開的窄門，每加一筆都
   要讀過 Odoo 原始碼確認不寫資料。整合者要加自己算的值時那是錯的門——那是他
   自己寫的程式碼。整份快照呼叫一次（結果放在 context 傳下去），失敗回空 dict。
4. **附頁**：把別的報表或固定 PDF 接在單據後面（合約＋標準條款、出貨單＋MSDS）。
   這是「攔在 HTML 層」的**唯一例外**——HTML 裡沒有 PDF 可接，所以多開一個
   `_render_qweb_pdf_prepare_streams` 攔截點。選它而不是 `_render_qweb_pdf`：
   前者給 `{res_id: {'stream': …}}`，接的是「這張單據的附頁」，多筆列印時每張
   後面都要有自己那一份。沒設附頁時那支覆寫等於不存在。
   - 重用既有附件的那幾筆要跳過：那份 PDF 上次就含附頁了，再接一次變兩份。
   - 固定 PDF 以 `sudo()` 讀位元組：它是**報表設定的一部分**，由能編輯
     `doc.report` 的人挑的，不是使用者資料。不 sudo 的話一般使用者列印會靜默少頁。

### 刻意不採用 bf 的做法

- `setattr(LookupBase, 'lookup_attr', …)`：行程層級 monkeypatch genshi，會影響
  同一個 Odoo 裡所有用到 genshi 的模組
- `key.split('bf_')[1]`：任何含 `bf_` 的屬性名都會被誤判，`IndexError` 還被
  下面的 `except` 吞掉
- `except (KeyError, TypeError, IndexError): val = undefined`：真正的錯誤變成
  靜默空白
- PyPDF2（已停止維護）／`unoconv`（需要外部 LibreOffice 行程）——附頁用 Odoo
  自己的 `odoo.tools.pdf.merge_pdf`，不加依賴

### 後果

- 格式規則從五份變一份，`_resolve_field` 的複本也收掉（轉換器委派給渲染層）
- 順手修掉 `digits` 是 decimal.precision 名字時退回兩位的既有錯誤
- 代價：渲染層現在會對每顆「只帶 path」的藥丸查一次欄位型別。走的是
  `_fields` 字典，成本可忽略，但它讓「藥丸的輸出」多依賴一個東西：模型定義。
  欄位型別改了，既有文件重新帶值時格式會跟著變（快照過的不受影響）。

---

## ADR-025：記錄這一側的設定，與「轉成列印範本」的入口

**日期**：2026-10-08
**狀態**：已實作
**起因**：`report_extend_bf` 的 `bf.extend` 是一個 AbstractModel，業務模型
`_inherit` 之後**每一筆記錄**自己帶報表設定（`template_odt_id`、`merge_report`
旗標、`list_pdf()`）。我們的設定全在 `doc.report`，依報表＋語言＋公司解析，
沒有任何 per-record 的概念。

### 問題

有些事只有「這一筆」知道：

* 這張出貨單要附的是**它自己上傳的**檢驗報告（每筆不同）
* 只有這一張合約要附標準條款（其他不要）
* 這一筆用客戶指定的版面

### 決定

三件都走**約定方法**（與 `doc_report_values()` 同一套做法），名字集中在
`doc.report._RECORD_HOOKS`，`doc.linked.mixin` 提供欄位與預設實作：

| 約定方法 | 用途 | mixin 的預設 |
|---|---|---|
| `doc_report_append_pdfs()` | 這一筆自己要附的 PDF（`ir.attachment` 或 bytes） | 回空——「哪些附件該印」是業務問題，猜錯會把不該外流的檔案印給客戶 |
| `doc_report_append_enabled()` | 這一筆要不要接附頁 | 讀 `doc_append_pages` 勾選 |
| `doc_report_template()` | 這一筆要用的範本 | 讀 `doc_report_template_id` |

**附頁的適用範圍是綁定決定的**（`append_record_policy`）：`always`（預設，
不問記錄）／`opt_out`／`opt_in`。預設 `always` 的理由是「在綁定上設好附頁卻
什麼都沒發生」會是個找不到原因的坑。記錄沒有那支方法時：`opt_out` 當成要附、
`opt_in` 當成不附——兩邊都取「設定者寫下的預設」而不是猜。

**範本覆寫的兩個限制，明寫在程式裡**：
* 模型對不上就忽略並留 log。拿 `sale.order` 的範本去印 `account.move`，
  印出來會是一張看起來正常、值全空的單據——比印出綁定的範本糟。
* **頁首頁尾只有一份**：wkhtmltopdf 的頁首頁尾是整份 PDF 共用的，做不到逐筆
  不同。覆寫的範本外框與綁定不同時留 log 並沿用綁定那一份。
* 解析結果依範本 id 快取：十張單據指定同一張特別範本時只解析一次。

### 「轉成列印範本」的入口

轉換器與精靈早就做完整件事，但**只能從選單進**，而那張表單第一個欄位是一個
有幾百筆的報表下拉。加三個入口（報表表單的 `button_box`、報表清單／表單的齒輪
動作、qweb 範本表單的 header 按鈕），都只是帶著 `report_id` 開同一個精靈——
**入口多、流程一條**。

從 view 反查報表（`_doc_candidate_reports`）依序試：完整 XML ID 相等 → 去掉
`_document` 後綴再比 → 詞幹 `ilike`（短於 6 字不比，`label`／`report` 會命中
一堆無關報表）。找不到就說明「轉換對象是報表不是範本」，**不猜**。

### 踩到的坑

☠️ **測試模式下 Odoo 會把 `_render_qweb_pdf` 短路成 HTML**
（`ir_actions_report.py:1008`，理由是「worker 不夠跑 wkhtmltopdf」）。兩個後果：

1. 我的 `_append_streams_for` 原本把回傳值直接 append，而測試模式下那是 **str**
   ——流到 `merge_pdf` 會變成一個看不懂的例外。已改成只收 `bytes`，其他型別
   跳過並留 log。
2. 用 `force_report_rendering` 強制產 PDF 的話，wkhtmltopdf 會回頭向同一個
   Odoo 行程要 assets，而 `--workers=0` 只有一條執行緒在跑測試——**直接死結**
   （實測一則測試卡 5 分鐘以上）。所以 `TestAppendPagesEndToEnd` 在
   `workers=0` 時 skip，訊息講明「附頁的頁數未由測試驗證」，頁數用
   `odoo shell` 手動量並記在
   [qweb_converter_coverage.md](qweb_converter_coverage.md) §7.5。

### 後果

- 附頁從「整張報表一組固定頁」變成「固定頁＋這一筆自己的頁」
- 代價：`_build_report_html` 現在每一筆都問一次記錄要不要覆寫範本。
  沒有任何記錄覆寫時只是多一個 `hasattr`，但它讓「印出來長什麼樣」多依賴
  一個地方：業務模型的程式碼。查問題時要記得看那三支方法。

---

## ADR-026：前後端都分層

**日期**：2026-10-08（Python）／2026-10-09（JS）
**狀態**：已實作

### 問題

兩個檔案長到沒有人會讀完：`models/doc_render_mixin.py` 3025 行 121 個成員、
`static/src/components/doc_editor/doc_editor.js` 7399 行 284 個成員。

但「太長」不是真正的問題。真正的問題是**每一層的不變量沒有地方可寫**：
pass 鏈的順序約束、`from_string()` 與 `compile_expression()` 的差別、
「canvas-editor 不能被 t-if unmount」——這些寫在三千行的中段，沒有人會讀到。

### 決定

| 原本 | 拆成 |
|---|---|
| `doc_render_mixin.py` 3025 行 | `models/render/` 六層（tree / sandbox / fields / i18n / snapshot / output）＋ 39 行組合點 |
| `doc_editor.js` 7399 行 | `doc_editor_{shared,shell,io,pills,templateui}.js` ＋ 809 行組合點 |
| `doc_qweb_converter.py` 2857 行 | `models/qweb/` 五層（entry / locate / expr / structure / blocks）＋ constants ＋ 65 行組合點 |
| `doc_controller.py` 2593 行 | `doc_convert.py`（轉換函式）＋ `doc_controller_base.py`（守衛，**不是** Controller）＋ 四個 Controller（文件 17／範本 10／多語 5／遙測 4 條路由）|
| `test_pill_pipeline.py` 3921 行 43 類 | 按被測層分成五支（snapshot / output / sandbox / fields / i18n）＋ 共用 helper |

四次都用**純組合**而不是「拆成多個可獨立存在的東西」：

* Python 用純 Python mixin（不帶 `_name`）再 `class X(A, B, …, AbstractModel)`。
  拆成六個 `AbstractModel` 再 `_inherit` 會在 registry 多出六個「單獨存在時是
  壞的」模型（snapshot 會呼叫 sandbox 的方法）。
  `_build_model` 以 `type(name, (cls,), …)` 建類別，宣告類別自己的 Python 基底
  會留在 MRO 裡——這是支援的做法。
* JS 用 mixin 工廠 `(Base) => class extends Base`。這是**一個** OWL 元件，
  四層共用同一個 `this.state` 與同一個 canvas 實例；拆成四個元件就要在它們
  之間同步狀態。
* JS 的常數另外一支（`doc_editor_shared.js`）是為了避免循環 import。

JS 分組依**檔案裡既有的 50 個區段註解**，不是用關鍵字猜。關鍵字分組試過：
96 個成員落到「其他」，而 `onPageFormatChange` 會因為帶 Format 被分到藥丸層。

### 怎麼驗證（這是這個 ADR 最該被重複使用的部分）

純搬移的重構不能只靠測試——測試覆蓋不到的成員搬丟了也是綠的。兩邊都用：

1. **成員逐一比對**：名稱集合相同、每個成員的原始碼文字相同
2. **程式碼行多重集比對**（JS 那次加的）：忽略空行與註解，比對所有程式碼行的
   `Counter`。這一招不依賴「我對成員邊界的判斷」，所以不會被我自己的切片邏輯
   誤差騙——JS 那次就是靠它才確定「只少兩行，而且兩行都是故意的」

兩次都靠這個抓到真缺陷：

* Python：`from .doc_document` 的相對 import 深了一層（測試抓到）；
  三個模組層級常數沒跟著搬（**測試沒抓到，pyflakes 抓到**）
* JS：同一個 class 裡有**兩支** `onTitleChange`（一支存檔名、一支套標題樣式），
  後面那個無聲覆蓋前面那個 → 在標題欄改檔名完全沒有作用。
  名稱集合出現重複才看得到。

### controller 的特殊之處

路由不能用 mixin 組合——Odoo 走 `http.Controller` 的**子類別樹**註冊路由。
所以拆法是「四個獨立的 Controller，各自擁有一組不重疊的路由」＋「守衛放在一個
**不繼承 Controller** 的純基底」。基底若繼承了 Controller，它會被當成另一組
路由來註冊。

這裡是**新增**而不是覆寫別人的路由，所以不涉及「覆寫路由要繼承擁有者 class」
那個坑。

驗證多一道：`TestRouteRegistration` 拿 Odoo 自己認路由的依據
（endpoint 身上的 `original_routing`，`http.py:759/827`）比對「宣告了但沒註冊」
的路由。☠️ 寫那一則時踩到：只看 `http.Controller.__subclasses__()` 會漏掉
`portal.py`——它繼承的是 portal 模組的 `CustomerPortal`，是**孫**類別。
漏掉的那三條是 portal 使用者唯一的入口。要遞迴走子類別樹。

### 後果

- 每一層的檔頭現在寫著自己的不變量，並指向對應的另一側（pills ↔ snapshot.py）
- ☠️ **import 區塊整段照抄，不要自己重組**：`doc_controller.py` 有一個跨 4 行的
  `from ..models.doc_zip_guard import (...)`，用「挑出開頭是 import/from 的行」
  重組會留下沒收尾的括號；而且模組層級常數（`_W` / `_XML` / `_HEADING_STYLES`）
  也會一起掉。這和 JS 那邊「重複整份 import」是同一個原則的兩種形式。
- ☠️ **相對 import 的深度**：`doc_qweb_converter.py` 在 `models/`、常數在
  `models/qweb/`，組合點要寫 `from .qweb.constants import`。少一層的症狀是模組
  整個載不進去。拆 `render/` 那次也踩過同一個坑——**第二次還是踩了**，
  所以寫在這裡。
- 代價：JS 五層各自重複整份 import 區塊。刻意的——少一個 import 的症狀是執行期
  `ReferenceError`，而 OWL 把它吞成一塊空白面板（我在組合點就犯過一次，
  tour 第 1/78 步停住）。多一個 import 沒有代價。
- ☠️ **不要在 `import {}` 裡面加註解**：Odoo 的 asset compiler 不會 strip 它，
  會輸出 `require({)` 讓整個 bundle parse fail。

---

## ADR-027：HTML → content_json 只處理自己的子集；`noupdate` 資料靠 migration

**日期**：2026-10-09
**狀態**：已實作

### 問題

模組自己出貨的 6 張 data 範本只有 `content_html`，沒有 `content_json`。
於是它們列印走 `_render_template` 那條舊路，**享受不到任何藥丸功能**——型別
格式、欄位標籤、頁面範圍、條件、重複列全都不生效。那是這個模組最實質的
完整性缺口：我們做的所有藥丸功能，在自己出貨的範本上都沒生效。

### 決定一：轉換器只處理「我們自己寫的那個子集」

Phase 5 的註解寫著「HTML → IElement 需要 canvas-editor 的 `executeSetHTML`，
那是瀏覽器端的東西」——**對任意 HTML 是對的**，所以那句話不是錯的，是範圍
的問題。出貨範本實際用到的標籤數過只有 12 個
（`p`/`h1`-`h3`/`b`/`strong`/`br`/`table`/`thead`/`tbody`/`tr`/`th`/`td`），
那個子集在伺服器端完全可靠。子集外的標籤留 note，不靜默吞。

正確性靠**來回轉換**：`html → content_json → html` 要與原 html 等價。
比逐個標籤寫斷言可靠，因為反向那條路（`_content_json_to_html`）本來就在用。

### 決定二：`noupdate` 的資料必須靠 migration

`data/doc_template_data.xml` 是 `<data noupdate="1">`，所以**改 XML 對既有
資料庫完全沒有作用**（只有新安裝會拿到）。`noupdate` 在這裡是對的——使用者會
編輯出貨範本，升級不該蓋掉他們的修改。

所以兩條路都要寫、而且不一樣：

| | 怎麼拿到 content_json |
|---|---|
| 新安裝 | 資料檔帶 |
| 既有資料庫 | `migrations/18.0.10.1.0/post-migrate.py` |

migration 只補「還沒有 `content_json` 的那幾張」，而且是照**使用者現有的**
`content_html` 轉，不是照我們出貨的。兩條都實測過。

### 決定三：去掉 `{{ var }}` placeholder

那些變數靠 `doc.linked.mixin._doc_render_context()` 帶入，而那支方法
**從來沒有任何消費者**——`_render_template()` 只以 `object=record` 與 `user`
求值。實測 render 一張出來，靠它填的格子就是空的。

留著的話在 content_json 路徑會變成印出「{{ subject }}」字樣，比今天的空白
更糟。所以遷移時一併去掉，並把那支方法刪了（ADR 之外另一個提交）。
正確做法：範本設適用模型 → 取值藥丸 → 要計算的值用 compute 欄位或
`doc_report_values()`。

### 踩到的坑

☠️ lxml 的**註解節點** `.tag` 不是字串而是 callable。`isinstance(tag, str)`
的寫法讓它掉進「未知標籤」分支，於是**註解內文被當成正文輸出**——估驗計價單
範本裡有一段 `<!-- Sprint Y12.2… -->`，轉出來那張印的是註解文字、
**而且後面的內容整段不見**。

抓到它的不是「轉得過、沒有 note」那一則測試（內容掉一整張它也會綠），
是後來補的 `test_shipped_templates_render_the_same_text_as_the_old_path`
——新路徑印出來的**文字**要與舊路徑一致。驗收測試要驗「輸出」，不是驗「沒報錯」。

---

## ADR-028：不做 GitHub Actions CI（2026-10-09 當天決定、當天撤回）

**日期**：2026-10-09
**狀態**：**撤回**——workflow 已刪除，repo 不再有 `.github/`

### 原本想解什麼

紀律 13 自己寫著「test 寫好 + tag 對 + script 一鍵跑都不夠，**沒人定期跑＝
半 dead test**」。586 則測試在那之前只在有人手動跑時跑，repo 連
`.github/workflows` 都沒有。做了兩支 workflow：static（push/PR 擋）與
backend（夜間不擋）。

### 為什麼撤回

撤回是專案決定（2026-10-09），不是技術失敗。但實作過程量到的三件事值得留著
——它們是**下次有人想重做時該先知道的前提**：

1. **夜間根本不會跑。** GitHub 的 `schedule` 事件**只從 repo 的預設分支讀
   workflow**。本 repo 預設分支是 `master`，而 `master` 是 2018-11-28 的單一
   提交、內容只有 `Readme.md`（repo 走每版一支分支：10.0 / dev-10.0 /
   dev-12.0 / dev-14.0 / dev-18.0，master 是遺棄的殘根）。
   把 workflow cherry-pick 到 master 更糟：它會在一個沒有模組的樹上跑
   `-i dobtor_doc_editor` → **每晚固定紅**。真正的前提是改 repo 的預設分支
   設定，那不是程式碼能解的。

2. **`paths` 篩選要把 workflow 檔自己列進去**，否則改了 gate 不會重跑 gate
   ——gate 壞掉要等下次有人改模組才發現，而修好它的那個提交也推不動驗證。

3. **第一次真的執行就紅在檢查自己。** static 寫好後隔了幾天才第一次真的跑
   （因為沒推），紅的是「`test_*.py` 都必須在 `tests/__init__.py` 裡」這條
   判準——純 helper 檔（零個類別）不該被 import。要用 AST 判斷有沒有
   `ClassDef`。
   ⚠️ 那次也暴露我自己的流程缺口：宣稱「本機跑過 CI」之前要把 workflow 的
   steps 列出來**逐一對照**，不要憑記憶列（六步我只跑了五步，漏的正好是紅
   掉那一步）。

### 撤回後靜態檢查靠什麼

Makefile 的 `ci-frontend` / `ci-python` / `ci-xml` / `test-js`（`make ci-all`
一次跑完）——這幾支 2026-06 就存在，是本機指令、沒有外部依賴。測試與 tour
仍然是 `make test-local` / `test-local-tour` 的責任。

**也就是說紀律 13 的那個缺口（沒人定期跑）在這個模組目前是敞著的，靠人跑。**
這是已知且被接受的狀態，不是漏掉。

---

## ADR-029：移除未出貨的 TS OOXML 子系統

**日期**：2026-10-09
**狀態**：已實作（版本 `18.0.12.0.0`）
**回退點**：`git tag doc-editor-before-ts-removal`

### 問題

第三輪稽核（§7.12）量到：模組裡有一整套自寫的 TS OOXML Parser 與它的測試、
fixture、量測 harness，**比出貨的部分還大**，而它不產生任何 production 行為。

| 未出貨 | 檔數 | 規模 |
|---|---|---|
| TS 原始碼 `static/src/core/**`、`components/doc_editor/Overlay*.ts` | 160 | 33,076 行 |
| vitest `tests/unit` | 134 | 29,578 行 |
| vitest `tests/integration` | 88 | 13,290 行 |
| fixtures（352 docx + 126 png） | 478 | **82 MB** |
| `scripts/` 量測 harness | 13 | 3,344 行 |
| `tools/`（CLI entry + fixture 建置） | 5 | — |
| rollup / tsconfig / vitest / package.json | 10 | — |
| `font_serve.py` ＋ 12 則 Python 測試 | 2 | 371 行 |
| 視覺回歸 harness（`test_layout.xml`、`test_harness.js`、2 條路由） | 3 | — |

| 出貨 | 檔數 | 規模 |
|---|---|---|
| Python | 44 | 15,001 行 |
| JS（manifest 有掛） | 29 | 12,035 行 |
| Python 測試 | 23 | 9,588 行 |

兩個產出都到不了使用者：

* `canvas-editor-custom.umd.js`：git 有追蹤，但**manifest 沒掛**。模組載的是
  上游 `canvas-editor.umd.min.js`（@hufe921 0.9.128）。除了產生它的 rollup
  config，沒有任何地方引用。
* `tools/dist/parse_docx_cli.cjs`：被 `.gitignore` 的 `dist/` 排除，**不進
  git**。`engine=ts` 找不到它就記 warning 回 `None`。

唯一的消費者 `importViaTsEngine()` 的 docstring 寫明是**驗收用途**
（「chichi 在 DevTools 跑」），沒有 UI 入口。`/dobtor/fonts/*` 兩條路由的唯一
消費者也是未出貨的 `font_loader.ts` 與 `ShapingFontChain.ts`。

### 決定

整批移除，不留孤兒。移除前逐項驗證「出貨的部分不依賴它」：

* 出貨的 `.js` **沒有任何一支** import `.ts`（grep 0 筆）
* `components/doc_editor/` 下那 14 支 `Overlay*.ts`，出貨的 JS 與 manifest **都沒提到**
* 出貨的三個 lib bundle 都**沒有**打到 `/dobtor/fonts`（grep 0 筆）

連帶處理：

* `import_document` 的 `engine` 參數**保留但只有一種行為**——舊呼叫端送
  `engine=ts` 不會壞，一律走 LibreOffice。
* `_ts_parse_docx_to_elements()` 刪除，原處留一行註記指向回退 tag。
* devtools 的 `/dobtor_doc_editor/test` 與 `test_data` 兩條路由刪除（fixtures
  與 CLI 都沒了，它們必然回 error）。
* Makefile 砍掉 `install` / `build` / `watch` / `dev` / `scan-ooxml` /
  `fixtures-*` / `visual-regression` / `ci-frontend` / `verify` / `clean-deps`，
  `ci-all` 收斂成 `ci-python + ci-xml + test-js`。
* `run_backend_tests.sh` 預設 tag 從 `font_serve,zip_guard` 改成 `zip_guard`
  ——不改的話那支會跑出「0 則測試」而看起來是綠的。

### 代價（寫清楚，因為這是可逆但不便宜的）

`engine=ts` 驗收通道消失。將來若要重做高保真 DOCX 匯入，得從
`doc-editor-before-ts-removal` 把需要的部分取回：

```bash
git checkout doc-editor-before-ts-removal -- dobtor_doc_editor/static/src/core/ooxml
```

### 驗證

後端 **590 則 0 失敗**（原 602，減掉 font_serve 的 12 則）、tour **78/78**、
manifest / flake8 / XML / `make test-js` 全過。

### 移除後的完整複查（同日第二輪）

第一次移除留了殘留，複查抓到並修掉：

| 殘留 | 為什麼漏掉 |
|---|---|
| `static/src/core/ooxml/worker/node_worker_entry.mjs` | 我只刪了 `*.ts`，那棵樹裡還有一支 `.mjs` |
| `canvas-editor-custom.umd.js` ＋ `.map`（695KB） | 在 `lib/` 不在 `dist/`，rollup 移除後再也 build 不出來 |
| 前端 `importViaTsEngine()`（53 行） | 後端已不回 `elements`，它必然卡在 `Array.isArray()` |
| `tests/scripts/run_backend_tests.sh` 預設 tag 仍是 `font_serve` | 打不存在的 tag ＝「0 則測試」看起來是綠的 |
| Makefile 的容器／DB／mount 預設還是 2026-05 的 `odoo18` / `odoo18_dev` / `/mnt/extra-addons` | `upgrade` / `restart` / `logs` / `test-backend` 在現在的 rig 上全都打不中；`ci-python` 還假設 host 有 flake8（這台沒有）|

**精確比對**（同一支 AST 腳本跑移除前後）：路由 **41 → 37**，差異正好是那四條
（`/dobtor_doc_editor/test`、`/dobtor_doc_editor/test_data`、
`/dobtor/fonts/<string:family>`、`/dobtor/fonts/list`），沒有多也沒有少。
（先前稽核記的「39 條」「40 條」都是正則漏數——AST 才準。）

**乾淨資料庫全新安裝**：`-i dobtor_doc_editor,sale,account,stock,purchase` 成功，
再於該新庫跑全部測試 **590 則 0 失敗**——證明沒有任何東西依賴舊庫的殘留狀態。
舊庫的 `test_layout` view 記錄已被 Odoo 自動清除（`ir_model_data` 查 0 筆）。

安裝期間的 docutils 錯誤與 `<i>` 無障礙警告都**本來就有**（manifest 的
`description` 與 views 都沒動過，用 `git diff` 對過 tag）。

**文件處理原則**：authoritative 的改（`CONTRIBUTING.md` 的指令表與 make target
清單、`glossary.md` 的 `--test-tags` 那條），**歷史與計畫 artifact 不改內容、
只加狀態 banner**（`SPRINT_AUDIT_CONSOLIDATED.md` 約 60 條死連結、
`高保真匯入開發規劃.md`、`canvas_editor_fork_strategy.md`、
`ooxml_whitelist.md`、`word_pagebreak_rules.md`）——改掉等於竄改當時的數據與
決策依據。

**剩下的已知項（不改）**：`models/qweb/expr.py:538` 的 F811（區域變數 `models`
遮蔽照抄 import 區塊裡的 `from odoo import models`，而那個名字在該檔從未以
`models.` 使用過——無害、且早於本次變更）。

---

## ADR-030：授權由 LGPL-3 改為 OPL-1

**日期**：2026-10-09
**狀態**：已實作（版本 `18.0.12.1.0`）

### 決定

`__manifest__.py` 的 `license` 由 `LGPL-3` 改為 `OPL-1`，依 Dobtor 模組授權統一
政策（新舊模組皆是）。新增模組根目錄的 `LICENSE`（官方 OPL-1 全文 ＋ 版權聲明
＋ 變更紀錄 ＋ 第三方盤點），並重寫 `LICENSES/README.md`。

`OPL-1` 是 Odoo 18 `ir.module.module.license` 的合法選項值
（`odoo/addons/base/models/ir_module.py:321`）——不是自訂字串。

### 改之前查證了什麼（這是重點，不是形式）

| 項目 | 結果 |
|---|---|
| **depends 的授權** | 六支全為 Odoo 18 CE 核心（`base` / `web` / `mail` / `html_editor` / `bus` / `portal`），**皆 LGPL-3，無 AGPL**。LGPL-3 相依不妨礙以 OPL-1 散布 |
| **自有檔案的授權標頭** | **0 個**——`models/` `controllers/` `wizards/` `views/` `security/` `data/` `static/src/` 全掃過，沒有任何檔案宣告 LGPL / AGPL / 第三方版權 |
| **有沒有 vendoring Odoo 核心碼** | 沒有。模組用 `_inherit` / override 擴充。唯一一處「一字不差的複本」註記（`models/qweb/expr.py:530`）指的是**本模組自己的** `doc.render.mixin`，不是核心 |
| **隨附第三方** | 三支檔案，詳見下 |

### 隨附第三方的實際組成（從打包檔的授權橫幅讀出，不是憑印象）

* `canvas-editor.umd.min.js` — `@hufe921/canvas-editor` 0.9.128，**MIT**
* `canvas-editor-plugin-docx.umd.js` — 同專案 docx plugin，**內嵌**：
  * **JSZip 3.10.1：MIT 或 GPLv3 雙授權 → 本模組選用 MIT**
  * pako：MIT（JSZip 的授權聲明中載明）
  * ieee754：BSD-3-Clause
  * `String.fromCodePoint` shim：MIT
* `canvas-editor-shim.js` — 本模組自有（414 bytes）

☠️ 第一版我把 `mammoth` 寫成「BSD-2-Clause、已內嵌」——**那是憑印象**。打包檔裡
只看得到 `http://schemas.zwobble.org/mammoth/style-map` 命名空間與 style-map
讀寫函式，不足以斷定內嵌範圍與授權。已改成據實記錄「可能內嵌，要回 upstream
的 `package.json` 才能確認」。

同理選用 Python 套件的授權改成**從已安裝版本的 package metadata 讀出**：
`python-docx` MIT、`docxtpl` **LGPL-2.1-only**（我原本寫 LGPL-3，錯）、
`odfpy` License 欄為 UNKNOWN 而 classifier 同時列 Apache-2.0 / GPL / LGPL。
這三者由使用者自行 pip 安裝、**不隨模組散布**，不影響本模組以 OPL-1 散布。

### 連帶清掉三份不再適用的授權檔

`LICENSES/` 原有 `fflate` / `opentype.js` / `harfbuzzjs` 三份——它們是**已移除的
TS 子系統**（ADR-029）的 npm 相依，會被打包進那個從未掛進 manifest 的
`canvas-editor-custom.umd.js`。模組現在完全沒有隨附這三個程式庫
（`grep -rli` 在 `static/` 下 0 筆），所以刪除並在 `LICENSES/README.md` 記明原因。

### 既有散布版本

2026-10-09 之前已散布的 LGPL-3 版本，其授權不受本次變更影響（已授出的 LGPL
權利無法追回）。這一點寫在 `LICENSE` 的「授權變更紀錄」。

### 驗證

乾淨資料庫全新安裝成功，`ir_module_module` 實際存到
`dobtor_doc_editor | OPL-1 | 18.0.12.1.0`；後端 **590 則 0 失敗**、
`make ci-all` 全過。

---

## ADR-031：移除模組內的 Claude Code hooks

**日期**：2026-10-09
**狀態**：已實作（版本 `18.0.12.1.1`）

### 移除什麼

`dobtor_doc_editor/.claude/`（git 追蹤，共 573 行）：

| 檔案 | 行數 | 原本在哪個時機強制什麼 |
|---|---|---|
| `settings.json` | 48 | 註冊下列四支到 PreToolUse / PostToolUse / Stop / SessionStart |
| `pre_bash_guard.py` | 110 | 擋 `git push`、production 升級、含 `stub`/`Phase D` 的 commit message、`rm -rf .claude\|.antigravity\|.git` |
| `post_edit_regulation_guard.py` | 120 | 偵測規畫書 §5 的違規寫法（勾選欄加敘述／百分比／刪除線） |
| `stop_audit_check.py` | 141 | `sprint-N-*` 分支結束時要求 `docs/sprintN_*.md` ≥ 50 行、含三層 SOP 數據、有 production code 變更 |
| `session_start_context.py` | 154 | 每個 session 注入當前 sprint 狀態與紀律提醒 |

### 為什麼

三個前提全部已經不成立：

1. **三層 SOP 的產出不存在了**。`stop_audit_check` 要求 audit doc 記錄
   「vitest + VR + spot check 結果」——那三層隨 ADR-029 移除，產不出來。
2. **sprint 流程的 artifact 不存在了**。339 份 `docs/sprintN_*.md` 在 2026-05
   合併成 `SPRINT_AUDIT_CONSOLIDATED.md` 並刪除；`session_start_context` 讀的
   `.antigravity/autopilot/state.json` 被 `.gitignore`、per-machine，實測這台
   機器沒有（它降級成不含 sprint 狀態的版本，不會炸）。
3. **`pre_bash_guard` 的「不 `git push`」與現在的工作方式衝突**。2026-10-09
   使用者明確指示推送（「推 dev-18.0」「直接執行」），而該 hook 的設計是擋下它。

☠️ 另一個發現：那四支 hook 在 2026-10-09 的工作 session **實際上沒有生效**
（推送全部成功、編輯沒有被攔）。也就是說它們已經是「寫著但沒在守」的狀態
——這和 ADR-029 移除的那個子系統、以及撤回 CI 的 ADR-028 是同一個形態：
**存在但不執行的東西，比不存在更糟，因為它會讓人以為有在把關。**

### 紀律本身沒有取消

`CONTRIBUTING.md` §5 的 22 條紀律仍然有效，只是回到靠人遵守與 review。
該節開頭已加註說明「不再有機器強制」，免得有人以為被擋下才算違規。

### 取回方式

```bash
git log --diff-filter=D -- dobtor_doc_editor/.claude
git checkout <那個 commit>^ -- dobtor_doc_editor/.claude
```

### 驗證

模組的安裝與測試完全不受影響（`.claude/` 不在 `manifest` 的 `data` 或
`assets`，也不被任何 Python / JS 引用）：後端 590 則 0 失敗、tour 78/78、
`make ci-all` 全過。

---

## ADR-032：取回 TS OOXML 子系統，並補上它從未真正運作的兩個環節

**日期**：2026-10-09
**狀態**：已實作（版本 `18.0.13.0.0`）
**取代**：ADR-029（移除）——該 ADR 的移除理由仍然成立，但**前提被這次修掉了**

### 為什麼取回

ADR-029 的核心論據是「這套東西不產生任何 production 行為」。查證之後發現那是
**結果，不是原因**——真正的原因是它的兩個產出從來沒有被接上：

| 環節 | 原本的狀態 | 後果 |
|---|---|---|
| `tools/dist/parse_docx_cli.cjs` | 被 `.gitignore` 的 `dist/` 排除、**從未進 git**。部署端容器只有 node、**沒有 npm**，不可能在機器上 build | `_ts_parse_docx_to_elements()` 永遠找不到 CLI → 記一行 warning 回 `None` → `engine=ts` 在**任何部署**上都沒運作過。而且因為優雅降級，沒有任何東西會報錯 |
| `canvas-editor-custom.umd.js` | git 有追蹤，但**從未出現在 manifest 的任何 bundle** | 瀏覽器端的 parser 從頭到尾沒被執行過。rollup 檔頭曾寫「Odoo 的靜態資源系統直接引用這個 bundle」——**那句話是錯的** |

兩個都是**接線沒接**，不是設計不可行。移除一套「只差兩條線」的 33,000 行投資，
代價不對。

### 補的兩件

**① CLI 產物進版控**

`.gitignore` 加例外：

```
dist/
!tools/dist/
!tools/dist/parse_docx_cli.cjs
```

理由寫在該處：部署端沒有 npm，產物進 git 是唯一可行的做法。

實測：host（node 22）與容器（node 18）跑同一份 `.cjs`，對同一個 fixture 輸出
**byte 數一致**（239,941），解析出 3 個 IElement。

**② 瀏覽器 bundle 掛進 manifest ＋ 給它一個消費者**

只掛不用等於每個後台頁面白載 425KB。所以同時加了
`DocEditorIo.importViaBrowserParser()`——與走後端 CLI 的 `importViaTsEngine()`
對稱的瀏覽器端通道，同一個 parser 兩條執行路徑，可以當場比對輸出。

查證過的事實（不是推測）：
* bundle 的全域是 **`DobtorCanvasEditor`**，16 個匯出
* 它**不含** canvas-editor 的編輯器 API（實測 `executeSetValue` / `CanvasEvent`
  / `command.execute` 皆 0 筆）→ 與上游 `canvas-editor.umd.min.js` **不衝突**、
  不會有兩份實例。rollup 檔頭寫「把 patch 過的 canvas-editor 一起打包」是錯的
  （`patches/` 本來就是空的，`patch-package` 跑起來說 "No patch files found"）
* **刻意不加到 `web.assets_frontend`**：portal 已經要下載 1.5MB，而 portal 沒有
  這條驗收通道

☠️ 寫這個方法時我第一版是**猜** API 的（`await parser.parse()`、
`ToCanvasEditor.toElements()`）——兩個都錯。正確用法在
`tools/parse_docx_cli.ts`：`parse()` 是**同步**的、mapper 的方法叫 `convert()`，
而且旗標要與後端送給 CLI 的一致（`renderGraphicsAsSvg: true`），否則兩條通道的
輸出不能互相比對。**有權威範例時不要猜。**

### 三道新的守門員（都驗過移掉會紅）

| 守什麼 | 怎麼守 | 移掉的話 |
|---|---|---|
| CLI 產物在版控裡 | `TestTsEngineChannel.test_cli_bundle_is_in_the_repo` | 3 則全紅 |
| `engine=ts` 端到端回得出 elements | `test_engine_ts_returns_elements`、`test_engine_both_...` | 同上 |
| manifest 真的載了 bundle、而且有消費者 | tour 第 2 步（真瀏覽器） | tour `[2/79]` 紅 |

最後一項特別重要：原本的失效模式正是「存在但不載入」，而那種狀態**不會報錯**。

### 順手修掉的測試缺陷

`sprint280_shaping_font_chain.test.ts` 與
`sprint281_phase2_1_full_chain_node_parity.test.ts` 在 `describe.skipIf(!HAS_FONT)`
的**主體頂層**做 `readFileSync(FONT)`。`skipIf` 只把裡面註冊的 test 標成 skip、
**不會阻止主體執行**，所以在沒有 DejaVu 字型的機器（macOS，那是 Debian 的路徑）
整個檔案 ENOENT 失敗而不是乾淨 skip。改成 lazy（第一次用到才讀）。

### 驗證

| | |
|---|---|
| vitest | **3059 passed / 108 skipped / 0 failed**（237 檔） |
| Odoo 後端 | **611 則 0 失敗**（596 ＋ 12 font_serve ＋ 3 ts engine） |
| tour | **79/79**（多一步 manifest 守門員） |
| CLI | host node 22 與容器 node 18 輸出 byte 一致 |
| 路由 | 37 → **41**（font_serve 2 條 ＋ 視覺回歸 2 條回來） |

### 仍然沒有解決的（誠實記錄）

* **規畫書 §5 那 36 項 `[x]`**：程式碼回來了，但「能力是否達成」要靠 VR 量測
  才能說，而 VR baseline 從 2026-10-09 之後沒有重跑過。取回 ≠ 回到當時的保真度。
* **`engine=ts` 仍然不是預設**：使用者按「匯入」走的還是 LibreOffice ＋
  canvas-editor 的 docx plugin。兩條 TS 通道（後端 CLI、瀏覽器 parser）都是
  驗收用，要不要升為預設是另一個決定，需要先有 A/B 保真度數據。
* **CI 沒有**（ADR-028 撤回），所以 `npm test` 的 3059 則與 tour 都靠人跑。

---

## ADR-033：檔案匯入拆成 `dobtor_doc_import` 獨立模組

**日期**：2026-10-09
**狀態**：已實作（核心 `18.0.15.1.0`、新模組 `18.0.1.3.0`）
**不含 migration**：此模組尚未正式商轉，依使用者指示略過既有 DB 升級路徑

### 為什麼拆

匯入這條線比核心編輯器還大，而它與核心的介面很窄：

| | 核心 `dobtor_doc_editor` | 新模組 `dobtor_doc_import` |
|---|---|---|
| Python | 44 檔 / 15,001 行 | 4 檔 |
| 出貨 JS | 29 檔 / 12,035 行 | 1 支 patch ＋ 1 個 bundle |
| TypeScript | **0** | 160 檔 / 33,076 行 |
| vitest | **0** | 222 檔 / 3,059 則 |
| fixtures | 0 | 82MB |
| 路由 | 36 | 5 |

混在一起的代價：每次部署都要帶上整套解析器的測試資料。

### 命名

`dobtor_doc_import`。評估過四個候選，理由寫在 2/5 的 commit：與
`dobtor_doc_editor` 同家族、夠短（XML ID 前綴每天都要打）、說的是能力不是技術。
否決 `dobtor_docx_import`（綁死格式，現在就同時吃 ODT）與 `dobtor_ooxml`
（說技術不說能力）。

### 跨模組介面只有四個

| 留在核心 | 為什麼 |
|---|---|
| `models/doc_zip_guard.py` | 核心的範本上傳也在用 |
| `models/doc_ins_syntax.py` | **只有**核心的範本上傳在用（步驟 1 從 doc_convert.py 抽出來的） |
| `controllers/doc_controller_base.py` | 新模組的 controller 繼承它拿 `json_http_route` |
| `tests/session_probe.py` | 新模組的 HttpCase 沿用，不複製一份 |

☠️ 核心的 `tests/` 因此變成**公開介面**（它是 Python 套件，跨模組 import 得到）。
改 `session_probe.py` 要想到新模組也在用。

### 五步，每步獨立驗證

拆之前刻意不一次搬完——937 檔那次移除（ADR-029）就是一次做完、結果留了 5 處殘留。

### 提案裡錯掉的一個前提（值得記）

提案寫「匯入按鈕在核心，路由搬走之後按鈕得改成 patch 注入」。量過之後不是：
`onImportClick` 打的是 `/dobtor_doc/upload_template`（**核心**路由）＋
canvas-editor 的 docx plugin（**核心**資源），**沒裝新模組也完全可用**。
真正依賴新模組的只有兩支沒有 UI 入口的驗收方法。步驟 5 因此從「重做入口」
縮成「patch 兩支方法」。

**先量再寫提案也還是會錯——提案的前提一樣要驗。**

### 搬的過程抓到的真問題

1. **批次精靈建出 0 份文件**（我搬壞的，但原因值得記）：它在**迴圈裡**
   `from ..controllers.doc_controller import _docx_to_html_with_format`——那是
   2026-05 controller 拆層**之前**的位置。拆層後仍然能動，是因為
   `doc_controller.py` 的「import 區塊整份照抄」慣例把那支 **re-export** 出來。
   搬到新模組後 ImportError 被 `except Exception` 吞掉 → 每個檔案走「跳過」分支
   → 精靈回報成功但建出 0 份。改成檔頭 import 正確的模組。
   **那個照抄慣例是為了安全（少一個 import ＝ 執行期 ReferenceError），但它
   也造成了隱性 re-export 耦合。**
2. **manifest assets 守門員守錯了模組**：原本由新模組的 vitest 守，但拆完之後
   核心才是有 28 支出貨 JS 的那一個、而核心沒有 vitest。核心補了
   `tests/test_manifest_assets.py`（3 則，Python，不需要 node）。
3. `scripts/font_probe.mjs` 等兩支寫死 `/mnt/d/work/...` 的 WSL 路徑——在任何
   其他機器上都不存在（早於拆模組）。
4. `jinja2_scanner.test.ts` 的被測對象是**核心**出貨的 JS，留在核心 → 改成跨模組
   相對路徑指回 sibling 目錄，代價寫在檔頭（核心搬那支檔案時這裡會以 Failed
   Suite 的形式壞掉，不靜默）。
5. 搬測試時漏帶兩個模組層名稱（`HAS_PYTHON_DOCX`、`_make_minimal_docx_bytes`）
   ——症狀是 NameError 被報成「測試錯誤」，看起來像被測路由壞了。

### 14 支 `Overlay*.ts` 是「寄放」不是歸屬

它們是 Phase 8 的 Phase 2.2 前置碼（§5 `[ ]` 未啟動），三個 rollup entry 都到
不了、出貨 JS 沒引用。放新模組的唯一理由是**拆完之後只有那裡有 TS 工具鏈**。
說明寫在 `static/src/components/doc_editor/README.md`。

### 驗證

| | |
|---|---|
| 兩個模組都裝 | **615 則 0 失敗**（591 核心 + 24 匯入） |
| **只裝核心** | **591 則 0 失敗**，新模組 uninstalled ← 拆乾淨的證明 |
| 核心 tour | 78/78 |
| 匯入模組 vitest | **3,059 passed / 108 skipped / 0 failed** |
| 兩邊靜態 | manifest / flake8 / XML / test-js 全過 |
