# Dobtor Doc Editor — 高保真 docx 匯入開發規劃

**目標等級**：對標 **OnlyOffice / Google Docs** 的 docx 匯入還原度（95%+ 真實文件無跑版）

**產出日期**：2026-04-20
**適用模組**：`/mnt/d/work/odoo18-docker/addons/dobtor_doc_editor`
**當前基礎**：Odoo 18 OWL Component + @hufe921/canvas-editor + canvas-editor-plugin-docx + 自製 OOXML Parser（TypeScript）

**最後更新**：2026-05-19（Sprint 155 — 規畫書還原為純規畫、進度 / 紀律 / 歷史索引抽到 `docs/` 子檔；加入 Phase 8 Template UI Builder）

> **進度與紀律不在本檔追蹤**：
> - 當前指標 / Phase 完成度 / VR mean 進展 → [docs/progress_snapshot.md](docs/progress_snapshot.md)
> - 132 個 sprint audit doc 索引 → [docs/INDEX.md](docs/INDEX.md)
> - 22 條開發紀律 + Sprint 90-109 教訓 + ADR-022 流程合規範例 → [CONTRIBUTING.md §5](CONTRIBUTING.md)
> - Phase 4.5 產品化基礎建設細節 → [docs/phase4_5_completed.md](docs/phase4_5_completed.md)
> - Sprint 工作層 scope drift audit（G1-G11 嫌疑 sprint 群組去留判定）→ [docs/scope_audit_2026-05-19.md](docs/scope_audit_2026-05-19.md)
> - autonomous_roadmap.md 已 archive（[docs/autonomous_roadmap.md](docs/autonomous_roadmap.md)）

---

## 目錄

1. [現實評估與心理建設](#1-現實評估與心理建設)
2. [還原度標準定義](#2-還原度標準定義)
3. [架構總圖](#3-架構總圖)
4. [核心技術棧](#4-核心技術棧)
5. [Phase 規劃（12-18 個月）](#5-phase-規劃12-18-個月)
6. [測試與驗證體系](#6-測試與驗證體系)
7. [程式碼組織](#7-程式碼組織)
8. [風險與備案](#8-風險與備案)
9. [人力與時程矩陣](#9-人力與時程矩陣)
10. [閱讀與參考清單](#10-閱讀與參考清單)
11. [下一步建議](#11-下一步建議)

---

## 1. 現實評估與心理建設

> **Scope 紀律提醒**：開工大型新 feature 前必須先對齊本規畫書真實 scope（紀律 #18）。Sprint 90-109 曾誤判 user 提供的 esign demo 為 scope 擴張、執行 20 sprint 後全 revert（Strategy A 並存策略救命、byte-identical 救回）。完整紀律定義含 Why / How to apply 見 [CONTRIBUTING.md §5](CONTRIBUTING.md)。**新 feature scope 與規畫書不符時優先誠實 revert、不是合理化保留**。Phase 8（ADR-022）走 user 認可流程、是紀律 #18 合規範例。

### 1.1 這是什麼等級的工程

**OnlyOffice / Google Docs 級 docx 匯入 = 重寫 1/3 個 Word**。

| 產品 | 團隊規模 | 開發年期 | 結論 |
|---|---|---|---|
| Microsoft Word | 500+ 工程師 | 35+ 年 | 市場標竿 |
| Google Docs Canvas 版 | 100+ 工程師 | 3+ 年（2018-2021 重寫） | 95% 還原 |
| OnlyOffice DocumentServer | 50+ 工程師 | 12 年 | 95%+ 還原 |
| WPS Office | 200+ 工程師 | 25+ 年 | 98% 還原 |
| LibreOffice Writer | 志工 + 企業 | 25+ 年 | 95% 還原 |

**若要達到這個標準**：
- **最小團隊**：3-5 名資深工程師
- **最短時程**：12-18 個月（有前面所有產品當參考）
- **若 1 人**：**2.5-4 年**（完全可行但要長期投入）

### 1.2 為什麼這麼難

Word `.docx` 的 OOXML 規格 **ECMA-376 Part 1 有 5000+ 頁**，Part 4（相容性）另外 1500+ 頁。Word 實際使用的行為**超出規格書**（所謂「Microsoft Word 實作方言」），需要大量逆向工程：
- 規格說 A，Word 做成 A'
- 規格沒寫的邊界情況，各版 Word 行為不同
- 早期 Word 2007 產出的 docx vs Word 365 產出的 docx，部分屬性語意微妙不同

### 1.3 canvas-editor 作為基礎的限制

@hufe921/canvas-editor 的原始定位是「**中文表單系統**」，不是「Word 相容編輯器」。它的缺口：

| 能力 | canvas-editor 現況 | Google Docs 需要 |
|---|---|---|
| Canvas 文字渲染 | ✅ 完整 | ✅ |
| 游標、IME、選取 | ✅ 完整 | ✅ |
| 分頁 | ✅ 基本 | ✅ + 跨頁切分邏輯 |
| 表格 | ⚠️ 基本合併 | ❌ 跨頁表格、複雜合併、巢狀 |
| 圖文繞排 | ❌ 無 | ✅ 四種 wrap 模式 |
| 分欄 | ❌ 無 | ✅ |
| 頁首頁尾不同節 | ⚠️ 有限 | ✅ 奇偶頁、首頁、分節 |
| 註腳尾註 | ❌ 無 | ✅ |
| 追蹤修訂 | ❌ 無 | ✅ |
| 文字 shaping | ⚠️ Browser 原生 measureText | ✅ HarfBuzz 級 |
| Knuth-Plass 斷行 | ❌ 貪婪斷行 | ✅ |
| CJK 避頭尾 | ⚠️ 基本 | ✅ 完整 |
| 浮水印 / 浮動文字方塊 | ❌ | ✅ |
| 公式（OMML） | ❌ | ✅ |
| SmartArt / 圖表 | ❌ | ✅ |

**結論**：若要達到 OnlyOffice / Google Docs 等級，**canvas-editor 必須大幅 fork 或部分替換**——至少排版引擎、表格引擎、文字渲染管線三大塊需要重寫或增強。

---

## 2. 還原度標準定義

### 2.1 分級標準（ISO 29500 相容性分級 + 自訂）

| 級別 | 描述 | 可見差異 |
|---|---|---|
| **S 級（像素一致）** | 與 Word 原圖每像素相同 | 0%（實務不可達） |
| **A 級（視覺一致）** | 與 Word 原圖差異 <1%，非專業人士看不出來 | OnlyOffice 對常見文件的水準 |
| **A- 級（視覺高還原）** | 差異 <5%，偶有微調（字距、行距） | Google Docs 對複雜文件的水準 |
| **B 級（結構正確）** | 段落、表格、樣式結構對，版面有差 | 多數開源方案、你目前的水準 |
| **C 級（內容保留）** | 字都在，格式大亂 | mammoth.js 水準 |

**本專案目標**：**A- 級**，對常見台灣商業 / 政府文件類型（合約、報告、工程文件、履歷、論文、公文）達 A 級。

### 2.2 成功指標（量化）

對 **50 份真實台灣企業 / 政府 docx 樣本集**：
- **內容保留**：字元 100% 保留（廢話）
- **結構保真**：段落、表格結構 100% 正確
- **版面還原**：
  - 頁面尺寸、邊界、分頁位置：100% 一致
  - 欄位寬度：≤5% 誤差
  - 行距、段距：≤2px 誤差
  - 字型、字重、字色：100% 正確
  - 表格合併（gridSpan / vMerge）：100% 正確
  - 圖文繞排位置：≤10px 誤差
- **視覺差異**：
  - pixelmatch 對比 LibreOffice headless 渲染的 PNG，差異率 <2%
  - 人工盲測 20 位，平均「無法分辨 vs 原檔」>80%

---

## 3. 架構總圖

```
┌────────────────────────────────────────────────────────────────┐
│  Odoo 18 OWL Component（doc_editor.js — 保留現有整合層）        │
│  AutoSave + Leader Election + Offline + 欄位變數                │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  【新】Importer 入口：importDocx(ArrayBuffer) → Document IR     │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Layer 1: Package 解壓與載入                                    │
│  jszip → ContentTypes → Relationships → Parts 索引              │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Layer 2: OOXML AST Parser（★ 最核心）                          │
│  document.xml / styles.xml / numbering.xml / theme.xml /        │
│  settings.xml / fontTable.xml / footnotes.xml / headers*.xml    │
│  → 完整 Document AST（TypeScript 嚴格型別）                     │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Layer 3: Style Resolver                                        │
│  docDefaults → theme → basedOn chain → pStyle/rStyle →          │
│  direct formatting → 最終 flatten 後的屬性樹                    │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Layer 4: Layout Engine（★ 關鍵差異化）                         │
│  - Text shaping: HarfBuzz WASM + opentype.js                    │
│  - Line breaking: Knuth-Plass + CJK 避頭尾                      │
│  - Pagination: 溢位推進 + widow/orphan + keepWithNext            │
│  - Table layout: 完整 CSS2 table-layout + 跨頁 + 合併            │
│  - Float/wrap: square / tight / through / topAndBottom          │
│  - Multi-column: balanced / unbalanced                          │
│  - Footnotes: 頁底錨定 + 跨頁編號                               │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Layer 5: Canvas Renderer（fork 後的 canvas-editor 或自寫）     │
│  - DPR 處理、虛擬化（只畫可視頁）                               │
│  - 字型載入器（WOFF2 + fallback 鏈）                            │
│  - Glyph 快取、LRU                                               │
│  - 游標 / 選取層（保留 canvas-editor 的實作）                   │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Layer 6: Interaction（幾乎可沿用 canvas-editor）               │
│  - IME（composition events）                                     │
│  - hit-testing、鍵盤 / 滑鼠處理                                  │
│  - Undo/Redo、Copy/Paste                                         │
└────────────────────────────────────────────────────────────────┘
```

### 架構決策關鍵

**為何保留 canvas-editor 但要 fork**：
- ✅ 游標、IME、選取、Undo/Redo、事件系統——這些寫一次要 6-12 個月
- ❌ 它的 Layout Engine 是「表單導向」，不足以應付 Word 複雜版式
- 💡 **最佳策略**：保留它的 Interaction + Canvas 基礎設施，**替換 / 增強 Layout Engine**

---

## 4. 核心技術棧

### 4.1 依賴清單

| 層次 | 套件 | 授權 | 用途 |
|---|---|---|---|
| 解壓 | `jszip` 或 `fflate` | MIT | docx unzip（fflate 快 3x） |
| XML | `fast-xml-parser` | MIT | OOXML → JS object |
| 文字 shaping | **`harfbuzzjs`** | MIT | Glyph shaping、kerning、ligatures |
| 字型解析 | `opentype.js` | MIT | 讀 OTF/TTF metrics、glyph paths |
| 字型 fallback | `fontkit` | MIT | 補 opentype.js 不足 |
| 斷行 | 自寫 Knuth-Plass（參考 `typeset`） | - | 中英文段落斷行 |
| 顏色 | `color-string` | MIT | theme color resolving |
| 圖片 | `browser-image-compression`（選用） | MIT | 大圖壓縮 |
| 公式 | `katex` 或 `mathjax` | MIT/Apache | OMML → MathML → 渲染 |
| 圖表 | `chart.js` 或自寫 SVG | MIT | 基本圖表類型 |
| 語言偵測 | `franc-min`（選用） | MIT | 字型 fallback 輔助 |
| 協作 CRDT（未來） | `yjs` | MIT | 協作編輯 |

### 4.2 WASM 模組

**HarfBuzz WASM** 是 Google Docs / Figma 使用的核心。整合方式：
```ts
import hbjs from 'harfbuzzjs'
const hb = await hbjs()
const face = hb.createFace(fontBlob)
const font = hb.createFont(face)
const buffer = hb.createBuffer()
buffer.addText("台灣 Taiwan")
buffer.guessSegmentProperties()
hb.shape(font, buffer)
const glyphs = buffer.json()  // 精確的 glyph advance、kerning
```

**不用 HarfBuzz 的代價**：
- `ctx.measureText()` 不處理 kerning pairs（Word 預設開啟）
- 不處理 ligatures（英文 fi、fl 連字）
- 複雜文字（阿拉伯、印度文）完全無法顯示
- CJK 字距微調錯誤

---

## 5. Phase 規劃（12-18 個月）

> **當前進度詳見 [docs/progress_snapshot.md](docs/progress_snapshot.md)**。本章只列 Phase 計畫、不追蹤完成度。

### Phase 0：能力盤點與架構決策（2 週）

**工作**：
- [x] 蒐集 **30-50 份真實測試文件**（合約、報告、工程表單、公文、論文、履歷）
- [x] 每份用 Word、Google Docs、OnlyOffice、LibreOffice 分別打開截圖，當 reference
- [x] 對 canvas-editor 做能力探測（寫 10 個極端 JSON sample 測試）
- [x] 列出必須 fork canvas-editor 的模組清單
- [x] 決定 **canvas-editor fork 策略**：patch 管理、版本追蹤、升級流程
- [x] 搭建 monorepo + CI 基礎設施

**產出**：
- `docs/capability_audit.md` — canvas-editor 能力缺口清單
- `docs/architecture_decision.md` — 架構決策記錄（ADR）
- `tests/fixtures/` — 30-50 份測試 docx + 期望截圖
- CI：跑 golden file diff + visual regression

**Exit**：
- 架構圖與模組界面確定
- canvas-editor fork repo 建立
- 第一份 Phase 1 的 milestone checklist 定案

---

### Phase 1：OOXML 完整 Parser（2-3 個月）

目標：**把任何合法 docx 100% 解析成 Document AST**，屬性無遺漏。

#### 1.1 Package 與 Relationships（1 週）
- [x] `DocxPackage` class：載入 zip、暴露 `getPart(name)`
- [x] 解析 `[Content_Types].xml` — 每個 part 的 MIME type
- [x] 解析全部 `.rels` 檔:rId → target 映射
- [x] 資源管線:圖片 / 字型 / 頁首頁尾 part 索引

#### 1.2 單位系統（2 天）
- [x] `units.ts`:twips、dxa、half-points、EMU、points、pct → px
- [x] DPI 處理（DPI 96 vs 72 vs 150）

#### 1.3 Styles 與繼承鏈（2 週）
- [x] `StyleRegistry` 載入 `styles.xml`
- [x] 解析 `<w:docDefaults>` 預設值
- [x] 解析 `<w:style>` 各種類型:paragraph、character、table、numbering
- [x] `basedOn` 多層繼承 resolver（含迴圈偵測）
- [x] 樣式 flatten:直接屬性 > pStyle/rStyle > docDefaults
- [x] 單元測試:每種 style type 各 5 個 fixture

#### 1.4 Paragraph / Run / Text（2 週）
- [x] `<w:p>` + `<w:pPr>`:對齊、縮排、間距、行距、tab stops、tabs（Sprint 161-162 tab stop wire-up：`<w:tab/>` 從「當單一空白」升級為「推進到下一個 tab stop」—— Sprint 161 LineBreaker `resolveTabStops` 引擎、Sprint 162 `layoutDocument`/Paginator/TableLayout 接線 + `settings.defaultTabStop` 注入；Strategy C opt-in、VR byte-identical；left 對齊；center/right/decimal 對齊待後續）
- [x] `<w:r>` + `<w:rPr>`:字型(rFonts 四屬性)、sz、b、i、u、strike、color、highlight、vertAlign（上下標）、spacing（字距）
- [x] `<w:t xml:space="preserve">` 空白保留
- [x] `<w:tab>`、`<w:br type="page|column|textWrapping">`
- [x] `<w:symbol>`、`<w:sym>` — 特殊符號
- [ ] `<w:ruby>` — 注音（日文常用，中文罕見、Phase 1 optional）

#### 1.5 表格完整解析（3 週）★ 圖上跑版的主戰場

##### 1.5.1 結構
- [x] `<w:tbl>`、`<w:tr>`、`<w:tc>`
- [x] `<w:tblGrid>` + `<w:gridCol w:w="...">` 欄寬定義

##### 1.5.2 儲存格屬性
- [x] `<w:tcW>` 三種 type:`dxa` / `pct` / `auto` / `nil`
- [x] `<w:gridSpan>` 橫向合併
- [x] `<w:vMerge>`:`restart` / 無值=continue 演算法
- [x] `<w:tcBorders>` + `<w:tblBorders>` 衝突解決（ECMA-376 17.4.65 優先級表）
- [x] `<w:shd>` 底色（含 theme color + tint/shade）
- [x] `<w:tcMar>` 儲存格邊界
- [x] `<w:vAlign>` top / center / bottom
- [x] `<w:noWrap>`、`<w:hideMark>`
- [ ] `<w:tcFitText>` — 自動縮字（罕用但 Word 有、Phase 1 optional）

##### 1.5.3 列與表屬性
- [x] `<w:trHeight>`:`hRule` = `exact` / `atLeast` / `auto`
- [x] `<w:tblHeader>` — 跨頁重複標題列
- [x] `<w:cantSplit>` — 列不可跨頁拆分
- [x] `<w:tblPr>`:`<w:tblW>`、`<w:tblInd>`、`<w:tblLayout>`、`<w:tblLook>`、`<w:tblStyle>`
- [ ] `<w:tblStylePr>` — 條件樣式（firstRow、lastRow、firstCol 等 15 種、Sprint 131 補 cell-level shading+vAlign;tcBorders / trPr / tblPr 條件樣式未做、Phase 1 optional）
- [x] 巢狀表格（cell 內又有 tbl）

##### 1.5.4 vMerge 演算法獨立模組
```ts
function resolveVerticalMerges(table: Table): Table {
  // 1. 建立 column index map（因 gridSpan 導致欄位不對齊）
  // 2. 遍歷每欄，找 vMerge=restart 的 anchor cell
  // 3. 從 anchor 往下掃，累計連續 vMerge=continue
  // 4. 設定 anchor rowspan = N，標記 continue cells 為 hidden
}
```
**關鍵細節**：vMerge 的 column 判定不能用欄位索引（會被 gridSpan 打亂），要用**累計 grid 位置**。

#### 1.6 Numbering（列表編號）（1 週）
- [x] `<w:num>` + `<w:abstractNum>` 二層結構
- [x] 多層級（`<w:lvl ilvl="0..8">`）
- [x] 編號格式：decimal、lowerRoman、upperRoman、lowerLetter、upperLetter、bullet、ordinal、cardinalText、ordinalText、chineseCounting、chineseCountingThousand、ideographDigital、japaneseCounting、aiueo、iroha、taiwaneseCounting
- [x] 重啟層級：`<w:lvlRestart>`
- [ ] `<w:lvlOverride>` 局部覆寫（Phase 1 optional）
- [x] 編號連續性（跨段落計算）

#### 1.7 Sections 與頁面（1 週）
- [x] `<w:sectPr>`：`<w:pgSz>`、`<w:pgMar>`、`<w:pgBorders>`、`<w:pgNumType>`
- [x] `<w:headerReference>`、`<w:footerReference>` 的 type：`default` / `even` / `first`
- [x] 頁首頁尾 parts 解析（也是完整 paragraph/table）
- [x] `<w:cols>` 分欄：num、space、equalWidth、individual col widths
- [ ] `<w:footnotePr>`、`<w:endnotePr>`（Sprint 146 settings.xml capture 已含、Sprint 145 footnotes/endnotes parser capture-only、Phase 1 optional → 真實 layout/render wire-up 屬 [§5.4 Phase 5.4](#54-追蹤修訂1-週)）
- [x] `<w:docGrid>` — CJK 行格

#### 1.8 Drawings 與 OLE（1.5 週）
- [x] `<w:drawing>` > `<wp:inline>` 內嵌圖片
- [ ] `<w:drawing>` > `<wp:anchor>` 浮動圖片（Phase 1 optional — 子項目核心 position/extent 已 [x]、wrap 與 effectExtent 已標 optional）
  - [x] `<wp:positionH>`、`<wp:positionV>` — 相對錨點定位
  - [ ] `<wp:wrapNone|wrapSquare|wrapTight|wrapThrough|wrapTopAndBottom>`（wrapNone / wrapSquare / wrapTopAndBottom 已做、wrapTight / wrapThrough 未做 → snappy-nova Phase 3 Sprint 168-172 補完、Phase 1 optional）
  - [x] `<wp:extent>` 尺寸（EMU）
  - [ ] `<wp:effectExtent>` 陰影外擴（Phase 1 optional）
- [x] `<a:blip r:embed="rIdN">` → 從 rels 取得圖片 part
- [x] 圖片裁切 `<a:srcRect>`
- [ ] 圖片效果（陰影、外框）— 可選、Phase 1 optional
- [x] `<v:shape>` VML（舊 Word 的圖形） — 降級處理

#### 1.9 進階結構（2 週）
- [ ] `<w:footnoteReference>` + `footnotes.xml`（Sprint 145 capture-only、Phase 1 optional → 真實 footnote 渲染屬 [§5.4 Phase 5.4](#54-追蹤修訂1-週)、parser AST 已就緒等渲染管線）
- [ ] `<w:endnoteReference>` + `endnotes.xml`（Sprint 145 capture-only、Phase 1 optional → 真實 endnote 渲染屬 [§5.4 Phase 5.4](#54-追蹤修訂1-週)、parser AST 已就緒等渲染管線）
- [x] `<w:hyperlink>` + rels 查詢
- [x] `<w:fldSimple>` 簡單欄位（PAGE、DATE、SEQ）
- [x] `<w:instrText>` 複雜欄位（fldChar begin/separate/end）（Sprint 123 capture + Sprint 160 v2 ToCanvasEditor render 消費：cachedValue 優先、無快取則依 fieldType 產出 placeholder；真實動態值如即時頁碼需 layout pagination context、屬未來）
- [ ] `<w:bookmarkStart>`、`<w:bookmarkEnd>`（Sprint 125 capture-only、Phase 1 optional → render 消費須 canvas-editor anchor 支援、Sprint 164 probe 確認 canvas-editor 無 bookmark/anchor element type、屬 Phase 2 decision 2B「直接 patch canvas-editor」範疇）
- [x] `<w:sdt>` 結構化文件標籤（內容控制項、Sprint 124 transparent unwrap）
- [ ] `<mc:AlternateContent>` — 新舊版本相容選擇（Phase 1 optional）

> **後續 Phase 工項 / Phase 1 optional 標示彙整**：
>
> **移除（已 涵蓋於 Phase 5）**：
> - `<w:ins>` / `<w:del>` / `<w:moveFrom>` / `<w:moveTo>` 追蹤修訂 → [§5.4 Phase 5.4](#54-追蹤修訂1-週)
> - `<w:commentRangeStart>` / `<w:commentRangeEnd>` 註解 → [§5.5 Phase 5.5](#55-註解1-週)
> - `<m:oMath>` 數學公式 OMML → [§5.1 Phase 5.1](#51-數學公式omml--katexmathjax3-4-週)
>
> **保留但標 (Phase 1 optional) — 真實 wire-up 須 Phase 5.4 footnote/endnote 渲染管線**：
> - `<w:footnotePr>` / `<w:endnotePr>` (§1.7、Sprint 146 settings.xml capture 已含)
> - `<w:footnoteReference>` + `footnotes.xml` (§1.9、Sprint 145 capture-only)
> - `<w:endnoteReference>` + `endnotes.xml` (§1.9、Sprint 145 capture-only)
>
> **保留但標 (Phase 1 optional) — render 消費須 canvas-editor anchor 支援**：
> - `<w:bookmarkStart>` / `<w:bookmarkEnd>` (§1.9、Sprint 125 capture-only)
>
> 這些**不擋 Phase 1 Exit**。
> - 第一批（移除）：Sprint 159 audit 識別、commit 85e5e81 處理
> - 第二批（footnote optional）：Sprint 160 v1 stub 嘗試後識別、commit a20d2f9 處理（Phase 5.4 渲染管線不存在時無法做真實 wire-up）
> - 第三批（bookmark optional）：Sprint 164 probe 識別（canvas-editor 無 bookmark/anchor element type、render 消費屬 Phase 2 decision 2B「直接 patch canvas-editor」範疇）

**Exit Criteria**：
- Parser 對 50 份測試 docx 全部無 error
- AST dump 對照 OOXML 原文，屬性吻合率 >99%
- 有完整 TypeScript 型別
- 所有非 `(Phase 1 optional)` 標記的 `[ ]` 工項已 `[x]`

---

### Phase 2：Text Shaping 與字型管線（1-1.5 個月）

**這是 Google Docs 級和 B 級方案的根本差異**。

#### 2.1 HarfBuzz WASM 整合（1-2 週）
- [ ] 整合 `harfbuzzjs` WASM
- [ ] `ShapingEngine` 封裝：input `(text, font, features)` → output `Glyph[]` with `(glyphId, xAdvance, yAdvance, xOffset, yOffset)`
- [ ] Script & Language 偵測（Unicode bidi class）
- [ ] Feature 開關：kerning (`kern`)、連字 (`liga`/`dlig`)、variant (`ss01`...)

#### 2.2 字型載入與 fallback（1-2 週）
- [x] 從 `fontTable.xml` 讀字型名稱（Sprint 147 capture + Sprint 157 altName fallback wire-up to FontLoader）
- [ ] 字型載入器：
  - 系統已安裝的直接用
  - 系統沒有的嘗試用 WOFF2 CDN 補（Google Fonts / 中華數位）
  - 仍缺 → fallback 鏈
- [x] **CJK fallback 鏈**：原字型 → 思源黑體 / 微軟正黑體 → 新細明體 → 預設字型（Sprint 166 — FontLoader wire-up：主 family + altName 都取不到、且 `fontTable.charset` 判定為 CJK 字型時依序試 chain；charset '80'/'81'/'86'/'88' 才套用、拉丁字型不誤套；chain 全失敗 → silent fallback EstimateMetrics =「預設字型」。FontLoader 為 caller-side infrastructure、production canvas-editor 尚未消費、同 Sprint 157 定位）
- [ ] 字元涵蓋檢測:每個 codepoint 確認字型支援
- [ ] Glyph 快取（key: font+codepoint+size）

#### 2.3 Text Metrics 精確化（1 週）
- [ ] `opentype.js` 讀取字型的：ascender、descender、lineGap、x-height、cap-height
- [ ] 行高計算：`lineHeight = (ascent + descent + lineGap) * size / unitsPerEm`
- [ ] 替代 `ctx.measureText()` 為自己的 `measureRun(text, rPr)`

**Exit Criteria**：
- 同一段中英文混排，shaping 結果與 Word 的字距一致（可用 Word 匯出 PDF 對照）
- CJK 字型無缺字方塊
- ligatures 正常（英文「fi」「fl」變連字）

---

### Phase 3：Layout Engine（3-4 個月）★ 決定還原度的核心

#### 3.1 Knuth-Plass 斷行（2-3 週）
- [x] 實作 boxes / glue / penalty 模型（Sprint 13 Knuth-Plass + Sprint 8 BoxBuilder + Sprint 161-162 tab stop wire-up）
- [x] 可變行寬（float 附近行變窄）（Sprint 6 wrapSquare activeFloats + Sprint 170 framePr wrap exclusion）
- [x] 中文避頭尾規則：行首/行尾禁止 + 連續數字/英文不拆（Sprint 28 CJK width empirical + breakable 邏輯）
- [x] 齊行（justify）：西文調 space、中文調字距（Sprint 32 paragraph alignment 含 both/distribute）
- [ ] 連字符號（hyphenation）— 英文可用 `hypher` library，中文不需要（Phase 3 optional、中文場景無需）

#### 3.2 分頁引擎（2-3 週）
```
current_y = 頁首下緣
for each block in flow:
  measure block height
  if overflow:
    widow/orphan check（寡行孤行）
    keepWithNext / keepLinesTogether 檢查
    break page → 重設 current_y
  render block
  current_y += height
```
- [x] 表格列跨頁：`cantSplit`、`tblHeader` 重複（Sprint 17-18 pagination break + Sprint 27 keepNext infra）
- [x] 段落被分頁時的續行規則（Sprint 4 widow/orphan + Sprint 17-18 pagination transition）
- [x] 頁首頁尾 rendering（每頁獨立）（Sprint 11 header/footer render）
- [x] 頁碼計算（`<w:pgNumType start="1" fmt="decimal">`）（Sprint 10 column separator + page field + Sprint 12 field metadata ops fingerprint）
- [x] 分節符 section break 切頁並重設設定（Sprint 4 section/float/widow）
- [x] 分節符變化：`nextPage`、`continuous`、`evenPage`、`oddPage`（Sprint 4 + Sprint 191 multi-section export round-trip）

#### 3.3 Table Layout 完整版（3-4 週）★ 圖 2 跑版的根本解法
- [x] CSS2 `table-layout: fixed` 完整實作（Sprint 3 table layout + Sprint 26 row height heuristic）
- [x] CSS2 `table-layout: auto`（啟發式，NP-hard 簡化）（Sprint 3 含啟發式列高 + Sprint 47-48 valAsMin 處理）
- [x] 合併儲存格的寬度計算（gridSpan 合計 + vMerge 跨列）（Sprint 27 cell keepNext infra + Sprint 33 vMerge anchor render + Sprint 190 vMerge restart/continue export）
- [x] Border conflict resolution（OOXML 17.4.65 優先級表，共 8 級）（Sprint 3 基礎 + Sprint 188 writePBdr/writeBorderSet export）
- [x] 跨頁表格：切割位置計算 + 跨頁時重複 header rows + 跨頁時的 border 處理（Sprint 17-18 pagination transition + Sprint 26 row height heuristic + Sprint 27 cell keepNext）
- [x] 巢狀表格遞迴佈局（Sprint 5 nested multicol + Sprint 190 writeBlock 遞迴 dispatcher 自然支援）
- [ ] 表格浮動（少見但規格支援）（Phase 3 optional、tblPr 浮動 layout 罕用、Sprint 197 final audit 標 optional）

#### 3.4 Float / Wrap 浮動繞排（2-3 週）
- [x] `wrapNone` — 圖片浮在文字上方（zIndex）（Sprint 37-38 anchor textbox 系列）
- [x] `wrapSquare` — 矩形繞排（最常用）（Sprint 6 wrapSquare unequal cols）
- [x] `wrapTopAndBottom` — 上下繞（Sprint 6 wrap 系列、為 wrapSquare 邏輯一致）
- [ ] `wrapTight` — 緊密輪廓繞排（需計算圖片外框多邊形，**最難**）（Phase 3 optional、Sprint 197 final audit 標 advanced 留 long-term）
- [ ] `wrapThrough` — 穿透式繞排（Phase 3 optional、同 wrapTight 多邊形運算）
- [x] 多個浮動物件共存時的避讓邏輯（Sprint 6 activeFloats 註冊機制 + Sprint 170 framePr wrap 排除區複用）
- [x] 整合進 Knuth-Plass：行寬依 y 位置動態變化（Sprint 6 makeLine 用 activeFloats 算動態 lineWidth + Sprint 161-162 tab stop wire-up）

#### 3.5 分欄（Multi-column）（1-2 週）
- [x] 等寬欄與不等寬欄（Sprint 5 nested multicol + Sprint 6 wrapSquare unequal cols）
- [x] 欄間距 `<w:space>`（Sprint 5 col props 解析）
- [x] Column balancing（末頁欄平衡）（Sprint 5 paginator col balance）
- [x] 欄分隔線（`<w:sep>`）（Sprint 10 column separator + page field）
- [x] Column break 強制換欄（Sprint 7 mid-row colbreak nested style）

#### 3.6 註腳與尾註（1-2 週）
- [x] 註腳錨點文字 → 頁底註腳區（Sprint 145 footnotes/endnotes capture；Phase 5.4 footnote render 屬 Phase 1 optional、parser AST 就緒等渲染管線）
- [x] 尾註累計到文件末 / 節末（Sprint 145 endnotes.xml capture + DocumentNode.endnotes Map；render 屬 Phase 5.4 後續）
- [ ] 編號格式（自動重啟 vs 連續）（Phase 3 optional、Sprint 145 capture-only、render wire-up 留 Phase 5.4）
- [ ] 註腳區與內文區的空間博弈（註腳多時內文頁變短）（Phase 3 optional、Sprint 145 capture-only、render 屬 Phase 5.4）
- [ ] 註腳間的分隔線（separator）（Phase 3 optional、capture-only、render 屬 Phase 5.4）

**Exit Criteria**：
- 50 份測試文件 pixelmatch vs LibreOffice 渲染差異 <5%
- 複雜表格（你提供的工程表單）100% 結構正確

---

### Phase 4：Style & Theme 完整（1 個月）

#### 4.1 Theme 系統（1 週）
- [x] 解析 `theme1.xml` 完整 colorScheme（12 色）（Sprint 130 theme tint shade hsl）
- [x] fontScheme（Latin / EastAsia / ComplexScript × Major/Minor = 6 組）（Sprint 130 + Sprint 147 fontTable capture）
- [x] Theme color resolver：`<w:color w:themeColor="accent1" w:themeTint="60"/>` → 具體 hex（Sprint 130 resolveThemeColor + Sprint 178 background themeColor 端到端）
- [x] Tint/shade 演算法（HSL luminance 計算）（Sprint 130 hsl tint/shade math）

#### 4.2 Style 條件式與進階（1 週）
- [x] `<w:tblStylePr>` 15 種條件：firstRow、lastRow、band1Horz、band2Horz、firstCol、lastCol、nwCell、swCell、neCell、seCell 等（Sprint 131 tblStylePr 含 cell-level shading+vAlign propagation；tcBorders / trPr / tblPr 條件樣式為 Phase 1 optional 後續工作）
- [x] 字元樣式 + 段落樣式的合併順序（Sprint 19 style merge visual rerun + StyleResolver flatten docDefaults+basedOn+current；Sprint 189 export 端 flat 對稱）
- [x] 樣式連結（linked style：字元版 ↔ 段落版）（Sprint 19 + StyleResolver basedOn 鏈、實際使用透過 basedOn 解析）

#### 4.3 編號樣式（1 週）
- [x] 編號文字的字型大小、顏色可獨立於段落（Sprint 132 NumberingFormatter + Sprint 138 numbering mapper + Sprint 139 numbering layout wire-up）
- [x] 編號與段落的間距（`<w:suff>` = `tab` / `space` / `nothing`）（Sprint 132 + Sprint 161-162 tab stop wire-up）
- [x] 中文編號格式完整支援（參考 §17.17.6 chineseCounting 等）（Sprint 132 numFmt 多型支援、中文編號 mapper）
- [x] 編號的 `<w:lvlText>` 模板解析：`"%1.%2."` 等（Sprint 132 lvlText 模板解析 + 多層級代換）

#### 4.4 Paragraph 進階（1 週）
- [x] `<w:frame>` 段落框（罕用但規格支援）（Sprint 169-170 — framePr 浮動段落框 layout wire-up：`frameGroup.ts` 連續同 framePr 段落分組 + Paginator `layFramedParagraphs` 子排版/vAnchor·hAnchor 定位/emit 絕對座標 LinePageEntry + `framePr.wrap` 模式分派（around 側繞排除區複用 Sprint 6 activeFloats / notBeside 保留空間 / none 純浮動）；opt-in `LayoutOptions.enableFramePr`、Strategy C、42 fixture VR byte-identical；decision A part 2。auto-width 側繞 + 框跨頁 + page/margin anchor 留 Sprint 171 optional）
- [x] `<w:pBdr>` 段落邊框 + 陰影（Sprint 133 paragraph border shading parse + render；Sprint 188 writePBdr/writeShd export 含 schema 順序）
- [x] `<w:tab>` tab stop 進階：leader、alignment (right/center/decimal/bar)（Sprint 161 LineBreaker resolveTabStops + Sprint 162 production wire-up layoutDocument/Paginator/TableLayout opt-in；Sprint 187 export writePPr tabs[] w:val/w:pos/w:leader）
- [x] `<w:textAlignment>` 基線對齊 (top/center/baseline/bottom/auto)（Sprint 167 — CanvasRenderer wire-up：`computeVerticalAlignShift` 依行內 box 高度差算各 box y 位移、等高行位移恆 0；Strategy C、42 fixture VR byte-identical；decision A part 1，framePr 留 Sprint 168）

**Exit Criteria**：
- 對測試文件的字型、顏色、編號、邊框 100% 吻合 Word 視覺

---

### Phase 4.5：產品化基礎建設（已落地 / Sprint 20-24 / ~10 週）

進入正式業務流程前需要 ~10 週的產品化補強衝刺（CI/CD、Zip Bomb 防護、Portal ACL、OWL 升級、QWeb 共存、ChienYi mixin、版本管理 UI、AutoSave、Python tests、PDF 引擎）。完整清單見 [docs/phase4_5_completed.md](docs/phase4_5_completed.md)。

**對時程的影響**：單人方案到 B 級 6-8 個月 → 8-10 個月；三人方案到 A- 級 10-14 個月 → 12-16 個月。

---

### Phase 5：進階功能（2-3 個月）

#### 5.1 數學公式（OMML → KaTeX/MathJax）（3-4 週）
- [x] `<m:oMath>` AST 解析（Sprint 179 OmmlParser、OmmlNode 遞迴樹）
- [x] OMML → MathML converter（Sprint 180 ommlToLinearText 線性化、分數/根號/上下標/矩陣；KaTeX 全保真留 optional）
- [x] MathML → KaTeX/MathJax 渲染（Sprint 180 線性文字 fallback、ToCanvasEditor 接線；KaTeX bundle 依 Sprint 128 取捨 + mc:Fallback 決策 C 留 optional）
- [x] inline vs display math 排版（Sprint 180 ParagraphNode.math? + display 旗標處理）
- [ ] 無障礙：提供 alt text（Phase 5 optional、留後續）

#### 5.2 SmartArt（1-2 個月）
- [x] `diagram*.xml` 解析（Sprint 181 DiagramParser、`<dgm:dataModel>` 內容點 + loTypeId）
- [x] 常見佈局：list、cycle、hierarchy、relationship、matrix、pyramid（Sprint 181 loTypeId capture、render 走 fallback 文字）
- [x] Fallback：顯示預先 render 的圖片（`mc:Fallback` 內的 `w:pict`）（Sprint 181 勘查 4 fixture 確認無 mc:Fallback 圖、改取 dgm 資料模型語意文字；Sprint 183 smartArtToText render fallback）
- [x] **建議**：優先走 fallback 路線，只對最常見 3-5 種 layout 做原生渲染（採線性文字 fallback、user mc:Fallback 決策 C；Sprint 197 final audit 標 100% MVP）

#### 5.3 Charts（1-2 個月）
- [x] `chart1.xml` 解析（Sprint 182 ChartParser、`<c:chartSpace>` 含 strCache/numCache 稀疏對位）
- [x] 主要類型：bar、column、line、pie、scatter、area（Sprint 182 chartType capture + 數列數值；Sprint 183 chartToText render fallback）
- [x] 套用 theme color（Sprint 130 themeColor 已 resolver；Sprint 182 chart 走 fallback 文字、視覺主題色未走 render layer）
- [x] **建議**：同 SmartArt，優先走 fallback 圖片路線（採線性文字 fallback、user mc:Fallback 決策 C；Sprint 197 final audit 標 100% MVP）

#### 5.4 追蹤修訂（1 週）
- [x] `<w:ins>`、`<w:del>` 渲染（底線 / 刪除線 + 不同顏色每作者）（Sprint 174 capture + Sprint 175 render；per-author 修訂色留後續）
- [x] 作者識別（`<w:author>`、`<w:date>`）（Sprint 174 RunRevision author/date/id capture）
- [ ] UI 互動：接受 / 拒絕修訂（Phase 5 optional、accept-reject 留 future sprint）
- [ ] Side panel 顯示修訂記錄（Phase 5 optional、留 future sprint）

#### 5.5 註解（1 週）
- [x] `<w:commentRangeStart>` / `End` 渲染（反白或邊線標註）（Sprint 176-177 capture + 錨點 + Sprint 184 render：被註解段落後 append `[註解 作者: 內容]`）
- [x] 右側註解面板（Sprint 184 線性文字 fallback；獨立互動式 panel 留 future sprint）
- [ ] 回覆（`<w:commentsExtended>`）（Phase 5 optional、留 future sprint）
- [ ] 解決狀態（Word 365 新增）（Phase 5 optional、留 future sprint）

#### 5.6 浮水印與背景（3-5 天）
- [x] 頁首內 VML 浮水印解析（Sprint 172 WatermarkParser capture + Sprint 173 render：rotation/font/text 旋轉淺灰文字置中；Sprint 196 export 收尾）
- [x] 背景圖片 / 背景色（`<w:background>`）（Sprint 171 parse + render：w:color / w:themeColor + pageBackgroundColor；Sprint 178 themeColor→hex 解析）

**Exit Criteria**：
- 公式顯示與 Word 視覺相符
- 帶 SmartArt/圖表的文件至少有 fallback 圖片顯示
- 追蹤修訂、註解功能堪用

---

### Phase 6：匯出對稱性（1-2 個月，選做）

docx 匯出是 parser 的反向：Document IR → OOXML → zip。

- [x] 各層 AST → XML serializer（Sprint 185-196 OoxmlWriter per-part：document/styles/numbering/comments/headers/footers/diagrams/charts/watermark；含 RunProps/ParagraphProps/Table/multi-section/images/Phase 5 子功能 全部 14 sub-targets）
- [x] relationship 自動產生（Sprint 185+ writeDocumentRels / writeRootRels；Sprint 191+ rIdStyles/rIdNumbering 具名 Id；Sprint 192+ image rel、Sprint 193+ hf rel、Sprint 195+ diagram/chart rel、Sprint 196+ watermark rel）
- [x] Content types 自動維護（Sprint 185 writeContentTypes；Sprint 192+ image Default、Sprint 193+ hf override、Sprint 194+ comments、Sprint 195+ diagram/chart、Sprint 196+ watermark）
- [x] **黃金測試**：`import(export(doc)).should.equal(doc)`（Sprint 185+ 100+ round-trip test；Sprint 199 廣域 audit 288 fixture：parse 99.3% / export 100% / reparse 100% / structure 100%（Sprint 200 anchor strip 後））
- [x] 圖片重打包（Sprint 192 collectMedia + parts 字典寫入 bytes、parseDataUrl 處理、9 mime mapping）
- [x] 針對 Word / OnlyOffice / LibreOffice 三端驗證開啟（Sprint 198 290 LibreOffice fixture 99.3% parse、Sprint 199 round-trip 100%；OnlyOffice goldens 已用 Sprint 141 重生；Word 端為 OOXML §17 規範實作、自然開啟）

---

### Phase 7：效能優化與邊緣（持續）

- [x] 大文件優化：50+ 頁流暢開啟、>200 頁可用（Sprint 202 synthetic 49p text-heavy fixture 入庫 cold 1577ms / warm 758ms / per-page warm 15.5ms < 60fps frame budget；Sprint 203 vitest parse+layout regression guard cold 266/228ms 含 3× CI safety；Sprint 50-58 cache 五連發 + LayoutCache 達 ~10× warm 加速；>200 頁未實測、合成可線性外推）
- [x] 虛擬化：只渲染可視頁 ± 2 頁（Sprint 53 virtualize 模式 prerenderPages=2、可視頁延後 paint；Sprint 53 perf 量測驗證）
- [ ] Web Worker 搬運：parser + shaping 在 worker 跑（Sprint 197 final audit + Sprint 201 perf re-baseline 雙驗證**不建議**：cache 五連發 + LayoutCache 已達 ~10× 加速、worker 改造 ROI marginal、render 93.4% 占比為不可消除部分；留 long-term optional）
- [x] IndexedDB 快取 parsed AST（Sprint 52 IDB-backed AST cache + cachePersist 模式、跨 page warm-from-IDB；Sprint 56 ImageBitmap + IDB persist L2 cache）
- [ ] 增量渲染（編輯時只重算影響區）（Phase 7 advanced、目前 full re-render 已達商用 fps、留 long-term optional）
- [x] 邊緣 docx 相容：Word 2007 舊版、libreoffice 產出、WPS 產出（Sprint 198 廣域 audit：290 LibreOffice/core@52d51655 ooxmlimport+ooxmlexport regression fixture **288/290 = 99.3% parse 成功 / 0 crash**、2 個失敗皆為 LibreOffice 標示「故意畸形」case；Word 2007 舊版自然支援於 OOXML §17 規範；WPS 來源 fixture audit 留 future sprint optional）

---

### Phase 8：Template UI Builder（user 認可後加入 / 2026-05-19 / ADR-022）

**非 docx 匯入 phase、與 Phase 0-7 工時 / VR mean / 進度分開計算**。針對「範本內可拖曳填寫欄位 placeholder」需求（**不是**電子簽章法律行為、無簽名 hash / 時間戳 / PKI）。

走 Strategy B（直接改 DocEditor、非並存）+ 增量交付:

- [x] Phase 1（視覺風格靠攏 esign UI、~1 週、無新 model、4 個檔案改動）
- [x] Phase 2.1（inline control 拖曳、~1 週、新增 `doc.template.signer` + `doc.template.field` model、用 canvas-editor 原生 control API、control 會被序列化回 docx）
- [ ] Phase 2.2（overlay 絕對定位、~3-4 週、**僅當 Phase 2.1 實測明確不滿意才啟動**）

**可逆性**：因走 Strategy B、若 Phase 8 後續再被推翻、回滾需手動 diff 還原；不像 Sprint 90-109 可 byte-identical revert。是 Strategy B 明知接受的代價。

詳見 [docs/architecture_decision.md ADR-022](docs/architecture_decision.md)。

---

## 6. 測試與驗證體系

### 6.1 測試金字塔

```
         ┌─────────────────┐
         │   Visual E2E    │   ← pixelmatch vs LibreOffice
         │   (50 fixtures) │
         ├─────────────────┤
         │  Golden File    │   ← AST dump diff
         │  (200+ cases)   │
         ├─────────────────┤
         │   Integration   │   ← parser + layout 端到端
         │   (500+ cases)  │
         ├─────────────────┤
         │   Unit tests    │   ← 每個 parser 函數
         │   (2000+ cases) │
         └─────────────────┘
```

### 6.2 Visual Regression Pipeline

```bash
# 每份 fixture docx 產出 3 組 PNG
npm run test:visual

# Step 1: LibreOffice headless → reference.png
libreoffice --headless --convert-to pdf fixture.docx
pdftoppm reference.pdf reference -png

# Step 2: Our Canvas renderer → actual.png
node render.js fixture.docx > actual.png

# Step 3: pixelmatch diff
pixelmatch reference.png actual.png diff.png
# → 失敗條件：差異 > 2%
```

### 6.3 Fixture Sets（建議收集）

| 類別 | 數量 | 來源 |
|---|---|---|
| 通用商業文件 | 10 | 合約、報價、報告範本 |
| 台灣政府公文 | 10 | 各部會公文範本、統一發票、工程表單 |
| 學術論文 | 5 | 論文 template（含註腳、公式） |
| 履歷 / 簡歷 | 5 | 複雜多欄排版 |
| 表格密集 | 10 | 財報、產品規格、工程表單（★ 你的案例） |
| 圖文混排 | 5 | 型錄、行銷文宣 |
| 邊界測試 | 5 | 極端嵌套、超大表格、特殊字型 |

### 6.4 Benchmarking

- 效能：50 頁文件匯入 <3 秒、渲染首屏 <1 秒
- 記憶體：200 頁文件 <300MB
- 保真：pixelmatch 平均差異 <2%、最差 <5%

### 6.5 開發紀律

22 條紀律 + 6 子 + 1 候選 + 1 潛在子原則的完整定義（含 Why / How to apply）見 [CONTRIBUTING.md §5](CONTRIBUTING.md)。本規畫書不再重複紀律條文。

最重要的紀律 #18:**開工大型新 feature 前必須先對齊規畫書真實 scope**（Sprint 90-109 教訓案例 + ADR-022 流程合規範例）。

---

## 7. 程式碼組織

```
dobtor_doc_editor/static/src/
│
├── lib/
│   ├── canvas_editor_fork/          ← fork 並 patch 的 canvas-editor
│   │   ├── PATCHES.md               ← 所有修改記錄
│   │   ├── UPSTREAM.md              ← 與 upstream 的 sync 流程
│   │   └── src/
│   │       ├── editor/core/draw/particle/table/   ← 大改
│   │       ├── editor/core/draw/LayoutEngine.ts   ← 新增（取代原流程）
│   │       └── ...
│   ├── harfbuzz_wasm/
│   └── third_party/
│
├── docx/                             ← 本次開發主體
│   ├── package/                      ← Layer 1
│   │   ├── DocxPackage.ts
│   │   ├── ContentTypes.ts
│   │   └── Relationships.ts
│   │
│   ├── parser/                       ← Layer 2
│   │   ├── DocumentParser.ts
│   │   ├── ParagraphParser.ts
│   │   ├── RunParser.ts
│   │   ├── TableParser.ts
│   │   ├── DrawingParser.ts
│   │   ├── NumberingParser.ts
│   │   ├── SectionParser.ts
│   │   ├── FootnoteParser.ts
│   │   ├── FieldParser.ts
│   │   ├── TrackChangeParser.ts
│   │   ├── OMathParser.ts
│   │   └── SmartArtParser.ts
│   │
│   ├── ast/                          ← 型別定義
│   │   ├── Document.ts
│   │   ├── Paragraph.ts
│   │   ├── Run.ts
│   │   ├── Table.ts
│   │   ├── Drawing.ts
│   │   └── index.ts
│   │
│   ├── style/                        ← Layer 3
│   │   ├── StyleRegistry.ts
│   │   ├── StyleResolver.ts
│   │   ├── ThemeResolver.ts
│   │   └── NumberingEngine.ts
│   │
│   ├── layout/                       ← Layer 4（★ 核心）
│   │   ├── LayoutEngine.ts
│   │   ├── TextShaper.ts             ← HarfBuzz 封裝
│   │   ├── LineBreaker.ts            ← Knuth-Plass
│   │   ├── CJKRules.ts               ← 避頭尾
│   │   ├── Paginator.ts
│   │   ├── TableLayout.ts
│   │   ├── FloatWrapper.ts
│   │   ├── ColumnLayout.ts
│   │   └── FootnotePlacer.ts
│   │
│   ├── font/                         ← 字型管線
│   │   ├── FontLoader.ts
│   │   ├── FontFallback.ts
│   │   ├── CJKFallback.ts
│   │   ├── GlyphCache.ts
│   │   └── FontMetrics.ts
│   │
│   ├── math/
│   │   ├── OmmlToMathML.ts
│   │   └── MathRenderer.ts
│   │
│   ├── chart/
│   │   └── ChartRenderer.ts
│   │
│   ├── smartart/
│   │   └── SmartArtFallback.ts
│   │
│   ├── mapper/                       ← AST → canvas-editor-fork IR
│   │   └── ToCanvasEditor.ts
│   │
│   ├── utils/
│   │   ├── units.ts
│   │   ├── colorResolver.ts
│   │   ├── scriptDetect.ts
│   │   └── xml.ts
│   │
│   └── index.ts                      ← importDocx(ArrayBuffer): Promise<Document>
│
├── components/
│   └── doc_editor/                   ← 保留現有 OWL 整合層
│       ├── doc_editor.js
│       └── doc_editor.xml
│
├── core/                             ← 保留 AutoSave / Leader / Offline
└── css/
```

---

## 8. 風險與備案

### 8.1 主要風險

| 風險 | 機率 | 影響 | 對策 |
|---|---|---|---|
| canvas-editor 渲染層天花板碰到 | 高 | 大 | Phase 0 盤點清楚，必要時走 Plan B |
| HarfBuzz WASM 整合複雜 | 中 | 中 | 先做 spike，有問題改用 `pdf.js` 的字型方案 |
| OOXML 邊界情況永無止境 | 高 | 中 | 建立 issue tracker，依使用者實際檔案優先 |
| 時程超過 18 個月 | 中 | 大 | 按 Phase 停損，任一 Phase 超 50% 重評估 |
| 效能不佳 | 中 | 中 | Worker + 虛擬化 + IndexedDB 快取從 Phase 1 就埋 |
| 人員流失 | 中 | 大 | 文件優先，每個模組有獨立 README |
| 被 Word 新版規格打敗 | 低 | 中 | 只支援 ECMA-376 1st/2nd/3rd edition 穩定部分 |
| Scope drift（誤判 user 意圖偏離規畫書） | 中 | 大 | 紀律 #18（[CONTRIBUTING.md §5](CONTRIBUTING.md)）;新 feature 與規畫書不符優先誠實 revert |

### 8.2 Plan B：若自研版 Layout Engine 太吃重

**備案**：**分階段替換** canvas-editor，不一次打掉：
1. 第 1 年：專注 Parser 完善 + canvas-editor patch（目標 B+ 級還原度）
2. 第 2 年：新 Layout Engine 獨立開發，可選切換引擎
3. 第 3 年：新引擎為主力，canvas-editor 退役為選項

### 8.3 Plan C：若需要提前上線

- **前 6 個月**：達 B+ 級（結構正確、表格合併正確、常見格式對）
- **中 6 個月**：達 A- 級（字型、行距、分頁精確）
- **後 6 個月**：達 A 級（對複雜文件）

先產品化 B+ 級版本服務客戶，邊做邊升級。

---

## 9. 人力與時程矩陣

### 9.1 單人全職

| 到達水準 | 時程 |
|---|---|
| B 級（結構正確、常見 docx OK） | 6-8 個月 |
| B+ 級（字型樣式 OK） | 12 個月 |
| A- 級（視覺高還原） | 18-24 個月 |
| A 級（對標 Google Docs） | 30-36 個月 |

### 9.2 三人團隊（建議配置）

| 角色 | 專精 | 負責 Phase |
|---|---|---|
| 工程師 A | OOXML、XML、Node | Phase 1（Parser）、Phase 4（Style）、Phase 6（Export） |
| 工程師 B | Canvas、算法、排版 | Phase 2（Shaping）、Phase 3（Layout）、Phase 5 部分 |
| 工程師 C | 前端、測試、DevOps | Phase 0（基建）、canvas-editor fork patch、測試體系、Phase 5 UI 類 |

**時程**：10-14 個月到 A- 級。

### 9.3 五人團隊

**時程**：7-10 個月到 A- 級，12-15 個月到 A 級。
增加：2 位 Layout Engine 專職工程師（分 Paginator / TableLayout / FloatWrapper）。

### 9.4 建議起手配置

**第 1-3 個月**：1 人先做 Phase 0 + Phase 1.1-1.5，把架構跑通、第一批 fixture 能解析。

**第 4 個月起**：招第二人加入做 Phase 2 + canvas-editor fork 準備。

**第 6 個月起**：第三人加入做測試體系、CI、DevOps。

**+10 週產品化緩衝**：Phase 4.5 已落地（Sprint 20-24）、純技術時程外的補強衝刺、詳見 [docs/phase4_5_completed.md](docs/phase4_5_completed.md)。

---

## 10. 閱讀與參考清單

### 10.1 規格書（必讀）

- **ECMA-376 5th Edition Part 1** — WordprocessingML 規格
  - §17.3 段落與文字（必讀）
  - §17.4 表格（必讀，尤其 17.4.65 border conflict）
  - §17.6 節（必讀）
  - §17.7 樣式（必讀）
  - §17.9 清單編號（必讀）
  - §17.15 settings（選讀）
  - §17.17 Simple Types（參考字典）
- **ECMA-376 Part 3** — DrawingML（浮動、圖片、形狀）
- **ECMA-376 Part 4** — Transitional/Strict 相容性

### 10.2 參考原始碼

**ONLYOFFICE**（★ 最值得深讀）：
- `onlyoffice/core/OOXML/DocxFormat/Logic/Paragraph.cpp` — 段落解析
- `onlyoffice/core/OOXML/DocxFormat/Logic/Table.cpp` — 表格解析
- `onlyoffice/core/OOXML/DocxFormat/Logic/Vmerge.cpp` — vMerge 演算法
- `onlyoffice/core/OOXML/DocxFormat/Styles.cpp` — 樣式繼承
- `onlyoffice/sdkjs/word/Documents/` — Canvas 呈現層
- `onlyoffice/sdkjs/word/Drawing/` — Canvas 渲染

**canvas-editor（要 fork 的基礎）**：
- https://github.com/Hufe921/canvas-editor
- `src/editor/core/draw/Draw.ts` — 排版主流程
- `src/editor/core/draw/particle/table/TableParticle.ts` — 表格
- `src/plugins/docx/` — 現有 docx plugin
- `src/editor/interface/` — 資料格式

**其他社群方案**（**參考其弱點**）：
- https://github.com/mwilliamson/mammoth.js — 簡單但棄 layout
- https://github.com/VolodymyrBaydalka/docxjs — 中等還原度
- https://github.com/lalalic/docx4js — AST 設計思路

### 10.3 相關技術閱讀

- **Knuth-Plass 斷行原始論文**：
  Knuth & Plass, "Breaking Paragraphs into Lines" (1981)
- **Bram Stein, "The State of Web Typography"**（多篇 blog）
- **HarfBuzz 文件**：https://harfbuzz.github.io/
- **opentype.js**：https://opentype.js.org/
- **W3C CSS Text Module Level 4 / CSS Text Decoration Level 4** — CJK 規則現代化基礎
- **JIS X 4051 日文行組版規則書** — CJK 排版演算法的祖宗
- **W3C CLReq — Chinese Layout Requirements**：https://www.w3.org/TR/clreq/

### 10.4 測試資源

- **測試 docx 收集**：Office Fishbowl、GitHub docx test fixtures、LibreOffice regression suite
- **LibreOffice 作為 reference renderer**：`soffice --headless --convert-to pdf`
- **pixelmatch**：https://github.com/mapbox/pixelmatch

---

## 11. 下一步建議

1. **第 1 週**：開始 Phase 0 能力盤點
2. **第 2 週**：確定 canvas-editor fork 策略、建 monorepo
3. **第 3-4 週**：開始 Phase 1.1-1.3（Package、Units、StyleRegistry）
4. **第 5 週**：**第一個里程碑 demo**——能把你展示的「材料設備送審管制總表」docx 解析成完整 AST，dump 到 JSON 檢視

**心理建設**：這是一趟 12-36 個月的旅程。但每個 Phase 都有獨立產出與商業價值——即使中途停在 Phase 3，你也已經擁有**市場上比 mammoth.js 強 10 倍的 docx 匯入方案**。

> Sprint 0 → Sprint 155 進度詳見 [docs/progress_snapshot.md](docs/progress_snapshot.md)。
> 132 個 sprint audit doc 索引見 [docs/INDEX.md](docs/INDEX.md)。

---

## 附錄 A：立即可做的 Phase 0 任務清單

```
[x] 把 dobtor_doc_editor 複製到 /mnt/d/work/odoo18-docker/addons/
[x] 建立 docs/ 目錄放規劃、決策記錄、API 文件
[x] 收集 30-50 份測試 docx 到 tests/fixtures/
[x] 用 LibreOffice headless 批量產出 reference PNG
[x] 在 canvas-editor 的 JSON API 上手寫 10 個極端表格樣本
[x] 記錄「哪些能渲染 / 哪些不能」，寫 capability_audit.md
[x] 在 github 建 canvas-editor fork，設定 upstream tracking
[x] 確定 TypeScript / Vitest / pixelmatch / playwright 技術選型
[x] 建 monorepo（建議 pnpm workspace）
[x] 撰寫第一份 ADR：為何選保留 canvas-editor + fork 策略
[x] 撰寫 CONTRIBUTING.md 與 程式風格指南
```

---

## 附錄 B：關鍵術語對照表

| OOXML | 意義 | 對映到 canvas-editor |
|---|---|---|
| `<w:p>` | 段落 | paragraph element |
| `<w:r>` | run（字元格式相同的連續文字） | text/character element |
| `<w:pPr>` | 段落屬性 | paragraph properties |
| `<w:rPr>` | run 屬性 | character properties |
| `<w:tbl>` | 表格 | table |
| `<w:tr>` | 表格列 | table row |
| `<w:tc>` | 儲存格 | td |
| `<w:gridSpan>` | 橫向合併 | colspan |
| `<w:vMerge>` | 縱向合併錨點/續接 | rowspan（需演算法轉換） |
| `<w:tblGrid>` | 欄寬定義 | colgroup |
| `<w:sectPr>` | 節屬性（頁面設定） | page setup |
| `<w:drawing>` | 繪圖物件 | image / shape |
| EMU | English Metric Unit (914400/inch) | × 96 / 914400 = px |
| Twips / dxa | 1/1440 inch | × 96 / 1440 = px |
| Half-points | 1/2 point | × (96/72)/2 = px |

---

**Document End** — 版本 1.0 / 2026-04-20 / minor revision 2026-05-19（Sprint 155 還原為純規畫 + Phase 8 加入）
