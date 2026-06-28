# Contributing to dobtor_doc_editor

> 本文檔是 dobtor_doc_editor 開發貢獻指南，補完 Phase 0 最後 5% 餘量（規畫書 §0.5 [`dobtor_doc_editor_高保真匯入開發規劃.md`](dobtor_doc_editor_高保真匯入開發規劃.md)）。Sprint 67 落地，2026-05-16。

## 目錄

1. [快速開始](#1-快速開始)
2. [開發環境設置](#2-開發環境設置)
3. [日常開發循環](#3-日常開發循環)
4. [三層 SOP（必須通過）](#4-三層-sop必須通過)
5. [Sprint 紀律（Sprint 50-66 累積 8 條）](#5-sprint-紀律sprint-50-66-累積-8-條)
6. [程式碼風格](#6-程式碼風格)
7. [PR 與分支策略](#7-pr-與分支策略)
8. [Sprint Audit Doc 慣例](#8-sprint-audit-doc-慣例)
9. [Scope 決策（何時用 QWeb vs dobtor_doc_editor）](#9-scope-決策何時用-qweb-vs-dobtor_doc_editor)
10. [Issue / Bug 回報](#10-issue--bug-回報)

---

## 1. 快速開始

```bash
# 1. clone 主 repo 後，進模組目錄
cd addons/dobtor_doc_editor

# 2. 安裝前端依賴（含 patch-package 自動套用）
make install

# 3. build 前端 bundle（產出 tools/dist/visual_regression_pipeline.iife.js 與 canvas-editor-custom.umd.js）
make build

# 4. 升級 Odoo 模組
make upgrade

# 5. 重啟 container（載入 Python controller 變更）
make restart
```

完整循環一行：`make dev`（build + upgrade + restart）。

驗證：`make verify`（typecheck + rollup build 通電檢查）。

---

## 2. 開發環境設置

### 系統需求

| 工具 | 最低版本 | 來源 |
|---|---|---|
| Docker Desktop | 4.x | Windows WSL2 backend |
| Node.js | 20.x（**鎖 v20 LTS**，與 CI 對齊） | nvm 建議 |
| npm | 10.x | 隨 Node 安裝 |
| Python | 3.10+（容器內為 Odoo 18 內建版本） | 容器內 |

### 容器與資料庫

- **container**：`odoo18`（主 Odoo） + `odoo_postgres`（PostgreSQL 15）
- **DB**：`odoo18_dev`（瀏覽器預設、所有測試/升級都用這個）
- **path mapping**：宿主 `D:\work\odoo18-docker\addons` → container `/mnt/extra-addons`

### 升級 SOP（兩步驟缺一不可）

```bash
# 1. 更新 DB schema / views / ACL
docker exec odoo18 odoo -c /etc/odoo/odoo.conf -d odoo18_dev -u dobtor_doc_editor --stop-after-init

# 2. 重啟主進程載入 Python controller 變更
docker restart odoo18
```

或直接 `make upgrade && make restart`。

⚠️ `--stop-after-init` 只更新 DB（templates / assets），**不重啟主進程** — Python 路由與 controller 邏輯需要 `docker restart` 才生效。

---

## 3. 日常開發循環

| 場景 | 指令 |
|---|---|
| 改 TypeScript（pipeline / parser / renderer） | `make build` → `npm test` → `make build` 重打 IIFE |
| 改 Python（model / controller） | `make upgrade restart` |
| 改 XML（views / templates） | `make upgrade`（dev_mode reload XML，F5 即生效但保險仍 upgrade） |
| 改 SCSS / CSS | F5 即生效（dev_mode reload assets） |
| 改 unit test | `npm test`（vitest） |
| 跑 VR baseline | `node scripts/visual_regression_v14.mjs`（42 fixture × 126 pages，~3-5 分鐘） |
| 跑 grid analysis（per-page diff 診斷） | `node scripts/grid_analysis.cjs <fixture>` |

### 完整 Make targets

```
help                  列出所有 target
install               安裝 npm 依賴（含 patch-package 套用）
build                 rollup 打包 OOXML Parser → canvas-editor-custom.umd.js
watch                 rollup --watch（修改 .ts 即時重打包）
upgrade               odoo -u dobtor_doc_editor（更新 DB schema / views / ACL）
restart               重啟 Odoo container（載入 Python controller 變更）
logs                  跟看 Odoo container 日誌
dev                   build + upgrade + restart 完整循環
scan-ooxml            掃 tests/fixtures/ 全部 DOCX 統計 OOXML 元素
fixtures-golden       用 LibreOffice + pdftoppm 為每份 DOCX 產 golden PNG
fixtures-compare      用 puppeteer + pixelmatch 比對 canvas-editor 與 golden
visual-regression     跑視覺回歸 + threshold 判定（PR block 用）
ci-frontend           CI 前端 job：typecheck + vitest + build
ci-python             CI Python job：flake8 + manifest 驗證
ci-xml                CI XML job：全 XML well-formed
ci-all                ci-frontend + ci-python + ci-xml
clean / clean-build / clean-deps   清理
verify                build 鏈通電（type check + rollup build）
```

---

## 4. 三層 SOP（必須通過）

**自 Sprint 23 起所有 sprint 適用 — 缺一視為不過。**

| 層 | 目的 | 指令 | 通過標準 |
|---|---|---|---|
| **L1 Vitest** | unit + integration 測試覆蓋 root cause | `npm test` | 全綠（當前 976 passed + 1 skipped） |
| **L2 Visual Regression v14** | 42 fixture × 126 pages × pixelmatch | `node scripts/visual_regression_v14.mjs` | mean ≤ baseline（當前 0.073191）、0 failed pages |
| **L3 Visual spot check** | 比對 render PNG vs golden 確認結構性差異消除 | 人工開 `tests/fixtures/*.golden.png` 與 render 並列 | 主 diff anchor 消除 |

每個 sprint 的 audit doc（`docs/sprintN_*.md`）必須記錄三層 SOP 的具體數據。

---

## 5. Sprint 紀律（Sprint 50-154 累積 22 條 + 6 子 + 1 候選 + 1 潛在子原則）

這 8 條紀律是從 Sprint 50-66 連 17 個 sprint 累積的、實戰證實會踩坑的工程紀律。**新 sprint 開工前先讀完**。

### 紀律 1（Sprint 57）：改 BrowserCanvasRenderContext / CanvasRenderer 後強制跑全 42-fixture VR

Sprint 57 把 CanvasRenderer 改 aggressive fast path（拿掉 save/restore + setState dedup），unit test 13 條全綠，但 VR 直接 0.0749 → 0.0998（+24% 退化）。**原因：spy canvas 不反映 OOXML pixels**。

→ 任何改動到 `BrowserCanvasRenderContext` / `CanvasRenderer` / `LineBreaker` / 任何 render path 的 PR，**必須**附 42-fixture VR 跑完結果（mean + failed pages）。

### 紀律 2（Sprint 57）：單元測試用 spy 驗 API、VR 驗 pixels — 兩者都綠才算過

Sprint 57 後不再相信「unit test 全綠 = sprint 過」。

→ unit test 驗「API 被呼叫的次序與參數」、VR 驗「pixels 對齊 golden」。**兩者都綠**才能 commit。

### 紀律 3（Sprint 60）：高風險改造前先 probe sprint 收集事實

Sprint 60 OffscreenCanvas Worker 是純診斷 probe（4/4 features 全綠），讓 Sprint 61-62 的決策建立在事實上，避免直接寫 worker render 然後翻車。

→ 任何「需要重寫 1000+ 行 / 改變 render 模型 / 引入新 dependency」的 sprint，**必須**先做 1 個純診斷 sprint 量化可行性。

### 紀律 4（Sprint 61）：負面結果 sprint 仍有結構價值；揭示隱性 assumption 是真實學習

Sprint 61 BrowserTextMetrics 預期改善 VR，實測 0.074899 → 0.076219（+0.001320 退化）。但這個 negative result 揭示了「**Sprint 50-60 一直在校準 LO anchor 卻沒人意識到**」— 後續 Sprint 62 直接用 LO 系統 fallback fonts 一擊命中 -1.7%。

→ Sprint 翻車不是 sprint 失敗，是 sprint 完成了揭示工作。Audit doc 必須誠實記錄 hypothesis 與 result，**不要倒推合理化**。

### 紀律 5（Sprint 62）：vitest 通過不保證 IIFE bundle 同 code 也 work

Sprint 14 nodeModuleStub 導致 `registerFont silent fail` — **47 sprints 沒人發現**，因為 vitest 走 ESM 直接 import opentype.js、IIFE bundle 走 stub。Sprint 62 才透過 diagnostic probe 揭示。

→ 任何「在 vitest 通過、但 production IIFE 路徑可能不同」的場景（library import / dynamic import / global registry），**必須**寫 IIFE-only smoke test 驗證 bundle 行為與 ESM 行為一致。

### 紀律 6（Sprint 63）：Promote default 前先做 per-fixture delta 分析

Sprint 62 命中 -0.001708 全域 VR mean，但只是「平均」改善。Sprint 63 純診斷做 per-fixture delta：5 大贏全 03 全套管、2 中贏 04 磺港溪、35 neutral、0 regression > 0.001。確認 **0 fixture 退化** 才在 Sprint 65 promote default。

→ 任何 promote 操作（feature flag opt-in → default-on / threshold 調整 / 新規則開全）前，**必須**寫 per-fixture / per-category delta 分析、量化 worst-case regression。

### 紀律 7（Sprint 65）：Mechanical commit 是多 sprint 紀律性投資的內化

Sprint 65 只改一行 default 值（`fontMetrics: false → true` + 加 `--no-font-metrics` 回退 flag），但這個 commit 站得住腳是因為 Sprint 60-64 連 5 個 sprint 累積：

- Sprint 60 probe（技術可行）
- Sprint 61 negative result（揭示 LO anchor）
- Sprint 62 IIFE bundle 修復 + 命中 VR -0.0017
- Sprint 63 per-fixture delta（量化零 regression）
- Sprint 64 baseline drift probe（量化 page/ops 零變動）

→ 不要追求每個 sprint 都「有 code 變動」。**Mechanical commit / 純診斷 / catch-up sprint 都是健康紀律分布**。

### 紀律 8（Sprint 64b）：架構發現的 sprint 也要記下來

Sprint 60-65 audit 連 6 個 sprint 假設「production 走自家 pipeline」、Sprint 64b 開工前 grep `doc_editor.js` 才發現 production 走 `window["canvas-editor"].Editor`、不是自家 pipeline。**架構認知與假設不符時、優先誠實定位 sprint scope、而非硬做**。

→ 開工前 60 秒的 `grep production entry` 比 sprint 中途撞牆便宜。任何「假設 X 走 Y 路徑」的 sprint，**必須**先 grep 驗證。

### 紀律 9（Sprint 67）：§附錄 A `[ ]` 項是 autonomous sprint 優先選擇

當下個 sprint 走向不明（user 未指定 / autonomous loop 觸發），規畫書 §附錄 A 的 `[ ]` 項是優先選擇 — 比硬做需 user 認可的 candidate 穩。Sprint 67 走「§附錄 A 唯一未打勾項」做 CONTRIBUTING.md、Phase 0 從 95% → 100%。

→ 應用：autonomous 開工前先 grep `\[ \]` in 規畫書。

### 紀律 10（Sprint 68）：catch-up sprint 不該停在最低限度補完

Catch-up sprint（補前 sprint 漏掉的紀律）容易停在「最低限度」、然後標 done。但 catch-up 的本意是「補完前 sprint 漏掉的工程紀律」、應該補到**與當前紀律標準對齊**。

→ Sprint 66 是 catch-up but 停在「Sprint 64b 之前的最低標準」、Sprint 68 是 catch-up to catch-up（補 Sprint 66 漏掉的 security tests）、Sprint 69 才真正補到當前紀律標準（runtime 驗證）。

### 紀律 11（Sprint 69）：Controller 觸碰 filesystem 必須 cross-check production 環境

Sprint 64b/66/68 寫的 `/dobtor/fonts/*` controller 假設 `/usr/share/fonts/truetype/droid/` 存在、但 odoo18 container 是 minimal Ubuntu base、無 droid 套件、endpoint 永遠 404 = dead code。Sprint 69 HttpCase runtime 跑才揭示。

→ 寫死 filesystem 路徑前先 `docker exec ls`、不是 dev 環境 `ls`。

#### 紀律 11.a（Sprint 77，廣域版）

任何 X-assumes-Y 都需 cross-check。Filesystem 只是其中一個 sub-domain。Dev tools 自身（Makefile 假設 dev host 有 make）、library imports、env vars 全都適用。

#### 紀律 11.b（Sprint 78，ACL 應用）

ACL / record rule 也是「access path」、同樣需 audit。每個 W/C-only model 必須驗 (1) `create_uid = user.id` 防偽造、(2) 有 rate limit 防膨脹。

### 紀律 12（Sprint 71）：test class 必須 explicit tag

`@tagged('post_install', '-at_install', 'dobtor_doc_editor')` 沒含 `font_serve` / `zip_guard` tag → `--test-tags=zip_guard` 抓不到、等同 silent skip。**沒 tag 的 test 不會被選跑、與沒寫 test 結果相同**。

### 紀律 13（候選，Sprint 72）：backend test 必須有定期跑機制

Test 寫好 + tag 對 + script 一鍵跑都不夠。**沒人定期跑 = 半 dead test**（regress 不被即時抓到）。Sprint 72 的 `run_backend_tests.sh` 是 enabler、不是 closure；CI gate 才是 closure。

### 紀律 14（候選，Sprint 75）：docs / audit / ADR / glossary 必須即時同步

Sprint 50-72 衍生 8 個架構決策、ADR 卻在 Sprint 75 才補完（catch-up）。**回頭補 ADR 不夠經濟**（每個 ADR 都要重讀 audit doc）。Sprint 75 揭示：應該在 audit doc 寫完當下就決定要不要升級為 ADR、不是事後 catch-up。

### 紀律 15（候選，Sprint 80）：security 變動後必跑 test class

紀律 #1 對「改 renderer 強制跑全 VR」的 ACL 廣域版。任何 security-affecting 變動（ACL / ir.rule / `auth='...'`）必須跑相關 test class。Sprint 80 是這條紀律的第一個 explicit 應用。

### 紀律 16（候選，Sprint 83）：disabled code 必須有 explicit rationale

`__manifest__.py` 註解掉的 plugin imports（HTML/Wysiwyg 時代遺物）必須有 explicit 註解說「為何 disabled、何時可移除」。否則 disabled code = repo bloat。

### 紀律 17（**已 revert**，原 Sprint 108）：大型新 UI feature 應分小 sprint

Phase 90 esign UI 嘗試的「lesson learned」、但因整個 Phase 已 revert、紀律 #17 也回收。**Sprint 110 揭示更上位的紀律 #18 取代之**。

### 紀律 18（Sprint 110）：開工大型新 feature 前必須先對齊規畫書真實 scope

> 看到 user 參考 UI 圖 / 第三方範例不等於規畫書方向；user 說「根據計劃書繼續執行」= **規畫書 scope 內推進**、不是「順便加新功能」。

Sprint 90-109 因看到 user 圖一 esign 參考、誤判要做 UI 改造、執行 20 sprint batch、全部 revert。即使技術上有並存策略救命（Strategy A）、20 sprint 仍是浪費。

→ 開工前 checklist：
1. 規畫書當前 phase 是什麼？
2. 這個 sprint 屬於哪個 phase？
3. 如果都不屬於 → STOP，先 user 認可或修改規畫書

#### 子原則 18.a：「根據計劃書繼續執行」是 scope 限制詞、不是擴張詞

#### 子原則 18.b：Strategy A 並存策略雖救命、不是大型新 feature scope alignment 的替代品

### 紀律 #1.a（Sprint 123 升正）：parser / style / layout 任一層變動、即使預期 VR 不變，也應 rebuild bundle + 跑全 VR 確認

> Sprint 121-122-123 跨 3 sprint 連續驗證：trHeight 入口防禦 / OLE+VML 降級 / field code 完整覆蓋 三次純 parser 改動都跑全 42 fixture VR、皆 0.073191 byte-identical。紀律 #1（VR）的範圍從「render 層變動」廣域應用到「parser / style / layout 任一層」。

→ 適用情境：類型擴展、入口防禦、style resolver、numbering、layout helper 等任何「概念上不該影響 render」的改動仍要驗 VR。

→ Sprint 138 驗證例外子原則：mapper（ToCanvasEditor）變動由於 VR pipeline 不走 mapper、屬於「VR 預期 byte-identical 的可預測類型」、但仍跑全 VR 確認 mental model 正確。

### 紀律 #21（Sprint 131 升正）：optional 欄位空集合不掛 key

> Sprint 125-126-131 跨 3 sprint 驗證：ParagraphNode.bookmarks / HyperlinkInfo boolean 欄位 / tblStylePr 條件 props 都依此原則處理。空集合 / undefined 不寫進 AST、避免 diff noise + 保 cache key 穩定。

→ 應用範例：
- `if (bookmarks.length > 0) props.bookmarks = bookmarks;`（不掛空陣列）
- `if (history !== undefined) ...`（用 `!== undefined` 不用 truthy、否則漏 `false`）
- counters / numFmts 收斂到當前 ilvl 長度、不掛深層 undefined

### 紀律 #22（Sprint 135 升正）：backlog 開工前先 probe sprint 確認 mental model vs 實況差距

> Sprint 127-128-135 跨 3 sprint 驗證：FontMetricsAdapter promotion probe / HarfBuzz spike probe / docGrid snap 判別子 probe 都先用 probe-only sprint 確認假設、避免「悶頭實作後才發現方向不對」。Sprint 138-142 接力應用（mapper wire-up probe / layout wire-up probe / abc 三連 probe）。

→ probe sprint 標準產出：
1. fixture 覆蓋率 + 分布
2. caller / consumer 對應評估
3. 預期收益 + 風險 + 工時估算
4. autonomous GO / DEFER / user GO 決策 + rationale

→ 第 9 次正式應用（Sprint 142）揭示新類型：「需 user GO 的預防 DEFER」、強調 autonomous 範圍邊界（換 baseline / 大依賴 / user 業務優先）。

### 紀律 #1.b（Sprint 143 升正）：spike 後遇結構性問題、必須 scope-down 或完整 revert byte-identical、不嘗試「微調 + retry」

> Sprint 110 / 136 / 137 / 138 / 139 / 140 / 141 / 142 跨 8 sprint × 3 類型驗證：
>
> - **全 revert**（Sprint 110、136）：spike 翻車 → byte-identical revert
> - **預防 scope-down**（Sprint 137、140、141、142）：probe 確認後主動 scope-down 或 DEFER
> - **實作 / 折衷**（Sprint 138、139）：probe 確認可行 → 實作；含 Strategy C 折衷（Sprint 139）保留主要工作 + scope-down 一個維度

→ 操作原則：
1. **不堆 hack**：避免 fitting noise 風險（如 Sprint 136 教訓「snap 比例縮 30%」「skip first paragraph」都屬此類）
2. **scope-down 維度可大可小**：
   - 全 revert（scope-down 100%）= Sprint 110 / 136 模式
   - 部分 revert（scope-down 1 維度）= Sprint 139 Strategy C 模式（保 layout wire-up、VR opt-in）
   - 預防 DEFER（scope-down 100% 在 probe 階段）= Sprint 137 / 140 / 141 / 142 模式
3. **若 scope-down 跨 autonomous 決策邊界**（換 baseline / 大依賴 / user 業務優先）→ probe-only sprint + DEFER user GO + 完整推薦路徑 ready

→ 8 次跨 sprint 驗證 + 3 類型完整光譜 + 「需 user GO 的 DEFER」次類型 3 次驗證、Sprint 143 正式升格為紀律 #1.b。

### 紀律 #21.a（**潛在子原則候選**、Sprint 154 揭示）：紀律 #21 例外判斷 — key 即 binary signal

紀律 #21 機械式應用 = optional 欄位空集合不掛 key（避 noise）。**例外**：當 key 本身已是 binary signal（存在 / 不存在）時、value 全空仍掛 key、因為 key 名本身已是資訊（如 latentStyles.exception 全空屬性 = user 未 override default、是合法 semantic）。

> 僅 1 sprint 案例（Sprint 153 LatentStylesParser 例外判斷）、需 3+ sprint 跨類型驗證才可升正、暫列**潛在子原則候選**。對照 Sprint 151 CustomPropsParser 「property 全空跳過」（property name 是 user-defined、空 value 是 noise）。

→ 紀律應用需 mental model 判斷、不是純機械式。詳見 [docs/sprint145_153_retro.md §4](docs/sprint145_153_retro.md)。

### 5.x Scope 紀律總結（含 #18 教訓案例 + ADR 流程合規範例）

紀律 #18 是規畫書最重要的紀律、源自 Sprint 90-109 教訓案例。

**Sprint 90-109 案例（誤判 → 全 revert）**：

User 提供 `test-risen.dobtor.com` esign UI 截圖、Claude 誤判為「規畫書方向擴張為 esign-style UI 改造」、執行 20 sprint 連續 batch（doc.template.signer / doc.template.field / overlay placement layer / sidebar inspector 等）後發現:
- 與規畫書 Phase 0-7「docx 1:1 高保真匯入」根本矛盾
- 未經 user 認可即啟動大型 scope 擴張
- 紀律 #1 / #3 / #5 並未阻止此偏離（紀律無 scope-alignment check）

最終結局:Strategy A 並存策略救命 + 全 20 sprint revert byte-identical;規畫書與 production code 都未受永久污染。Sprint 110 揭示紀律 #18:**「開工大型新 feature 前必須先對齊規畫書真實 scope」**。

詳見 [docs/sprint90_to_109_revert.md](docs/sprint90_to_109_revert.md)。

**ADR-022 案例（流程合規 scope 擴張）**：

2026-05-19 user 再次提供 esign UI 截圖、要求改造 dobtor 後台 `ir.actions.client` 視覺 + 拖曳欄位範本。**差異**:user 明確認知 Sprint 90-109 revert 教訓、明確認知衝突、仍決定推進 → 屬紀律 #18 「user 認可或修改規畫書」**合法路徑**。

走 Strategy B（直接改 DocEditor、非並存）+ 增量交付 + 條件啟動。詳見 [docs/architecture_decision.md ADR-022](docs/architecture_decision.md#adr-022) + [docs/sprint90_to_109_revert.md「2026-05-19 後續」段](docs/sprint90_to_109_revert.md)。

**紀律 #18 應用原則**:
- 紀律 #18 **不禁止** scope 擴張
- 紀律 #18 **禁止**「未 user 認可的擴張」
- scope 擴張須走 ADR 流程或修改規畫書 + user 明確認可
- 看到 user 提供參考 UI / 第三方 demo **不等於規畫書方向**
- user 說「根據計劃書繼續執行」= 規畫書 scope 內推進、**不是順便加新功能**

### 5.y 進度進展紀錄（搬出 CONTRIBUTING、見 docs/）

完整紀律應用次數、Sprint 145-153 capture-only 九連對紀律的驗證、cluster retro 紀錄等 *進度* 性質內容、見:
- [docs/progress_snapshot.md](docs/progress_snapshot.md) — 當前指標 + Phase 完成度
- [docs/INDEX.md](docs/INDEX.md) — 132 個 sprint audit doc 索引
- [docs/scope_audit_2026-05-19.md](docs/scope_audit_2026-05-19.md) — sprint 工作層 scope drift audit

本 CONTRIBUTING **只保留紀律定義本身**、不再追蹤紀律應用次數 / 升正 sprint 等流動性指標。

### 健康紀律分布（Sprint 50-89 累積，Sprint 90-109 已 revert 不計入）

| 類型 | 個數 | 比例 |
|---|---|---|
| Code change（改善）| 8 | 20% |
| Code change（neutral，揭示用）| 3 | 8% |
| 純診斷 | 13 | 33% |
| Mechanical commit | 2 | 5% |
| Catch-up sprint | 4 | 10% |
| Infra | 2 | 5% |
| Docs（autonomous）| 6 | 15% |
| Meta | 1 | 3% |

純診斷 + neutral + mechanical + catch-up + docs + meta + infra ≈ **80%**。看起來「無 visual mean 變動」但是讓「有 visual mean 變動」的 sprint 真正 land。

---

## 6. 程式碼風格

### TypeScript（前端）

- **檔頭註解**：用繁體中文寫意圖、限制、與相關 sprint。例：
  ```typescript
  /**
   * FontMetricsAdapter — 用 opentype.js 量真實字型 metric 餵 LineBreaker。
   * Sprint 62 落地（修復 Sprint 14 nodeModuleStub 47-sprint blocker）。
   * IIFE bundle 必須走 ESM `import * as opentypeNs from "opentype.js"`。
   */
  ```
- **命名**：`PascalCase` class、`camelCase` function/variable、`UPPER_SNAKE` const、`I` prefix 介面（沿用 canvas-editor 慣例）。
- **不要寫 magic number**：抽 `const FONT_LOAD_TIMEOUT_MS = 5000`。
- **import 順序**：node 內建 → 第三方 → 內部模組（rollup 不強制但 review 會看）。

### Python（後端 controller / model）

- **PEP 8**，最大行長 120（與 lint 對齊）。
- **欄位 string 繁體中文**、**name snake_case 英文**：
  ```python
  font_family = fields.Char(string='字型名稱', index=True)
  ```
- **controller 註解必寫 route 用途**：
  ```python
  @http.route('/dobtor/fonts/<string:family>', auth='public', methods=['GET'])
  def serve_font(self, family):
      """提供 LO 系統 fallback font bytes（1 年 immutable cache）— Sprint 64b 落地。"""
  ```

### Odoo XML（views / templates）

- **Odoo 18 chatter 用 `<chatter>` 標籤**（不是 `<div class="oe_chatter">`，會跑版）。
- **list view 用 `<list>` 不是 `<tree>`**（Odoo 18 已更名）。
- 詳細規範見 [/mnt/d/work/odoo18-docker/CLAUDE.md](../../CLAUDE.md) 的 Portal 模板章節。

---

## 7. PR 與分支策略

### 分支命名

- `sprint-<N>-<short-description>`：例 `sprint-67-contributing-md`
- `fix-<short-description>`：bugfix
- `docs-<short-description>`：純文件
- `chore-<short-description>`：build / CI / 依賴

### PR 標題與描述

- **標題**：`Sprint N: 一句話描述` 或 `fix: 一句話描述`
- **描述**必須包含：
  - 三層 SOP 結果（vitest 數 + VR mean + failed pages）
  - 對應 audit doc 連結（`docs/sprintN_*.md`）
  - 是否影響 IIFE bundle 大小（如有，註明 KB delta）
  - 是否需要 user 手動操作（migrations / config）

### Commit 訊息

- 第一行 ≤ 70 字、簡潔描述「為什麼」而不是「做了什麼」
- 使用 imperative：`Add font metrics adapter`、`Fix nodeModuleStub blocker`
- 多檔案 commit 內文列出 sprint 紀律對應（如 #3 probe / #4 negative result）

### CI gates

PR 必須通過：
- `make ci-frontend`：typecheck + vitest + build
- `make ci-python`：flake8 + manifest 驗證
- `make ci-xml`：所有 XML well-formed
- VR baseline drift ≤ 容差（手動跑、附結果於 PR）

---

## 8. Sprint Audit Doc 慣例

每個 sprint 必須在 `docs/sprintN_<short-name>.md` 留下 audit doc，至少包含：

```markdown
# Sprint N: <Title>

## 0. 一句話定位
（sprint 性質：code change / 純診斷 / mechanical / catch-up，預期 vs 結果）

## 1. Hypothesis
（開工前的假設，包含「我們相信 X 會 Y」）

## 2. Method
（具體做了什麼、量了什麼，含指令）

## 3. Result
（實測數據，三層 SOP 全列：vitest / VR / spot check）

## 4. Root cause / Mechanism
（為什麼成立 / 為什麼翻車）

## 5. 紀律與啟示
（這個 sprint 補完 / 強化哪一條紀律？或揭示新紀律？）

## 6. 後續 sprint 候選
（建議 Sprint N+1 做什麼）
```

不要省略 **Hypothesis** — 哪怕後來 hypothesis 被證偽，audit doc 必須誠實記錄（紀律 #4）。

---

## 9. Scope 決策（何時用 QWeb vs dobtor_doc_editor）

完整決策樹見 [`docs/scope_decision.md`](docs/scope_decision.md) 與 [/mnt/d/work/odoo18-docker/CLAUDE.md](../../CLAUDE.md) 「文件產製選擇決策」段。簡表：

| 文件特性 | 用 QWeb PDF | 用 dobtor_doc_editor |
|---|---|---|
| 系統自動產出、無人工編輯 | ✅ | ❌ |
| 範本欄位固定、需簽核（通報單 / 估驗單 / 施工日誌 / 自主檢查表） | ✅（保留現狀） | ⚠️ 短期不取代 |
| 需多人協作、版面複雜、現場需編輯（監造會議記錄 / 施工計畫書） | ❌ | ✅ |
| 需法定固定格式（政府公文 / 報部資料） | ✅ | ❌ |
| 需即時填表 + 版本歷史 | ❌ | ✅ |

### 引用規則

- **不要把既有 QWeb 報表搬到 dobtor**：QWeb 已穩定且支援批量列印，搬遷成本高、收益低。
- **新文件需求預設用 QWeb**，除非該文件**明確需要多人協作或現場編輯**。
- **ChienYi 整合走 mixin**：未來模型若要關聯 dobtor 文件，inherit `doc.linked.mixin`（規劃中），不要在模型直接寫 `doc_id` Many2one。

---

## 10. Issue / Bug 回報

提 issue 時請包含：

1. **重現步驟**：環境 / 檔案 / 操作 / 期望 vs 實際結果
2. **VR mean 變化**：如果是回歸問題，附 `node scripts/visual_regression_v14.mjs` 輸出
3. **檔案範例**：能附上能重現的 fixture（脫敏後）放 `tests/fixtures/` 或 issue 附件
4. **影響等級**：low / medium / high / critical（critical = 阻斷使用者操作或資料遺失）
5. **hypothesis vs 確認**：標明是 hypothesis 還是已確認的 bug（紀律 #4）

回報用詞請遵循 [全域指示 - 防禦省電模式](/home/chichi/.claude/CLAUDE.md)：
- **不要 magic number**：所有數值要有命名常數或量測來源
- **不要 hallucinate 環境 / 工具 / 版本**：不知道標 "unknown"
- **區分事實與猜測**：hypothesis vs confirmed bug

---

## 參考

- [規畫書 dobtor_doc_editor_高保真匯入開發規劃.md](dobtor_doc_editor_高保真匯入開發規劃.md)（Sprint 全索引）
- [docs/scope_decision.md](docs/scope_decision.md)（QWeb vs dobtor 決策樹）
- [docs/onboarding_sop.md](docs/onboarding_sop.md)（客戶導入 SOP，角色別流程）
- [NOTICE.md](NOTICE.md)（第三方授權）
- [/mnt/d/work/odoo18-docker/CLAUDE.md](../../CLAUDE.md)（ChienYi 主專案 Odoo 規範）
