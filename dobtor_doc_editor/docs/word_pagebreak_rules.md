# Word page-break 規則樣本資料庫

**目的**：累積真實 .docx fixture 觀察到的 Word 內部 pagination 行為，作為 Paginator
heuristic 的依據；避免「對單一 fixture 修 paginator → 其他 fixture 退步」的隨機修法。

**起點**：Sprint 16 對 04_with_image 的深度診斷（[sprint16_pagination_baseline.md §4](sprint16_pagination_baseline.md)）。

**Sprint 17 補入**：04_with_image 全 4 個 fixture 的 trPr / drawing extent / row 結構數據，
做為「image-row break heuristic」的設計基礎。

---

## 1. 規則 R1：含大型 image 的 cantSplit row 強制獨佔頁面

### 觀察 fixture

| fixture | 我們 pages | golden pages | delta |
|---|---|---|---|
| 04_with_image/01.image_basic.docx | 1 | 4 | -3 |
| 04_with_image/02.圖.docx | 1 | 4 | -3 |
| 04_with_image/05.環檢圖.docx | 3 | 6 | -3 |
| 04_with_image/06.環清表.docx | 3 | 6 | -3 |

### 共通結構（以 06.環清表.docx 為代表）

```
section.body = [
  paragraph 段 ×3,
  table A: 6-row, all cantSplit
    row[0..3]: trHeight=340 twips (17pt), 一般文字 row
    row[4]:    trHeight=5159 twips (258pt), 內含 wp:inline image extent ≈ 368×276pt
    row[5]:    同 row[4]
  table B: 同 A 結構
  table C: 同 A 結構
]
```

### 我們的處理

contentHeight ≈ 742pt（A4 - top 50pt - bottom 50pt）。

逐 row 累加 pendingHeight：
- row[0..3] = 4 × ~17 = ~68pt（加 cell padding 後 ~91pt）
- row[4] image row = ~291pt（trHeight 5159 → 258pt + cell padding，但 cell 內 image 高
  4676820 EMU / 9525 ÷ 12.7 ≈ 276pt + cell padding > trHeight，故 atLeast 規則取 max ≈ 291pt）
- row[5] image row = ~291pt
- 總 = 91 + 291 + 291 = **673pt < 742pt** → 整 6-row table 一頁裝得下

3 個 table + 段落 → 我們算 3 頁。

### Word 的處理（從 golden 反推）

- 06.環清表.docx: golden 6 頁
- 規則推斷：每張 image row **獨佔一頁**

可能對應的 Word 內部規則（推測）：
- **Rule R1**：當 row 含 inline image 且 row.height 占 contentHeight 的較大比例（≥30%）
  且 cantSplit=true 時，Word 為避免 image 與其他 row 在同頁產生「視覺擁擠」，將該 row
  獨自推到新頁。
- 等價 heuristic：**行內含 image 的 cantSplit row 視為「強斷點」**，在排版時強制
  flush 當前頁。

### Sprint 17 採用的 heuristic（opt-in，預設關閉）

**條件**（同時成立才觸發）：
1. row.containsImage = true
2. row.cantSplit = true
3. row.height ≥ contentHeight × `imageRowBreakRatio`
4. pendingRows.length > 0 OR ctx.entries.length > 0（當前頁已有內容；空頁則不必換）

**觸發行為**：在放此 row 之前，先 flushTableEntry → nextColumnOrPage，讓此 row 從新頁起點放。

**為何預設 OFF（imageRowBreakRatio = 0）**：

Sprint 17 早期實驗：把 ratio 設 0.3，全 fixture 的 mismatched 從 17 升到 23，totalDelta
從 -26 翻成 +9（over-paginate）。原因：

- 04_with_image image row 連續出現（row[4] + row[5] 相鄰），ratio=0.3 會讓兩個都各自獨佔
  一頁 → 表格被切成 3 頁；但 Word 實際是 row[4] 獨佔頁、row[5] 與下一張表 std rows 共頁
  （連續 image row 不一定要跨頁）
- 規則本身不夠精細，需要更多 fixture 樣本（連續 image row、image+table 混排、image 與
  trHeight w:hRule="exact" 互動等）才能調出穩定 heuristic

**Sprint 17 交付（infra-only，預設不啟用 R1）**：

| 元件 | 狀態 | 用途 |
|---|---|---|
| `RowLayout.containsImage` 旗標 | ✅ Sprint 17 | TableLayout 計算；下游 layout / Renderer 可查 |
| `LayoutOptions.imageRowBreakRatio` | ✅ Sprint 17 | 0 = OFF（預設）；> 0 = 啟用 R1 |
| Paginator R1 邏輯 | ✅ Sprint 17 | 條件式 flush，opt-in |
| 全套 unit + integration test | ✅ Sprint 17 | 驗證旗標與 heuristic 條件分支 |

**Sprint 18+ 啟用 R1 的條件**：累積至少 5 個 fixture 樣本，含「連續 image row」「image
跨表混排」「image + 不同 trHeight 規則」，並建立每個樣本的「對 N 個 ratio 跑一次的
mismatched 計數矩陣」，挑出全 fixture 最低總 delta 的 ratio。

---

## 2. 規則 R2：trHeight w:hRule 的 atLeast / exact 行為

### 觀察

```xml
<w:trPr>
  <w:trHeight w:val="5159" />               ← 沒寫 w:hRule，預設 atLeast
  <!-- vs -->
  <w:trHeight w:val="5159" w:hRule="exact" /> ← 強制此高，超出 cell 內容也截斷
</w:trPr>
```

### Word 行為

| w:hRule | 行為 |
|---|---|
| 缺省 / `auto` | 高度 = max(trHeight, content height)；row 至少 trHeight，content 過高就撐高 |
| `atLeast` | 同上 |
| `exact` | 強制等於 trHeight，內容超出 cell 範圍**截斷**（不撐高） |

### 我們當前實作

[`TableLayout.ts:177-182`](../static/src/core/layout/TableLayout.ts) 已正確處理：
- `atLeast` → `Math.max(rowHeight, props.height)`
- `exact` → `rowHeight = props.height`

無需 Sprint 17 修改。

---

## 3. 規則 R3：wp:anchor 與 wp:inline 在 mc:AlternateContent 內的混用

### 觀察（04_with_image/06.環清表.docx row[4]）

```xml
<w:tr>
  <w:trPr><w:cantSplit/><w:trHeight w:val="5159"/></w:trPr>
  <w:tc>
    <w:p>
      <w:r>
        <mc:AlternateContent>
          <mc:Choice Requires="wps">
            <w:drawing>
              <wp:anchor ...>          ← 文字框 overlay（非主圖）
                <wp:extent cx="998220" cy="283845"/>  ≈ 78×22pt
              </wp:anchor>
            </w:drawing>
          </mc:Choice>
          <mc:Fallback>...</mc:Fallback>
        </mc:AlternateContent>
      </w:r>
      <w:r>
        <w:drawing>
          <wp:inline ...>              ← 主圖
            <wp:extent cx="4676820" cy="3506033"/>  ≈ 368×276pt
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>
  </w:tc>
</w:tr>
```

### Word 行為

- `wp:anchor` 是浮動繪圖，有自己的 wrap layout（layoutInCell="1" 表示限制在 cell 內）
- `wp:inline` 是內聯圖，主導 row 高度
- 兩者疊加時 row 高度 = max(inline image height, trHeight, anchor box absolute pos+height)

### 我們當前實作

| 步驟 | 實作位置 | 行為 |
|---|---|---|
| `effectiveChildren` 展開 mc:AlternateContent | [dom.ts:66](../static/src/core/ooxml/utils/dom.ts) | 取 mc:Choice 的子節點，跳過 mc:Fallback |
| Choice 內 wp:anchor → FloatImageNode | [DrawingParser.ts:38-45](../static/src/core/ooxml/drawing/DrawingParser.ts) | 路由到 FloatImageNode |
| ParagraphParser run loop | [ParagraphParser.ts:294,322-326](../static/src/core/ooxml/document/ParagraphParser.ts) | 兩者都進 RunNode list |
| Paginator filter floatImage | [Paginator.ts:600-617](../static/src/core/layout/Paginator.ts) | floatImage 不參與行內，獨立 placeFloatImage |

**結論**：wp:anchor / wp:inline 路由在 Sprint 17 之前**已正確分流**，不需 Sprint 17 補。
Sprint 16 audit §4.2 對此的指摘不成立（已驗證 effectiveChildren 行為）。

但 cell 內呼叫 `placeFloatImage` 時的座標與 wrap 邏輯**不太精確**（簡化為 row 內絕對
posOffset）。對 04_with_image fixture 影響輕微，因為 anchor box 體積小（78×22pt），不主
導 row 高度。

---

## 4. 規則 R4：cantSplit row 跨頁時的 fallback

### 觀察

如果 row.height > contentHeight 且 cantSplit=true → Word 強制把該 row 放在新頁，但
若新頁也放不下，**截斷顯示**或維持單頁含 overflow（不切 cell 內部）。

### 我們當前實作

[Paginator.ts:957-987](../static/src/core/layout/Paginator.ts)：
```ts
if (row.height > remainingHeightForRow && !row.cantSplit && remainingHeightForRow > 0) {
  // mid-row split
} else {
  // cantSplit 或 splitRowAtHeight 失敗 → 警告 + 整列推下一頁/欄
  ctx.warnings.push(`row 高度超過剩餘空間；無法 mid-row split，整列推下一頁`)
}
```

正確處理 cantSplit 整列推下頁，但**不處理 row.height > contentHeight 的 hard overflow**
（罕見極端 case，留 Sprint 18+）。

---

## 5. 規則 R5：tblHeader 列在跨頁時重複

### 觀察

OOXML 17.4.42 規格：`<w:tblHeader/>` 在 trPr 內標記此 row 為表頭；表格跨頁時自動在
延續頁頂端重複。

### 我們當前實作

[Paginator.ts:874-958](../static/src/core/layout/Paginator.ts)：跨頁時 push headerRows 到
新頁開頭，**符合規格**。

無需 Sprint 17 修改。

---

## 6. 規則 R6：keepNext / keepLines 段落黏住

### 觀察

`<w:keepNext/>` 表示「此段落不可與下個段落分頁」；`<w:keepLines/>` 表示「此段落內所有
行不可拆分到不同頁」。

### 我們當前實作

[ParagraphParser.ts:240-241](../static/src/core/ooxml/document/ParagraphParser.ts) 解析
flag，但 **Paginator 尚未實作 keepNext / keepLines 邏輯**。

### 影響

01_simple 等含「標題段 + 內文段」結構的 fixture 可能因 keepNext 行為差異產生 -1 偏差。

**Sprint 18+ 候選工項**：實作 keepNext / keepLines 推段邏輯。

---

## 7. Sprint 17 暫不採行的規則（留待後續累積樣本）

### R-pending-1：頁底 widow window 機制
Word 在頁底有「最少 N 行內文 + 段落空白」的最小空間，否則推下一頁。
我們的 widow/orphan 控制（widowMin=2, orphanMin=2）僅針對段落首尾，對表格 row 與 image row 的「視覺呼吸空間」沒實作。

### R-pending-2：trHeight w:hRule="exact" + image overflow 截斷渲染
Renderer 端目前不會把 image 截斷到 trHeight=exact 的範圍。01_simple fixture 中也未發現
此案例，留待 Sprint 18+。

### R-pending-3：wp:anchor 多列覆蓋（layoutInCell="0" 情境）
當前實作把 anchor 視為 cell 內的，沒處理 layoutInCell="0" 跨 cell 跨 row 的情境。
需要更多 fixture 樣本支撐才動。

### R-pending-4：mc:Choice Requires 屬性決定優先級
我們現在固定取 mc:Choice 的第一個。應依 Requires 屬性對應的 namespace 是否支援來決定
是否 fallback。對當前 fixture 影響為零（Word 365 產的 wps、wpc 等都在 Choice 內）。

---

## 8. 維護指南

每加入新 fixture 並發現 page count 偏差時：

1. 抓問題 fixture 的 docx XML：`unzip -p file.docx word/document.xml > /tmp/doc.xml`
2. 找出 trPr / wp:extent / w:hRule 等關鍵屬性
3. 比對「我們 ours」「golden ours」差距
4. 來這個檔加一個小節，描述觀察、推測規則、是否觸發既有 heuristic
5. 若需新 heuristic：列出條件、預估觸發 fixture 範圍、評估 regression 風險
6. 寫測試後再動 Paginator

---

## 9. 規則摘要表

| 規則 | 狀態 | 對應 fixture | 實作位置 |
|---|---|---|---|
| R1 | ✅ Sprint 17 採用（imageRowBreakRatio=0.3） | 04_with_image ×4 | Paginator.ts laySingleTable |
| R2 | ✅ 已實作（atLeast/exact） | 全部含 trHeight 的 fixture | TableLayout.ts layoutRow |
| R3 | ✅ 已實作（effectiveChildren + DrawingParser 分流） | 含 mc:AlternateContent 的 fixture | dom.ts + DrawingParser |
| R4 | ✅ 已實作（cantSplit fallback push 下頁） | 罕見極端 case | Paginator.ts laySingleTable |
| R5 | ✅ 已實作（tblHeader 跨頁重複） | 02_std_table、03_complex_table | Paginator.ts laySingleTable |
| R6 | ⏳ 待實作（keepNext / keepLines） | 01_simple -1 偏差候選 | Sprint 18+ |
| R-pending-1..4 | ⏳ 累積樣本中 | — | — |
