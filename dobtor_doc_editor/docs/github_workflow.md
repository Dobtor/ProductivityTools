# GitHub Workflow — Issue / Project Board / Milestones

本文件定義 dobtor_doc_editor 開發的 GitHub 工作流程。所有 issue、milestone、label、project board column 都列在此處，可直接由負責人複製到 GitHub UI 或 `gh` CLI 建立。

> 對應規劃文件：`dobtor_doc_editor_高保真匯入開發規劃.md`、Plan file Part 2 Roadmap

---

## 1. Milestones（對應 Sprint）

每個 Milestone 對應一個 Sprint（2 週）。在 GitHub 建立順序：

| Milestone 名稱 | 預計起迄 | 對應 Sprint | 主要交付 |
|---------------|---------|-------------|----------|
| `Sprint 0 — Build chain ready` | 第 1-2 週 | Sprint 0 | rollup 通電、fixture 對比管線、patches/ 工作流 |
| `Sprint 1 — Parser foundations` | 第 3-4 週 | Sprint 1 | PackageReader + DocumentParser + ParagraphParser + RunParser |
| `Sprint 2 — Style & section` | 第 5-6 週 | Sprint 2 | StyleResolver + NumberingResolver + SectionParser + Header/Footer |
| `Sprint 3 — Tables (vMerge)` | 第 7-8 週 | Sprint 3 | TableParser + GridResolver + 簡單 Drawing |
| `Sprint 4 — HarfBuzz shaping` | 第 9-10 週 | Sprint 4 | HarfBuzz WASM 整合 + ShapingEngine + GlyphCache |
| `Sprint 5 — Renderer assessment` | 第 11-12 週 | Sprint 5 | canvas-editor 能力天花板測試 + patch list 報告（**決策關卡**） |
| `Sprint 6 — Layout: pagination` | 第 13-14 週 | Sprint 6 | Knuth-Plass 斷行 + 基礎 Paginator |
| `Sprint 7 — Layout: tables` | 第 15-16 週 | Sprint 7 | CSS2 Table Layout + canvas-editor fork（gridSpan/vMerge） |
| `Sprint 8 — vMerge cross-page` | 第 17-18 週 | Sprint 8 | 跨頁表格 + Drawing wrap |
| `Sprint 9 — Theme & numbering` | 第 19-20 週 | Sprint 9 | theme.xml + 多層次清單 + DocDefaults 鏈 |
| `Sprint 10 — ChienYi integration` | 第 21-22 週 | Sprint 10 | construction_supervision_base + portal 整合 |
| `Sprint 11 — Math (OMML)` | 第 23-24 週 | Sprint 11 | OMML → KaTeX |
| `Sprint 12 — SmartArt fallback` | 第 25-26 週 | Sprint 12 | SmartArt 圖片 fallback |
| `Sprint 13 — Track changes` | 第 27-28 週 | Sprint 13 | w:ins / w:del + comments |
| `Sprint 14 — DOCX export` | 第 29-30 週 | Sprint 14 | AST → DOCX 序列化 |
| `Sprint 15+ — Polish & ship` | 第 31+ 週 | 持續 | 效能、邊界、多人協作、產品化 |

```bash
# 用 gh CLI 一鍵建立所有 milestones
gh api repos/:owner/:repo/milestones -f title='Sprint 0 — Build chain ready' -f description='rollup 通電、fixture 管線、patches/ 工作流'
gh api repos/:owner/:repo/milestones -f title='Sprint 1 — Parser foundations' -f description='PackageReader + DocumentParser + ParagraphParser'
# ... (其餘 14 個 milestone 依此類推)
```

---

## 2. Labels（標籤系統）

```bash
# === 類型 ===
gh label create "type/parser"      --color "0E8A16" --description "OOXML Parser TypeScript"
gh label create "type/renderer"    --color "1D76DB" --description "canvas-editor / Layout / 視覺渲染"
gh label create "type/integration" --color "5319E7" --description "Odoo Python controller / portal 整合"
gh label create "type/fixture"     --color "FBCA04" --description "fixture / TDD / golden PNG"
gh label create "type/devops"      --color "C2E0C6" --description "build / CI / 工具鏈"
gh label create "type/docs"        --color "BFDADC" --description "規劃文件、patches 紀錄"

# === 嚴重度 ===
gh label create "P0"               --color "B60205" --description "阻擋上線，必須 sprint 內完成"
gh label create "P1"               --color "D93F0B" --description "影響核心場景"
gh label create "P2"               --color "FBCA04" --description "Nice-to-have"

# === 角色 ===
gh label create "role/A-parser"    --color "BFD4F2" --description "Parser 工程師主責"
gh label create "role/B-renderer"  --color "BFD4F2" --description "Renderer 工程師主責"
gh label create "role/C-qa"        --color "BFD4F2" --description "QA + 整合工程師主責"

# === 狀態 ===
gh label create "blocked"          --color "000000" --description "被其他 issue 卡住"
gh label create "needs-decision"   --color "FF00FF" --description "需要 chichi 拍板"
gh label create "fixture-fail"     --color "B60205" --description "fixture pixelmatch diff > 閾值"

# === canvas-editor ===
gh label create "ce-fork"          --color "5319E7" --description "需要 patch-package 修改 canvas-editor"
gh label create "ce-upstream"      --color "0E8A16" --description "已對 hufe921/canvas-editor 提 PR"
```

---

## 3. Project Board 結構（GitHub Projects v2）

建立一個 board，命名為 **dobtor_doc_editor Roadmap**，欄位（status field）：

| Status | 用途 |
|--------|------|
| 📋 Backlog | 尚未排入 sprint 的 issue |
| 🎯 Sprint Planned | 已分派到某 milestone，待開工 |
| 🚧 In Progress | 開發中（負責人 assign） |
| 🧪 Fixture-Testing | 程式碼完成，跑 fixture 回歸 |
| 👀 Review | PR 已開，等其他角色 review |
| ✅ Done | 已 merge 且 fixture pass |
| ❄️ Blocked | 等待外部依賴或決策 |

**自訂欄位建議**：
- `Sprint`（select）— Sprint 0 ~ Sprint 15+
- `Role`（select）— A-Parser / B-Renderer / C-QA
- `Fixture Pass Rate`（number）— 0-100，sprint 結束時填寫

---

## 4. Issue 範本（複製到 .github/ISSUE_TEMPLATE/）

### 4.1 Parser 模組 issue

```markdown
---
name: Parser 模組
about: 實作 OOXML Parser 的某個模組
title: '[Parser] '
labels: ['type/parser', 'role/A-parser']
---

## 範圍
- **檔案**：`static/src/core/ooxml/<dir>/<File>.ts`
- **規格依據**：ECMA-376 Part 1 §<章節>
- **AST 輸出**：`<TypeName>` (ast/types.ts)

## 任務清單
- [ ] 實作 `<MethodName>()`
- [ ] 移除 stub `throw new Error()`
- [ ] 加入單元測試 `tests/unit/<File>.test.ts`
- [ ] 跑 fixture：`make fixtures-compare FIXTURE=<dir>`
- [ ] fixture diff 為 0（或文字結構面 100%）

## 白名單對照
參照 [docs/ooxml_whitelist.md](../docs/ooxml_whitelist.md) 確認此 issue 涵蓋下列元素：
- `w:<element1>`（出現 X 次 / Y 檔）
- `w:<element2>`

## 驗收標準
- 對應 fixture 子集（`tests/fixtures/<category>/`）100% 通過
- TS strict mode 無 error
- 與其他模組無循環依賴

## 預估
- **工作量**：X 人天
- **Sprint**：Sprint N
```

### 4.2 Renderer / canvas-editor patch issue

```markdown
---
name: canvas-editor patch
about: 修改 canvas-editor 第三方源碼
title: '[CE-Patch] '
labels: ['type/renderer', 'role/B-renderer', 'ce-fork']
---

## 修改原因
<為什麼 canvas-editor 原生無法滿足？引用 fixture 範例與失敗截圖>

## 修改範圍
- **檔案**：`node_modules/@hufe921/canvas-editor/<path>`
- **API 影響**：是否影響對外 API？是→需要更新 OWL 元件呼叫端

## 工作流
- [ ] 編輯 node_modules 內檔案
- [ ] `npx patch-package @hufe921/canvas-editor`
- [ ] 在 `docs/patches/NNN_<descriptive>.md` 寫說明
- [ ] commit 兩個檔（patch + 說明）

## 上游回饋
- [ ] 已建立 hufe921/canvas-editor#XXX issue
- [ ] 已開 PR #YYY
- [ ] 上游接受後可移除此 patch（記錄條件）

## Fixture 驗證
- [ ] `tests/fixtures/<相關 fixture>` 渲染前後對比 PNG
- [ ] pixelmatch diff < X%

## 預估
- **工作量**：X 人天
- **Sprint**：Sprint N
```

### 4.3 Fixture 回歸 issue

```markdown
---
name: Fixture 失敗
about: 某個 fixture diff 超過閾值
title: '[Fixture-Fail] '
labels: ['type/fixture', 'fixture-fail', 'role/C-qa']
---

## 失敗 fixture
- **路徑**：`tests/fixtures/<category>/<name>.docx`
- **golden**：`tests/fixtures/<category>/golden/<name>-1.png`
- **diff PNG**：附上對比圖

## 量化失敗指標
- pixelmatch 差異率：X%
- 失敗 sprint commit：<hash>
- 上次 pass commit：<hash>

## 假設原因
<推測哪個 Parser/Renderer 模組導致>

## 任務
- [ ] root cause 找出
- [ ] 修正模組
- [ ] 重生 golden（若 golden 本身有誤）
- [ ] CI 加 regression test

## 對應 Issue
- 修正 PR：#XXX
- 預期影響其他 fixture：<列出>
```

---

## 5. 三人團隊工作流

### 開發 cycle（一個 issue 從接到到 close）

```
1. 從 Backlog 拉到 Sprint Planned （chichi 排優先）
   └─ assignee 確定（A-Parser / B-Renderer / C-QA）
2. 開工 → status = In Progress
3. 開 PR → status = Review
   └─ PR 必附：fixture diff PNG（成功 = 0 diff）
4. PR 必須得到第二人 approve
   └─ Parser PR 由 C 或 chichi review
   └─ Renderer PR 由 A 或 chichi review
   └─ Integration PR 由 chichi review
5. CI 跑 fixture 回歸 → 全 pass 才能 merge
6. merge → status = Done
```

### Sprint 末儀式

每個 sprint 結束（每 2 週週五）：
1. 跑完整 fixture 回歸：`make fixtures-compare`
2. 在當前 milestone 寫 retrospective comment：
   - 完成的 issue 數
   - fixture pass rate（與上 sprint 比）
   - 阻擋項目（needs-decision label）
3. 建立下個 sprint 的 issue（chichi 拍板）
4. 三人 sync 30 分鐘 → 調整 Sprint N+1 範圍

### Branch 命名

```
parser/<sprint>-<module>          # 例：parser/sprint1-paragraph
renderer/<sprint>-<feature>       # 例：renderer/sprint7-table-layout
ce-patch/<NNN>-<descriptive>      # 例：ce-patch/001-table-vmerge
fixture/<category>-<descriptive>  # 例：fixture/03-complex-table-fail
docs/<descriptive>                # 例：docs/sprint-5-decision-report
```

---

## 6. CI 建議（GitHub Actions）

`.github/workflows/fixture-regression.yml`（建議草案）：

```yaml
name: Fixture Regression
on: [pull_request]

jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npm run build:frontend
      - run: npx tsc --noEmit
      # fixture 比對需要 LibreOffice + Chromium + Noto CJK
      # 可考慮 cache golden PNG，只測 fixture-fail label 的 issue
      - name: Run fixture regression
        run: node tests/scripts/compare_fixtures.js --threshold 5
```

---

## 7. 第一波要建立的 Sprint 1 Issues（複製貼上）

> 開工 Sprint 1 時，把下列 issue 全部建立到 `Sprint 1 — Parser foundations` milestone

```
Issue 1.1: [Parser] PackageReader — ZIP 解包與 relationship 解析
Issue 1.2: [Parser] PackageReader — Content_Types.xml 解析
Issue 1.3: [Parser] DocumentParser — body 走訪框架
Issue 1.4: [Parser] ParagraphParser — w:pPr 段落屬性
Issue 1.5: [Parser] ParagraphParser — w:r 與 w:rPr Run 屬性
Issue 1.6: [Parser] ParagraphParser — w:t / w:br / w:tab / w:fldSimple
Issue 1.7: [Fixture] tests/fixtures/01_simple/ 7 份段落結構 100% 通過
Issue 1.8: [Devops] CI 加 fixture regression workflow（需先 cache golden PNG）
```

---

## 附錄：與 Plan file 的對應

本文件的 sprint 編號、role 分工、決策關卡，與 `~/.claude/plans/d-work-odoo18-docker-dobtor-doc-editor-pure-duckling.md` Part 2 完全對應。如兩處衝突，以 plan file 為準（plan file 是 chichi 與團隊的合約）。
