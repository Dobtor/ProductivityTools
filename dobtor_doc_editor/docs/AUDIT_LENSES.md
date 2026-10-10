# 稽核的尺（AUDIT LENSES）

`DONE_CRITERIA.md` 保證的是「**這 12 條判準今天成立，而且任何一條退步都會有東西
變紅**」。它**不**保證「沒有缺陷」。

這份文件是另一半：**稽核面的窮舉**。分母在這裡，不在判準表。

☠️ 這份文件本身就是一個教材：`DONE_CRITERIA.md` 在 2026-10-09 寫下「見
`AUDIT_LENSES.md`」而我當天沒有建它——那正是本模組一整天在修的失效模式
（宣告了但不存在），發生在宣告這件事的那份文件上。它是在同一天的全檔案稽核
階段 6（掃文件裡的死連結）被抓到的。

## 為什麼要窮舉「尺」

2026-10-09 當天「全部修正優化完成了嗎？」被問了四次，而每次回答之後都還能
再找到東西。原因不是程式越改越糟，是**每換一把新尺就量到新東西**——
尺是新的，不是程式變差了。

只要尺的清單沒有窮舉，這個過程就沒有終點。所以：**先列尺，再開始挖。**
邊想邊挖就是「答了四次還有」的成因。

## 已用過的尺

| # | 尺 | 量到什麼 | 留下的守衛 |
|---|---|---|---|
| 1 | 判決傳遞（檢查的結果到得了人眼前嗎） | 5 個：`find -exec` 退出碼恆 0、匯入 `ci-python` 必失敗、匯入無 XML 檢查、`tools/`／`migrations/` 漏掃、`typecheck` 兩錯讓 `ci-frontend` 停在第一行 | `test_static_checks_wiring.py`（兩模組各 4 則） |
| 2 | 量測閘門在零結果時會不會說通過 | 2 個：VR threshold gate 與 v14 pipeline 都會 | `measurement_gates.test.ts`（5 則，真的執行閘門） |
| 3 | 不可達的 TS 有沒有宣告與軸別 | 78 支／14,144 行全部宣告並分軸（ADR-034） | `bundle_reachability.test.ts`（8 則） |
| 4 | `ir.cron` 的 `code` 字串解析得到嗎 | 0（5 條都健全），但原本零守衛 | `test_cron_wiring.py`（3 則） |
| 5 | 測試用什麼識別「自己建的記錄」 | 1 個：遙測用 `order='id desc' limit=1` 猜最新那筆，而前端會送同一個 metric_type | `test_telemetry.py` 改用 `extra` 標記 |
| 6 | 診斷工具自己量對東西了嗎 | 1 個（最嚴重）：session 探針只看 Content-Type，而 `get_session_info` 是 `auth='public'`——**它永遠不可能偵測到 session 掉了** | `test_session_probe_self.py`（6 則） |
| 7 | ACL／record rule 逐 model 對照 | **2 個真的跨公司讀取漏洞**：manager 讀得到所有公司的文件內容；範本的 3 個子 model 完全沒有 rule | `test_acl_company_isolation.py`（4 則）＋ migration `18.0.15.2.0` |
| 8 | 每條路由的輸入邊界守衛 | 3 個：`save` 的 4 個內容欄位無上限、`i18n/import` 無上限、harness 的 traversal 守衛從沒被送過 payload | `test_input_bounds.py`（3 則）＋ `TestHarnessRoutesRejectTraversal`（2 則） |
| 9 | 路由到底有沒有被任何東西驗過（**跑 tour 看 werkzeug 日誌**） | **22 條零驗證**（tour 只打到 5 條，不是我以為的「前端都走過了」）；`/dobtor_doc/models` **一直是壞的**（`ir.model` 沒有 `abstract` 欄位） | `test_route_smoke.py`（含 `_UNVERIFIED` 分母） |
| 10 | compute／constrains 的接線 | 0（全部健全）；但 3 條約束原本零行為測試 | `test_model_constraints.py`（11 則） |
| 11 | docstring 的承諾比行為強嗎 | 1 個：`json_http_route` 標題行寫「保證永遠回 JSON」而它有兩個刻意的例外 | `scan_absolute_promises.py`（工具，不是閘門） |
| 12 | 升級路徑（既有資料經 `-u` 還正確嗎） | 原本**完全沒有驗證**——而 `noupdate` 的資料檔改 XML 對既有 DB 無效 | `run_upgrade_check.sh` ＋ 判準 `upgrade-path` |
| 13 | 全檔案清查（1,140 檔逐一歸類） | 1 個：匯入模組出貨內嵌 fflate／xmldom 卻**沒有 `LICENSE` 也沒有 `LICENSES/`** | `TestThirdPartyLicenseRegistry`（3 則）＋ `TestPythonPackageWiring`（4 則） |
| 14 | 文件裡的連結與路徑還成立嗎 | 4 處會害人的：`CONTRIBUTING.md` 把規矩外包給另一個 repo 的檔案、`onboarding_prompt.md` 叫人讀兩個從未存在的檔案並 `cd` 到已不存在的機器 | `test_doc_links.py` |
| 15 | 視圖的無障礙警告（**用 Odoo 自己的驗證器**，不自己重寫判準） | 6 處裝飾性 fa 圖示沒有說明文字——安裝時 Odoo 一直在報，沒有人在看。☠️ 我第一次自己重寫判準漏了第一段檢查，算出 21 處；補回去算出 7 處；Odoo 報 6 處（差的那 1 處是 QWeb 模板，`_check_xml()` 對 qweb 直接 `continue`） | `test_view_a11y.py`（4 則，含負向控制與一則掃 Odoo 根本不看的 qweb） |
| 16 | 部署足跡（`git pull` 會送多少東西到正式機） | 94.4 MB 裡有 85.4 MB 是 `tests/`，而正式機不跑測試。前提「出貨程式不依賴 `tests/`」成立但**真的可能破**——`tests/session_probe.py` 已經是跨模組公開介面 | `run_ships_without_tests_check.sh` ＋ 判準 `ships-without-tests`；數字與部署端寫法見 [`DEPLOYMENT_FOOTPRINT.md`](DEPLOYMENT_FOOTPRINT.md) |

## 還沒用過的尺

這一欄是**待辦**，不是建議。每清掉一把就搬到上面那張表。

| 尺 | 預期會抓到什麼 | 為什麼還沒做 |
|---|---|---|
| 前端 JS 的行為測試 | 核心 32 支出貨 JS 只有 tour（78 步，實測只打到 5 條路由）在驗。OWL component 的渲染邏輯幾乎零驗證 | 需要 hoot 或等價的前端測試環境；本模組目前只有 `tests/js/` 的純函式測試 |
| 並行與交易邊界 | 樂觀鎖（`if_unmodified_since`）在真正並行下的行為；`doc.output` 的 cron GC 與使用者下載同時發生 | 要造出真並行，本機 rig 是 `--workers=0` |
| 效能回歸 | 大文件（11_perf_synthetic_large 的 200 頁）的解析與排版時間有 guard，但出貨路徑（`engine=ts` 的 node CLI）沒有 | 需要穩定的量測環境；目前只有 vitest 內的 perf guard |
| i18n 完整性 | `docs/a11y_i18n_design.md` 明訂「預設語系 zh_TW、hardcode 中文是刻意的」。英文需求出現時要掃哪些字串該包 `_()` | **刻意不做**——那份設計文件說了它是決定，不是缺口 |
| 資料遷移的反向路徑 | 降版（18.0.15.2.0 → 18.0.10.1.0）會發生什麼 | 沒有降版需求；Odoo 本身也不支援 |

## 用這份文件的方式

1. 問「完成了嗎」→ 跑 `make done`（12 條判準，見 `DONE_CRITERIA.md`）。
2. 問「還有什麼沒查」→ 看上面「還沒用過的尺」那張表。
3. 新想到一把尺 → **先加進那張表**，再開始挖。加進去的時候寫清楚「預期會抓到
   什麼」——那一欄是在逼自己先想清楚這把尺量的是什麼，而不是挖到哪算哪。
4. 清掉一把尺 → 搬到「已用過」那張表，並寫下它量到什麼、留下什麼守衛。
   **沒有留下守衛的尺不算清掉**——下次程式改動它就會復發。
