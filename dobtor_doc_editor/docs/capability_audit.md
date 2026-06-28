# Canvas-Editor 能力缺口審計

**審計日期**：2026-04-21  
**審計版本**：@hufe921/canvas-editor v0.9.128  
**審計人**：Phase 0 自動分析 + 人工觀察  
**基準**：42 份台灣工程文件 fixture（監造會議、自主檢查表、估驗、照片報告等）

---

## 1. 測試 Fixture 分類

| 類別 | 目錄 | 份數 | 代表難度 |
|------|------|------|---------|
| 文字為主（監造會議記錄）| `01_simple` | 7 | 低 |
| 標準表格（週報、工地密度）| `02_std_table` | 8 | 中 |
| 複雜表格（估驗、送審管制、查驗）| `03_complex_table` | 8 | 高 |
| 含圖片（抽查照片）| `04_with_image` | 6 | 中-高 |
| 頁首頁尾（自主檢查表）| `05_header_footer` | 10 | 中 |
| 模板（含 +++INS+++ 變數）| `06_template` | 3 | 中 |

---

## 2. canvas-editor 已確認缺口（觀察自實際匯入）

### 2.1 表格渲染（高優先）★

| 功能 | 狀態 | 觀察 |
|------|------|------|
| 基本表格 | ⚠️ 部分 | 簡單表格可顯示 |
| `gridSpan`（橫向合併）| ❌ 跑版 | 合併格寬度計算錯誤 |
| `vMerge`（縱向合併）| ❌ 跑版 | 合併格位置錯位 |
| **跨頁 vMerge（合併儲存格跨分頁）** | ❌ 渲染斷裂 | 見下方說明 ★★ |
| 跨頁表格 | ❌ 截斷 | 表格在頁底被截斷不延續 |
| 巢狀表格 | ❌ 未支援 | 內部表格消失 |
| `tblHeader`（標題列重複）| ❌ 未支援 | 換頁後不重複標題 |
| 儲存格邊框衝突解決 | ❌ 未支援 | ECMA-376 §17.4.65 優先級未實作 |

> **已驗證案例**：`03_complex_table/送審管制.docx`（14欄跨欄合併）匯入後，
> 表格結構完全走樣，欄位重疊。

> **★★ 跨頁 vMerge（隱藏大魔王）**：當一個縱向合併儲存格橫跨分頁邊界時，
> 同一個 Cell 需在兩個 Page Context 中**分兩次繪製**（而非切割成兩個獨立 Cell）。
> 真正的演算法難點在於 **border 處理**：第一頁底部省略 Cell 下邊框、第二頁頂部省略
> Cell 上邊框，視覺上形成連通效果——而 Canvas 每頁為獨立 context，需明確記錄
> 「此處省略邊框」的狀態。實作時須在 `OoxmlTableLayout` 內建立 `CellContinuationRecord`
> 資料結構，於 Paginator 觸發分頁時偵測「Cell 尚未結束但頁面已滿」，並在下一頁頂部
> 重建渲染上下文。此問題是整個 Table Renderer 重寫中複雜度最高的單一挑戰，
> 建議參考 LibreOffice `SwTabFrame` 的 `bFollow` 機制。

### 2.2 文字渲染

| 功能 | 狀態 | 觀察 |
|------|------|------|
| 基本 CJK 文字 | ✅ 正常 | 標楷體、新細明體均可顯示 |
| Kerning / 字距 | ⚠️ 近似 | 使用 `ctx.measureText()`，非 HarfBuzz |
| **行高與 Font Metrics 精確度** | ⚠️ 累積誤差 | 見下方說明 ★★ |
| 上下標（vertAlign）| ⚠️ 部分 | 偏移量有誤差 |
| 注音（ruby）| ❌ 未支援 | |
| 欄位（PAGE、DATE）| ❌ 未展開 | 顯示原始 `fldChar` 文字 |

> **★★ 行高 Font Metrics 累積誤差（隱藏大魔王）**：`ctx.measureText()` 的
> `actualBoundingBoxAscent` / `actualBoundingBoxDescent` 在 CJK 字型上跨瀏覽器
> 不一致，導致每行約 +0.3px 的誤差。100 行後累積約 30px，正好將最後一行
> 錯誤地推入下一頁（蝴蝶效應），造成**分頁點判定錯誤**。
> 解法是引入精確字型度量管線：`opentype.js`（直接讀 TTF/OTF Ascender/Descender
> 原始數值，但每個 CJK 字型檔案 1–10MB，記憶體壓力較大）或 **HarfBuzz WASM**
> （Phase 2 正式方案，同時解決 Kerning 與 Metrics 問題）。
> 在 Phase 1 Parser 階段即需預留 `LineMetrics` 介面，避免 Phase 3 Layout Engine
> 與 `ctx.measureText()` 深度耦合。

### 2.3 頁面結構

| 功能 | 狀態 | 觀察 |
|------|------|------|
| 頁首（header）| ⚠️ 部分 | 內容可顯示，但奇偶頁/首頁切換無 |
| 頁尾（footer）| ⚠️ 部分 | 同上 |
| 多節（sectPr）| ❌ 未支援 | 節切換後頁面設定不更新 |
| 分欄（cols）| ❌ 未支援 | |
| 頁碼自動更新 | ❌ 未支援 | |

### 2.4 圖片與浮動元素

| 功能 | 狀態 | 觀察 |
|------|------|------|
| 內嵌圖片（inline）| ✅ 可顯示 | 尺寸基本正確 |
| 浮動圖片（anchor）| ❌ 位置錯誤 | 圖片落在段落外，位置不正確 |
| 圖文繞排（wrapSquare 等）| ❌ 未支援 | 文字不繞圖排列 |
| 文字方塊 | ❌ 未支援 | |

### 2.5 列表編號（Numbering）

| 功能 | 狀態 | 觀察 |
|------|------|------|
| 簡單項目符號 | ✅ 正常 | |
| 多層級編號 | ⚠️ 部分 | 縮排正確，但 CJK 編號格式（一、二、三）有誤 |
| `lvlRestart`（重啟計數）| ❌ 未支援 | |

---

## 3. 還原度等級評估

| Fixture 類別 | mammoth.js（目前）| canvas-editor 直接匯入 | 目標（Phase 3 後）|
|-------------|-------------------|----------------------|-----------------|
| 01_simple | C 級 | B 級 | A 級 |
| 02_std_table | C 級 | B- 級 | A 級 |
| 03_complex_table | C 級 | **D 級**（嚴重跑版）| A- 級 |
| 04_with_image | C 級 | C+ 級 | A- 級 |
| 05_header_footer | C 級 | B- 級 | A 級 |
| 06_template | — | — | A 級（Track A 已達）|

> **D 級**：結構性錯誤，無法辨識原始內容排列。

---

## 4. 必須 Fork 的 canvas-editor 模組

| 模組 | 原因 | 替換/增強方式 |
|------|------|-------------|
| Layout Engine（`editor/core/draw/`）| 表單導向，不支援 Word 表格模型 | 新增 `OoxmlTableLayout` |
| Table Renderer | 不計算 gridSpan/vMerge | 完整重寫 |
| Section/Page 管理 | 單節，不支援多節 sectPr | 增強 `PageBreakManager` |
| Text Shaping Pipeline | 使用 `ctx.measureText()`，精度不足 | 加入 HarfBuzz WASM 管線 |
| Float Manager | 無浮動元素管理 | 新增 `FloatAnchorManager` |

**不需替換的模組**（保留）：
- IME / composition event 處理
- 游標 hit-testing
- Undo/Redo stack
- Copy/Paste
- 基本 Canvas 渲染基礎設施

---

## 5. 下一步（Phase 1 前置）

1. 對每份 fixture 用 LibreOffice headless 生成 PNG 作為 golden reference
2. 建立 pixelmatch 自動化比對腳本
3. 確認 canvas-editor fork 倉庫結構（見 `architecture_decision.md`）
