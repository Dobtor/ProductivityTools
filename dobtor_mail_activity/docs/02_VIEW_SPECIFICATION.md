# 視圖規格 (View Specification)

## 1. 視圖總覽

### 1.1 視圖清單

| 模型 | 視圖類型 | XML ID | 優先級 | 說明 |
|------|---------|--------|--------|------|
| mail.activity | Form (popup) | mail_activity_view_form_popup_inherit | - | 繼承修改 |
| mail.activity | Kanban | view_mail_activity_kanban_schedule | 100 | 週天排程看板 |
| mail.activity | List | view_mail_activity_list | 100 | 待辦清單 |
| mail.activity | Search | view_mail_activity_search | 100 | 搜尋篩選 |
| note.note | Kanban | view_note_note_kanban | 10 | 筆記看板 |
| note.note | List | view_note_note_list | 10 | 筆記清單 |
| note.note | Form | view_note_note_form | 10 | 筆記表單 |
| note.note | Search | view_note_note_search | 10 | 搜尋篩選 |
| note.stage | List | view_note_stage_list | 10 | 階段清單 |
| note.stage | Form | view_note_stage_form | 10 | 階段表單 |
| note.tag | List | view_note_tag_list | 10 | 標籤清單 |
| note.tag | Form | view_note_tag_form | 10 | 標籤表單 |
| weekly.report | Form | view_weekly_report_form | 10 | 週報表單 |
| weekly.report | List | view_weekly_report_list | 10 | 週報清單 |
| activity.efficiency.metrics | Pivot | view_efficiency_pivot | 10 | 效率分析 |
| activity.efficiency.metrics | Graph | view_efficiency_graph | 10 | 效率圖表 |

---

## 2. Odoo 18 視圖語法變更對照

### 2.1 屬性語法變更

| Odoo 14 語法 | Odoo 18 語法 | 說明 |
|-------------|-------------|------|
| `attrs="{'invisible': [('field', '=', value)]}"` | `invisible="field == value"` | 簡化條件 |
| `attrs="{'readonly': [('state', '!=', 'draft')]}"` | `readonly="state != 'draft'"` | 簡化條件 |
| `attrs="{'required': [('type', '=', 'required')]}"` | `required="type == 'required'"` | 簡化條件 |
| `states="draft,confirmed"` | `invisible="state not in ('draft', 'confirmed')"` | states 已棄用 |
| `<tree>` | `<list>` | 視圖標籤名稱 |

### 2.2 欄位語法變更

| Odoo 14 語法 | Odoo 18 語法 | 說明 |
|-------------|-------------|------|
| `<field name="x" attrs="{'invisible': ...}"/>` | `<field name="x" invisible="..."/>` | 直接屬性 |
| `widget="statusbar" statusbar_visible="..."` | `widget="statusbar" options="{'clickable': '1'}"` | 選項調整 |
| `context="{'group_by': 'field'}"` | `context="{'group_by': 'field'}"` | 無變更 |

### 2.3 按鈕語法變更

| Odoo 14 語法 | Odoo 18 語法 |
|-------------|-------------|
| `<button states="draft" .../>` | `<button invisible="state != 'draft'" .../>` |
| `attrs="{'invisible': [...]}"` | `invisible="..."` |

---

## 3. mail.activity 視圖規格

### 3.1 Form 視圖 (Popup 繼承)

**XML ID**: `mail_activity_view_form_popup_inherit`

```xml
<record id="mail_activity_view_form_popup_inherit" model="ir.ui.view">
    <field name="name">mail.activity.view.form.popup.inherit.dobtor</field>
    <field name="model">mail.activity</field>
    <field name="inherit_id" ref="mail.mail_activity_view_form_popup"/>
    <field name="arch" type="xml">
        <!-- 重新排版：摘要置頂 -->
        <xpath expr="//sheet/group[last()]" position="replace">
            <group>
                <field name="summary" placeholder="請輸入待辦摘要..."
                       nolabel="1" colspan="2"
                       style="font-size: 1.2em; font-weight: 500;"/>
            </group>

            <!-- 目標文件選擇 -->
            <group>
                <field name="res_model_id" invisible="1"/>
                <field name="res_id" invisible="1"/>
                <field name="target_ref" string="目標文件"
                       invisible="res_model_id and res_id"
                       required="not res_model_id"
                       options="{'no_create': True}"/>
                <field name="res_name" string="關聯文件" readonly="1"
                       invisible="not res_model_id or not res_id"/>
            </group>

            <group>
                <!-- 左側：基本資訊 -->
                <group>
                    <field name="activity_type_id" string="待辦類型"
                           required="1" options="{'no_create': True, 'no_open': True}"/>
                    <field name="date_deadline" string="截止日期"/>
                    <field name="estimated_hours" string="預估工時" widget="float_time"/>
                </group>

                <!-- 右側：優先級 + 指派 -->
                <group>
                    <field name="urgency" string="時間性" widget="radio"
                           options="{'horizontal': true}"/>
                    <field name="importance" string="重要性" widget="radio"
                           options="{'horizontal': true}"/>
                    <field name="user_id" string="指派給" widget="many2one_avatar_user"/>
                </group>
            </group>
        </xpath>

        <!-- 訊息來源區塊 -->
        <xpath expr="//field[@name='note']" position="before">
            <field name="source_message_id" invisible="1"/>
            <div invisible="not source_message_id"
                 class="alert alert-info py-2 mb-2" role="alert">
                <i class="fa fa-commenting-o" title="訊息來源"/>
                <span class="ms-1">此待辦由訊息建立</span>
                <button name="action_open_source_message" type="object"
                        class="btn btn-sm btn-link p-0 ms-2">
                    查看原始訊息 <i class="fa fa-external-link"/>
                </button>
            </div>
        </xpath>

        <!-- Footer 按鈕 -->
        <xpath expr="//footer/button[@name='action_close_dialog']" position="after">
            <button string="轉移" name="action_transfer_activity" type="object"
                    class="btn-secondary" invisible="not id"/>
            <button string="取消待辦" name="action_cancel" type="object"
                    class="btn-secondary" invisible="not id"/>
        </xpath>
    </field>
</record>
```

### 3.2 Kanban 視圖 (週天排程)

**XML ID**: `view_mail_activity_kanban_schedule`

```xml
<record id="view_mail_activity_kanban_schedule" model="ir.ui.view">
    <field name="name">mail.activity.kanban.schedule</field>
    <field name="model">mail.activity</field>
    <field name="priority">100</field>
    <field name="arch" type="xml">
        <kanban default_group_by="schedule_status"
                class="o_kanban_small_column o_activity_kanban"
                quick_create="false"
                group_create="false"
                group_delete="false"
                group_edit="false"
                archivable="false"
                records_draggable="true"
                default_order="urgency desc, importance desc, date_deadline asc">
            <field name="id"/>
            <field name="summary"/>
            <field name="user_id"/>
            <field name="date_deadline"/>
            <field name="urgency"/>
            <field name="importance"/>
            <field name="estimated_hours"/>
            <field name="schedule_status"/>
            <field name="activity_type_id"/>
            <field name="res_name"/>
            <field name="active"/>
            <field name="schedule_warning"/>
            <field name="postpone_count"/>

            <templates>
                <t t-name="card">
                    <div t-attf-class="o_activity_card #{record.urgency.raw_value == 'urgent' ? 'border-danger' : ''} #{record.importance.raw_value == 'important' ? 'fw-bold' : ''}">
                        <!-- 標題列 -->
                        <div class="d-flex align-items-center mb-1">
                            <field name="activity_type_id" class="text-muted small"/>
                            <span class="ms-auto">
                                <field name="urgency" widget="badge"
                                       decoration-danger="urgency == 'urgent'"
                                       decoration-warning="urgency == 'standard'"
                                       decoration-success="urgency == 'flexible'"/>
                            </span>
                        </div>

                        <!-- 摘要 -->
                        <div class="o_kanban_record_title mb-1">
                            <field name="summary" placeholder="(無摘要)"/>
                        </div>

                        <!-- 關聯文件 -->
                        <div class="text-muted small mb-2">
                            <i class="fa fa-file-text-o me-1"/>
                            <field name="res_name"/>
                        </div>

                        <!-- 底部資訊 -->
                        <div class="d-flex align-items-center">
                            <field name="user_id" widget="many2one_avatar_user"/>
                            <span class="ms-2 small text-muted">
                                <i class="fa fa-clock-o me-1"/>
                                <field name="estimated_hours" widget="float_time"/>
                            </span>
                            <span class="ms-auto">
                                <field name="date_deadline" widget="remaining_days"/>
                            </span>
                        </div>

                        <!-- 警告 -->
                        <div t-if="record.schedule_warning.raw_value"
                             class="alert alert-warning py-1 px-2 mt-2 mb-0 small">
                            <field name="schedule_warning"/>
                        </div>

                        <!-- 延期標記 -->
                        <div t-if="record.postpone_count.raw_value > 0"
                             class="badge bg-secondary mt-1">
                            已延期 <field name="postpone_count"/> 次
                        </div>
                    </div>
                </t>
            </templates>
        </kanban>
    </field>
</record>
```

### 3.3 List 視圖

**XML ID**: `view_mail_activity_list`

```xml
<record id="view_mail_activity_list" model="ir.ui.view">
    <field name="name">mail.activity.list</field>
    <field name="model">mail.activity</field>
    <field name="priority">100</field>
    <field name="arch" type="xml">
        <list string="待辦事項"
              default_order="date_deadline asc, urgency desc"
              multi_edit="1"
              expand="1">
            <field name="summary" string="摘要"/>
            <field name="activity_type_id" string="類型"/>
            <field name="res_name" string="關聯文件"/>
            <field name="user_id" string="負責人" widget="many2one_avatar_user"/>
            <field name="date_deadline" string="截止日" widget="remaining_days"/>
            <field name="planned_date" string="計畫日" optional="show"/>
            <field name="urgency" string="時間性" widget="badge"
                   decoration-danger="urgency == 'urgent'"
                   decoration-warning="urgency == 'standard'"
                   decoration-success="urgency == 'flexible'"/>
            <field name="importance" string="重要性" optional="show"/>
            <field name="estimated_hours" string="預估工時" widget="float_time" optional="show"/>
            <field name="schedule_status" string="排程" optional="hide"/>
            <field name="schedule_week" string="週次" optional="hide"/>
            <field name="postpone_count" string="延期次數" optional="hide"/>
        </list>
    </field>
</record>
```

### 3.4 Search 視圖

**XML ID**: `view_mail_activity_search`

```xml
<record id="view_mail_activity_search" model="ir.ui.view">
    <field name="name">mail.activity.search</field>
    <field name="model">mail.activity</field>
    <field name="priority">100</field>
    <field name="arch" type="xml">
        <search string="搜尋待辦">
            <field name="summary" string="摘要"/>
            <field name="user_id" string="負責人"/>
            <field name="activity_type_id" string="類型"/>
            <field name="res_name" string="關聯文件"/>

            <separator/>
            <filter string="我的待辦" name="my_activities"
                    domain="[('user_id', '=', uid)]"/>
            <filter string="我建立的" name="created_by_me"
                    domain="[('create_uid', '=', uid)]"/>
            <filter string="未指派" name="unassigned"
                    domain="[('user_id', '=', False)]"/>

            <separator/>
            <filter string="等待排程" name="waiting"
                    domain="[('schedule_status', '=', 'waiting')]"/>
            <filter string="本週" name="this_week"
                    domain="[('schedule_week', '=', 'week0')]"/>
            <filter string="下週" name="next_week"
                    domain="[('schedule_week', '=', 'week1')]"/>

            <separator/>
            <filter string="緊急" name="urgent"
                    domain="[('urgency', '=', 'urgent')]"/>
            <filter string="重要" name="important"
                    domain="[('importance', '=', 'important')]"/>

            <separator/>
            <filter string="進行中" name="active"
                    domain="[('active', '=', True)]"/>
            <filter string="已完成" name="done"
                    domain="[('done_date', '!=', False)]"/>
            <filter string="已取消" name="cancelled"
                    domain="[('cancel_date', '!=', False)]"/>
            <filter string="已封存" name="archived"
                    domain="[('active', '=', False)]"/>

            <separator/>
            <filter string="逾期" name="overdue"
                    domain="[('date_deadline', '&lt;', context_today().strftime('%Y-%m-%d'))]"/>

            <group expand="0" string="分組">
                <filter string="排程狀態" name="group_schedule"
                        context="{'group_by': 'schedule_status'}"/>
                <filter string="負責人" name="group_user"
                        context="{'group_by': 'user_id'}"/>
                <filter string="週次" name="group_week"
                        context="{'group_by': 'schedule_week'}"/>
                <filter string="類型" name="group_type"
                        context="{'group_by': 'activity_type_id'}"/>
                <filter string="時間性" name="group_urgency"
                        context="{'group_by': 'urgency'}"/>
                <filter string="重要性" name="group_importance"
                        context="{'group_by': 'importance'}"/>
                <filter string="截止日" name="group_deadline"
                        context="{'group_by': 'date_deadline:week'}"/>
            </group>
        </search>
    </field>
</record>
```

---

## 4. note.note 視圖規格

### 4.1 Kanban 視圖

```xml
<record id="view_note_note_kanban" model="ir.ui.view">
    <field name="name">note.note.kanban</field>
    <field name="model">note.note</field>
    <field name="arch" type="xml">
        <kanban default_group_by="stage_id"
                class="o_kanban_small_column"
                on_create="quick_create"
                quick_create_view="view_note_note_quick_create"
                archivable="true"
                sample="1">
            <field name="color"/>
            <field name="stage_id"/>
            <field name="user_id"/>
            <field name="tag_ids"/>
            <field name="active_activity_count"/>

            <templates>
                <t t-name="menu">
                    <a role="menuitem" type="set_cover" class="dropdown-item"
                       data-field="color">設定顏色</a>
                    <a role="menuitem" type="archive" class="dropdown-item">封存</a>
                    <a role="menuitem" type="delete" class="dropdown-item">刪除</a>
                </t>
                <t t-name="card">
                    <field name="color" widget="color_picker"/>
                    <div class="oe_kanban_content">
                        <div class="o_kanban_record_title">
                            <field name="name" placeholder="(無標題)"/>
                        </div>
                        <div class="o_kanban_record_body">
                            <field name="memo" class="text-muted"/>
                        </div>
                        <div class="o_kanban_record_bottom">
                            <div class="oe_kanban_bottom_left">
                                <field name="tag_ids" widget="many2many_tags"
                                       options="{'color_field': 'color'}"/>
                            </div>
                            <div class="oe_kanban_bottom_right">
                                <span t-if="record.active_activity_count.raw_value > 0"
                                      class="badge bg-primary">
                                    <i class="fa fa-tasks"/>
                                    <field name="active_activity_count"/>
                                </span>
                                <field name="user_id" widget="many2one_avatar_user"/>
                            </div>
                        </div>
                    </div>
                </t>
            </templates>
        </kanban>
    </field>
</record>
```

### 4.2 Form 視圖

```xml
<record id="view_note_note_form" model="ir.ui.view">
    <field name="name">note.note.form</field>
    <field name="model">note.note</field>
    <field name="arch" type="xml">
        <form string="筆記">
            <header>
                <field name="stage_id" widget="statusbar"
                       options="{'clickable': '1', 'fold_field': 'fold'}"/>
            </header>
            <sheet>
                <widget name="web_ribbon" title="已封存" bg_color="text-bg-danger"
                        invisible="active"/>
                <div class="oe_title">
                    <label for="name" string="標題"/>
                    <h1>
                        <field name="name" placeholder="筆記標題..."/>
                    </h1>
                </div>
                <group>
                    <group>
                        <field name="user_id" widget="many2one_avatar_user"/>
                        <field name="tag_ids" widget="many2many_tags"
                               options="{'color_field': 'color'}"/>
                    </group>
                    <group>
                        <field name="date_done" invisible="open"/>
                        <field name="active" invisible="1"/>
                        <field name="open" invisible="1"/>
                    </group>
                </group>
                <notebook>
                    <page string="內容" name="content">
                        <field name="memo" placeholder="在此輸入筆記內容..."
                               options="{'collaborative': true}"/>
                    </page>
                    <page string="關聯待辦" name="activities">
                        <field name="activity_ids" context="{'active_test': False}">
                            <list>
                                <field name="summary"/>
                                <field name="user_id" widget="many2one_avatar_user"/>
                                <field name="date_deadline" widget="remaining_days"/>
                                <field name="activity_state" widget="badge"
                                       decoration-success="activity_state == 'done'"
                                       decoration-danger="activity_state == 'cancelled'"
                                       decoration-info="activity_state == 'active'"/>
                            </list>
                        </field>
                    </page>
                </notebook>
            </sheet>
            <chatter/>
        </form>
    </field>
</record>
```

---

## 5. weekly.report 視圖規格

### 5.1 Form 視圖

```xml
<record id="view_weekly_report_form" model="ir.ui.view">
    <field name="name">weekly.report.form</field>
    <field name="model">weekly.report</field>
    <field name="arch" type="xml">
        <form string="週報告">
            <header>
                <button name="action_generate_report" string="產生報告"
                        type="object" class="btn-primary"
                        invisible="state != 'draft'"/>
                <button name="action_confirm" string="確認"
                        type="object" class="btn-primary"
                        invisible="state != 'draft'"/>
                <button name="action_reset_draft" string="重設草稿"
                        type="object"
                        invisible="state != 'confirmed'"/>
                <field name="state" widget="statusbar"
                       statusbar_visible="draft,confirmed"/>
            </header>
            <sheet>
                <div class="oe_title">
                    <h1>
                        <field name="name" readonly="1"/>
                    </h1>
                </div>
                <group>
                    <group>
                        <field name="user_id" widget="many2one_avatar_user"/>
                        <field name="week_start"/>
                        <field name="week_end"/>
                        <field name="week_number"/>
                    </group>
                    <group>
                        <field name="total_planned_hours" widget="float_time"/>
                        <field name="completion_rate" widget="progressbar"/>
                        <field name="planned_completion_rate" widget="progressbar"/>
                        <field name="inserted_count"/>
                    </group>
                </group>
                <notebook>
                    <page string="上週執行回顧" name="review">
                        <group>
                            <group>
                                <field name="total_review_planned_hours" widget="float_time"/>
                            </group>
                            <group>
                                <field name="total_review_actual_hours" widget="float_time"/>
                            </group>
                        </group>
                        <field name="previous_week_review_ids">
                            <list>
                                <field name="summary"/>
                                <field name="source" widget="badge"
                                       decoration-info="source == 'planned'"
                                       decoration-warning="source == 'inserted'"/>
                                <field name="status" widget="badge"
                                       decoration-success="status == 'completed'"
                                       decoration-danger="status == 'cancelled'"
                                       decoration-warning="status == 'postponed'"
                                       decoration-info="status == 'pending'"/>
                                <field name="planned_hours" widget="float_time"/>
                                <field name="actual_hours" widget="float_time"/>
                                <field name="hours_diff" widget="float_time"/>
                            </list>
                        </field>
                    </page>
                    <page string="本週計畫" name="this_week">
                        <field name="this_week_snapshot_ids">
                            <list>
                                <field name="summary"/>
                                <field name="planned_date"/>
                                <field name="date_deadline"/>
                                <field name="urgency"/>
                                <field name="importance"/>
                                <field name="estimated_hours" widget="float_time"/>
                            </list>
                        </field>
                    </page>
                    <page string="未來安排" name="future">
                        <field name="future_activity_ids">
                            <list>
                                <field name="summary"/>
                                <field name="scheduled_date"/>
                                <field name="date_deadline"/>
                                <field name="estimated_hours" widget="float_time"/>
                            </list>
                        </field>
                    </page>
                    <page string="尚未安排" name="unscheduled">
                        <field name="unscheduled_activity_ids">
                            <list>
                                <field name="summary"/>
                                <field name="date_deadline"/>
                                <field name="urgency"/>
                                <field name="importance"/>
                                <field name="estimated_hours" widget="float_time"/>
                            </list>
                        </field>
                    </page>
                    <page string="自評建議" name="evaluation">
                        <field name="self_evaluation"
                               placeholder="本週自我評價與下週改進建議..."/>
                    </page>
                </notebook>
            </sheet>
            <chatter/>
        </form>
    </field>
</record>
```

---

## 6. Wizard 視圖規格

### 6.1 完成待辦 Wizard

```xml
<record id="view_mail_activity_done_wizard_form" model="ir.ui.view">
    <field name="name">mail.activity.done.wizard.form</field>
    <field name="model">mail.activity.done.wizard</field>
    <field name="arch" type="xml">
        <form string="完成待辦">
            <group>
                <field name="activity_id" invisible="1"/>
                <field name="summary" readonly="1"/>
                <field name="planned_date" readonly="1"/>
                <field name="estimated_hours" widget="float_time" readonly="1"/>
            </group>
            <group>
                <field name="actual_hours" widget="float_time"/>
                <field name="feedback" placeholder="完成回饋或說明..."/>
                <field name="attachment_ids" widget="many2many_binary"/>
            </group>
            <group string="安排下一次待辦" invisible="not schedule_next">
                <field name="schedule_next"/>
                <field name="next_activity_type_id"
                       invisible="not schedule_next"/>
                <field name="next_date_deadline"
                       invisible="not schedule_next"/>
                <field name="next_summary"
                       invisible="not schedule_next"/>
                <field name="next_user_id"
                       widget="many2one_avatar_user"
                       invisible="not schedule_next"/>
            </group>
            <footer>
                <button name="action_done" string="完成"
                        type="object" class="btn-primary"/>
                <button name="action_done_and_schedule_next"
                        string="完成並安排下一次"
                        type="object" class="btn-secondary"
                        invisible="not schedule_next"/>
                <button name="action_postpone" string="延至下週"
                        type="object" class="btn-secondary"/>
                <button string="取消" special="cancel"/>
            </footer>
        </form>
    </field>
</record>
```

### 6.2 延期 Wizard

```xml
<record id="view_mail_activity_postpone_wizard_form" model="ir.ui.view">
    <field name="name">mail.activity.postpone.wizard.form</field>
    <field name="model">mail.activity.postpone.wizard</field>
    <field name="arch" type="xml">
        <form string="延至下週">
            <group>
                <field name="activity_id" invisible="1"/>
                <field name="summary" readonly="1"/>
                <field name="planned_date" readonly="1"/>
            </group>
            <group>
                <field name="reason" placeholder="請說明延期原因..."/>
            </group>
            <footer>
                <button name="action_postpone" string="確認延期"
                        type="object" class="btn-primary"/>
                <button string="取消" special="cancel"/>
            </footer>
        </form>
    </field>
</record>
```

### 6.3 轉移 Wizard

```xml
<record id="view_mail_activity_transfer_wizard_form" model="ir.ui.view">
    <field name="name">mail.activity.transfer.wizard.form</field>
    <field name="model">mail.activity.transfer.wizard</field>
    <field name="arch" type="xml">
        <form string="轉移待辦">
            <group>
                <field name="activity_id" invisible="1"/>
                <field name="source_model" invisible="1"/>
                <field name="source_id" invisible="1"/>
                <field name="source_display" readonly="1" string="來源"/>
            </group>
            <group>
                <field name="target_ref" string="目標記錄"
                       options="{'no_create': True}"/>
            </group>
            <footer>
                <button name="action_transfer" string="轉移"
                        type="object" class="btn-primary"/>
                <button string="取消" special="cancel"/>
            </footer>
        </form>
    </field>
</record>
```

---

## 7. 選單結構設計

### 7.1 主選單結構

```xml
<!-- 主應用選單 -->
<menuitem id="menu_productivity_root"
          name="生產力工具"
          sequence="260"
          web_icon="dobtor_mail_activity,static/description/icon.png"/>

<!-- 筆記本 -->
<menuitem id="menu_note_notes"
          name="筆記本"
          parent="menu_productivity_root"
          sequence="10"/>

<!-- 代辦事項 -->
<menuitem id="menu_mail_activity_root"
          name="代辦事項"
          parent="menu_productivity_root"
          sequence="20"/>

<menuitem id="menu_mail_activity_my_schedule"
          name="我的待辦事項"
          parent="menu_mail_activity_root"
          action="action_mail_activity_my_schedule"
          sequence="1"/>

<menuitem id="menu_mail_activity_created_by_me"
          name="我建立的待辦"
          parent="menu_mail_activity_root"
          action="action_mail_activity_created_by_me"
          sequence="2"/>

<menuitem id="menu_mail_activity_my_history"
          name="我的歷史代辦"
          parent="menu_mail_activity_root"
          action="action_mail_activity_my_history"
          sequence="3"/>

<!-- 尚未指派 -->
<menuitem id="menu_mail_activity_unassigned"
          name="尚未指派"
          parent="menu_productivity_root"
          action="action_mail_activity_unassigned"
          sequence="30"/>

<!-- 週報告 -->
<menuitem id="menu_weekly_report"
          name="我的報告"
          parent="menu_productivity_root"
          action="action_weekly_report"
          sequence="40"/>

<!-- 效率分析 -->
<menuitem id="menu_efficiency_analysis"
          name="效率分析"
          parent="menu_productivity_root"
          sequence="50"/>

<!-- 設定 -->
<menuitem id="menu_configuration"
          name="設定"
          parent="menu_productivity_root"
          sequence="100"
          groups="group_activity_manager"/>
```

### 7.2 需要隱藏的 project_todo 選單

```xml
<!-- 隱藏 project_todo 主選單 -->
<record id="project_todo.menu_todo" model="ir.ui.menu">
    <field name="active" eval="False"/>
</record>

<!-- 或者限制存取群組 -->
<record id="project_todo.menu_todo" model="ir.ui.menu">
    <field name="groups_id" eval="[(6, 0, [])]"/>
</record>
```

---

## 8. Actions 定義

### 8.1 待辦事項 Actions

```xml
<!-- 我的待辦事項 -->
<record id="action_mail_activity_my_schedule" model="ir.actions.act_window">
    <field name="name">我的待辦事項</field>
    <field name="res_model">mail.activity</field>
    <field name="view_mode">kanban,list,form</field>
    <field name="domain">[('user_id', '=', uid), ('active', '=', True)]</field>
    <field name="context">{'search_default_this_week': 1}</field>
    <field name="search_view_id" ref="view_mail_activity_search"/>
</record>

<!-- 我建立的待辦 -->
<record id="action_mail_activity_created_by_me" model="ir.actions.act_window">
    <field name="name">我建立的待辦</field>
    <field name="res_model">mail.activity</field>
    <field name="view_mode">list,kanban,form</field>
    <field name="domain">[('create_uid', '=', uid), ('user_id', '!=', uid), ('active', '=', True)]</field>
    <field name="search_view_id" ref="view_mail_activity_search"/>
</record>

<!-- 尚未指派 -->
<record id="action_mail_activity_unassigned" model="ir.actions.act_window">
    <field name="name">尚未指派</field>
    <field name="res_model">mail.activity</field>
    <field name="view_mode">list,kanban,form</field>
    <field name="domain">[('user_id', '=', False), ('active', '=', True)]</field>
    <field name="search_view_id" ref="view_mail_activity_search"/>
</record>

<!-- 我的歷史代辦 -->
<record id="action_mail_activity_my_history" model="ir.actions.act_window">
    <field name="name">我的歷史代辦</field>
    <field name="res_model">mail.activity</field>
    <field name="view_mode">list,form</field>
    <field name="domain">['|', ('user_id', '=', uid), ('create_uid', '=', uid), ('active', '=', False)]</field>
    <field name="context">{'active_test': False}</field>
    <field name="search_view_id" ref="view_mail_activity_search"/>
</record>
```

---

**文件版本**: 1.0.0
**建立日期**: 2026-01-15
