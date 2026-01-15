# 遷移檢查清單 (Migration Checklist)

## 1. ORM API 變更清單

### 1.1 Command API 替換

| 位置 | Odoo 14 語法 | Odoo 18 語法 | 狀態 |
|------|-------------|-------------|------|
| mail_activity.py L365 | `[(6, 0, activities.ids)]` | `[Command.set(activities.ids)]` | [ ] |
| mail_activity.py L401 | `[(6, 0, future_activities.ids)]` | `[Command.set(future_activities.ids)]` | [ ] |
| mail_activity.py L412 | `[(6, 0, unscheduled.ids)]` | `[Command.set(unscheduled.ids)]` | [ ] |
| mail_activity.py L650 | `[(4, att_id) for att_id in ...]` | `[Command.link(att_id) for ...]` | [ ] |
| mail_activity.py L999-1001 | `[(4, partner.id)]` | `[Command.link(partner.id)]` | [ ] |
| weekly_report.py | 所有 Many2many 操作 | Command API | [ ] |
| wizards/*.py | 所有關聯操作 | Command API | [ ] |

### 1.2 導入 Command

```python
# 在所有使用 Command 的檔案開頭加入
from odoo import Command
```

**需要修改的檔案**:
- [ ] models/mail_activity.py
- [ ] models/weekly_report.py
- [ ] models/note_note.py
- [ ] wizards/mail_activity_done_wizard.py
- [ ] wizards/mail_activity_reassign_wizard.py

### 1.3 其他 ORM 方法變更

| Odoo 14 | Odoo 18 | 說明 | 狀態 |
|---------|---------|------|------|
| `self.env.ref('xml_id').id` | `self.env.ref('xml_id').id` | 無變更 | [x] |
| `xmlid_to_res_id()` | `_xmlid_to_res_id()` | 方法名稱 | [ ] |
| `fields.Date.from_string()` | `fields.Date.from_string()` | 無變更 | [x] |
| `sudo().create()` | `sudo().create()` | 無變更 | [x] |
| `with_context()` | `with_context()` | 無變更 | [x] |

### 1.4 棄用方法檢查

| 棄用方法 | 替代方案 | 狀態 |
|---------|---------|------|
| `@api.multi` | 移除（Odoo 13+ 預設） | [ ] |
| `@api.one` | 使用 `ensure_one()` | [ ] |
| `_register_hook()` | `_register_hook()` | [x] |

---

## 2. 視圖語法變更清單

### 2.1 attrs 屬性替換

| 檔案 | 行號 | Odoo 14 | Odoo 18 | 狀態 |
|------|------|---------|---------|------|
| mail_activity_views.xml | 25-28 | `attrs="{'invisible': ...}"` | `invisible="..."` | [ ] |
| mail_activity_views.xml | 52-59 | `attrs="{'invisible': ...}"` | `invisible="..."` | [ ] |
| mail_activity_views.xml | 74-79 | `attrs="{'invisible': ...}"` | `invisible="..."` | [ ] |
| note_note_views.xml | 全部 | `attrs` | 直接屬性 | [ ] |
| weekly_report_views.xml | 全部 | `attrs` | 直接屬性 | [ ] |
| wizards/*.xml | 全部 | `attrs` | 直接屬性 | [ ] |

### 2.2 視圖類型標籤

| 檔案 | Odoo 14 | Odoo 18 | 狀態 |
|------|---------|---------|------|
| 所有 list 視圖 | `<tree>` | `<list>` | [ ] |
| view_mode 屬性 | `tree` | `list` | [ ] |

**需要檢查的檔案**:
- [ ] views/mail_activity_views.xml
- [ ] views/note_note_views.xml
- [ ] views/note_tag_views.xml
- [ ] views/weekly_report_views.xml
- [ ] views/efficiency_views.xml
- [ ] views/weekly_schedule_config_views.xml
- [ ] wizards/*.xml

### 2.3 states 屬性替換

```xml
<!-- Odoo 14 -->
<button states="draft" string="確認"/>

<!-- Odoo 18 -->
<button invisible="state != 'draft'" string="確認"/>
```

### 2.4 widget 變更

| Odoo 14 Widget | Odoo 18 Widget | 說明 | 狀態 |
|---------------|---------------|------|------|
| `statusbar_visible` | `options="{'clickable': '1'}"` | 狀態欄 | [ ] |
| `handle` | `handle` | 無變更 | [x] |
| `many2one_avatar_user` | `many2one_avatar_user` | 無變更 | [x] |
| `float_time` | `float_time` | 無變更 | [x] |
| `remaining_days` | `remaining_days` | 無變更 | [x] |

### 2.5 CSS 類別變更 (Bootstrap 5)

| Bootstrap 4 | Bootstrap 5 | 狀態 |
|------------|-------------|------|
| `ml-*` | `ms-*` | [ ] |
| `mr-*` | `me-*` | [ ] |
| `pl-*` | `ps-*` | [ ] |
| `pr-*` | `pe-*` | [ ] |
| `text-left` | `text-start` | [ ] |
| `text-right` | `text-end` | [ ] |
| `float-left` | `float-start` | [ ] |
| `float-right` | `float-end` | [ ] |

---

## 3. JavaScript 變更清單

### 3.1 模組系統遷移

| 檔案 | Odoo 14 | Odoo 18 | 狀態 |
|------|---------|---------|------|
| activity.js | `odoo.define()` | ES6 模組 | [ ] |
| related_notes.js | `odoo.define()` | ES6 模組 | [ ] |
| activity_box.js | `odoo.define()` | ES6 模組 | [ ] |
| chatter.js | `odoo.define()` | ES6 模組 | [ ] |
| message.js | `odoo.define()` | ES6 模組 | [ ] |
| week_selector.js | `odoo.define()` | ES6 模組 | [ ] |
| activity_kanban.js | `odoo.define()` | ES6 模組 | [ ] |

### 3.2 OWL 版本遷移

| OWL 1.x | OWL 2.x | 說明 | 狀態 |
|---------|---------|------|------|
| `owl.Component` | `@odoo/owl` | 導入路徑 | [ ] |
| `useState` | `useState` | 無變更 | [x] |
| `useRef` | `useRef` | 無變更 | [x] |
| `mounted()` | `onMounted()` | 生命週期 | [ ] |
| `willStart()` | `onWillStart()` | 生命週期 | [ ] |
| `willUnmount()` | `onWillUnmount()` | 生命週期 | [ ] |

### 3.3 Patch 語法

```javascript
// Odoo 14
patch(Activity.prototype, 'patch_name', { ... });

// Odoo 18
import { patch } from "@web/core/utils/patch";
patch(Activity.prototype, { ... });
```

### 3.4 服務使用

| Odoo 14 | Odoo 18 | 狀態 |
|---------|---------|------|
| `this.env.services.rpc()` | `this.orm.call()` | [ ] |
| `this.env.bus.trigger()` | `this.env.bus.trigger()` | [x] |
| `this.env.services.action` | `useService('action')` | [ ] |

### 3.5 資源聲明遷移

```python
# Odoo 14 __manifest__.py
'qweb': [
    'static/src/components/related_notes/related_notes.xml',
    'static/src/components/activity_box/activity_box.xml',
    'static/src/components/activity/activity.xml',
    'static/src/components/chatter/chatter.xml',
],

# Odoo 18 __manifest__.py
'assets': {
    'web.assets_backend': [
        'dobtor_mail_activity/static/src/components/**/*',
        'dobtor_mail_activity/static/src/views/**/*',
        'dobtor_mail_activity/static/src/web/**/*',
        'dobtor_mail_activity/static/src/scss/**/*',
    ],
},
```

---

## 4. __manifest__.py 變更

### 4.1 依賴變更

```python
# Odoo 14
'depends': [
    'mail',
    'note',           # 移除
    'hr_timesheet',
    'hr',
    'project',
    'crm',
],

# Odoo 18
'depends': [
    'mail',
    # 'note' - 自行實現
    'hr_timesheet',
    'hr',
    'project',
    'crm',
],
```

### 4.2 資源聲明

```python
# Odoo 14
'qweb': [
    'static/src/components/related_notes/related_notes.xml',
    ...
],

# Odoo 18
'assets': {
    'web.assets_backend': [
        'dobtor_mail_activity/static/src/**/*',
    ],
    'web.assets_unit_tests': [
        'dobtor_mail_activity/static/tests/**/*',
    ],
},
```

### 4.3 其他變更

| 項目 | Odoo 14 | Odoo 18 | 狀態 |
|------|---------|---------|------|
| version | 14.0.2.0.0 | 18.0.1.0.0 | [ ] |
| license | LGPL-3 | LGPL-3 | [x] |
| application | True | True | [x] |

---

## 5. 測試計劃

### 5.1 單元測試

| 測試項目 | 測試檔案 | 狀態 |
|---------|---------|------|
| mail.activity CRUD | tests/test_mail_activity.py | [ ] |
| note.note CRUD | tests/test_note_note.py | [ ] |
| weekly.report 產生 | tests/test_weekly_report.py | [ ] |
| 效率指標計算 | tests/test_efficiency_metrics.py | [ ] |
| Wizard 操作 | tests/test_wizards.py | [ ] |

### 5.2 整合測試

| 測試項目 | 測試檔案 | 狀態 |
|---------|---------|------|
| 工時表建立 | tests/test_timesheet_integration.py | [ ] |
| 權限規則 | tests/test_access_rights.py | [ ] |
| 週轉換定時任務 | tests/test_cron_jobs.py | [ ] |

### 5.3 UI 測試

| 測試項目 | 測試檔案 | 狀態 |
|---------|---------|------|
| Kanban 拖放 | static/tests/tours/test_kanban_drag.js | [ ] |
| 完成 wizard | static/tests/tours/test_done_wizard.js | [ ] |
| 週選擇器 | static/tests/tours/test_week_selector.js | [ ] |

### 5.4 測試資料

```python
# tests/common.py
class TestCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_demo = cls.env.ref('base.user_demo')
        cls.user_admin = cls.env.ref('base.user_admin')
        cls.activity_type = cls.env.ref('mail.mail_activity_data_todo')
        cls.project = cls.env['project.project'].create({
            'name': 'Test Project',
            'allow_timesheets': True,
        })
```

---

## 6. 遷移腳本

### 6.1 pre_init_hook

```python
def pre_init_hook(env):
    """安裝前執行：建立必要的資料表結構"""
    cr = env.cr

    # 檢查是否存在 note_note 表（可能來自舊版 note 模組）
    cr.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'note_note'
        )
    """)
    if cr.fetchone()[0]:
        # 備份舊資料
        cr.execute("""
            CREATE TABLE IF NOT EXISTS note_note_backup
            AS SELECT * FROM note_note
        """)
```

### 6.2 post_init_hook

```python
def post_init_hook(env):
    """安裝後執行：資料遷移和初始化"""
    # 遷移舊的 note 資料（如果有）
    cr = env.cr
    cr.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'note_note_backup'
        )
    """)
    if cr.fetchone()[0]:
        _logger.info('Migrating note_note data from backup...')
        # 執行資料遷移邏輯

    # 建立預設的筆記階段
    env['note.stage'].create([
        {'name': '新建', 'sequence': 10, 'user_id': env.ref('base.user_admin').id},
        {'name': '進行中', 'sequence': 20, 'user_id': env.ref('base.user_admin').id},
        {'name': '完成', 'sequence': 30, 'user_id': env.ref('base.user_admin').id, 'fold': True},
    ])
```

### 6.3 uninstall_hook

```python
def uninstall_hook(env):
    """解除安裝時執行：清理資料"""
    # 移除自定義的 note 資料（可選）
    pass
```

---

## 7. 遷移執行順序

### 7.1 階段一：基礎遷移

1. [ ] 更新 `__manifest__.py` 版本和依賴
2. [ ] 建立 note.note, note.stage, note.tag 模型
3. [ ] 更新所有 ORM API（Command API）
4. [ ] 更新所有視圖語法（attrs -> 直接屬性）

### 7.2 階段二：JavaScript 遷移

1. [ ] 將所有 JS 檔案轉換為 ES6 模組
2. [ ] 更新 OWL 語法至 2.0
3. [ ] 更新 patch 語法
4. [ ] 更新資源聲明

### 7.3 階段三：測試和修復

1. [ ] 執行所有單元測試
2. [ ] 執行整合測試
3. [ ] 執行 UI 測試
4. [ ] 修復發現的問題

### 7.4 階段四：最終確認

1. [ ] 完整功能測試
2. [ ] 效能測試
3. [ ] 安全性檢查
4. [ ] 文件更新

---

## 8. 驗證清單

### 8.1 功能驗證

- [ ] 待辦建立正常
- [ ] 待辦指派正常
- [ ] 待辦完成正常
- [ ] 待辦延期正常
- [ ] 待辦轉移正常
- [ ] 筆記本 CRUD 正常
- [ ] 週報告產生正常
- [ ] 效率指標計算正常
- [ ] 工時表建立正常
- [ ] 權限控制正常

### 8.2 UI 驗證

- [ ] Kanban 視圖正常顯示
- [ ] List 視圖正常顯示
- [ ] Form 視圖正常顯示
- [ ] 拖放功能正常
- [ ] 週選擇器正常
- [ ] 勾選完成正常
- [ ] 系統欄整合正常

### 8.3 效能驗證

- [ ] 大量資料載入正常（>1000筆）
- [ ] 計算欄位效能正常
- [ ] 搜尋功能效能正常

---

**文件版本**: 1.0.0
**建立日期**: 2026-01-15
