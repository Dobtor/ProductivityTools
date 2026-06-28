# dobtor_doc_editor 客戶導入 SOP（P3-1）

**狀態**：補強衝刺實作  
**對應漏項**：P3-1 — 客戶導入流程缺  
**完成日期**：2026-05-06

---

## 目錄

1. [角色別 SOP](#1-角色別-sop)
2. [批次匯入工具使用](#2-批次匯入工具使用)
3. [試營運計畫](#3-試營運計畫)
4. [常見問題 FAQ](#4-常見問題-faq)

---

## 1. 角色別 SOP

ChienYi 系統使用者依職責分四種角色，dobtor_doc_editor 對每種角色開放不同入口。

### 1.1 監造主管 / 工程師（Internal user, group_doc_editor / group_doc_manager）

**入口**：Odoo 主導覽列 → 「文件編輯器」

**典型操作流程**：

| 步驟 | 操作 | 預期 |
|---|---|---|
| 1 | 點「文件編輯器 → 我的文件」進列表 | 看到自己建立或被加為協作者的文件 |
| 2 | 點右上「新增」建立空白文件 | 開啟 Canvas 編輯器 |
| 3 | 編輯內容（標題、內文、表格） | 1.5 秒 debounce 後自動存（statusbar 顯示「已儲存」） |
| 4 | 工具列「存版本」按鈕 | 輸入 label → 確認，建立版本快照 |
| 5 | 工具列「歷史」按鈕（或 Alt+H） | 開啟版本歷史對話框 |
| 6 | 想邀承包商編輯：後台 form 加入 collaborator | portal user 下次登入會在 `/my/documents` 看到 |
| 7 | 列印：點工具列「PDF」匯出 | 透過 wkhtmltopdf 產生 |

**鍵盤快捷鍵**（無障礙友善）：
- `Ctrl+S` → 儲存
- `Ctrl+Shift+S` → 建立版本快照
- `Alt+H` → 版本歷史
- `Esc` → 關閉對話框
- `Ctrl+Z / Ctrl+Y` → 復原 / 重做

**避免操作**：
- 不要在 Odoo 後台直接 `unlink` 文件 — 監造紀錄有法律效力，刪除前先確認非當期文件
- 不要把與 ChienYi 業務無關的文件存到此模組 — 改用 Odoo `dms` 模組

### 1.2 承包商代表 / 業主（Portal user, group_doc_portal）

**入口**：登入 ChienYi portal → `/my/documents`

**典型操作流程**：

| 步驟 | 操作 | 預期 |
|---|---|---|
| 1 | 收到 ChienYi 監造方寄出的「您已被邀請為文件協作者」通知 | email 附 portal 連結 |
| 2 | 點連結登入 portal（首次需設密碼） | 進入 `/my/documents` 列表頁 |
| 3 | 看到自己被加入的文件名稱 | **只看得到被邀請的，看不到別人的** |
| 4 | 點任一文件 | 進編輯頁 |
| 5 | 編輯內容 → 自動儲存 | 1.5 秒後 statusbar 顯示「已儲存」 |
| 6 | 與監造方衝突時（兩人同時改） | 看到 sticky 警告「文件已被 X 修改」+ 自動 reload，自己剛才的內容已暫存於 IndexedDB |

**權限限制**（不能做）：
- ❌ 建立新文件（要監造方先建好再邀請）
- ❌ 刪除文件
- ❌ 看到其他案件的文件
- ❌ 看到別的承包商的文件

### 1.3 系統管理者（admin, group_doc_manager）

**入口**：Odoo 後台「文件編輯器 → 監控」

**典型維運操作**：

| 任務 | 進入 | 頻率 |
|---|---|---|
| 看錯誤紀錄 | 監控 → 錯誤紀錄 | 每週一次 |
| 看效能指標 | 監控 → 效能指標 | 上線後第一個月每天，穩定後每月 |
| 批次匯入既有 .docx | 文件編輯器 → 批次匯入 | 客戶導入期 |
| 文件範本管理 | 文件編輯器 → 文件範本 | 樣板修改時 |
| 系統升級後驗證 | `make ci-all` + Odoo 測試 | 每次 push 後 CI 自動跑 |

### 1.4 IT 支援人員

**入口**：直接 SSH / docker exec 到 odoo container

**檢查清單**：

```bash
# 1. CI 狀態檢查
docker exec odoo18 odoo -c /etc/odoo/odoo.conf -d odoo18_dev \
    --test-tags dobtor_doc_editor --stop-after-init --http-port=8169

# 2. 監控 metric 彙總
docker exec odoo18 odoo shell -c /etc/odoo/odoo.conf -d odoo18_dev <<'PY'
m = env['doc.editor.perf.metric'].aggregate_recent('save_latency_ms', hours=24)
print(f"24h save_latency: count={m['count']}, mean={m.get('mean', 0):.1f}ms")
PY

# 3. 錯誤紀錄速查
docker exec odoo18 odoo shell -c /etc/odoo/odoo.conf -d odoo18_dev <<'PY'
errors = env['doc.editor.error.log'].search([], limit=10)
for e in errors:
    print(f"{e.create_date} {e.error_type}: {e.message[:80]}")
PY
```

---

## 2. 批次匯入工具使用

**情境**：客戶 ChienYi 已有 200+ 份既有 `.docx` 監造文件想轉到 dobtor_doc_editor。

### 2.1 步驟

1. **準備 ZIP**：把所有 `.docx` 打包成一個 `.zip`（無需資料夾結構，扁平就好）
2. **進 Odoo 後台 → 文件編輯器 → 批次匯入**
3. **上傳 ZIP**：限制 50MB / 5000 個檔案 / 解壓後 ≤500MB
4. **選 target 公司**（多公司隔離）
5. **勾「略過失敗檔案」**（建議開啟，否則第一個失敗就 abort）
6. **點「開始匯入」**
7. **等待結果**（200 份約 1-2 分鐘）
8. **檢視 log**：每筆顯示 OK / SKIP / FAIL，FAIL 含錯誤原因

### 2.2 失敗檔案處理

常見失敗原因：

| 錯誤 | 解決 |
|---|---|
| 不是合法 ZIP | 檔案損壞，重新壓縮 |
| LibreOffice 無法解析 | DOCX 含特殊巨集；先用 Word 另存新檔（不勾「使用相容模式」） |
| 解壓尺寸超標 | 拆成多個小 ZIP 分批匯入 |
| 字型 fallback 失敗 | 確認 container 安裝 `fonts-noto-cjk`（PDF 引擎評估文件有列） |

### 2.3 匯入後分類

每筆文件名稱會自動加上 `[批次匯入_YYYY-MM-DD]` 後綴，方便事後篩選：

```
我的會議記錄_20260301 [批次匯入_2026-05-06]
工地查驗表_20260315 [批次匯入_2026-05-06]
```

之後可在 Odoo 列表用 search domain `name ilike "[批次匯入_2026-05-06]"` 過濾。

---

## 3. 試營運計畫

### 3.1 階段定義

| 階段 | 時間 | 範圍 | 退出條件 |
|---|---|---|---|
| **Stage 1：內部測試** | W11+ 第 1-2 週 | 監造工程師 1-2 人試用，case = HGX-A 新增的 1 份監造會議記錄 | 至少完成 1 份完整週期（建立 → 編輯 → 版本 → 簽核 → PDF 匯出）無 critical bug |
| **Stage 2：友善客戶試營運** | W11+ 第 3-6 週 | A 標案件 + 1 個友善承包商，文件數 ≤10 | 承包商 1 週至少編輯 3 次無投訴；錯誤紀錄無 critical |
| **Stage 3：擴大試營運** | W11+ 第 7-12 週 | 3 個案件 + 5 個承包商 portal user | 承包商 SUS 滿意度 ≥70；無資料遺失事件 |
| **Stage 4：全面上線** | W11+ 第 13 週後 | 所有新案件預設啟用 | — |

### 3.2 觀察指標（dashboard）

每階段監控以下指標（從 `doc.editor.perf.metric` 抓）：

| 指標 | 目標值 | 警戒值 |
|---|---|---|
| `load_doc_ms` 中位數 | <800ms | >2000ms |
| `save_latency_ms` 中位數 | <500ms | >1500ms |
| `web_vitals_lcp_ms` p95 | <2500ms | >4000ms |
| `web_vitals_cls` p95 | <0.1 | >0.25 |
| 錯誤率（error log / metric count） | <1% | >5% |
| 衝突發生率（save 收到 conflict） | <5% | >20%（可能要轉 OT） |

### 3.3 風險與回退

| 風險 | 偵測 | 回退方案 |
|---|---|---|
| 大量衝突警告 | conflict 比例 >20% | 提早投入 W11+ Sprint 14（CRDT/OT） |
| 字型 fallback 失敗 | PDF 出現方塊 | 暫時改用 LibreOffice 路徑（既有） |
| Portal user 抱怨 UI 太複雜 | SUS <50 | 把 toolbar 簡化版做成 portal-only 模板 |
| 資料遺失事件 | error log 有 save_failure 且 IndexedDB 也沒救回 | 立即停用 AutoSave，改回手動儲存；事後 RCA |
| 容器 OOM | 監控 RAM | 確認 W4 記憶體釋放真的有效 |

### 3.4 教學素材清單（待 W11+ 補拍）

| 素材 | 對象 | 長度 | 狀態 |
|---|---|---|---|
| 「監造工程師：建立第一份線上會議記錄」 | 監造方 | 5 分鐘影片 | TODO |
| 「承包商：如何接受邀請並編輯文件」 | 承包商 | 3 分鐘影片 | TODO |
| 「IT 管理員：批次匯入 200 份既有 docx」 | IT | 5 分鐘影片 + 文字步驟 | TODO（文字 SOP §2 已備） |
| 「衝突處理：兩人同時改的應對」 | 全員 | 2 分鐘影片 | TODO |
| 「鍵盤快捷鍵速查」 | 全員 | 1 頁 PDF | TODO |

---

## 4. 常見問題 FAQ

### Q1：portal user 為什麼看不到任何文件？

A：portal user 必須**先被 internal user 加為 collaborator** 才看得到。流程：
1. 監造工程師後台開文件 form
2. 在「協作者」欄位加入承包商 user
3. 承包商重新整理 `/my/documents` 即可看到

### Q2：自動儲存到底是即時還是 debounce？

A：1.5 秒 debounce + 10 秒 max-wait + 3 秒 idle。也就是說：
- 你停止打字 1.5 秒就會存
- 即使一直打字，最多 10 秒一定會強制存一次
- 完全閒置 3 秒會再存一次（保險）

### Q3：版本快照會佔多少空間？

A：每個版本約等於文件 HTML + JSON 大小（壓縮後）。一份 100 頁文件約 500KB-1MB，存 100 個版本約 100MB。建議：
- 監造會議記錄：每次定稿存一個版本，期末歸檔保留最後 10 個
- 高頻編輯文件（每天改）：超過 50 個版本後手動清舊版（W11+ 加自動清理 cron）

### Q4：與 QWeb PDF 報表怎麼選？

A：見 [scope_decision.md](scope_decision.md) §3 表格。簡言之：固定格式簽核走 QWeb，協作 / 版面複雜走 dobtor。

### Q5：可以離線編輯嗎？

A：目前 offline_manager 框架已備但 IndexedDB 持久化未完整啟用（W7-8 P1-4 寫了一半，W11+ 補完）。短期建議：
- 確保有網路再開始編輯
- 短暫斷線（<30 秒）AutoSaveManager 會 buffer，恢復連線自動重送
- 長時間離線 → 手動複製內容到本機 Word，恢復連線後貼回

### Q6：手機可以用嗎？

A：可以，但體驗未最佳化。Phase 4.5 補強衝刺重點是 PC 桌機；手機優化屬 W11+ Phase 5 範圍。短期建議：手機只看不編輯，編輯回 PC。

---

**附註**：對應計畫檔 [federated-swimming-creek.md](/home/chichi/.claude/plans/federated-swimming-creek.md) 的 P3-1。
