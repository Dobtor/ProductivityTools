# dobtor_doc_import

把 `.docx` / `.odt` 匯入成 `doc.document`。從 `dobtor_doc_editor` 拆出來
（2026-10-09，見核心的 `docs/architecture_decision.md` **ADR-033**）。

## 這個模組有什麼

| | |
|---|---|
| 路由 | 5 條（`/dobtor_doc/import`、`/dobtor/fonts/*` ×2、視覺回歸 harness ×2） |
| Python | 轉換函式 9 支、批次匯入精靈、字型服務 |
| TypeScript | 160 檔 / 33,076 行——自寫的 OOXML parser / layout / render 管線 |
| vitest | 222 檔 / **3,059 則**（`npm test`） |
| fixtures | 82MB（352 份 docx + 126 張 golden PNG） |
| 量測 harness | `scripts/` 13 支（視覺回歸、perf、字型探查） |

**整條 TS 工具鏈在這個模組**（rollup / tsconfig / vitest / package.json）。
核心 `dobtor_doc_editor` 拆分後**完全沒有 TypeScript**。

## 兩條解析路徑

| | 誰在用 | 前提 |
|---|---|---|
| **LibreOffice headless → HTML** | 預設，使用者按「匯入」走這條 | 容器裡有 `soffice`；缺了退回 python-docx / odfpy |
| **自寫 OOXML 管線** | `engine=ts`（後端 node CLI）與 `importViaBrowserParser()`（瀏覽器）——**都是驗收通道，沒有 UI 入口** | 見下 |

自寫管線**不是預設**。要升為預設需要先有 A/B 保真度數據（ADR-032）。

## 三個 build 產物，其中一個必須進版控

```bash
npm install          # 一次
make build-all       # 三個產物
```

☠️ `npm install` 原本有個 `postinstall: patch-package` 的 hook，但 `patches/`
從頭到尾是空的（5 個月 0 個 patch），所以那是個 no-op。2026-10-09 連同
`patches/` 一起移除。要 patch 上游 canvas-editor 的話重新加回來即可。

| 產物 | 進 git？ | 為什麼 |
|---|---|---|
| `tools/dist/parse_docx_cli.cjs` | **是** | production 的 `engine=ts` 在用，而部署端容器**只有 node、沒有 npm**，不可能現場 build。`.gitignore` 有 `!` 例外 |
| `static/src/lib/canvas_editor/canvas-editor-custom.umd.js` | 是 | 掛在 manifest assets，瀏覽器要載 |
| `tools/dist/visual_regression_pipeline.iife.js` | **否** | 只有開發端的量測腳本在用，那台機器有 npm |

☠️ 這兩件事在 2026-10-09 之前**都沒接上**（CLI 沒進 git、bundle 沒掛 manifest），
所以兩條通道從頭到尾沒真的運作過，而且因為優雅降級，**不會報錯**。
現在各有守門員：`tests/test_import_routes.py` 與 `tests/test_bundle_loaded.py`，
兩者都驗過「移掉就會紅」。

## 跑測試

```bash
npm test             # vitest 3,059 則（TS 管線的主要驗證）
make test-odoo       # 本模組的 Odoo 測試 24 則
make ci-all          # 靜態檢查
```

視覺回歸要先 `make build-all`，然後：

```bash
node scripts/visual_regression_v14.mjs --no-font-metrics
```

☠️ 預設寫到 `tests/fixtures/.visual_regression_tmp/`（已 ignore）。要更新 git 裡的
**基準**紀錄才用 `--report-out tests/fixtures/visual_regression_v14_report.json`
——那份是 2026-05-25 的量測（per-page mean 0.073191），跑一次量測不該蓋掉它。

`--font-metrics`（真正的 0.073191 那條）需要兩個 Debian 字型包
（`fonts-liberation`、`fonts-droid-fallback`），host 與容器目前都沒有。

## 與核心的介面只有四個

```
dobtor_doc_editor.models.doc_zip_guard          zip bomb 防護（核心也在用）
dobtor_doc_editor.models.doc_ins_syntax         只有核心在用（這裡沒引用）
dobtor_doc_editor.controllers.doc_controller_base   拿 json_http_route
dobtor_doc_editor.tests.session_probe           HttpCase 的 session 健康檢查
```

改核心那四個要想到這個模組。

## 這裡有一塊不屬於匯入

`static/src/components/doc_editor/` 的 14 支 `.ts` 是 Phase 8 Phase 2.2 的前置碼
（未啟動），放這裡只因為 TS 工具鏈在這裡。見該目錄的 `README.md`。

## 2026-10-09 的設計檢討與清理

### 修掉兩個安全缺口（都實測過、都有會變紅的測試）

**① 批次匯入可以寫進使用者沒有的公司**

`target_company_id` 沒有任何約束，而建立文件用 `Doc.sudo().create(...)`。
一個只屬於 A 公司的 doc manager 可以用 RPC 把 target 設成他**連讀都讀不到**的
B 公司——實測建出 1 份。與核心匯出紀錄那次同一類：**`sudo()` 繞過 record rule
＋ 使用者可控的公司欄位**。

三層修正：欄位加 domain（UI）、`action_run_import` 開頭檢查
`in env.companies`（RPC 擋不住 domain）、`create` 去掉 `sudo()`（讓
`rule_doc_document_company` 真的生效）。

**② 視覺回歸 harness 的兩條路由對任何登入者開放**

`/dobtor_doc_editor/test` 與 `test_data` 會讀 `tests/fixtures/` 的 .docx，而那些
是**真實的台灣企業／政府文件樣本**。原本只有 `auth='user'`。路徑防護
（normpath + startswith + 只收 .docx）擋的是 traversal，擋不住「誰可以看」。
收緊到 `group_doc_manager`——harness 都以 admin 跑，不會壞。

### 清掉的

| | 理由 |
|---|---|
| `scripts/verify_sprint277.mjs` | 它存在的理由是「WSL ENOMEM 時走此路徑」，那台機器已不存在；對應的 `tests/unit/sprint277_linebreaker_mvp.test.ts`（6 則）在 3059 則裡跑 |
| `patches/` ＋ `postinstall: patch-package` ＋ devDep | 5 個月 **0 個 patch**，而 README 的計畫停在「當下我們在 Day 1 階段」。custom bundle 實測也不含 canvas-editor，所以那個機制從來沒用上 |
| `models/` 空套件 | 拆模組時建的佔位，沒有任何內容 |
| `tests/fixtures/.visual_regression_tmp/` | 52MB 未追蹤產生物，VR 跑一次就重生 |

`npm install` 之後 `package-lock.json` 少了 43 個套件。

### 刻意不清的（量過，都有理由）

| | 為什麼留 |
|---|---|
| 82MB fixtures | **11 個目錄全部**被 8–41 支測試引用，沒有閒置的 |
| `scripts/visual_regression.mjs` | `visual_regression_v14.mjs` 的檔頭明寫「老 CLI 仍保留：可比對 canvas-editor 端的 IElement 邏輯本身有沒有改錯」 |
| 6 份 report JSON | 是 `SPRINT_AUDIT_CONSOLIDATED.md` 引用的量測證據 |
| `tools/build_phase5_fixtures.py` | grep 不到引用，但它是 07/08/09/11 四個 fixture 目錄**唯一的來源憑證**。差點被當成孤兒刪掉 → 補了 `tests/fixtures/PROVENANCE.md` 把這件事寫下來 |
| 14 支 `Overlay*.ts` | Phase 8 Phase 2.2 未啟動，寄放理由寫在那個目錄的 README |

### 檢討過、確認不缺的

`static/description/` 圖示（Odoo 會給預設的）、`i18n/`（核心
`docs/a11y_i18n_design.md` 明訂預設 zh_TW、硬寫中文是刻意的）、`migrations/`
（尚未商轉）、record rule（本模組沒有自己的 model）。

## 錯誤處理的約定（2026-10-09 統一）

**一條路由只有一套慣例**：使用者層的錯誤 `raise UserError`，由繼承自核心的
`json_http_route` 統一成 **400 ＋ `{'success': False, 'error': …}`**；
非預期的例外讓它漏出去，decorator 給 **500 ＋ 可追代碼**並記 log。

改之前不是這樣：`/dobtor_doc/import` 的錯誤路徑走本地的 `_json_resp`，
所以「未收到檔案」「zip bomb」「不支援格式」「轉換失敗」全都回 **HTTP 200**
＋ `{'error': …}`——同一條路由兩套慣例，前端能動是湊巧而非設計。

**函式庫與子程序的原文只進 log，不給使用者看。** LibreOffice 的 stderr 原本
會被 `raise Exception(f'…{stderr[:400]}')` 一路送到瀏覽器（含容器路徑）。

### ☠️ 兩處「把失敗當成文件內容」

`_docx_to_html_with_format()` 原本在解析失敗時回傳
`<p>（無法解析 DOCX：…）</p>`。可達情境：**把改名的 .zip 當 .docx 上傳**
——zip_guard 放行（它確實是合法 zip），使用者於是得到一份內容是英文函式庫
錯誤訊息的文件；經**批次精靈更糟**：那份文件會被建出來並**計為成功**。

兩處都改成 `raise UserError`：路由 → 400；精靈 → `failed_count` ＋ log
（精靈本來就是為這件事準備了那兩個欄位）。

## 轉換函式的測試覆蓋

`controllers/doc_convert.py` 的九支原本**只靠路由間接覆蓋**，而其中一整條是
**降級路徑**：`_lo_convert_to_html()` 沒有 LibreOffice 時回 `None`，呼叫端改走
純 python-docx 的 `_docx_to_html_with_format()`。容器裡有 `soffice`，所以那條
降級鏈在測試裡**永遠走不到**——「寫好了但從沒被執行過」的典型。

`tests/test_doc_convert.py` 用 `patch.object(doc_convert.shutil, 'which')`
把 LibreOffice 拿掉，讓降級鏈真的跑一次；另外直接驗純函式的行為（段落、表格、
粗體、HTML 轉義、頁面邊距、壞 CSS 不炸）。
