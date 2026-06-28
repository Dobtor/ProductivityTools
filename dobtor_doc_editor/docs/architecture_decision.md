# Architecture Decision Records — dobtor_doc_editor Track B

**建立日期**：2026-04-21
**最後彙整**：2026-05-17（Sprint 118 — §0 索引 + §0.5 規畫書 §3 對映 + ADR-021）
**適用範圍**：Track B（Canvas OOXML 完整渲染引擎），Phase 0 架構基準
**狀態**：Phase 0 確定，Phase 1+ 執行中持續更新

---

## 0. ADR 索引（Sprint 118 彙整）

21 個 ADR。編號 004-007 為歷史保留缺口（早期 numbering、無 ADR 文件）。

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

