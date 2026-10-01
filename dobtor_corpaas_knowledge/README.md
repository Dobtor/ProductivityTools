# dobtor_corpaas_knowledge — CorPaaS 方案知識核心

監控方案母體的程式改版，自動盤點功能、計算畫面指紋、重建說明庫並以無頭瀏覽器截圖。
這是**事實層**；三個出口各自一個模組：

| 模組 | 出口 |
|---|---|
| `dobtor_corpaas_knowledge_manual` | 操作說明 → slide channel（一個方案一個） |
| `dobtor_corpaas_knowledge_marketing` | 產品行銷 → 方案商品頁 |
| `dobtor_corpaas_knowledge_proposal` | 服務建議書、評估報價、預估成本 |
| `dobtor_ai_hub_content`（裝在 AI Hub） | content 模式端點 |
| `dobtor_ai_bridge_help`（裝在租戶） | 「此畫面說明」與說明連結 |

設計文件：Claude Docs「CorPaaS 方案知識核心設計」。實作契約：`IMPLEMENTATION_SPEC.md`。

## 更新流程（`knowledge_refresh`，走 corpaas.queue）

```
kb_check → kb_golden_sync → kb_inventory → kb_fingerprint → kb_ai_catalog
         → kb_sandbox → kb_shoot → kb_outlets → kb_cleanup
```

觸發：方案上架（`_corpaas_bind_masters`）、說明主機上的母體「下載新版」且程式碼清單真的變了、
每月保底（排程，預設停用）、母體容器映像 digest 改變（排程，預設停用）、手動按鈕。

## 素材從哪裡來（D7）

說明主機上**方案母體裡的內部資料庫**（說明庫，`docsbx-p<方案>-<情境>`），從黃金庫複製。
不另建實例、不建 `infrastructure.database` 記錄（建了會被服務盤點、授權推送、容量、計量、
dbfilter 收斂當成客戶庫）。方案沒有在說明主機上架 → 直接擋下。

- 黃金庫全程唯讀：盤點與指紋腳本結尾 rollback；暫存角色使用者建在交易內。
- 說明庫：複製 → D1 清除（只留模組資料與 `__doc_scenario_*`）→ 重播情境示範資料＋角色帳號。
- 截圖（D8）：主控台經 SSH 在說明主機 `docker run --rm` Playwright 官方映像，
  `--host-resolver-rules` 把 `<庫名>.internal` 映射到母體容器（共享母體依網址第一段選庫），
  外部經 nginx 進不來。截圖前檢查畫面上每筆記錄都屬於示範資料（D1），否則不採用。

## 部署前設定

1. 設定 › CorPaaS 基礎建設 › 方案知識：說明主機、AI Hub 網址與金鑰、預算、截圖映像、字型目錄。
2. 說明主機上準備中文字型目錄（預設 `/usr/share/fonts/opentype/noto`，放 Noto Sans CJK TC）。
   ☠️ 沒有字型，中文全部變方框，而且截圖流程不會報錯。
3. AI Hub：安裝 `dobtor_ai_hub_content`，把主控台的 `ai.hub.source` 勾「允許 content」，
   並調高它的每日次數與成本上限（預設 50 次／5 USD，一次全量更新就會用完）。
   ☠️ Hub 的 `run_status` 會經 `brand_sanitize` 把「Odoo」與引擎名稱換成品牌別名；
   說明內容要保留原字就關掉 `ai_hub.brand_filter`。
4. 說明主機要能 `docker pull` Playwright 映像（或事先 pull 好）。
5. 方案表單 › 方案知識：勾啟用、設定情境與能力，按「立即全量更新」。
6. 租戶說明查詢的簽章：每小時排程替「知識已啟用方案」底下的正式庫下發金鑰（寫進租戶的
   `dobtor_ai_help.console_key`）；也可在資料庫的「動作 › 下發說明查詢金鑰」手動下發。
   `corpaas_knowledge.help_require_signature` 預設 True（未簽章的查詢一律拒絕）；
   過渡期若租戶還沒裝新版 `dobtor_ai_bridge_help`，可暫時設為 False。

## 已知限制與待實機確認

- 平台的「無人納管資料庫」巡檢會看到說明庫：以 `docsbx-` 前綴辨識，**不要清掉**。
- 建庫時的「沒有網址的庫」檢查：說明庫不經 `create_db`，不受影響；但若日後改走 `create_db` 需比照黃金庫豁免。
- 母體 nginx 不可有 catch-all 的 default_server，否則外部可偽造 Host 進入說明庫（部署前檢查）。
- 清除（D1）以 ORM 逐筆刪除；刪不掉的記錄列在清除報告的 residual，截圖前檢查會擋住它們出現在畫面上。
- 授權推送等「整台下發」的作業會連到母體容器內所有庫，包含說明庫；影響是說明庫被停權／改 CCU，不影響客戶。

## 測試

`tests/`：純函式（指紋、dHash、檢索評分）、內容狀態機、shell 腳本在測試庫內實際執行（指紋、示範資料、D1 檢查）、
整條 refresh（遠端 shell 換成在測試庫內 exec 同一份腳本）。
