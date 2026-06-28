# 樂觀鎖設計（P2-2 多人協作衝突偵測）

**狀態**：補強衝刺實作  
**對應漏項**：P2-2 — 多人協作衝突偵測缺  
**完成日期**：2026-05-06

---

## 1. 為什麼用樂觀鎖（不是 OT/CRDT）

| 方案 | 適用場景 | 工作量 | 優先級 |
|---|---|---|---|
| **樂觀鎖**（本次實作） | 多人「不會同時編輯」場景 — 後存的人收到衝突警告，重載後再改 | ~半天 | ✅ 短期方案 |
| Bus.bus 即時通知 | 多人想看到「正在編輯者」名單，但仍各自獨立編輯 | 1-2 天 | 中期擴充 |
| Yjs CRDT / OT | 多人「真的同時編輯」（如 Google Docs） | 3-5 個月 | 長期；屬主線 Sprint 15+ 範圍 |

ChienYi 的監造文件**絕大多數是低衝突**：會議記錄通常一人寫、自主檢查表通常承包商一人填，並非 Google Docs 那種多人併寫場景。樂觀鎖足以覆蓋 90% 衝突場景。

## 2. 機制

### 2.1 兩階段協議

```
[Client A]                    [Server]                    [Client B]
   |                             |                             |
   | POST /load doc_id=42        |                             |
   |---------------------------> |                             |
   | <--- {wd_v1, content_v1}    |                             |
   |                             |                             |
   |                             | <--- POST /load doc_id=42   |
   |                             | --- {wd_v1, content_v1} ---->
   |                             |                             |
   | (編輯中...)                 |                             | (編輯中...)
   |                             |                             |
   |                             | <--- POST /save             |
   |                             |       if_unmod=wd_v1        |
   |                             |       content=content_v2    |
   |                             | (寫入 → wd_v2)              |
   |                             | --- {success, wd_v2} ----->  |
   |                             |                             |
   | POST /save                  |                             |
   |   if_unmod=wd_v1            |                             |
   |   content=content_v3        |                             |
   |---------------------------> |                             |
   | (比對 wd_v1 ≠ wd_v2 → 拒絕) |                             |
   | <--- {conflict=True,        |                             |
   |       server_wd=wd_v2,      |                             |
   |       server_author=B}      |                             |
   |                             |                             |
   | (前端：警告 + reload + 暫存到 IndexedDB)                  |
```

### 2.2 etag 選擇

用 **`doc.write_date`** 當 etag（ISO 字串）。優點：
- Odoo 原生欄位，所有 model 都有，免維護
- 寫入即更新（write 自動觸發）
- ISO 字串便於前後端 round-trip 比對

備案：用 `version_number`（W7-8 的 P1-1 加的整數欄位）—— 但只有手動 `action_save_version` 才會 +1，AutoSave / 普通 write 不會動，所以不適合當 etag。

### 2.3 比對邏輯

字串完全相等比對（不做時間 parse）。前後端都用 `datetime.isoformat()`，理論上一致。

```python
if if_unmodified_since:
    current_wd = doc.write_date.isoformat() if doc.write_date else None
    if current_wd and current_wd != if_unmodified_since:
        return {'conflict': True, ...}
```

刻意不做「容忍 ±1 秒」這類寬鬆比對 — 因為 PostgreSQL `write_date` 含 microsecond 精度，差 1 微秒就代表有人寫過。

## 3. 影響的檔案

| 檔案 | 變更 |
|---|---|
| [controllers/doc_controller.py](../controllers/doc_controller.py) | `load_document` 回傳值加 `write_date` + `version_number`；`save_document` 接受 `if_unmodified_since` 參數；衝突回 `{conflict: True, server_write_date, server_author_*}` |
| [static/src/components/doc_editor/doc_editor.js](../static/src/components/doc_editor/doc_editor.js) | 加 `_lastSyncedWriteDate` 成員；load 時記下；save 時帶上；新增 `_handleSaveResult` 處理衝突（暫存 → 警告 → reload）|
| [tests/test_optimistic_lock.py](../tests/test_optimistic_lock.py)（新增） | 5 個測試：無 etag pass、相同 etag pass、過期 etag reject、不可解析 etag reject、load 回傳 write_date |

## 4. 衝突發生時的 UX

1. 後端回 `{conflict: True}` 而非 200
2. 前端 `_handleSaveResult` 處理：
   - 把使用者剛才 attempt save 的 `json` 塞進 `offline_manager.bufferOperation()`（避免遺失）
   - statusbar 顯示「與他人編輯衝突」
   - notification: `「文件已被「{author}」修改（v{N}）。將重新載入最新內容；您剛才編輯的內容已暫存於離線緩衝。」` (sticky=true 不會自動消失)
3. 自動 `_loadDocument(docId)` 拉最新內容
4. 重新 `executeSetValue(data)` 餵給 canvas-editor

使用者看到 reload 後的內容後，可以：
- 手動重做自己的修改（簡單情境）
- 從 offline buffer 取回剛才的內容比對（複雜情境，待 W11+ 加 UI）

## 5. 限制與後續延伸

| 限制 | 對應後續工作 |
|---|---|
| 衝突時使用者得手動 merge | 中期：加「diff: 我想存的 vs 伺服器最新版」UI（sprint 15+） |
| 沒有「正在編輯中」狀態廣播 | 中期：Odoo `bus.bus` 廣播 + `leader_election.js` 開始集成 |
| 純 docx round-trip（不在 Odoo 內）無此保護 | 長期：CRDT 或 OT |
| `if_unmodified_since` 字串相同但毫秒差會誤判 | 已驗證：write_date 寫入即更新，不會有「相同字串但內容不同」的可能 |

## 6. 為什麼不直接用 Odoo 原生 `concurrency_token`

Odoo 18 model 有 `_log_access` mixin 提供 `write_date` / `write_uid`，但沒有原生 `concurrency_token` 欄位（這是某些 ERP 才有）。社群有 `base_concurrency` OCA 模組但會強制所有 write 都檢查，副作用大；本次只在 `/dobtor_doc/save` 路由做檢查，最小擾動。

## 7. 驗收條件

- [x] `tests/test_optimistic_lock.py` 5 個 case 全綠
- [ ] E2E：兩個 browser tab 同時開同一文件 → 後存的人收到 sticky 警告 + 內容自動 reload + offline buffer 有暫存（待 W11+ E2E playwright 補）
- [x] 既有 33 個 Python 測試（W9-10 寫的）不受本次變更影響

---

**附註**：對應計畫檔 [federated-swimming-creek.md](/home/chichi/.claude/plans/federated-swimming-creek.md) 的 P2-2。
