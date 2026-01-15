# dobtor_mail_activity 改版規格計劃書

## Odoo 14 -> Odoo 18 升級規格

**版本資訊**
| 項目 | Odoo 14 版本 | Odoo 18 版本 |
|------|-------------|-------------|
| 模組版本 | 14.0.2.0.0 | 18.0.1.0.0 |
| 模組名稱 | dobtor_mail_activity | dobtor_mail_activity |
| 技術名稱 | 生產力工具 | 生產力工具 |

---

## 1. 模組概述

### 1.1 功能定位

dobtor_mail_activity 是一個整合 mail.activity、筆記本和週報告的完整生產力管理系統。主要功能包括：

- **待辦管理**: 基於 mail.activity 的待辦事項系統
- **筆記本功能**: 替代 Odoo 18 已移除的 note 模組
- **週報告**: 週計畫與執行回顧
- **效率分析**: 個人/團隊效率指標
- **工時追蹤**: 與 hr_timesheet 整合

### 1.2 設計理念差異

| 方面 | Odoo 14 dobtor | Odoo 18 project_todo | dobtor_mail_activity (Odoo 18) |
|------|---------------|---------------------|--------------------------------|
| 主要模型 | mail.activity | project.task (project_id=False) | mail.activity |
| 筆記本 | 依賴 note 模組 | 無筆記本功能 | 自建 note.note/stage/tag |
| 排程 | 週天排程系統 | 個人階段 | 保留週天排程 + 多週預排 |
| 工時 | hr_timesheet 整合 | 無 | hr_timesheet 整合 |

---

## 2. 依賴變更說明

### 2.1 Odoo 14 原始依賴

```python
'depends': [
    'mail',
    'note',           # Odoo 18 已移除！
    'hr_timesheet',
    'hr',
    'project',
    'crm',
]
```

### 2.2 Odoo 18 新依賴

```python
'depends': [
    'mail',
    'hr_timesheet',
    'hr',
    'project',
    'crm',
    # 'note' 移除 - 自行實現
    # 可選：'project_todo' - 用於整合 UI 組件
]
```

### 2.3 note 模組替代方案

Odoo 18 已移除 note 模組，需自行實現以下模型：

| 原 note 模組模型 | 替代方案 |
|-----------------|---------|
| note.note | 自建 note.note |
| note.stage | 自建 note.stage |
| note.tag | 自建 note.tag |

---

## 3. 完整功能清單對照

### 3.1 核心待辦功能

| 功能 | Odoo 14 | Odoo 18 | 變更說明 |
|------|---------|---------|---------|
| 待辦建立 | mail.activity.create | mail.activity.create | 無變更 |
| 待辦指派 | user_id 欄位 | user_id 欄位 | 改為非必填 |
| 待辦完成 | 封存機制 | 封存機制 | 無變更 |
| 待辦取消 | action_cancel | action_cancel | 無變更 |
| 待辦恢復 | action_restore | action_restore | 無變更 |
| 待辦轉移 | wizard | wizard | 無變更 |

### 3.2 排程功能

| 功能 | Odoo 14 | Odoo 18 | 變更說明 |
|------|---------|---------|---------|
| 週天排程 | schedule_status | schedule_status | 無變更 |
| 計畫日期 | planned_date | planned_date | 無變更 |
| 預排日期 | scheduled_date | scheduled_date | 無變更 |
| 週次計算 | schedule_week | schedule_week | 支援上週~第四週 |
| 延期功能 | wizard + history | wizard + history | 無變更 |

### 3.3 筆記本功能

| 功能 | Odoo 14 | Odoo 18 | 變更說明 |
|------|---------|---------|---------|
| 筆記模型 | 繼承 note.note | 自建 note.note | 需自行實現 |
| 標籤模型 | 繼承 note.tag | 自建 note.tag | 支援階層 |
| 階段模型 | 使用 note.stage | 自建 note.stage | 需自行實現 |
| 封存機制 | active 欄位 | active 欄位 | 無變更 |
| 關聯待辦 | activity_ids | activity_ids | 無變更 |

### 3.4 週報告功能

| 功能 | Odoo 14 | Odoo 18 | 變更說明 |
|------|---------|---------|---------|
| 週報告模型 | weekly.report | weekly.report | 無變更 |
| 計畫快照 | snapshot.line | snapshot.line | 無變更 |
| 執行回顧 | review.line | review.line | 無變更 |
| 自動排程 | weekly.schedule.config | weekly.schedule.config | 無變更 |

### 3.5 效率分析功能

| 功能 | Odoo 14 | Odoo 18 | 變更說明 |
|------|---------|---------|---------|
| 效率指標 | activity.efficiency.metrics | activity.efficiency.metrics | 無變更 |
| 定時計算 | cron | cron | 無變更 |
| 儀表板 | 視圖 | 視圖 | 需更新視圖語法 |

### 3.6 工時追蹤功能

| 功能 | Odoo 14 | Odoo 18 | 變更說明 |
|------|---------|---------|---------|
| 預估工時 | estimated_hours | estimated_hours | 無變更 |
| 實際工時 | actual_hours | actual_hours | 無變更 |
| 工時表記錄 | timesheet_id | timesheet_id | 無變更 |
| 自動建立 | _create_timesheet_entry | _create_timesheet_entry | 無變更 |

---

## 4. 與 project_todo 的整合策略

### 4.1 設計決策

| 決策項目 | 選擇 | 原因 |
|---------|------|------|
| 主要模型 | mail.activity | 保持原有設計，避免資料遷移複雜度 |
| 筆記本 | 自建模型 | note 模組已移除，需自行實現 |
| UI 組件 | 移植 project_todo | 善用 Odoo 18 原生 UI 設計 |
| 系統欄 | 整合 dobtor 入口 | 統一使用體驗 |

### 4.2 從 project_todo 移植的功能

| 功能 | 說明 | 整合方式 |
|------|------|---------|
| todo_done_checkmark | 勾選完成 widget | 調整適配 mail.activity |
| todo_chatter_panel | 側邊評論面板 | 移植並調整 |
| activity_menu_patch | 系統欄分離 | 覆蓋/整合 |
| 快捷鍵 Alt+Shift+T | 快速建立待辦 | 保留並調整目標 |

### 4.3 覆蓋 project_todo 的處理

```xml
<!-- 隱藏 project_todo 選單 -->
<record id="project_todo.menu_todo" model="ir.ui.menu">
    <field name="active" eval="False"/>
</record>

<!-- 或限制群組 -->
<record id="project_todo.menu_todo" model="ir.ui.menu">
    <field name="groups_id" eval="[(6, 0, [])]"/>
</record>
```

---

## 5. 資料庫遷移注意事項

### 5.1 新增模型

| 模型 | 資料表 | 說明 |
|------|--------|------|
| note.note | note_note | 替代原 note 模組 |
| note.stage | note_stage | 筆記階段 |
| note.tag | note_tag | 筆記標籤（支援階層） |

### 5.2 欄位變更

| 模型 | 欄位 | 變更類型 | 說明 |
|------|------|---------|------|
| mail.activity | user_id | 修改 | required=False |
| mail.activity | schedule_week | 新增 | 支援更多週次 |
| mail.activity | activity_state | 新增 | 自定義狀態 |

### 5.3 遷移腳本需求

```python
# pre_init_hook: 建立 note 相關資料表
def pre_init_hook(env):
    # 建立 note_note 資料表（如果不存在）
    env.cr.execute("""
        CREATE TABLE IF NOT EXISTS note_note (
            id SERIAL PRIMARY KEY,
            ...
        )
    """)

# post_init_hook: 資料遷移
def post_init_hook(env):
    # 遷移既有資料（如果有的話）
    pass
```

---

## 6. 技術架構變更摘要

### 6.1 ORM API 變更

| Odoo 14 | Odoo 18 | 說明 |
|---------|---------|------|
| `(0, 0, vals)` | `Command.create(vals)` | 建立關聯記錄 |
| `(1, id, vals)` | `Command.update(id, vals)` | 更新關聯記錄 |
| `(4, id)` | `Command.link(id)` | 新增關聯 |
| `(6, 0, ids)` | `Command.set(ids)` | 設定關聯 |
| `xmlid_to_res_id` | `_xmlid_to_res_id` | 方法名稱變更 |

### 6.2 視圖語法變更

| Odoo 14 | Odoo 18 | 說明 |
|---------|---------|------|
| `attrs="{'invisible': ...}"` | `invisible="..."` | 簡化語法 |
| `states="draft"` | `invisible="state != 'draft'"` | 取代 states |
| `tree` | `list` | 視圖類型名稱 |

### 6.3 JavaScript 架構變更

| Odoo 14 | Odoo 18 | 說明 |
|---------|---------|------|
| OWL 1.x | OWL 2.x | 組件架構升級 |
| `odoo.define()` | ES6 模組 | 模組系統 |
| `patch(Class)` | `patch(Class.prototype)` | patch 語法 |

---

## 7. 檔案結構

```
dobtor_mail_activity/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── mail_activity.py
│   ├── mail_activity_type.py
│   ├── mail_activity_assignment_history.py
│   ├── mail_activity_postpone_history.py
│   ├── mail_activity_transfer_config.py
│   ├── mail_message.py
│   ├── note_note.py           # 自建（替代 note 模組）
│   ├── note_stage.py          # 新增
│   ├── note_tag.py            # 自建（支援階層）
│   ├── weekly_report.py
│   ├── weekly_schedule_config.py
│   ├── activity_efficiency_metrics.py
│   ├── res_users.py
│   └── res_company.py
├── wizards/
│   ├── __init__.py
│   ├── mail_activity_done_wizard.py
│   ├── mail_activity_postpone_wizard.py
│   ├── mail_activity_transfer_wizard.py
│   ├── mail_activity_from_message_wizard.py
│   └── mail_activity_reassign_wizard.py
├── views/
│   ├── mail_activity_views.xml
│   ├── mail_activity_type_views.xml
│   ├── mail_activity_schedule_views.xml
│   ├── mail_activity_transfer_config_views.xml
│   ├── note_note_views.xml
│   ├── note_stage_views.xml   # 新增
│   ├── note_tag_views.xml
│   ├── weekly_report_views.xml
│   ├── weekly_schedule_config_views.xml
│   ├── efficiency_views.xml
│   ├── res_users_views.xml
│   ├── res_company_views.xml
│   └── menu_views.xml
├── security/
│   ├── security.xml
│   └── ir.model.access.csv
├── data/
│   ├── mail_activity_data.xml
│   ├── mail_activity_transfer_config_data.xml
│   └── cron_data.xml
├── static/
│   └── src/
│       ├── components/
│       │   ├── activity_done_checkmark/      # 移植自 project_todo
│       │   ├── activity_chatter_panel/       # 移植自 project_todo
│       │   ├── related_notes/
│       │   └── activity_box/
│       ├── views/
│       │   ├── activity_list/
│       │   └── activity_form/
│       ├── web/
│       │   └── activity/
│       │       └── activity_menu_patch.js
│       └── scss/
│           ├── activity.scss
│           └── week_selector.scss
├── i18n/
│   └── zh_TW.po
└── docs/
    ├── 01_MODEL_SPECIFICATION.md
    ├── 02_VIEW_SPECIFICATION.md
    ├── 03_JAVASCRIPT_SPECIFICATION.md
    ├── 04_SECURITY_SPECIFICATION.md
    ├── 05_MIGRATION_CHECKLIST.md
    └── 06_INTEGRATION_PLAN.md
```

---

## 8. 開發優先順序

### 階段一：核心功能（必要）
1. 自建 note.note, note.stage, note.tag 模型
2. 更新 mail.activity 擴展
3. 更新所有視圖語法至 Odoo 18
4. 更新 ORM API（Command API）

### 階段二：UI 整合（重要）
1. 移植 todo_done_checkmark widget
2. 移植 todo_chatter_panel widget
3. 更新 JavaScript 至 OWL 2.0
4. 整合系統欄活動選單

### 階段三：進階功能（增強）
1. 效率分析儀表板
2. 週報告自動化
3. 工時追蹤整合
4. 多語言支援

---

## 9. 風險評估

| 風險項目 | 影響程度 | 機率 | 緩解措施 |
|---------|---------|------|---------|
| note 模組資料遷移 | 高 | 中 | 提供遷移腳本 |
| JavaScript 架構變更 | 中 | 高 | 漸進式重構 |
| project_todo 衝突 | 中 | 中 | 明確隱藏/覆蓋策略 |
| 視圖語法變更 | 低 | 高 | 系統性更新 |

---

## 10. 參考文件

- [Odoo 18 Release Notes](https://www.odoo.com/documentation/18.0/developer/reference/changelog.html)
- [OWL 2.0 Migration Guide](https://github.com/odoo/owl/blob/master/doc/miscellaneous/MIGRATION_GUIDE.md)
- [Odoo 18 JavaScript Reference](https://www.odoo.com/documentation/18.0/developer/reference/frontend/framework_overview.html)

---

**文件版本**: 1.0.0
**建立日期**: 2026-01-15
**作者**: Dobtor SI
