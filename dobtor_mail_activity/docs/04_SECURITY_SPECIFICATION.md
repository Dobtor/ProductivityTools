# 安全規格 (Security Specification)

## 1. 用戶群組定義

### 1.1 群組清單

| 群組 ID | 群組名稱 | 分類 | 說明 |
|---------|---------|------|------|
| group_activity_user | 待辦用戶 | 生產力工具 | 基本用戶，可管理自己的待辦 |
| group_activity_manager | 待辦管理者 | 生產力工具 | 可查看所有人的待辦和報告 |

### 1.2 群組定義 XML

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="0">
        <!-- 模組分類 -->
        <record id="module_category_productivity" model="ir.module.category">
            <field name="name">生產力工具</field>
            <field name="sequence">50</field>
        </record>

        <!-- 待辦用戶群組（隱含 base.group_user） -->
        <record id="group_activity_user" model="res.groups">
            <field name="name">待辦用戶</field>
            <field name="category_id" ref="module_category_productivity"/>
            <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
            <field name="comment">可建立和管理自己的待辦事項、筆記本和週報告</field>
        </record>

        <!-- 待辦管理者群組（隱含 group_activity_user） -->
        <record id="group_activity_manager" model="res.groups">
            <field name="name">待辦管理者</field>
            <field name="category_id" ref="module_category_productivity"/>
            <field name="implied_ids" eval="[(4, ref('group_activity_user'))]"/>
            <field name="comment">可查看所有人的待辦事項、週報告和效率分析</field>
        </record>
    </data>
</odoo>
```

### 1.3 群組繼承關係

```
base.group_user (內部用戶)
    |
    v
group_activity_user (待辦用戶)
    |
    v
group_activity_manager (待辦管理者)
    |
    v
base.group_system (系統管理員)
```

---

## 2. 存取控制清單 (ACL)

### 2.1 核心模型 ACL

#### mail.activity 相關

| 模型 | 群組 | 讀取 | 寫入 | 建立 | 刪除 | 說明 |
|------|------|------|------|------|------|------|
| mail.activity | base.group_user | 1 | 1 | 1 | 1 | 官方定義 |
| mail.activity.assignment.history | base.group_user | 1 | 0 | 0 | 0 | 用戶唯讀 |
| mail.activity.assignment.history | group_activity_manager | 1 | 1 | 1 | 1 | 管理者完整 |
| mail.activity.postpone.history | base.group_user | 1 | 1 | 1 | 0 | 用戶可建立 |
| mail.activity.postpone.history | group_activity_manager | 1 | 1 | 1 | 1 | 管理者完整 |
| mail.activity.transfer.config | base.group_user | 1 | 0 | 0 | 0 | 用戶唯讀 |
| mail.activity.transfer.config | base.group_system | 1 | 1 | 1 | 1 | 系統管理員 |

#### note 相關

| 模型 | 群組 | 讀取 | 寫入 | 建立 | 刪除 | 說明 |
|------|------|------|------|------|------|------|
| note.note | base.group_user | 1 | 1 | 1 | 1 | 用戶完整 |
| note.stage | base.group_user | 1 | 1 | 1 | 1 | 用戶完整 |
| note.tag | base.group_user | 1 | 1 | 1 | 0 | 用戶不可刪除 |
| note.tag | base.group_system | 1 | 1 | 1 | 1 | 系統管理員 |

#### 週報告相關

| 模型 | 群組 | 讀取 | 寫入 | 建立 | 刪除 | 說明 |
|------|------|------|------|------|------|------|
| weekly.report | base.group_user | 1 | 1 | 1 | 0 | 用戶不可刪除 |
| weekly.report | group_activity_manager | 1 | 1 | 1 | 1 | 管理者完整 |
| weekly.report.snapshot.line | base.group_user | 1 | 1 | 1 | 1 | 用戶完整 |
| weekly.report.review.line | base.group_user | 1 | 1 | 1 | 1 | 用戶完整 |

#### 效率指標相關

| 模型 | 群組 | 讀取 | 寫入 | 建立 | 刪除 | 說明 |
|------|------|------|------|------|------|------|
| activity.efficiency.metrics | base.group_user | 1 | 0 | 0 | 0 | 用戶唯讀 |
| activity.efficiency.metrics | hr_timesheet.group_timesheet_manager | 1 | 1 | 1 | 1 | 工時管理員 |

#### 週報排程配置相關

| 模型 | 群組 | 讀取 | 寫入 | 建立 | 刪除 | 說明 |
|------|------|------|------|------|------|------|
| weekly.schedule.config | base.group_user | 1 | 1 | 1 | 0 | 用戶不可刪除 |
| weekly.schedule.config | base.group_system | 1 | 1 | 1 | 1 | 系統管理員 |

### 2.2 Wizard ACL

| 模型 | 群組 | 讀取 | 寫入 | 建立 | 刪除 |
|------|------|------|------|------|------|
| mail.activity.done.wizard | base.group_user | 1 | 1 | 1 | 1 |
| mail.activity.postpone.wizard | base.group_user | 1 | 1 | 1 | 1 |
| mail.activity.transfer.wizard | base.group_user | 1 | 1 | 1 | 1 |
| mail.activity.from.message.wizard | base.group_user | 1 | 1 | 1 | 1 |
| mail.activity.reassign.wizard | base.group_user | 1 | 1 | 1 | 1 |

### 2.3 ir.model.access.csv

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
# Wizards
access_mail_activity_done_wizard,mail.activity.done.wizard,model_mail_activity_done_wizard,base.group_user,1,1,1,1
access_mail_activity_postpone_wizard,mail.activity.postpone.wizard,model_mail_activity_postpone_wizard,base.group_user,1,1,1,1
access_mail_activity_transfer_wizard,mail.activity.transfer.wizard,model_mail_activity_transfer_wizard,base.group_user,1,1,1,1
access_mail_activity_from_message_wizard,mail.activity.from.message.wizard,model_mail_activity_from_message_wizard,base.group_user,1,1,1,1
access_mail_activity_reassign_wizard,mail.activity.reassign.wizard,model_mail_activity_reassign_wizard,base.group_user,1,1,1,1

# Transfer Config
access_mail_activity_transfer_config_user,mail.activity.transfer.config.user,model_mail_activity_transfer_config,base.group_user,1,0,0,0
access_mail_activity_transfer_config_admin,mail.activity.transfer.config.admin,model_mail_activity_transfer_config,base.group_system,1,1,1,1

# History
access_mail_activity_assignment_history_user,mail.activity.assignment.history.user,model_mail_activity_assignment_history,base.group_user,1,0,0,0
access_mail_activity_assignment_history_manager,mail.activity.assignment.history.manager,model_mail_activity_assignment_history,dobtor_mail_activity.group_activity_manager,1,1,1,1
access_mail_activity_postpone_history,mail.activity.postpone.history,model_mail_activity_postpone_history,base.group_user,1,1,1,0

# Note
access_note_note,note.note,model_note_note,base.group_user,1,1,1,1
access_note_stage,note.stage,model_note_stage,base.group_user,1,1,1,1
access_note_tag_user,note.tag.user,model_note_tag,base.group_user,1,1,1,0
access_note_tag_admin,note.tag.admin,model_note_tag,base.group_system,1,1,1,1

# Weekly Report
access_weekly_report_user,weekly.report.user,model_weekly_report,base.group_user,1,1,1,0
access_weekly_report_manager,weekly.report.manager,model_weekly_report,dobtor_mail_activity.group_activity_manager,1,1,1,1
access_weekly_report_snapshot_line,weekly.report.snapshot.line,model_weekly_report_snapshot_line,base.group_user,1,1,1,1
access_weekly_report_review_line,weekly.report.review.line,model_weekly_report_review_line,base.group_user,1,1,1,1

# Efficiency Metrics
access_activity_efficiency_metrics_user,activity.efficiency.metrics.user,model_activity_efficiency_metrics,base.group_user,1,0,0,0
access_activity_efficiency_metrics_manager,activity.efficiency.metrics.manager,model_activity_efficiency_metrics,hr_timesheet.group_timesheet_manager,1,1,1,1

# Weekly Schedule Config
access_weekly_schedule_config_user,weekly.schedule.config.user,model_weekly_schedule_config,base.group_user,1,1,1,0
access_weekly_schedule_config_admin,weekly.schedule.config.admin,model_weekly_schedule_config,base.group_system,1,1,1,1
```

---

## 3. 記錄規則 (Record Rules)

### 3.1 mail.activity 記錄規則

```xml
<data noupdate="1">
    <!-- 用戶可存取被指派的待辦 -->
    <record id="mail_activity_rule_user_assigned" model="ir.rule">
        <field name="name">待辦：用戶存取被指派的待辦</field>
        <field name="model_id" ref="mail.model_mail_activity"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
        <field name="groups" eval="[(4, ref('base.group_user'))]"/>
        <field name="perm_read" eval="True"/>
        <field name="perm_write" eval="True"/>
        <field name="perm_create" eval="False"/>
        <field name="perm_unlink" eval="True"/>
    </record>

    <!-- 用戶可存取自己建立的待辦 -->
    <record id="mail_activity_rule_user_created" model="ir.rule">
        <field name="name">待辦：用戶存取自己建立的待辦</field>
        <field name="model_id" ref="mail.model_mail_activity"/>
        <field name="domain_force">[('create_uid', '=', user.id)]</field>
        <field name="groups" eval="[(4, ref('base.group_user'))]"/>
        <field name="perm_read" eval="True"/>
        <field name="perm_write" eval="True"/>
        <field name="perm_create" eval="True"/>
        <field name="perm_unlink" eval="True"/>
    </record>

    <!-- 用戶可存取未指派的待辦 -->
    <record id="mail_activity_rule_user_unassigned" model="ir.rule">
        <field name="name">待辦：用戶存取未指派的待辦</field>
        <field name="model_id" ref="mail.model_mail_activity"/>
        <field name="domain_force">[('user_id', '=', False)]</field>
        <field name="groups" eval="[(4, ref('base.group_user'))]"/>
        <field name="perm_read" eval="True"/>
        <field name="perm_write" eval="True"/>
        <field name="perm_create" eval="False"/>
        <field name="perm_unlink" eval="False"/>
    </record>

    <!-- 管理者可存取所有待辦 -->
    <record id="mail_activity_rule_manager_all" model="ir.rule">
        <field name="name">待辦：管理者存取所有待辦</field>
        <field name="model_id" ref="mail.model_mail_activity"/>
        <field name="domain_force">[(1, '=', 1)]</field>
        <field name="groups" eval="[(4, ref('group_activity_manager'))]"/>
    </record>
</data>
```

### 3.2 note.note 記錄規則

```xml
<data noupdate="1">
    <!-- 用戶只能存取自己的筆記 -->
    <record id="note_note_rule_user" model="ir.rule">
        <field name="name">筆記：用戶只能存取自己的筆記</field>
        <field name="model_id" ref="model_note_note"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
        <field name="groups" eval="[(4, ref('base.group_user'))]"/>
    </record>

    <!-- 管理者可存取所有筆記 -->
    <record id="note_note_rule_manager" model="ir.rule">
        <field name="name">筆記：管理者存取所有筆記</field>
        <field name="model_id" ref="model_note_note"/>
        <field name="domain_force">[(1, '=', 1)]</field>
        <field name="groups" eval="[(4, ref('group_activity_manager'))]"/>
    </record>
</data>
```

### 3.3 note.stage 記錄規則

```xml
<data noupdate="1">
    <!-- 用戶只能存取自己的階段 -->
    <record id="note_stage_rule_user" model="ir.rule">
        <field name="name">筆記階段：用戶只能存取自己的階段</field>
        <field name="model_id" ref="model_note_stage"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
        <field name="groups" eval="[(4, ref('base.group_user'))]"/>
    </record>

    <!-- 管理者可存取所有階段 -->
    <record id="note_stage_rule_manager" model="ir.rule">
        <field name="name">筆記階段：管理者存取所有階段</field>
        <field name="model_id" ref="model_note_stage"/>
        <field name="domain_force">[(1, '=', 1)]</field>
        <field name="groups" eval="[(4, ref('group_activity_manager'))]"/>
    </record>
</data>
```

### 3.4 weekly.report 記錄規則

```xml
<data noupdate="1">
    <!-- 用戶只能存取自己的週報 -->
    <record id="weekly_report_rule_user" model="ir.rule">
        <field name="name">週報：用戶只能存取自己的週報</field>
        <field name="model_id" ref="model_weekly_report"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
        <field name="groups" eval="[(4, ref('base.group_user'))]"/>
    </record>

    <!-- 管理者可存取所有週報 -->
    <record id="weekly_report_rule_manager" model="ir.rule">
        <field name="name">週報：管理者存取所有週報</field>
        <field name="model_id" ref="model_weekly_report"/>
        <field name="domain_force">[(1, '=', 1)]</field>
        <field name="groups" eval="[(4, ref('group_activity_manager'))]"/>
    </record>
</data>
```

### 3.5 weekly.schedule.config 記錄規則

```xml
<data noupdate="1">
    <!-- 用戶只能存取自己的配置 -->
    <record id="weekly_schedule_config_rule_user" model="ir.rule">
        <field name="name">週報排程配置：用戶只能存取自己的配置</field>
        <field name="model_id" ref="model_weekly_schedule_config"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
        <field name="groups" eval="[(4, ref('base.group_user'))]"/>
    </record>

    <!-- 系統管理員可存取所有配置 -->
    <record id="weekly_schedule_config_rule_admin" model="ir.rule">
        <field name="name">週報排程配置：系統管理員存取所有配置</field>
        <field name="model_id" ref="model_weekly_schedule_config"/>
        <field name="domain_force">[(1, '=', 1)]</field>
        <field name="groups" eval="[(4, ref('base.group_system'))]"/>
    </record>
</data>
```

### 3.6 activity.efficiency.metrics 記錄規則

```xml
<data noupdate="1">
    <!-- 用戶只能查看自己的效率指標 -->
    <record id="efficiency_metrics_rule_user" model="ir.rule">
        <field name="name">效率指標：用戶只能查看自己的指標</field>
        <field name="model_id" ref="model_activity_efficiency_metrics"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
        <field name="groups" eval="[(4, ref('base.group_user'))]"/>
        <field name="perm_read" eval="True"/>
        <field name="perm_write" eval="False"/>
        <field name="perm_create" eval="False"/>
        <field name="perm_unlink" eval="False"/>
    </record>

    <!-- 工時管理員可查看所有效率指標 -->
    <record id="efficiency_metrics_rule_timesheet_manager" model="ir.rule">
        <field name="name">效率指標：工時管理員存取所有指標</field>
        <field name="model_id" ref="model_activity_efficiency_metrics"/>
        <field name="domain_force">[(1, '=', 1)]</field>
        <field name="groups" eval="[(4, ref('hr_timesheet.group_timesheet_manager'))]"/>
    </record>

    <!-- 待辦管理者可查看所有效率指標 -->
    <record id="efficiency_metrics_rule_activity_manager" model="ir.rule">
        <field name="name">效率指標：待辦管理者存取所有指標</field>
        <field name="model_id" ref="model_activity_efficiency_metrics"/>
        <field name="domain_force">[(1, '=', 1)]</field>
        <field name="groups" eval="[(4, ref('group_activity_manager'))]"/>
    </record>
</data>
```

---

## 4. 與 project_todo 的權限整合

### 4.1 隱藏 project_todo 選單

```xml
<!-- 隱藏 project_todo 主選單（僅 dobtor 模組安裝時） -->
<record id="project_todo.menu_todo" model="ir.ui.menu">
    <field name="groups_id" eval="[(6, 0, [])]"/>
</record>
```

### 4.2 整合方式說明

由於 dobtor_mail_activity 使用 mail.activity 而非 project.task，
project_todo 的權限規則不會衝突，但需要：

1. **隱藏 project_todo 選單**: 避免使用者困惑
2. **保留 project_todo 功能**: 不破壞原有整合
3. **統一入口**: 所有待辦操作從 dobtor 入口進行

---

## 5. 程式碼層面的安全檢查

### 5.1 排程操作權限

```python
# mail_activity.py
def write(self, vals):
    # 驗證：只有被指派人或系統管理員可以設定排程相關欄位
    schedule_fields = {'planned_date', 'schedule_status', 'scheduled_date'}
    changing_schedule = bool(schedule_fields & set(vals.keys()))

    if changing_schedule and not self.env.su:
        is_internal_operation = self.env.context.get('skip_schedule_check', False)
        if not is_internal_operation:
            for activity in self:
                if activity.user_id and activity.user_id.id != self.env.uid:
                    if not self.env.user.has_group('base.group_system'):
                        raise UserError(_(
                            '排程操作僅限被指派人執行。\n'
                            '待辦「%s」已指派給 %s，您無法修改其排程。'
                        ) % (activity.summary, activity.user_id.name))
    return super().write(vals)
```

### 5.2 領取待辦權限

```python
def action_claim_activity(self):
    """領取待辦"""
    self.ensure_one()
    if self.user_id:
        raise UserError(_('此待辦已被指派，無法領取。'))
    # 只有未指派的待辦可以被領取
    self.write({'user_id': self.env.user.id})
```

### 5.3 變更指派權限

```python
def action_reassign_activity(self):
    """變更指派"""
    self.ensure_one()
    if not self.user_id:
        raise UserError(_('此待辦尚未指派，請使用領取功能。'))
    # 已指派的待辦需要透過 wizard 變更
    return self.env.ref('dobtor_mail_activity.action_reassign_wizard').read()[0]
```

---

## 6. 選單權限控制

### 6.1 選單群組設定

```xml
<!-- 所有代辦事項（管理者專用） -->
<menuitem id="menu_mail_activity_all"
          name="所有代辦事項"
          parent="menu_productivity_root"
          action="action_mail_activity_all"
          groups="group_activity_manager"/>

<!-- 所有歷史代辦（管理者專用） -->
<menuitem id="menu_mail_activity_archived"
          name="所有歷史代辦"
          parent="menu_productivity_root"
          action="action_mail_activity_archived"
          groups="group_activity_manager"/>

<!-- 團隊分析（管理者專用） -->
<menuitem id="menu_efficiency_team"
          name="團隊分析"
          parent="menu_efficiency_analysis"
          action="action_efficiency_team"
          groups="group_activity_manager"/>

<!-- 設定選單（管理者專用） -->
<menuitem id="menu_configuration"
          name="設定"
          parent="menu_productivity_root"
          groups="group_activity_manager"/>

<!-- 待辦轉移配置（系統管理員） -->
<menuitem id="menu_activity_transfer_config"
          name="待辦轉移配置"
          parent="menu_configuration"
          action="action_mail_activity_transfer_config"
          groups="base.group_system"/>
```

---

## 7. 安全性最佳實踐

### 7.1 SQL 注入防護

```python
# 正確：使用 ORM 或參數化查詢
activities = self.env['mail.activity'].search([
    ('user_id', '=', user_id),
    ('summary', 'ilike', search_term),
])

# 錯誤：字串拼接
# activities = self.env.cr.execute(
#     "SELECT * FROM mail_activity WHERE summary LIKE '%" + search_term + "%'"
# )
```

### 7.2 權限提升檢查

```python
# 使用 sudo() 時必須明確檢查
def _create_timesheet_entry(self):
    self.ensure_one()
    # 確認用戶有權限建立工時表
    if not self.env.user.has_group('hr_timesheet.group_hr_timesheet_user'):
        return False
    # 使用 sudo() 建立工時表
    timesheet = self.env['account.analytic.line'].sudo().create(vals)
```

### 7.3 敏感資料保護

```python
# 不記錄敏感資訊到日誌
_logger.info('Activity %s completed by user %s', activity.id, self.env.uid)
# 而非
# _logger.info('Activity completed with feedback: %s', feedback_text)
```

---

**文件版本**: 1.0.0
**建立日期**: 2026-01-15
