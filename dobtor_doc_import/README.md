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
