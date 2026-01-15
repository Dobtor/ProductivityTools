# 整合計劃 (Integration Plan)

## 1. project_todo 整合方案

### 1.1 整合策略概述

| 方面 | 策略 | 原因 |
|------|------|------|
| 主要模型 | 保持 mail.activity | 避免資料遷移複雜度，保持原有設計 |
| UI 組件 | 移植 project_todo | 善用 Odoo 18 原生優秀 UI |
| 選單 | 隱藏 project_todo | 統一使用 dobtor 入口 |
| 系統欄 | 整合覆蓋 | 統一待辦管理體驗 |

### 1.2 移植組件清單

| 組件 | 原始位置 | 目標位置 | 修改程度 |
|------|---------|---------|---------|
| todo_done_checkmark | project_todo/components | dobtor/components | 高（適配 mail.activity） |
| todo_chatter_panel | project_todo/components | dobtor/components | 低（通用性高） |
| activity_menu_patch | project_todo/web | dobtor/web | 高（覆蓋整合） |
| todo.scss | project_todo/scss | dobtor/scss | 中（命名空間） |

### 1.3 移植實施步驟

#### 步驟一：複製並重命名

```bash
# 建立目標目錄
mkdir -p static/src/components/activity_done_checkmark
mkdir -p static/src/components/activity_chatter_panel
mkdir -p static/src/web/activity

# 複製原始檔案
cp project_todo/static/src/components/todo_done_checkmark/* \
   dobtor/static/src/components/activity_done_checkmark/

cp project_todo/static/src/components/todo_chatter_panel/* \
   dobtor/static/src/components/activity_chatter_panel/

cp project_todo/static/src/web/activity/activity_menu_patch.js \
   dobtor/static/src/web/activity/
```

#### 步驟二：修改命名空間

```javascript
// activity_done_checkmark.js
// 變更前
export class TodoDoneCheckmark extends StateSelectionField {
    static template = "project_todo.TodoDoneCheckmark";
    ...
}
registry.category("fields").add("todo_done_checkmark", todoDoneCheckmark);

// 變更後
export class ActivityDoneCheckmark extends StateSelectionField {
    static template = "dobtor_mail_activity.ActivityDoneCheckmark";
    ...
}
registry.category("fields").add("activity_done_checkmark", activityDoneCheckmark);
```

#### 步驟三：適配 mail.activity

```javascript
// activity_done_checkmark.js
setup() {
    super.setup();
    onMounted(() => {
        // project_todo 使用 project.task.state (1_done)
        // dobtor 使用 mail.activity.activity_state (done)
        const fieldValue = this.props.record.data[this.props.name];
        this.notDoneState = fieldValue === 'done' ? 'active' : fieldValue;
    });
    onRendered(() => {
        if (!this.stateDone.notReloadState) {
            this.stateDone.isDone = this.props.record.data[this.props.name] === 'done';
        }
    });
}

async onDoneToggled(ev) {
    const currentValue = this.props.record.data[this.props.name];
    // 適配 mail.activity 的狀態值
    const newValue = currentValue !== 'done' ? 'done' : this.notDoneState;
    ...
}
```

### 1.4 隱藏 project_todo 選單

```xml
<!-- views/project_todo_override.xml -->
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- 方案一：完全隱藏 -->
    <record id="project_todo.menu_todo" model="ir.ui.menu">
        <field name="active" eval="False"/>
    </record>

    <!-- 方案二：限制群組（無人可見） -->
    <record id="project_todo.menu_todo" model="ir.ui.menu">
        <field name="groups_id" eval="[(6, 0, [])]"/>
    </record>

    <!-- 方案三：改為隱藏群組（保留但不顯示） -->
    <record id="project_todo.menu_todo" model="ir.ui.menu">
        <field name="groups_id" eval="[(6, 0, [ref('base.group_no_one')])]"/>
    </record>
</odoo>
```

**建議選擇方案一或方案三**，以便日後需要時可以恢復。

---

## 2. note 模組替代方案

### 2.1 替代範圍

| 原 note 模組功能 | dobtor 替代方案 | 說明 |
|-----------------|----------------|------|
| note.note 模型 | 自建 note.note | 保持相同 _name |
| note.stage 模型 | 自建 note.stage | 看板階段 |
| note.tag 模型 | 自建 note.tag | 支援階層 |
| 筆記視圖 | 自建視圖 | Kanban/List/Form |
| 選單 | 整合至 dobtor | 統一入口 |

### 2.2 模型差異對照

#### note.note

| 欄位 | 原 note 模組 | dobtor 版本 | 差異 |
|------|-------------|-------------|------|
| name | Text (計算) | Text (計算) | 相同 |
| user_id | Many2one | Many2one | 相同 |
| memo | Html | Html | 相同 |
| sequence | Integer | Integer | 相同 |
| stage_id | Many2one (計算) | Many2one (計算) | 相同 |
| stage_ids | Many2many | Many2many | 相同 |
| open | Boolean | Boolean | 相同 |
| date_done | Date | Date | 相同 |
| color | Integer | Integer | 相同 |
| tag_ids | Many2many | Many2many | 相同 |
| **active** | 無 | Boolean | **新增** |
| **main_tag_id** | 無 | Many2one | **新增** |
| **activity_ids** | 無 | One2many | **新增** |
| **activity_count** | 無 | Integer | **新增** |

#### note.tag

| 欄位 | 原 note 模組 | dobtor 版本 | 差異 |
|------|-------------|-------------|------|
| name | Char | Char | 相同 |
| color | Integer | Integer | 相同 |
| **parent_id** | 無 | Many2one | **新增（階層）** |
| **child_ids** | 無 | One2many | **新增** |
| **parent_path** | 無 | Char | **新增** |
| **active** | 無 | Boolean | **新增** |

### 2.3 資料遷移腳本

```python
# scripts/migrate_note_data.py
def migrate_note_data(env):
    """從舊版 note 模組遷移資料"""
    cr = env.cr

    # 檢查是否有舊資料
    cr.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'note_note_legacy'
        )
    """)
    if not cr.fetchone()[0]:
        return

    # 遷移 note.tag
    cr.execute("""
        INSERT INTO note_tag (name, color, active, create_uid, create_date, write_uid, write_date)
        SELECT name, color, true, create_uid, create_date, write_uid, write_date
        FROM note_tag_legacy
        WHERE NOT EXISTS (
            SELECT 1 FROM note_tag WHERE name = note_tag_legacy.name
        )
    """)

    # 遷移 note.stage
    cr.execute("""
        INSERT INTO note_stage (name, sequence, user_id, fold, create_uid, create_date, write_uid, write_date)
        SELECT name, sequence, user_id, fold, create_uid, create_date, write_uid, write_date
        FROM note_stage_legacy
    """)

    # 遷移 note.note
    cr.execute("""
        INSERT INTO note_note (name, user_id, memo, sequence, open, date_done, color, active,
                               create_uid, create_date, write_uid, write_date)
        SELECT name, user_id, memo, sequence, open, date_done, color, true,
               create_uid, create_date, write_uid, write_date
        FROM note_note_legacy
    """)

    # 遷移關聯表
    cr.execute("""
        INSERT INTO note_tags_rel (note_id, tag_id)
        SELECT n.id, t.id
        FROM note_tags_rel_legacy rel
        JOIN note_note_legacy n_old ON rel.note_id = n_old.id
        JOIN note_note n ON n.memo = n_old.memo AND n.user_id = n_old.user_id
        JOIN note_tag_legacy t_old ON rel.tag_id = t_old.id
        JOIN note_tag t ON t.name = t_old.name
    """)
```

---

## 3. 分階段實施計劃

### 3.1 第一階段：核心遷移（第 1-2 週）

#### 目標
- 完成所有 Python 程式碼遷移
- 建立新的 note 模型

#### 任務清單

| 任務 | 預估時間 | 負責人 | 狀態 |
|------|---------|--------|------|
| 建立 note.note 模型 | 4h | - | [ ] |
| 建立 note.stage 模型 | 2h | - | [ ] |
| 建立 note.tag 模型（含階層） | 3h | - | [ ] |
| 更新 mail.activity（Command API） | 4h | - | [ ] |
| 更新 weekly.report（Command API） | 2h | - | [ ] |
| 更新所有 wizards | 3h | - | [ ] |
| 更新 __manifest__.py | 1h | - | [ ] |
| 建立遷移腳本 | 4h | - | [ ] |

#### 驗收標準
- [ ] 模組可正常安裝
- [ ] 所有模型可正常 CRUD
- [ ] 無 Python 語法錯誤

### 3.2 第二階段：視圖遷移（第 2-3 週）

#### 目標
- 完成所有視圖語法更新
- 確保 UI 正常運作

#### 任務清單

| 任務 | 預估時間 | 負責人 | 狀態 |
|------|---------|--------|------|
| 更新 mail_activity_views.xml | 4h | - | [ ] |
| 更新 note_note_views.xml | 3h | - | [ ] |
| 新增 note_stage_views.xml | 2h | - | [ ] |
| 更新 note_tag_views.xml | 2h | - | [ ] |
| 更新 weekly_report_views.xml | 3h | - | [ ] |
| 更新 efficiency_views.xml | 2h | - | [ ] |
| 更新所有 wizard 視圖 | 3h | - | [ ] |
| 更新選單結構 | 2h | - | [ ] |
| 隱藏 project_todo 選單 | 1h | - | [ ] |

#### 驗收標準
- [ ] 所有視圖正常顯示
- [ ] 沒有 attrs 相關錯誤
- [ ] 沒有 tree -> list 相關錯誤
- [ ] 選單結構正確

### 3.3 第三階段：JavaScript 遷移（第 3-4 週）

#### 目標
- 完成所有 JS 檔案遷移至 ES6 模組
- 完成 OWL 2.0 遷移
- 移植 project_todo 組件

#### 任務清單

| 任務 | 預估時間 | 負責人 | 狀態 |
|------|---------|--------|------|
| 移植 activity_done_checkmark | 8h | - | [ ] |
| 移植 activity_chatter_panel | 4h | - | [ ] |
| 遷移 related_notes.js | 4h | - | [ ] |
| 遷移 activity_box.js | 3h | - | [ ] |
| 遷移 week_selector.js | 4h | - | [ ] |
| 遷移 activity_kanban.js | 4h | - | [ ] |
| 建立 activity_menu_patch.js | 4h | - | [ ] |
| 更新資源聲明 | 2h | - | [ ] |
| 整合測試 | 4h | - | [ ] |

#### 驗收標準
- [ ] 勾選完成功能正常
- [ ] Chatter 面板正常
- [ ] 關聯筆記顯示正常
- [ ] 週選擇器正常
- [ ] 系統欄整合正常
- [ ] 快捷鍵正常

### 3.4 第四階段：安全性與測試（第 4-5 週）

#### 目標
- 完成安全性配置
- 完成測試覆蓋

#### 任務清單

| 任務 | 預估時間 | 負責人 | 狀態 |
|------|---------|--------|------|
| 更新 security.xml | 2h | - | [ ] |
| 更新 ir.model.access.csv | 2h | - | [ ] |
| 新增記錄規則 | 3h | - | [ ] |
| 編寫單元測試 | 8h | - | [ ] |
| 編寫整合測試 | 6h | - | [ ] |
| 編寫 UI 測試 | 6h | - | [ ] |
| 執行完整測試 | 4h | - | [ ] |
| 修復問題 | 8h | - | [ ] |

#### 驗收標準
- [ ] 權限控制正確
- [ ] 測試覆蓋率 > 80%
- [ ] 所有測試通過

### 3.5 第五階段：最終整合（第 5-6 週）

#### 目標
- 完成最終整合測試
- 完成文件更新
- 準備發布

#### 任務清單

| 任務 | 預估時間 | 負責人 | 狀態 |
|------|---------|--------|------|
| 完整功能測試 | 8h | - | [ ] |
| 效能測試 | 4h | - | [ ] |
| 安全性審查 | 4h | - | [ ] |
| 更新翻譯檔 | 4h | - | [ ] |
| 更新 README | 2h | - | [ ] |
| 建立變更日誌 | 2h | - | [ ] |
| 準備發布版本 | 2h | - | [ ] |

#### 驗收標準
- [ ] 所有功能正常
- [ ] 效能達標
- [ ] 文件完整
- [ ] 可發布

---

## 4. 風險評估

### 4.1 技術風險

| 風險 | 影響 | 機率 | 緩解措施 |
|------|------|------|---------|
| note 模組資料遷移失敗 | 高 | 中 | 建立完整備份和回滾機制 |
| OWL 2.0 遷移問題 | 中 | 高 | 漸進式遷移，保留舊版相容 |
| project_todo 衝突 | 中 | 低 | 明確隱藏策略，測試驗證 |
| 效能退化 | 中 | 中 | 效能測試，優化關鍵路徑 |

### 4.2 時程風險

| 風險 | 影響 | 機率 | 緩解措施 |
|------|------|------|---------|
| JavaScript 遷移延誤 | 高 | 高 | 優先處理核心組件 |
| 測試不足 | 中 | 中 | 建立測試優先文化 |
| 需求變更 | 中 | 低 | 明確範圍，變更管理 |

### 4.3 依賴風險

| 風險 | 影響 | 機率 | 緩解措施 |
|------|------|------|---------|
| Odoo 18 API 變更 | 高 | 低 | 追蹤官方文件 |
| 第三方模組衝突 | 中 | 中 | 相容性測試 |

---

## 5. 回滾計劃

### 5.1 回滾觸發條件

- 關鍵功能無法正常運作
- 資料遺失或損毀
- 嚴重效能問題
- 安全性漏洞

### 5.2 回滾步驟

```bash
# 步驟 1：停止服務
sudo systemctl stop odoo

# 步驟 2：還原資料庫
pg_restore -d odoo_db backup_before_upgrade.dump

# 步驟 3：還原模組
git checkout pre-upgrade-tag

# 步驟 4：重啟服務
sudo systemctl start odoo

# 步驟 5：驗證
./odoo-bin -c odoo.conf --test-enable -u dobtor_mail_activity
```

### 5.3 備份策略

```bash
# 升級前完整備份
pg_dump -Fc odoo_db > backup_$(date +%Y%m%d_%H%M%S).dump

# 模組備份
tar -czvf dobtor_mail_activity_$(date +%Y%m%d).tar.gz dobtor_mail_activity/
```

---

## 6. 溝通計劃

### 6.1 相關人員

| 角色 | 姓名 | 職責 |
|------|------|------|
| 專案經理 | - | 進度追蹤、資源協調 |
| 開發主管 | - | 技術決策、程式碼審查 |
| 開發人員 | - | 實作、測試 |
| QA | - | 測試、驗收 |
| 用戶代表 | - | 需求確認、驗收 |

### 6.2 溝通頻率

| 會議類型 | 頻率 | 參與者 |
|---------|------|--------|
| 每日站會 | 每日 | 開發團隊 |
| 週進度會議 | 每週 | 全體 |
| 技術討論 | 需要時 | 開發人員 |
| 階段驗收 | 每階段 | 全體 |

---

## 7. 成功標準

### 7.1 功能標準

- [ ] 所有 Odoo 14 功能在 Odoo 18 正常運作
- [ ] project_todo UI 組件成功整合
- [ ] note 模組功能完整替代
- [ ] 無功能退化

### 7.2 效能標準

- [ ] 頁面載入時間 < 2 秒
- [ ] Kanban 拖放響應 < 500ms
- [ ] 大量資料（>1000筆）操作正常

### 7.3 品質標準

- [ ] 測試覆蓋率 > 80%
- [ ] 無嚴重 bug
- [ ] 程式碼符合 Odoo 18 規範

---

**文件版本**: 1.0.0
**建立日期**: 2026-01-15
