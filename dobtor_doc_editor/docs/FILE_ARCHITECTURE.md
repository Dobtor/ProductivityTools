# 檔案架構與用途

**回答的問題**：這兩個模組的每一個目錄是幹什麼的，一個檔案該放哪裡，
哪些目錄**不會**跟著部署下去。

數字都是 2026-10-10 從 `git ls-files` 量的（追蹤檔案，不是磁碟）。

## 0. 兩個模組的分工

| | `dobtor_doc_editor`（核心） | `dobtor_doc_import`（匯入） |
|---|---|---|
| 做什麼 | 編輯、範本、報表、版本、權限、入口 | 把 `.docx`／`.odt` 變成 `doc.document` |
| 誰依賴誰 | 不依賴匯入模組 | `depends: ['dobtor_doc_editor']` |
| 追蹤檔案 | 182 支 | 965 支 |
| 主語言 | Python 11,418 行（`models/`）＋ OWL JS 9,236 行 | **TypeScript 33,800 行** |
| 自有 model | 16 個 | **0 個**（只加路由與精靈） |
| 路由 | 36 條 | 5 條 |
| 測試 | 680 則 Odoo 測試 ＋ 1 支 tour | 56 則 Odoo 測試 ＋ 3,087 則 vitest |

拆開的理由（ADR-033）：匯入那條線比核心還大，而**介面很窄**——
跨模組只用到 4 個東西：

```
models/doc_zip_guard        ZIP 炸彈與大小上限守衛
models/doc_ins_syntax       <ins> → Jinja 的轉換（只有核心自己用）
controllers/doc_controller_base   路由基底（_resolve_edit_target 等）
tests/session_probe         ☠️ 這一條讓核心的 tests/ 成為公開介面
```

☠️ 最後那條有部署上的後果，見 [`DEPLOYMENT_FOOTPRINT.md`](DEPLOYMENT_FOOTPRINT.md)。

---

## 1. `dobtor_doc_editor` — 核心編輯器

### `models/`（31 支，11,418 行）— 資料與渲染的權威

扁平的 15 支是 model 本體，兩個子套件是被切出來的渲染引擎：

| 檔案／目錄 | 行數 | 用途 |
|---|---|---|
| `doc_document.py` | 1,501 | `doc.document`——文件本體。內容權威格式是 `content_json`（Canvas JSON），`content_html` 是攤平備份 |
| `doc_template.py` | 683 | `doc.template`——範本。`role` 分 `content`／`layout`（外框只給頁首頁尾與紙張） |
| `doc_report.py` | 600 | `doc.report`——把範本綁到 Odoo 報表動作 |
| `doc_output.py` | 320 | `doc.output`——「某人在某時用某版範本印了某張單據」的稽核紀錄。ACL 刻意是 **RU**（不給 C/D，理由寫在 class docstring） |
| `doc_telemetry.py` | 242 | 三個遙測 model：錯誤記錄、效能指標、匯出記錄 |
| `doc_zip_guard.py` | 199 | ZIP 炸彈守衛 ＋ `assert_input_size()`／`assert_text_size()`（50 MB 上限）。**跨模組介面** |
| `doc_sanitizer.py` | 188 | HTML 清洗 |
| `doc_template_field*.py`／`_signer.py` | 219 | 範本的欄位／選項／簽核人三個子 model |
| `doc_linked_mixin.py` | 344 | `doc.linked.mixin`——讓任何 model 掛上文件（含 `construction.meeting.record` 範例） |
| `doc_render_mixin.py`／`doc_qweb_converter.py` | 104 | 渲染與 QWeb 轉換的 mixin 入口 |
| `doc_ins_syntax.py` | 84 | `<ins>` 藥丸 → Jinja。**跨模組介面** |
| `report_entry_points.py`／`report_overrides.py` | 323 | 把 Odoo 原生報表動作接到這一套 |
| `models/render/`（7 支） | 3,586 | **渲染管線**：`snapshot.py`(1,413) 凍結來源值、`sandbox.py`(608) Jinja 沙箱、`output.py`(574)、`tree.py`(410)、`fields.py`、`i18n.py` |
| `models/qweb/`（7 支） | 3,007 | **QWeb 報表轉換器**：`blocks.py`(862)、`expr.py`(733)、`structure.py`(612)、`locate.py`(479)、`constants.py`、`entry.py` |

### `controllers/`（8 支，2,095 行）— 36 條路由

| 檔案 | 路由 | 用途 |
|---|---|---|
| `doc_controller.py` | 16 | 主控制器：存檔、版本、匯出、藥丸 |
| `doc_controller_template.py` | 10 | 範本欄位、模型清單、編輯目標 |
| `doc_controller_i18n.py` | 5 | 語言清單、抽取、轉換、CSV 匯出匯入 |
| `doc_controller_devtools.py` | 2 | 開發用 harness |
| `portal.py` | 2 | Portal 協作者的唯讀／編輯入口 |
| `report_download.py` | 1 | 報表下載 |
| `doc_controller_base.py` | 0 | 基底 class。**跨模組介面** |

☠️ `auth='public'` 的路由現在是 **0 條**，而且那是完工判準 `no-public-routes`
（AST 判定，不用 grep）。要新增就得改判準。

### 其餘目錄

| 目錄 | 支數 | 用途 |
|---|---|---|
| `views/` | 8 | 四個 model 的 form/list ＋ `menu.xml` ＋ `portal_templates.xml`（QWeb）＋ 報表入口 |
| `wizards/` | 5 | 欄位挑選器、QWeb 範本匯入精靈（各一支 .py ＋ 一支 .xml） |
| `security/` | 3 | `doc_groups.xml` 群組、`doc_security.xml` record rule（☠️ `noupdate="1"`——改 XML 對既有 DB 無效，修正只能靠 migration）、`ir.model.access.csv` |
| `data/` | 2 | 6 張出貨範本 ＋ 5 條 `ir.cron` |
| `migrations/` | 2 | `18.0.10.1.0`（補出貨範本的 `content_json`）、`18.0.15.2.0`（收斂 manager rule 的公司範圍） |
| `i18n/` | 2 | `.pot` ＋ `zh_TW.po`。☠️ 預設語系就是 zh_TW、hardcode 中文是刻意的（見 `a11y_i18n_design.md`），**不要**去包 `_()` |
| `static/src/` | 24 | 見下 |
| `static/tests/` | 1 | `tours/doc_editor_panels_tour.js`——在 manifest 的 `web.assets_tests` bundle（只在測試模式建）。☠️ 部署時排 `tests/` **不可以**把它一起排掉 |
| `docs/` | 24 | 見第 3 節 |
| `spikes/` | 8 | 兩個獨立的技術驗證沙盒（各有自己的 `.gitignore`／`README`／`index.html`），不進 manifest、不出貨 |
| `tests/` | 40 ＋ 10 腳本 ＋ 1 mjs | 見第 4 節 |
| `LICENSES/` | 5 | 內嵌第三方程式碼的授權全文 |

### `static/src/`（24 支，自有 JS 9,236 行）

```
components/doc_editor/      8 支  OWL 編輯器主體（shell / io / pills / templateui / jinja2_scanner）
components/doc_version_panel/ 3 支  版本面板（js + xml + css）
components/doc_field_picker/  2 支  欄位挑選器
components/portal_doc_editor_loader.js   Portal 的掛載器
core/                       5 支  auto_save_manager、lazy_loader、leader_election、
                                  offline_manager、telemetry
views/                      1 支  list 視圖上的「開啟編輯器」按鈕
css/                        1 支
lib/canvas_editor/          3 支  **第三方 fork**：canvas-editor umd ＋ docx plugin ＋ shim
```

---

## 2. `dobtor_doc_import` — 匯入（TypeScript 為主）

### Python 很薄（2,826 行）

| 檔案 | 路由 | 用途 |
|---|---|---|
| `controllers/doc_import_controller.py` | 3 | 匯入主路由（`engine` 參數選解析路徑） |
| `controllers/font_serve.py` | 2 | OOXML 管線的字型服務。☠️ 2026-10-09 從 `auth='public'` 收緊成 `auth='user'`，並移除 `Access-Control-Allow-Origin: *` |
| `controllers/doc_convert.py` | 0 | LibreOffice headless 的呼叫封裝（缺 LO 時退回 python-docx／odfpy） |
| `wizards/doc_bulk_import_wizard.py` | — | 批次匯入精靈 |
| `views/` | — | `menu.xml` ＋ `test_layout.xml` |

**自有 model 0 個**——它只寫 `doc.document`／`doc.template`。

### `static/src/core/`（142 支）— 自寫 OOXML 管線

```
ooxml/              118 支  OOXML 解析器本體
  OoxmlParser.ts            進入點
  ast/ document/ styles/ numbering/ table/ section/ header-footer/
  drawing/ chart/ diagram/ omml/ watermark/ background/ comments/
  footnotes/ font-table/ doc-props/ settings/ web-settings/ package/ units/ utils/
                            ——以上是「讀 OOXML」的各個部位
  mapper/ToCanvasEditor.ts  AST → canvas-editor 的 IElement[]
  font/               16 支  字型量測與 canvas-editor 的快取橋接
  layout/             16 支  文繞圖（wrap polygon）排版
  revision/           13 支  修訂（追蹤修訂）接受／拒絕／合併
  export/              2 支  OoxmlWriter（寫回 .docx）
  worker/             18 支  worker pool 派工（☠️ 依指示留下不接）
layout/              12 支  排版引擎：LineBreaker、Paginator、TableLayout、BoxBuilder、
                            TextMetrics／BrowserTextMetrics／FontMetricsAdapter
render/               6 支  CanvasRenderer ＋ 兩個 RenderContext（Browser／Mock）
cache/                4 支  AST／layout／image bitmap／image decode 四層快取
types/                1 支  opentype.d.ts（上游缺型別宣告，自己補的）
font_loader.ts        1 支
```

`components/doc_editor/`（14 支，2,088 行）是 **Overlay 編輯器**：
選取、拖曳、對齊輔助線、剪貼簿、復原堆疊、Z 序、觸控映射。

### ☠️ 兩條管線很容易搞混

```
出貨路徑：   docx → LibreOffice headless → HTML → canvas-editor
驗收通道：   docx → OoxmlParser → ToCanvasEditor → IElement[] → canvas-editor 自己排版
比對用：     docx → OoxmlParser → layoutDocument → CanvasRenderer → canvas → 比 golden
```

`engine=ts` 路徑**完全不呼叫 `layoutDocument`**。所以需求書 §2.2 的
「pixelmatch < 2%」描述的是**第三條**，不是使用者按匯入會看到的那條
（見 [`REQUIREMENTS_CONFORMANCE.md`](REQUIREMENTS_CONFORMANCE.md)）。

### 出貨 TS 157 支／33,800 行，其中 78 支現在不可達——每一支都已宣告分軸

可達性的分母是 `static/src/**/*.ts` 扣掉 `.d.ts`（＝**154** 支；`.d.ts` 是
ambient 型別，本質上不會被 import，算進「必須可達」是分類錯誤）。
現況 **76 可達／78 不可達（50.6%）**。

ADR-034：不可達不等於該刪。判斷「要不要」之前要先問**它是為哪一軸寫的**
——我就是用「1:1 Word 匯入」這條線判定 Overlay／CanvasEditor 量測／revision
「不需要」並 `git rm` 掉，而那三個是**編輯器軸**的資產，用匯入軸的尺量當然是
0 分。現在每條宣告都要寫 `axis`／`why`／`activation`，由
`tests/unit/bundle_reachability.test.ts` 強制（少一個就紅，不可達比例超過
60% 也紅）：

| 軸 | 目錄 | 支數／行數 | 什麼條件會讓它上線 |
|---|---|---|---|
| `import` | `ooxml/layout/` | 16／2,413 | 文繞圖 layout 接上出貨路徑（**優先序已下調**，見下） |
| `import` | `ooxml/font/Shaping*`、`font/index.ts`、`font_loader.ts` | 4／1,038 | 接 HarfBuzz。**量測後條件不成立**——VR 誤差拆解顯示整體位移只解釋 4.3%，接 ~400KB WASM 不會改善 7.89% |
| `editor` | `components/doc_editor/` | 14／2,088 | Overlay 編輯器接上 UI |
| `editor` | `ooxml/font/CanvasEditor*`、`TextMeasureProxy.ts` | 12／1,787 | 同上（canvas-editor 的量測橋接） |
| `frozen` | `ooxml/revision/` | 13／2,139 | 追蹤修訂功能開案 |
| `tooling` | `ooxml/export/` | 2／2,297 | 匯出回 .docx 開案 |
| `declined` | `ooxml/worker/` | 17／2,382 | **依指示留下不接** |

### `tests/`（757 支）

```
fixtures/   489 支（82.2 MB）  11 個分類目錄（01_simple … 11_perf_synthetic_large），
                              最大的是 10_ooxml_libreoffice/（292 支上游語料）；
                              另有 9 支直接放在 fixtures 下——GOLDEN_SOURCE.md、
                              PROVENANCE.md、phase5_fixture_manifest.json，
                              以及 6 支量測輸出（見第 5 節最後一段）
unit/       165 支（vitest 3,087 則）
integration/ 91 支
scripts/      4 支
```

☠️ 這 82 MB **不是冗餘**：全部被 `readdirSync` 列舉，290 支上游語料庫全被測到。
要省的是正式機的硬碟（排除規則放部署端），不是 repo 的內容。

### 建置產物（三個，兩個進版控）

| 產物 | 進版控？ | 誰在用 |
|---|---|---|
| `static/src/lib/canvas_editor/canvas-editor-custom.umd.js` | **是** | manifest assets（內嵌 fflate） |
| `tools/dist/parse_docx_cli.cjs` | **是** | production 的 `engine=ts`（內嵌 fflate ＋ @xmldom/xmldom） |
| `tools/dist/visual_regression_pipeline.iife.js` | 否 | 只有 VR 量測 |

前兩個由完工判準 `artifacts-present` 與 `artifacts-reproducible` 守住
（重建後必須 byte-identical）。`LICENSES/`（3 支）放的就是那兩個產物內嵌的
第三方授權全文——判定依據是「產物裡實際找到實作符號」，不是 `package.json`。

`scripts/`（13 支 .mjs／.cjs／.html）是**量測**用的：VR 主腳本與 v14、
誤差歸因（`vr_attribution.mjs`）、字型量測探針、效能基線、offscreen canvas 探針。
它們不是閘門，刻意不用退出碼表示「有候選」。

---

## 3. `docs/`（24 支）— 分兩種

**治理文件**（現在要讀的，入口在 [`INDEX.md`](INDEX.md)，有守衛確保它們不從 INDEX 消失）：

| 文件 | 回答 |
|---|---|
| [`DONE_CRITERIA.md`](DONE_CRITERIA.md) | 完成了嗎——13 條可機器判定的判準 |
| [`AUDIT_LENSES.md`](AUDIT_LENSES.md) | 還有什麼沒查——16 把用過的尺 ＋ 5 把沒用過的 |
| [`REQUIREMENTS_CONFORMANCE.md`](REQUIREMENTS_CONFORMANCE.md) | 符合需求嗎 |
| [`OPTIMIZATION_RECOMMENDATIONS.md`](OPTIMIZATION_RECOMMENDATIONS.md) | 下一步做什麼（含**不該做**那張表） |
| [`DEPLOYMENT_FOOTPRINT.md`](DEPLOYMENT_FOOTPRINT.md) | `git pull` 會送多少東西到正式機 |
| 本檔 | 檔案架構與用途 |

**設計與歷史**：`architecture_decision.md`（ADR-028～034）、`glossary.md`、
`scope_decision.md`、`ooxml_whitelist.md`、`word_pagebreak_rules.md`、
`a11y_i18n_design.md`、`optimistic_lock_design.md`、`memory_release_design.md`、
`portal_integration_design.md`、`pdf_engine_evaluation.md`、
`qweb_converter_coverage.md`、`capability_audit.md`、
`canvas_editor_fork_strategy.md`、`chienyi_integration_examples.md`、
`onboarding_sop.md`／`onboarding_prompt.md`（☠️ 檔頭標了過期）、
`github_workflow.md`，以及 `SPRINT_AUDIT_CONSOLIDATED.md`（42,899 行的歷史日誌，
339 個 sprint 區塊；它提到已消失的檔案是它的工作，不是缺陷）。

---

## 4. 核心的 `tests/`（40 支 ＋ 10 支腳本）

測試檔名一律 `test_<被測對象>.py`。另外三支**不是測試**而是共用模組
（所以不在 `tests/__init__.py` 的 import 清單裡，由
`test_python_package_wiring.py` 的兩條判準分開處理）：

- `session_probe.py` — HttpCase 的 session 存活探針。☠️ 它是**跨模組公開介面**
- `test_pill_helpers.py` — 藥丸測試的共用輔助
- （核心 `models/qweb/constants.py` 同一類形狀）

### `tests/scripts/`（10 支）— 可重跑的入口

| 腳本 | 用途 |
|---|---|
| `run_local_rig.sh` | 本機 rig：`test`／`tour`／`all` |
| `run_backend_tests.sh`／`run_tour_tests.sh` | 分別跑後端與瀏覽器 tour |
| `run_done_check.sh` | **13 條完工判準的單一判決** |
| `run_upgrade_check.sh` | 判準 `upgrade-path`：乾淨裝 → 把 DB 推回升級前 → `-u` → 斷言 migration 真的改到資料 |
| `run_ships_without_tests_check.sh` | 判準 `ships-without-tests`：沒有 `tests/` 也裝得起來 |
| `audit_file_inventory.py` | 尺：全檔案清查 |
| `audit_route_coverage.py` | 尺：路由對測試覆蓋 |
| `audit_acl_rules.py` | 尺：ACL／record rule 對照 |
| `scan_absolute_promises.py` | 尺：docstring 的承諾比行為強嗎 |

後四支由 `make audit` 一次跑完。☠️ 它們**刻意不用退出碼**表示「有候選」
——判讀需要人，當成閘門就會開始被加例外清單繞過去。

---

## 5. 一個新檔案該放哪裡

| 它是什麼 | 放哪 |
|---|---|
| 新 model | 核心 `models/`，並在 `models/__init__.py` import |
| 渲染／QWeb 轉換的一部分 | 核心 `models/render/` 或 `models/qweb/` |
| 新路由 | 核心 `controllers/`；**不可以** `auth='public'`（判準會紅） |
| OOXML 解析的新部位 | 匯入 `static/src/core/ooxml/<部位>/` |
| 排版／渲染 | 匯入 `static/src/core/layout/` 或 `render/` |
| OWL component | 核心 `static/src/components/<名>/` |
| 一次性量測腳本 | 匯入 `scripts/`（不是 `tests/`——那裡是測試**輸入**） |
| 可重跑的稽核尺 | 核心 `tests/scripts/` ＋ 掛進 `make audit` |
| 技術驗證沙盒 | 核心 `spikes/`（不進 manifest） |
| 改既有資料的修正 | `migrations/<新版號>/`，並把 manifest 版號往上帶。☠️ `security/` 與 `data/` 是 `noupdate="1"`，只改 XML 對既有 DB 無效 |

☠️ 量測輸出目前有 5 支（190 KB）住在匯入模組的 `tests/fixtures/`
（`perf_baseline_report.json` 等），而那個目錄的語意是測試**輸入**。
它們全是「只寫不讀」。建議搬到 `docs/measurements/`——還沒做，
等使用者決定（見 `OPTIMIZATION_RECOMMENDATIONS.md`）。
