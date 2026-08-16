# 生產力工具 (Productivity Tool)

## 概述

`dobtor_mail_activity` 是一個整合待辦管理、筆記本、週報告與效率分析的完整生產力管理系統，專為 Odoo 18 設計。

## 功能特色

### 待辦管理
- **封存機制**：完成/取消待辦時封存而非刪除，保留完整歷史
- **排程系統**：支援週計畫與多週預排功能
- **優先級管理**：時間性（緊急/標準/彈性）與重要性標記
- **工時追蹤**：預估與實際工時記錄，整合 hr_timesheet
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

### 筆記本功能
- **自建 note 模組**：替代 Odoo 18 已移除的 note 模組
- **看板管理**：支援個人化的階段設定
- **標籤分類**：階層式標籤管理
- **待辦整合**：筆記可關聯多個待辦

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
- `project`
- `crm`
- `sale_crm`
- `project_todo`
- `hr_timesheet`

### 模型清單

| 模型 | 說明 |
|------|------|
| `mail.activity` | 待辦擴展 |
| `mail.activity.type` | 待辦類型擴展 |
| `mail.activity.assignment.history` | 指派歷史 |
| `mail.activity.postpone.history` | 延期歷史 |
| `mail.activity.transfer.config` | 轉移目標配置 |
| `note.note` | 筆記本 |
| `note.stage` | 筆記階段 |
| `note.tag` | 筆記標籤 |
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
| `Alt+Shift+N` | 新增筆記 |

### 週天排程

待辦可排程至特定週天（週一至週日），並支援多週預排：
- 本週
- 下週
- 第三週
- 第四週

### 工時記錄

完成待辦時會自動建立工時表記錄，需設定：
1. 系統設定 > 生產力工具 > 預設工時表專案
2. 或待辦關聯的文件（如 project.task）有對應專案

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
| `models/crm_lead.py` | `create` / `write` | `crm/models/crm_lead.py` | 18.0 | 低 |
| `models/note_note.py` | `name_create` | — | 18.0 | 低 |
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
| `views/project_todo_override.xml` | **覆寫** `project_todo.menu_todo_todos` 的 action。因本模組 depends `project_todo` 而載入在後才生效；若單獨 `-u project_todo` 會被還原，需連同本模組一起升級 |
| `views/crm_lead_views.xml` / `project_project_views.xml` / `res_company_views.xml` / `res_config_settings_views.xml` / `res_users_views.xml` | `crm` / `project` / `base` 的表單 |

### 升級後務必回歸的路徑

1. `-u dobtor_mail_activity` 無 ParseError（xpath 錨點失效會中斷升級，一次只噴一顆）
2. `--test-tags /dobtor_mail_activity`（78 個 Python 測試 + 2 支 tour）
3. 手動：週次選擇器 × 搜尋 facet 共存、合併後膠囊轉向、未指派清單的過期項目可見

## 版本資訊

- **版本**：18.0.1.8.0
- **相容性**：Odoo 18
- **授權**：LGPL-3

## 作者

Dobtor SI
https://www.dobtor.com

## 技術支援

如有問題，請聯繫 Dobtor SI 技術團隊。
