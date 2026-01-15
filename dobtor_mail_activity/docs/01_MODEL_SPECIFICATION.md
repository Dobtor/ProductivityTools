# 模型規格 (Model Specification)

## 1. 模型總覽

### 1.1 核心模型清單

| 模型名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 待辦事項 | mail.activity | 繼承 | 擴展官方待辦模型 |
| 待辦類型 | mail.activity.type | 繼承 | 擴展官方待辦類型 |
| 指派歷史 | mail.activity.assignment.history | 新建 | 記錄指派變更 |
| 延期歷史 | mail.activity.postpone.history | 新建 | 記錄延期操作 |
| 轉移配置 | mail.activity.transfer.config | 新建 | 配置允許轉移的模型 |
| 筆記本 | note.note | 新建 | 替代原 note 模組 |
| 筆記階段 | note.stage | 新建 | 筆記看板階段 |
| 筆記標籤 | note.tag | 新建 | 階層式標籤 |
| 週報告 | weekly.report | 新建 | 週計畫與回顧 |
| 計畫快照 | weekly.report.snapshot.line | 新建 | 週計畫凍結記錄 |
| 執行回顧 | weekly.report.review.line | 新建 | 週執行比對 |
| 效率指標 | activity.efficiency.metrics | 新建 | 效率統計 |
| 週報排程配置 | weekly.schedule.config | 新建 | 自動排程設定 |

### 1.2 模型關係圖

```
                    +------------------+
                    |   res.users      |
                    +--------+---------+
                             |
          +------------------+------------------+
          |                  |                  |
    +-----v------+     +-----v------+     +-----v------+
    |mail.activity|     |weekly.report|     |note.note   |
    +-----+------+     +-----+------+     +-----+------+
          |                  |                  |
    +-----+-----+      +-----+-----+      +-----+-----+
    |           |      |           |      |           |
+---v---+  +---v---+  +---v---+  +---v---+  +---v---+
|assign |  |post-  |  |snap-  |  |review |  |note.  |
|history|  |pone   |  |shot   |  |line   |  |tag    |
+-------+  +-------+  +-------+  +-------+  +-------+
```

---

## 2. mail.activity 擴展

### 2.1 欄位定義

#### 基本欄位修改

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 預設值 | 說明 |
|---------|---------|------|------|--------|------|
| 指派給 | user_id | Many2one | 否 | False | **修改**: 改為非必填 |
| 啟用 | active | Boolean | - | True | 封存控制 |
| 完成時間 | done_date | Datetime | - | - | 完成時自動填入 |
| 取消時間 | cancel_date | Datetime | - | - | 取消時自動填入 |
| 待辦狀態 | activity_state | Selection | - | - | 計算欄位 |

#### 關聯欄位

| 欄位名稱 | 技術名稱 | 類型 | 關聯模型 | 說明 |
|---------|---------|------|---------|------|
| 關聯筆記 | note_id | Many2one | note.note | 待辦關聯的筆記本 |
| 目標文件 | target_ref | Reference | 動態 | 建立時選擇關聯文件 |
| 來源訊息 | source_message_id | Many2one | mail.message | 從訊息建立時記錄 |
| 指派歷史 | assignment_history_ids | One2many | mail.activity.assignment.history | 指派變更記錄 |
| 延期歷史 | postpone_history_ids | One2many | mail.activity.postpone.history | 延期記錄 |
| 工時表記錄 | timesheet_id | Many2one | account.analytic.line | 完成後的工時記錄 |

#### 排程欄位

| 欄位名稱 | 技術名稱 | 類型 | 選項 | 說明 |
|---------|---------|------|------|------|
| 排程狀態 | schedule_status | Selection | waiting/monday~sunday | 週天排程 |
| 計畫日期 | planned_date | Date | - | 排入本週的日期 |
| 預排日期 | scheduled_date | Date | - | 下週預排日期 |
| 排程週次 | schedule_week | Selection | week_prev~future | 計算欄位 |
| 週次編號 | schedule_week_number | Integer | - | 計算欄位 |
| 來源標記 | schedule_origin | Selection | planned/inserted/postponed/transferred | 來源追蹤 |
| 原始預排週次 | original_schedule_week | Char | - | 格式: 2026-W02 |

#### 優先級欄位

| 欄位名稱 | 技術名稱 | 類型 | 選項 | 預設值 |
|---------|---------|------|------|--------|
| 時間性 | urgency | Selection | urgent/standard/flexible | standard |
| 重要性 | importance | Selection | important/normal | normal |

#### 工時欄位

| 欄位名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 預估工時 | estimated_hours | Float | 預估執行時間（小時） |
| 執行工時 | actual_hours | Float | 實際執行時間（小時） |
| 完成回饋 | feedback | Text | 完成時的回饋說明 |

#### 關聯顯示欄位（計算）

| 欄位名稱 | 技術名稱 | 類型 | 關聯模型 | 說明 |
|---------|---------|------|---------|------|
| 客戶 | partner_id | Many2one | res.partner | 從關聯文件計算 |
| 專案 | project_id | Many2one | project.project | 從關聯文件計算 |
| CRM 商機 | crm_lead_id | Many2one | crm.lead | 從關聯文件計算 |
| 文件名稱 | res_name | Char | - | 關聯文件顯示名稱 |

#### 轉移追蹤欄位

| 欄位名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 轉移來源模型 | transferred_from_model | Char | 原始模型名稱 |
| 轉移來源 ID | transferred_from_id | Integer | 原始記錄 ID |
| 轉移來源名稱 | transferred_from_name | Char | 計算欄位 |
| 已轉移 | is_transferred | Boolean | 計算欄位 |

### 2.2 計算欄位邏輯

#### _compute_activity_state
```python
@api.depends('active', 'done_date', 'cancel_date')
def _compute_activity_state(self):
    for activity in self:
        if activity.cancel_date:
            activity.activity_state = 'cancelled'
        elif activity.done_date:
            activity.activity_state = 'done'
        else:
            activity.activity_state = 'active'
```

#### _compute_schedule_week
```python
@api.depends('planned_date', 'scheduled_date')
def _compute_schedule_week(self):
    """計算排程週次（支援上週到第四週）"""
    today = fields.Date.today()
    current_week_start = today - timedelta(days=today.weekday())

    week_mapping = {
        -1: 'week_prev',  # 上週
        0: 'week0',       # 本週
        1: 'week1',       # 下週
        2: 'week2',       # 第三週
        3: 'week3',       # 第四週
    }

    for activity in self:
        date_to_check = activity.planned_date or activity.scheduled_date
        if not date_to_check:
            activity.schedule_week = False
            activity.schedule_week_number = -999
        else:
            days_diff = (date_to_check - current_week_start).days
            week_number = days_diff // 7

            if week_number < -1:
                activity.schedule_week = 'week_prev'
                activity.schedule_week_number = -1
            elif week_number <= 3:
                activity.schedule_week = week_mapping.get(week_number, 'week0')
                activity.schedule_week_number = week_number
            else:
                activity.schedule_week = 'future'
                activity.schedule_week_number = week_number
```

### 2.3 重要方法

#### _action_done (覆寫)
```python
def _action_done(self, feedback=False, attachment_ids=None):
    """覆寫：封存而非刪除待辦"""
    # 1. 處理附件
    # 2. 處理自動下一待辦
    # 3. 發送完成訊息
    # 4. 封存（不刪除）
    self.write({
        'active': False,
        'done_date': fields.Datetime.now(),
        'feedback': feedback,
    })
    # 5. 建立工時表記錄
    for activity in self:
        activity._create_timesheet_entry()
    # 6. 發送 bus 通知
```

#### _create_timesheet_entry
```python
def _create_timesheet_entry(self):
    """完成待辦時建立工時表記錄"""
    # 1. 檢查有無執行工時
    # 2. 確認員工記錄
    # 3. 取得專案（從關聯文件或預設）
    # 4. 確保 analytic_account_id 存在
    # 5. 建立 account.analytic.line
```

---

## 3. note.note 模型（新建）

### 3.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 名稱 | name | Text | - | 計算自 memo 第一行 |
| 擁有者 | user_id | Many2one(res.users) | - | 預設當前用戶 |
| 內容 | memo | Html | - | 筆記內容 |
| 順序 | sequence | Integer | - | 排序用 |
| 階段 | stage_id | Many2one(note.stage) | - | 看板階段 |
| 階段集合 | stage_ids | Many2many(note.stage) | - | 多用戶階段 |
| 啟用 | open | Boolean | - | True=開啟 |
| 完成日期 | date_done | Date | - | 關閉時填入 |
| 顏色 | color | Integer | - | 顏色索引 |
| 標籤 | tag_ids | Many2many(note.tag) | - | 分類標籤 |
| 啟用 | active | Boolean | - | 封存控制 |
| 主要標籤 | main_tag_id | Many2one(note.tag) | - | 計算欄位 |
| 關聯待辦 | activity_ids | One2many(mail.activity) | - | 反向關聯 |
| 待辦數量 | activity_count | Integer | - | 計算欄位 |
| 進行中待辦 | active_activity_count | Integer | - | 計算欄位 |

### 3.2 繼承

```python
class NoteNote(models.Model):
    _name = 'note.note'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = '筆記本'
    _order = 'sequence, id desc'
```

---

## 4. note.stage 模型（新建）

### 4.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 名稱 | name | Char | 是 | 階段名稱 |
| 順序 | sequence | Integer | - | 排序用 |
| 擁有者 | user_id | Many2one(res.users) | 是 | 階段擁有者 |
| 預設收合 | fold | Boolean | - | Kanban 預設收合 |

### 4.2 模型定義

```python
class NoteStage(models.Model):
    _name = 'note.stage'
    _description = '筆記階段'
    _order = 'sequence'
```

---

## 5. note.tag 模型（新建）

### 5.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 名稱 | name | Char | 是 | 標籤名稱 |
| 顏色 | color | Integer | - | 顏色索引 |
| 父類別 | parent_id | Many2one(note.tag) | - | 階層支援 |
| 子類別 | child_ids | One2many(note.tag) | - | 反向關聯 |
| 父路徑 | parent_path | Char | - | 階層路徑 |
| 啟用 | active | Boolean | - | True |

### 5.2 模型定義

```python
class NoteTag(models.Model):
    _name = 'note.tag'
    _description = '筆記標籤'
    _parent_store = True
    _order = 'parent_path, name'
```

### 5.3 約束

```python
_sql_constraints = [
    ('name_parent_uniq', 'unique (name, parent_id)',
     '同一類別下標籤名稱不可重複！'),
]

@api.constrains('parent_id')
def _check_parent_id(self):
    if not self._check_recursion():
        raise ValidationError(_('不可建立循環的標籤層級。'))
```

---

## 6. mail.activity.assignment.history 模型

### 6.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 待辦 | activity_id | Many2one(mail.activity) | 是 | 關聯待辦 |
| 原指派人 | previous_user_id | Many2one(res.users) | - | - |
| 新指派人 | new_user_id | Many2one(res.users) | - | - |
| 變更者 | changed_by | Many2one(res.users) | - | 預設當前用戶 |
| 變更時間 | changed_date | Datetime | - | 預設當前時間 |
| 變更原因 | reason | Text | - | - |

---

## 7. mail.activity.postpone.history 模型

### 7.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 待辦 | activity_id | Many2one(mail.activity) | 是 | 關聯待辦 |
| 原計畫日期 | original_planned_date | Date | - | - |
| 原週次 | original_week | Char | - | 格式: 2026-W02 |
| 延期時間 | postpone_date | Datetime | - | 預設當前時間 |
| 延期者 | postpone_by | Many2one(res.users) | - | 預設當前用戶 |
| 延期原因 | reason | Text | 是 | - |

---

## 8. mail.activity.transfer.config 模型

### 8.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 名稱 | name | Char | - | 計算自 model_id |
| 順序 | sequence | Integer | - | 預設 10 |
| 模型 | model_id | Many2one(ir.model) | 是 | 允許的模型 |
| 模型名稱 | model | Char | - | related |
| 啟用 | active | Boolean | - | True |

### 8.2 約束

```python
_sql_constraints = [
    ('model_unique', 'unique(model_id)', '每個模型只能配置一次！')
]
```

---

## 9. weekly.report 模型

### 9.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 名稱 | name | Char | - | 計算欄位 |
| 用戶 | user_id | Many2one(res.users) | 是 | - |
| 週起始日 | week_start | Date | 是 | - |
| 週結束日 | week_end | Date | - | 計算欄位 |
| 週次 | week_number | Char | - | 計算欄位 |
| 狀態 | state | Selection | - | draft/confirmed |
| 上週回顧 | previous_week_review_ids | One2many | - | - |
| 本週計畫 | this_week_activity_ids | Many2many | - | - |
| 本週快照 | this_week_snapshot_ids | One2many | - | - |
| 未來安排 | future_activity_ids | Many2many | - | - |
| 尚未安排 | unscheduled_activity_ids | Many2many | - | - |
| 本週計畫工時 | total_planned_hours | Float | - | 計算欄位 |
| 上週計畫工時 | total_review_planned_hours | Float | - | 計算欄位 |
| 上週實際工時 | total_review_actual_hours | Float | - | 計算欄位 |
| 完成率 | completion_rate | Float | - | 計算欄位 |
| 計畫完成率 | planned_completion_rate | Float | - | 計算欄位 |
| 臨時插入數 | inserted_count | Integer | - | 計算欄位 |
| 自評建議 | self_evaluation | Html | - | - |
| 前週報告 | previous_report_id | Many2one | - | 計算欄位 |

### 9.2 繼承

```python
class WeeklyReport(models.Model):
    _name = 'weekly.report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = '週報告'
    _order = 'week_start desc'
```

---

## 10. weekly.report.snapshot.line 模型

### 10.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 週報告 | report_id | Many2one(weekly.report) | 是 | - |
| 待辦 | activity_id | Many2one(mail.activity) | - | - |
| 摘要 | summary | Char | - | 快照 |
| 預估工時 | estimated_hours | Float | - | 快照 |
| 計畫日期 | planned_date | Date | - | 快照 |
| 截止日 | date_deadline | Date | - | 快照 |
| 時間性 | urgency | Selection | - | 快照 |
| 重要性 | importance | Selection | - | 快照 |

---

## 11. weekly.report.review.line 模型

### 11.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 週報告 | report_id | Many2one(weekly.report) | 是 | - |
| 待辦 | activity_id | Many2one(mail.activity) | - | - |
| 原計畫快照 | snapshot_line_id | Many2one | - | - |
| 來源 | source | Selection | - | planned/inserted |
| 狀態 | status | Selection | - | completed/postponed/cancelled/pending |
| 摘要 | summary | Char | - | - |
| 計畫工時 | planned_hours | Float | - | - |
| 實際工時 | actual_hours | Float | - | - |
| 計畫日期 | planned_date | Date | - | - |
| 完成時間 | done_date | Datetime | - | - |
| 工時差異 | hours_diff | Float | - | 計算欄位 |

---

## 12. activity.efficiency.metrics 模型

### 12.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 用戶 | user_id | Many2one(res.users) | - | - |
| 部門 | department_id | Many2one(hr.department) | - | - |
| 期間類型 | period_type | Selection | 是 | week/month/quarter |
| 期間起始 | period_start | Date | 是 | - |
| 期間結束 | period_end | Date | 是 | - |
| 期間名稱 | period_name | Char | - | 計算欄位 |
| 總待辦數 | total_activities | Integer | - | - |
| 完成待辦數 | completed_activities | Integer | - | - |
| 準時完成數 | on_time_activities | Integer | - | - |
| 延期待辦數 | postponed_activities | Integer | - | - |
| 取消待辦數 | cancelled_activities | Integer | - | - |
| 總預估工時 | total_estimated_hours | Float | - | - |
| 總執行工時 | total_actual_hours | Float | - | - |
| 預排計畫數 | planned_source_count | Integer | - | - |
| 臨時插入數 | inserted_source_count | Integer | - | - |
| 完成率 | completion_rate | Float | - | 計算欄位 |
| 準時完成率 | on_time_rate | Float | - | 計算欄位 |
| 預估準確度 | estimation_accuracy | Float | - | 計算欄位 |
| 延期率 | postpone_rate | Float | - | 計算欄位 |
| 效率指數 | efficiency_index | Float | - | 計算欄位 (滿分5) |

---

## 13. weekly.schedule.config 模型

### 13.1 欄位定義

| 欄位名稱 | 技術名稱 | 類型 | 必填 | 說明 |
|---------|---------|------|------|------|
| 名稱 | name | Char | - | 計算欄位 |
| 用戶 | user_id | Many2one(res.users) | 是 | - |
| 啟用 | active | Boolean | - | True |
| 待辦類型 | activity_type_id | Many2one | 是 | - |
| 建立日期 | schedule_day | Selection | 是 | 0~6 (週一~週日) |
| 建立時段 | schedule_time | Selection | - | morning/noon/evening |
| 截止日偏移 | deadline_offset | Integer | - | 0 |
| 關聯文件類型 | target_model | Selection | 是 | note.note/res.users/weekly.report |
| 指定筆記本 | note_id | Many2one(note.note) | - | - |
| 自動建立筆記 | auto_create_note | Boolean | - | False |
| 摘要模板 | summary_template | Char | - | - |
| 包含預設說明 | include_note | Boolean | - | True |
| 上次建立日期 | last_created_date | Date | - | 唯讀 |
| 上次建立待辦 | last_activity_id | Many2one | - | 唯讀 |

---

## 14. mail.activity.type 擴展

### 14.1 新增欄位

| 欄位名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 指派通知模板 | notify_template_id | Many2one(mail.template) | 自定義通知郵件 |
| 使用自定義通知 | use_custom_notify | Boolean | 是否使用自定義模板 |

---

## 15. res.users 擴展

### 15.1 新增欄位

| 欄位名稱 | 技術名稱 | 類型 | 預設值 | 說明 |
|---------|---------|------|--------|------|
| 約定時數 | weekly_committed_hours | Float | 40.0 | 每週約定工作時數 |

---

## 16. res.company 擴展

### 16.1 新增欄位

| 欄位名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 預設工時表專案 | default_timesheet_project_id | Many2one(project.project) | 待辦完成無專案時使用 |

---

## 17. Wizard 模型

### 17.1 mail.activity.done.wizard

| 欄位名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 待辦 | activity_id | Many2one | 必填 |
| 執行工時 | actual_hours | Float | 必填 |
| 回饋說明 | feedback | Text | - |
| 附件 | attachment_ids | Many2many | - |
| 安排下一次 | schedule_next | Boolean | - |
| 下一次類型 | next_activity_type_id | Many2one | - |
| 下一次到期日 | next_date_deadline | Date | - |
| 下一次摘要 | next_summary | Char | - |
| 下一次負責人 | next_user_id | Many2one | - |

### 17.2 mail.activity.postpone.wizard

| 欄位名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 待辦 | activity_id | Many2one | 必填 |
| 延期原因 | reason | Text | 必填 |

### 17.3 mail.activity.transfer.wizard

| 欄位名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 待辦 | activity_id | Many2one | 必填 |
| 來源模型 | source_model | Char | 唯讀 |
| 來源 ID | source_id | Integer | 唯讀 |
| 來源顯示 | source_display | Char | 計算 |
| 目標記錄 | target_ref | Reference | 必填 |

### 17.4 mail.activity.from.message.wizard

| 欄位名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 來源訊息 | message_id | Many2one | - |
| 訊息預覽 | message_body_preview | Html | 計算 |
| 目標記錄 | target_ref | Reference | 必填 |
| 待辦類型 | activity_type_id | Many2one | 必填 |
| 摘要 | summary | Char | - |
| 備註 | note | Html | - |
| 截止日期 | date_deadline | Date | 必填 |
| 預估工時 | estimated_hours | Float | - |
| 時間性 | urgency | Selection | - |
| 重要性 | importance | Selection | - |
| 指派給 | user_id | Many2one | - |

### 17.5 mail.activity.reassign.wizard

| 欄位名稱 | 技術名稱 | 類型 | 說明 |
|---------|---------|------|------|
| 待辦 | activity_id | Many2one | 必填 |
| 目前負責人 | current_user_id | Many2one | related |
| 新負責人 | new_user_id | Many2one | 必填 |
| 變更原因 | reason | Text | - |

---

**文件版本**: 1.0.0
**建立日期**: 2026-01-15
