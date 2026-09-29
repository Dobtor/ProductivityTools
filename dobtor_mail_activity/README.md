# 生產力工具 (Productivity Tool)

## 概述

`dobtor_mail_activity` 是一個整合待辦管理、週報告與效率分析的生產力管理系統，專為 Odoo 18 設計。
筆記（個人筆記 App、會議記錄）在 `dobtor_meeting_minutes`（相依本模組）。

## 功能特色

### 待辦管理
- **封存機制**：完成/取消待辦時封存而非刪除，保留完整歷史
- **排程系統**：支援週計畫與多週預排功能
- **優先級管理**：時間性（緊急/標準/彈性）與重要性標記
- **工時追蹤**：預估工時；實際工時與工時表整合由 `dobtor_mail_activity_project` 提供（見下方「模組拆分」）
- **轉移功能**：支援待辦在不同文件間轉移
- **指派變更追蹤**：完整記錄指派歷史
- **獨立待辦**：允許不指定關聯文件/筆記的獨立待辦（需求七）
- **關聯邏輯圖（relation diagram）**：待辦表單內以向右邏輯圖（vendored jsmind）
  呈現「專案 → 多層任務/商機/訂單」關聯樹，可縮放/適應視窗；點節點回填相關文件；
  每個記錄節點可用 level-down/up 鈕垂直下拉檢視其「未完成待辦」（眼睛 icon 為總開關）
- **CRM 建立專案**：商機表單可一鍵以標題建立專案並回填

### 報告與整合
- **待辦報告**：分組清單（客戶 → 專案 → 相關文件 → 負責人 → 狀態）
- **訊息/編輯器整合**：從 Discuss 訊息建立待辦（自動帶入客戶公司）、
  富文字編輯器 powerbox 與內嵌待辦清單

### 筆記（18.0.3.0.0 起移至 `dobtor_meeting_minutes`）
`note.note` / `note.stage` / `note.tag`、「個人筆記」App、待辦的「參考來源／引用筆記」、
chatter 相關筆記、合併時改寫筆記膠囊、週排程自動建立週筆記、Alt+Shift+N 新增筆記，
全部由 `dobtor_meeting_minutes` 提供。本模組的編輯器內嵌待辦對任何 HTML 欄位有效；
在筆記內使用時，「引用本筆記」的待辦由該模組擴充列出。

### 週報告功能
- **週計畫快照**：記錄每週開始時的計畫狀態
- **執行回顧**：週末自動統計執行結果
- **差異分析**：計畫 vs 實際的差異追蹤

### 效率分析
- **個人指標**：完成率、準確度、延期率等
- **團隊分析**：跨用戶效率比較
- **儀表板**：Pivot 與 Graph 視圖

## 技術規格

### 依賴模組
- `mail`
- `calendar`
- `portal`
- `hr`

**不相依專案**：`project` / `hr_timesheet` / `project_todo` / `crm` / `sale_crm` 皆非必裝。

### 模組拆分（18.0.2.0.0 起）

| 模組 | 相依 | 安裝方式 | 內容 |
|---|---|---|---|
| `dobtor_mail_activity` | mail, calendar, portal, hr | 手動 | 待辦、週報、效率分析、關聯圖（無專案時以客戶為根）、自有「待辦事項」App |
| `dobtor_meeting_minutes` | 核心 + calendar + portal | 手動（升級核心時若未裝會自動安裝，以保留既有筆記） | 筆記、會議記錄、待辦↔筆記整合 |
| `dobtor_mail_activity_project` | 核心 + project + project_todo + hr_timesheet | **自動**（裝了工時表即安裝） | 待辦的專案欄位、完成時登錄工時、事後「登錄工時」補登、預設工時專案、隱藏 project_todo 的同名 App |
| `dobtor_mail_activity_crm` | 專案橋接 + crm + sale_crm | **自動** | 商機的專案、建立專案、銷售訂單回寫商機專案、商機待辦以商機專案登錄工時 |

沒裝專案時：完成待辦不記工時（精靈沒有工時欄位），效率分析的實際工時為 0。

### 模型清單

| 模型 | 說明 |
|------|------|
| `mail.activity` | 待辦擴展 |
| `mail.activity.type` | 待辦類型擴展 |
| `mail.activity.assignment.history` | 指派歷史 |
| `mail.activity.postpone.history` | 延期歷史 |
| `mail.activity.transfer.config` | 轉移目標配置 |
| `weekly.report` | 週報告 |
| `weekly.report.snapshot.line` | 計畫快照明細 |
| `weekly.report.review.line` | 執行回顧明細 |
| `activity.efficiency.metrics` | 效率指標 |
| `weekly.schedule.config` | 週報排程配置 |

## 安裝

1. 將模組放置於 Odoo addons 路徑
2. 更新模組列表
3. 搜尋並安裝「生產力工具」

## 使用說明

### 快捷鍵

| 快捷鍵 | 功能 |
|--------|------|
| `Alt+Shift+A` | 新增待辦 |
| `Alt+Shift+N` | 新增筆記（需 `dobtor_meeting_minutes`） |

### 週天排程

待辦可排程至特定週天（週一至週日），並支援多週預排：
- 本週
- 下週
- 第三週
- 第四週

### 工時記錄（需 `dobtor_mail_activity_project`）

完成待辦時登錄的工時會寫進工時表，專案依序取：關聯任務的專案 → 關聯商機的專案
（CRM 橋接）→ 待辦的專案 → 公司預設工時專案（系統設定 > 待辦事項）。
找不到專案時照常完成、跳過工時（chatter 留痕）；之後掛上專案可在待辦「工時表」
分頁按「登錄工時」補登（已完成待辦亦可）。

## 升級 Odoo 版本前的檢查清單

本模組對 Odoo 核心的覆寫面積偏大。**每次升級 Odoo 小版本（18.0.x → 18.0.y）或大版本
前，請逐項比對官方原始碼是否變動**；下表的「對齊版本」代表最後一次人工核對的版本。

### 後端：覆寫 core 方法

| 檔案 | 方法 | 官方原始碼 | 對齊版本 | 風險 |
|---|---|---|---|---|
| `models/mail_activity.py` | `_search` | `mail/models/mail_activity.py` | 18.0 | **高** — 整段重寫，繞過官方存取過濾以支援 res 為空的獨立待辦。官方若調整過濾邏輯不會自動反映 |
| `models/mail_activity.py` | `_check_access` | 同上 | 18.0 | **高** — 同理，獨立待辦自官方文件 gating 拆出 |
| `models/mail_activity.py` | `create` | 同上 | 18.0 | **最高** — `_CREATE_BYPASS_APPLICABLE` 為真時直接呼叫 `models.Model.create`，**完全繞過** 官方 `mail.activity.create`（繞過 18.0 的 UnboundLocalError bug）。官方在該方法新增的任何邏輯都會靜默失效。官方修掉該 bug 後應移除此 bypass |
| `models/mail_activity.py` | `write` / `_action_done` / `_action_cancel` / `action_done` / `action_notify` / `_compute_res_name` | 同上 | 18.0 | 中 — 皆有呼叫 `super()` |
| `models/mail_activity_merge.py` | `unlink` | 同上 | 18.0 | 低 — 呼叫 `super()` |
| `models/res_users.py` | `_get_activity_groups` | `mail/models/res_users.py` | 18.0 | 中 — 系統匣待辦分組，另行併入獨立待辦 |
| `dobtor_mail_activity_crm/models/crm_lead.py` | `create` / `write` | `crm/models/crm_lead.py` | 18.0 | 低 |
| `dobtor_meeting_minutes/models/note_note_base.py` | `name_create` | — | 18.0 | 低 |
| `models/weekly_report.py`、四個 wizard | `default_get` | — | 18.0 | 低 |

### 前端：patch core 元件

| 檔案 | 被 patch 的元件 | 官方模組 |
|---|---|---|
| `core/message_created_activities.js` | `Message` | `@mail/core/common/message` |
| `web/activity/activity_markasdone_patch.js` | `ActivityMarkAsDone` | `@mail/core/web/activity_markasdone_popover` |
| `web/activity/activity_menu_patch.js` | `ActivityMenu` | `@mail/core/web/activity_menu` |
| `web/activity/activity_list_popover_item_patch.js` | `ActivityListPopoverItem` | `@mail/core/web/activity_list_popover_item` |
| `web/activity/schedule_activity_patch.js` | `Store.scheduleActivity` | `@mail/core/common/store_service` |
| `web/chatter/chatter_patch.js` | `Chatter.components`（加入 `RelatedNotes`） | `@mail/chatter/web_portal/chatter` |
| `editor/html_field_activity_patch.js` | `HtmlField.getConfig` | `@html_editor/fields/html_field` |
| `views/calendar_popover/calendar_popover_patch.js` | `AttendeeCalendarCommonPopover` | `@calendar/...` |

### 繼承 core 視圖 / 覆寫 core 選單

| 檔案 | 繼承目標 |
|---|---|
| `views/mail_activity_schedule_views.xml` | `mail.mail_activity_view_search`（**core 上 mail.activity 唯一的 search view**，同時作用於系統列的 `mail.mail_activity_action_my`，該 action 以 `search_default_` 引用 `filter_user_id_uid` / `filter_date_deadline_past` / `filter_date_deadline_today` → 這三個 filter 不得移除） |
| `views/mail_activity_views.xml` | `mail.mail_activity_view_form_popup` |
| `views/mail_activity_type_views.xml` | `mail.mail_activity_type_view_form` |
| `dobtor_mail_activity_project/views/project_todo_override.xml` | 以無成員群組隱藏 `project_todo.menu_todo_todos`（改用本模組自有 App `menu_todo_root`）。群組不會被 `-u project_todo` 重設；卸載橋接時群組刪除、選單自動恢復 |
| `res_config_settings_views.xml` / `res_users_views.xml`；橋接的 `crm_lead_views.xml` / `project_project_views.xml` / `res_company_views.xml` | `base` / `crm` / `project` 的表單 |

### 升級後務必回歸的路徑

1. `-u dobtor_mail_activity` 無 ParseError（xpath 錨點失效會中斷升級，一次只噴一顆）
2. `--test-tags /dobtor_mail_activity,/dobtor_mail_activity_project,/dobtor_mail_activity_crm`
   （另需在「只裝核心、不裝專案」的庫跑一次 `/dobtor_mail_activity`）
3. 手動：週次選擇器 × 搜尋 facet 共存、合併後膠囊轉向、未指派清單的過期項目可見

## 版本資訊

- **版本**：18.0.3.0.0
- **相容性**：Odoo 18
- **授權**：LGPL-3

## 作者

Dobtor SI
https://www.dobtor.com

## 技術支援

如有問題，請聯繫 Dobtor SI 技術團隊。
