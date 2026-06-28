# dobtor_doc_editor — 術語表（Glossary）

> Sprint 73 落地、Sprint 119 擴充到 Sprint 118 era、**Sprint 155 catch-up 到 Sprint 154 era**（+ Sprint 145-153 三新變體 / autonomous 邊界第二次揭示 / Phase 1 90% 整數里程碑 / 紀律 #21.a 潛在子候選等）。規畫書附錄 B 已有 OOXML 對映表、本 glossary 補完 *sprint 紀律 / 衡量指標 / 內部子系統 / 工具鏈 / process 模式* 術語。新貢獻者 / 跨 sprint 回顧時對齊用語。

## 0. 章節索引（Sprint 119 加、Sprint 155 更新；驗證紀律 #20 候選）

| § | 章節 | 主要術語數 |
|---|---|---|
| 1 | VR 與衡量指標 | 13（+ byte-identical 23 連 / Phase 1 90% 整數里程碑） |
| 2 | Sprint 紀律與類型 | 紀律 22 條 + 6 子 + 1 候選 + **1 潛在子（#21.a、Sprint 154 retro）**；10 種 sprint 類型（Sprint 143 升正 #1.a/#1.b/#21/#22；Sprint 145-153 第 8-16 次連續應用）|
| 3 | 前端子系統與術語 | 核心模組 **17**（+ Sprint 145-153 八個 capture-only parser）+ 衡量單位 4 |
| 4 | 後端 / Odoo 整合 | 12 |
| 5 | 工具鏈與 CI | 11 + CI gate 漸進模式 3 階段（vitest baseline 1331 + 1 skipped、Sprint 153）|
| 6 | 角色與權限 | 3 group + cross-company 邏輯 |
| 7 | 縮寫 | 14 |
| 8 | Process 模式（Sprint 113+ 新增、Sprint 155 擴充）| **16**（Sprint 119-154 era +8 條：probe 例行化 / Strategy C / autonomous 邊界 / capture-only 四連 archetype / retro 短週期 / 最薄變體 / discriminated union variant / 紀律 #21 例外判斷）|

## 目錄

1. [VR 與衡量指標](#1-vr-與衡量指標)
2. [Sprint 紀律與類型](#2-sprint-紀律與類型)
3. [前端子系統與術語](#3-前端子系統與術語)
4. [後端 / Odoo 整合](#4-後端--odoo-整合)
5. [工具鏈與 CI](#5-工具鏈與-ci)
6. [角色與權限](#6-角色與權限)
7. [縮寫](#7-縮寫)
8. [Process 模式（Sprint 113+ 新增）](#8-process-模式sprint-113-新增)

---

## 1. VR 與衡量指標

| 術語 | 定義 | 來源 |
|---|---|---|
| **VR** | Visual Regression — 對全 42 fixture 跑 puppeteer 渲染、用 pixelmatch 對比 golden PNG | Sprint 14 |
| **VR mean** | 42 fixture × 126 pages 的 per-page diff 平均；當前 baseline = **0.073191**（Sprint 65 promote `--font-metrics` default-on）；Sprint 145-153 維持 byte-identical 第 23 次連續（跨 8 production sprint、九連 capture-only cluster）| Sprint 50-65 / 145-153 |
| **byte-identical streak** | VR mean 連續 N 個 production sprint 保持 0.073191（無 floating-point diff、無新 ops、無 page count drift）的指標；Sprint 153 結尾 = **第 23 次連續**；斷裂條件 = parser/style/layout/render 任一引入新行為（Sprint 139 numbering layout wire-up = 末次斷裂、Strategy C 折衷後恢復）| Sprint 121-153 |
| **Phase 1 整數里程碑** | Phase 1 OOXML 完成度突破 10% 整數的事件；Sprint 153 latentStyles capture 後 89.5% → **90%**；Sprint 144-153 平均 0.75pp/sprint（後期報酬遞減）| Sprint 153 |
| **failed pages** | VR mean > threshold（0.5）的 page 數；當前 = 0 | Sprint 14 |
| **goldens** | 每份 fixture 的 reference PNG，由 LibreOffice headless 渲染、放在 `tests/fixtures/<category>/golden/<name>-<page>.png` | Sprint 0 |
| **LO anchor** | LibreOffice 渲染 metric 校準基準。Sprint 28 經驗值 1.15em / Sprint 62 用 LO 系統 fallback fonts 對齊 | Sprint 61 揭示 |
| **fingerprint** | render ops 的 SHA-256 hash（含 x/y 座標）— 用來偵測 render 結構變動 | Sprint 12 |
| **page count baseline** | 每份 fixture 的預期頁數；當前 Sprint 16 baseline 全綠 | Sprint 16 |
| **per-fixture delta** | 對單一 fixture 的 VR mean 變動量；promote default 前必查（紀律 #6） | Sprint 63 |
| **baseline drift** | feature flag 切換後對 page count / ops count / fingerprint 的影響量 | Sprint 64 |
| **comparedPages** | 渲染後實際被 pixel diff 的 page 數；當前 = 126 | Sprint 31 era |
| **A- 級 / B+ 級** | 還原度等級（A- = mean ≤ 0.10、B+ = mean ≤ 0.13）；當前在 **A- 級** | 規畫書 §2.1 |

---

## 2. Sprint 紀律與類型

### 2.1 22 條紀律 + 6 子原則 + 1 候選 + 1 潛在子原則（Sprint 50-154 累積；Sprint 90-109 已 revert）

> **Sprint 155 catch-up**：Sprint 143 升正 #1.a / #1.b / #21 / #22 → 紀律 18 → 22 條（[sprint143_148_retro.md](sprint143_148_retro.md) §1）。Sprint 154 retro §4 揭示 1 潛在子原則 #21.a 候選（key 即 binary signal 例外）— 待 3 sprint 跨類型驗證升正。

| # | 紀律 | Sprint 來源 |
|---|---|---|
| 1 | 改 BrowserCanvasRenderContext / CanvasRenderer 後強制跑全 42-fixture VR | 57 |
| 1.a | 廣域版 — parser / style / layout 任一層變動、即使預期 VR 不變也跑全 VR rebuild + 確認（跨 Sprint 121-138 第 14 次連續 byte-identical 驗證）| 123 |
| 1.b | spike 後遇結構性問題、必須 scope-down 或完整 revert byte-identical、不嘗試「微調 + retry」（跨 Sprint 110-153 累計 **16 次正面驗證** × 3 類型完整光譜：全 revert × 2 / 預防 ×4 / 實作 + 折衷 ×2 / capture-only 變體 ×8、含「需 user GO 的 DEFER」次類型 3 次）| 143 |
| 2 | 單元測試用 spy 驗 API、VR 驗 pixels — 兩者都綠才算過 | 57 |
| 3 | 高風險改造前先 probe sprint 收集事實 | 60 |
| 4 | 負面結果 sprint 仍有結構價值；揭示隱性 assumption 是真實學習 | 61 |
| 5 | vitest 通過不保證 IIFE bundle 同 code 也 work | 62 |
| 6 | Promote default 前先做 per-fixture delta 分析 | 63 |
| 7 | Mechanical commit 是多 sprint 紀律性投資的內化 | 65 |
| 8 | 架構發現的 sprint 也要記下來；架構認知與假設不符時優先誠實定位 | 64b |
| 9 | §附錄 A `[ ]` 項是 autonomous sprint 優先選擇 | 67 |
| 10 | catch-up sprint 不該停最低限度補完、應對齊當前紀律標準 | 68 |
| 11 | Controller 觸碰 filesystem 必須 cross-check production 環境實際路徑 | 69 |
| 11.a | 廣域版 — 任何 X-assumes-Y 都需 cross-check（filesystem / dev tool / lib import / env var）| 77 |
| 11.b | ACL 應用 — record rule 也是 access path、需 audit | 78 |
| 12 | test class 必須 explicit tag 對應到 `--test-tags` query | 71 |
| 13 | backend test 必須有「定期跑」機制才算真實 coverage | 72 |
| 14 | docs / audit / ADR / glossary 必須即時同步（不是事後 catch-up）| 75 |
| 14.a | 集中索引（CONTRIBUTING / glossary）新紀律確立即更新、不是事後 catch-up | 111 |
| 14.b | 規畫書 §11 候選達 30+ sprint 規模應外部化為 roadmap doc | 113 |
| 15 | security 變動後必跑 test class（紀律 #1 的 ACL 廣域版）| 80 |
| 15.a | security test 要進 CI gate 才算「跑」；漸進 dispatch v1 → nightly v2 → push v3 | 114 |
| 15.b | security 邊界紀律廣域應用到所有同類 controller / route | 115 |
| 16 | disabled code 必須有 explicit rationale 註解 | 83 |
| ~~17~~ | **已回收**（隨 Sprint 90-109 revert） | ~~108~~ |
| 18 | **開工大型新 feature 前必須先對齊規畫書真實 scope**（最重要、Sprint 110 揭示）| 110 |
| 18.a | 「根據計劃書繼續執行」是 scope 限制詞、不是擴張詞 | 110 |
| 18.b | Strategy A 並存策略雖救命、不是 scope alignment 的替代品 | 110 |
| 18.c | critical finding 揭示 sprint 後、下個 sprint 應 enforce fix（cooldown ≤ 1 sprint）| 116 |
| 18.d | 「待 user 決策」候選的 autonomous 收口必須讀原始設計意圖後才決、不能憑 default-secure 直覺 | 117 |
| 20（候選）| 集中索引文件（ADR / glossary / CONTRIBUTING）超過 10 entry 應有 §0 索引段；歷史缺口保留編號 | 118 |
| 21 | optional 欄位空集合不掛 key（避免 AST diff noise + 保 cache key 穩定）| 131 |
| 22 | backlog 開工前先 probe sprint 確認 mental model vs 實況差距（跨 Sprint 127-153 累計 **17 次正式應用**、含「需 user GO 的預防 DEFER」次類型 / 跨 fixture part 統計 / variant 型別覆蓋 / fixture parts gap 系統掃描等子變體）| 135 |
| 21.a（**潛在子原則候選**、Sprint 154 揭示）| 紀律 #21 例外判斷:key 本身已是 binary signal（存在/不存在）時、value 全空仍掛 key;mental model 主導非機械式應用;**僅 1 sprint 案例**（Sprint 153 latentStyles exception）、待 3+ sprint 跨類型驗證升正 | 154 retro §4 |

### 2.2 Sprint 類型

| 類型 | 定義 | Sprint 50-89 比例 |
|---|---|---|
| **Code change（改善）** | 有 source code 變動、VR 或功能性改善 | 20% |
| **Code change（neutral）** | 有 source code 變動但 VR 持平、用於揭示或架構鋪墊 | 8% |
| **純診斷** | 0 行 production code 變動、收集事實供下個 sprint 決策 | 33% |
| **Mechanical commit** | 1-2 行 default flag / baseline 變動、多 sprint 累積後內化 | 5% |
| **Catch-up** | 補前 sprint 漏掉的工程紀律（test / doc / lint） | 10% |
| **Infra** | 開發工具腳本 / Makefile target / CI config | 5% |
| **Docs（autonomous）** | glossary / retro / ADR / CONTRIBUTING / sprint audit | 15% |
| **Meta** | 候選耗盡聲明、scope 規劃 | 3% |
| **Probe** | 純診斷的高風險變種、用 puppeteer / docker exec 量可行性 | 含於純診斷 |
| **Revert** | 整個 phase 移除（如 Sprint 110 revert Sprint 90-109）| 不計入 |

---

## 3. 前端子系統與術語

### 3.1 核心模組

| 名稱 | 角色 | 路徑 |
|---|---|---|
| **OOXML Parser** | 把 .docx 解析為 canvas-editor IElement[] AST | `static/src/core/parser/` |
| **LayoutEngine** | 段落 / 表格 / 分頁 layout 引擎 | `static/src/core/layout/` |
| **CanvasRenderer** | 把 layout 結果繪到 canvas | `static/src/core/renderer/` |
| **BrowserCanvasRenderContext** | 抽象化 canvas API、支援 spy / OffscreenCanvas | `static/src/core/renderer/` |
| **AstCache (L1)** | in-memory LRU AST cache | Sprint 51 |
| **IdbAstCache (L2)** | IndexedDB 持久化 AST cache | Sprint 52 |
| **ImageBitmapIdbCache** | L1+L2 ImageBitmap 跨 page 持久化 | Sprint 56 |
| **LayoutCache** | layout 結果 L1 cache | Sprint 58 |
| **FontMetricsAdapter** | opentype.js 真實字型 metric（取代 1.15em empirical） | Sprint 62 |
| **FontLoader** | portal/canvas-editor 端 lazy load + IDB cache | Sprint 64b |
| **NumberingCounterState** | 純函式 state machine、OOXML §17.9 多 numId × ilvl 0-8 獨立計數 + 深層 reset + lvlRestart=0 跨章節連續 | Sprint 137 |
| **FootnotesParser** | footnotes.xml + endnotes.xml 同 parser、capture-only（無 wire-up）；fixture footnoteReference 0/42 覆蓋 | Sprint 145 |
| **SettingsParser** | settings.xml capture-only：9 元素（zoom / defaultTabStop twip→pt / characterSpacingControl / 3 toggles / proofState / footnotePr / endnotePr / compat 子元素）；紀律 #21 雙層雙模式 | Sprint 146 |
| **FontTableParser** | fontTable.xml capture-only：7 元素（name / altName / charset hex / family 6 列舉 / pitch 3 列舉 / panose1 10-byte / sig 6 屬性）；與 FontMetricsAdapter 互補關係 | Sprint 147 |
| **WebSettingsParser** | webSettings.xml capture-only：4 toggle + hasDivs；scope-down 不深入 w:divs 巢狀（留 Phase 6 docx export） | Sprint 148 |
| **AppPropsParser** | docProps/app.xml capture-only：17 元素（4 字串 / 8 整數含 DocSecurity enum / 5 布林）；嚴格規格 "true"/"false" / 嚴格整數 / xmldom localName fallback | Sprint 150 |
| **CustomPropsParser** | docProps/custom.xml capture-only：discriminated union variant（string / int / bool / real / filetime / unknown 降級）；scope-down 5 常見 variant + unknown raw | Sprint 151 |
| **LatentStylesParser** | styles.xml `<w:latentStyles>` capture-only：5 root defaults + Map<name, exception>；紀律 #21 例外判斷（exception 全空仍掛 key、key 即 binary signal） | Sprint 153 |
| **PackageContentTypes** | PackageReader internal `parseContentTypes` 暴露給 DocumentNode 的 capture-only「最薄」變體；+0 行新 parser code、復用既有 internal | Sprint 152 |

### 3.2 衡量單位

| 單位 | 意義 |
|---|---|
| **pt** | point（1/72 inch）|
| **px** | pixel（DPI 96 / 150 取決於 fixture）|
| **EMU** | English Metric Unit（914400 / inch、OOXML 用）|
| **twip / dxa** | 1/1440 inch（OOXML 段落單位） |

---

## 4. 後端 / Odoo 整合

| 術語 | 定義 |
|---|---|
| **doc.document** | 主文件 model（`models/doc_document.py`）|
| **doc.linked.mixin** | ChienYi 整合 mixin、讓 supervision model 關聯 doc | Sprint 21-22 |
| **doc_zip_guard** | DOCX 上傳 zip bomb 防護（3 道閘門）| Sprint 20 W1 |
| **doc_telemetry** | 監控與遙測（錯誤紀錄 / 效能指標）| W7-8 P2-4 |
| **/dobtor/fonts/*** | Sprint 64b font 供應 endpoint（Strategy B）|
| **FONT_PATH_MAP** | font family → candidate paths fallback chain | Sprint 64b → 69 |
| **resolve_font_path()** | 依序試 candidate 回第一個 exists 的路徑 | Sprint 69 |
| **OWL Component** | Odoo 18 前端 component 框架（DocEditor 用）|
| **portal user** | 受邀協作者（group_doc_portal）|
| **internal user** | 監造主管 / 工程師（group_doc_editor / group_doc_manager）|
| **null byte sanitize** | upload_template 入口對 filename 內 `\x00` 做 explicit reject（400）+ basename 取 path component | Sprint 116 |
| **cross-company collaboration** | portal user 屬於承包商公司、被監造公司邀為 collaborator → 可讀寫不同 company_id 的文件；rule_doc_document_portal 刻意不加 company filter | Sprint 117 |
| **lock-in test** | 鎖定既有 by-design 行為的 test、防未來「security review」誤改；fail 訊息引導讀對應 audit doc | Sprint 117 |
| **autonomous_roadmap.md** | 規畫書 §11 候選外部化為 sprint 113-175 排程；user 已授權 Claude 自主決策 | Sprint 113 |

---

## 5. 工具鏈與 CI

| 名稱 | 用途 |
|---|---|
| **rollup** | TS → IIFE bundle |
| **vitest** | unit + integration test runner（Sprint 153 結尾 **1331 passed + 1 skipped**；Sprint 110 → 153 期間 +355 test）|
| **pixelmatch** | PNG pixel-level diff |
| **puppeteer** | headless Chromium、跑 VR |
| **HttpCase** | Odoo runtime HTTP test base class |
| **TransactionCase** | Odoo runtime DB test base class（無 HTTP）|
| **`--test-tags=<tag>`** | Odoo test 選取 query；常用 `font_serve` / `zip_guard` |
| **`--http-port=8169`** | 避開 production server 8069 |
| **IIFE bundle** | `tools/dist/visual_regression_pipeline.iife.js` — VR pipeline browser-side |
| **parse_docx_cli.cjs** | TS parser CLI（subprocess 呼叫）| Phase E |
| **`make dev`** | build + upgrade + restart 完整循環 |
| **`run_backend_tests.sh`** | Sprint 72 加的 Odoo backend test 一鍵觸發 |
| **CI gate v1 dispatch** | workflow_dispatch 手動觸發、Sprint 114 落地 font_serve 12 test 進 CI | Sprint 114 |
| **CI gate v2 nightly** | schedule cron 每晚自動跑、v1 跑穩 3 次後升級 | Sprint 114（規劃中）|
| **CI gate v3 push / PR** | push / PR 阻擋式 gate、v2 跑穩 3 次後升級；最終 enforce 形式 | Sprint 114（規劃中）|

---

## 6. 角色與權限

| 群組 | 中文 | 權限 |
|---|---|---|
| `group_doc_editor` | 文件編輯員 | 建立 / 編輯 / 刪自己的文件 |
| `group_doc_manager` | 文件管理員 | 全域 CRUD + telemetry 監控 |
| `group_doc_portal` | Portal 協作者 | 只看 / 編輯被邀請的文件 |

---

## 7. 縮寫

| 縮寫 | 全稱 |
|---|---|
| ADR | Architecture Decision Record |
| AST | Abstract Syntax Tree |
| BFS / DFS | Breadth/Depth-First Search |
| CJK | Chinese-Japanese-Korean |
| CRDT | Conflict-free Replicated Data Type（Yjs 用）|
| IDB | IndexedDB |
| L1 / L2 | Cache 層級（L1 = in-memory、L2 = IDB persistent）|
| LRU | Least Recently Used |
| OCR | Optical Character Recognition |
| OOXML | Office Open XML（.docx 標準）|
| QWeb | Odoo template engine |
| SOP | Standard Operating Procedure |
| TTC | TrueType Collection（多字型打包）|
| VR | Visual Regression |
| WSL | Windows Subsystem for Linux |

---

## 8. Process 模式（Sprint 113+ 新增）

| 名稱 | 定義 | 來源 |
|---|---|---|
| **autonomous 決策** | user 授權的「待 user 決策」候選 Claude 自主執行；需做技術可行性檢查 + 副作用評估 + fallback / revert 路徑 + audit doc 寫 rationale | Sprint 113 / autonomous_roadmap.md §授權範圍 |
| **scope drift enforce** | 每 sprint 開工前 grep 規畫書 + 開工偏離立即停手、走 Sprint 110 模式 byte-identical revert | 紀律 #18 / Sprint 113 roadmap |
| **三層 SOP**（Sprint 23+）| L1 vitest / L2 VR v14 / L3 spot check / L4 Odoo HttpCase；source code 變動全跑、純 docs 誠實聲明跳過 | Sprint 23 / autonomous_roadmap.md §每 sprint 標準流程 |
| **progressive CI gate** | security test 進 CI 走漸進 dispatch v1 → nightly v2 → push v3，每階段穩定 3 次升級 | Sprint 114（紀律 #15.a）|
| **critical-fix cooldown ≤ 1 sprint** | 上 sprint audit 揭示 critical → 下 sprint 必須含 fix（可與 roadmap 主線同 sprint batch）| Sprint 116（紀律 #18.c）|
| **read-design-intent-first** | autonomous 收口「待 user 決策」候選前、grep 該功能 group / model 註解；決策若覆蓋既有設計、audit doc 必須明示 | Sprint 117（紀律 #18.d）|
| **§0 索引段** | 集中索引文件超過 10 entry 應有；歷史缺口（如 ADR-004-007）保留編號標示 | Sprint 118（紀律 #20 候選）|
| **lock-in test** | 鎖既有 by-design 行為的 test；fail 訊息引導讀 audit doc；防未來「security review」型 sprint 誤改 | Sprint 117 |
| **probe-only sprint 例行化** | 純診斷 sprint 從零星轉為例行流程；Sprint 127-153 累計 9+ 次（FontMetricsAdapter / HarfBuzz / docGrid snap / textAlignment / goldens / Phase 5 / fixture parts gap / variant 覆蓋 / fontTable element 結構）；0 production code 變動 + audit doc 含 5 維度評估表 | Sprint 127-153（紀律 #22 case study）|
| **Strategy C 折衷模式** | autonomous 翻車後不全 revert、保留 layout wire-up 但 VR pipeline 改 opt-in（caller 顯式傳才啟用）的部分翻車 scope-down 模式；填補「全做/全不做」二元中間 | Sprint 139（紀律 #1.b 完整光譜第 3 類）|
| **autonomous 邊界 3 維度** | autonomous 自主決策受限的 3 種維度:(1) baseline 改變需 user 同意（Sprint 141 goldens）;(2) 大依賴需 user 提供 fixture（Sprint 142 Phase 5）;(3) user 業務優先順序未知；對應產出「需 user GO 的 DEFER」audit doc | Sprint 141-142 / 154 retro §8 |
| **capture-only 四連 archetype** | 9-step 模式可複製:probe fixture 覆蓋 → 新 parser 模組 → types interface → OoxmlParser Step N 接線 → DocumentNode constructor patch → vitest unit test → bundle rebuild → VR full run → audit doc;Sprint 145-148 連 4 sprint 應用 → 紀律 #1.a / #21 / #22 同步驗證 | Sprint 145-148 |
| **retro 短週期觸發** | cluster 模式成熟即可寫 retro、不必等 ≥10 sprint;6 sprint(Sprint 149)、9 sprint(Sprint 154)兩次短週期 retro 已驗證;觸發條件 = 3+ 新 explicit 模式或紀律升正 + 上次 retro 距離 ≥ 5 sprint | Sprint 149 / 154 |
| **「最薄」capture-only variant** | capture-only sprint 中、無需新 parser code、僅暴露既有 internal 結構至 DocumentNode 的變體;紀律 #14 DRY 應用峰值;適用情境 = 既有 parser 已 internal 處理但未對外暴露 | Sprint 152（紀律 #14 DRY 主導）|
| **discriminated union variant capture** | capture variant 值（OOXML §22.4 vt:* 等）使用 TypeScript discriminated union;`kind` 屬性 narrow + 未知 variant 降級 `unknown` raw;caller 用 switch case 編譯期保證 exhaustive | Sprint 151（紀律 #18 scope-down + TS 型別系統）|
| **紀律 #21 例外判斷** | 紀律 #21 機械式 = optional 空集合不掛 key;例外 = key 本身已是 binary signal（存在/不存在）時、value 全空仍掛 key（user 未 override default 是合法 semantic）;mental model 主導非機械式應用 | Sprint 153 / 154 retro §4（潛在子 #21.a）|
