# 前端規格 (JavaScript Specification)

## 1. 架構概述

### 1.1 Odoo 14 vs Odoo 18 JavaScript 架構差異

| 方面 | Odoo 14 | Odoo 18 |
|------|---------|---------|
| 框架版本 | OWL 1.x | OWL 2.x |
| 模組系統 | `odoo.define()` | ES6 Modules |
| 類別定義 | `Class.extend()` | `class extends` |
| Patch 語法 | `patch(Class)` | `patch(Class.prototype)` |
| 資源聲明 | `qweb`, `assets.xml` | `__manifest__.py` assets |

### 1.2 Odoo 18 資源聲明

```python
# __manifest__.py
{
    'assets': {
        'web.assets_backend': [
            # 組件
            'dobtor_mail_activity/static/src/components/**/*',
            # 視圖擴展
            'dobtor_mail_activity/static/src/views/**/*',
            # 系統欄整合
            'dobtor_mail_activity/static/src/web/**/*',
            # 樣式
            'dobtor_mail_activity/static/src/scss/**/*',
        ],
        'web.assets_unit_tests': [
            'dobtor_mail_activity/static/tests/**/*',
        ],
    },
}
```

---

## 2. OWL 2.0 組件清單

### 2.1 組件目錄結構

```
static/src/
├── components/
│   ├── activity_done_checkmark/
│   │   ├── activity_done_checkmark.js
│   │   ├── activity_done_checkmark.xml
│   │   └── activity_done_checkmark.scss
│   ├── activity_chatter_panel/
│   │   ├── activity_chatter_panel.js
│   │   └── activity_chatter_panel.xml
│   ├── related_notes/
│   │   ├── related_notes.js
│   │   ├── related_notes.xml
│   │   └── related_notes.scss
│   ├── activity_box/
│   │   ├── activity_box.js
│   │   └── activity_box.xml
│   └── week_selector/
│       ├── week_selector.js
│       ├── week_selector.xml
│       └── week_selector.scss
├── views/
│   ├── activity_kanban/
│   │   ├── activity_kanban_controller.js
│   │   ├── activity_kanban_renderer.js
│   │   └── activity_kanban_view.js
│   ├── activity_list/
│   │   ├── activity_list_controller.js
│   │   └── activity_list_view.js
│   └── activity_form/
│       ├── activity_form_controller.js
│       └── activity_form_view.js
├── web/
│   └── activity/
│       └── activity_menu_patch.js
└── scss/
    ├── activity.scss
    ├── week_selector.scss
    └── related_notes.scss
```

---

## 3. 從 project_todo 移植的組件

### 3.1 ActivityDoneCheckmark (移植自 todo_done_checkmark)

**原始檔案**: `project_todo/static/src/components/todo_done_checkmark/`

**移植後檔案**: `dobtor_mail_activity/static/src/components/activity_done_checkmark/`

#### activity_done_checkmark.js

```javascript
/** @odoo-module */

import { useState, onRendered, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import {
    StateSelectionField,
    stateSelectionField
} from "@web/views/fields/state_selection/state_selection_field";

export class ActivityDoneCheckmark extends StateSelectionField {
    static template = "dobtor_mail_activity.ActivityDoneCheckmark";
    static props = {
        ...stateSelectionField.component.props,
        viewType: { type: String },
    };

    setup() {
        super.setup();
        this.stateDone = useState({
            isDone: false,
            notReloadState: false,
        });

        onMounted(() => {
            // 針對 mail.activity 的 activity_state 欄位
            const fieldValue = this.props.record.data[this.props.name];
            this.notDoneState = fieldValue === 'done' ? 'active' : fieldValue;
        });

        onRendered(() => {
            if (!this.stateDone.notReloadState) {
                this.stateDone.isDone = this.props.record.data[this.props.name] === 'done';
            }
        });
    }

    /**
     * 切換完成狀態
     */
    async onDoneToggled(ev) {
        const currentValue = this.props.record.data[this.props.name];
        const newValue = currentValue !== 'done' ? 'done' : this.notDoneState;

        if (['kanban', 'list'].includes(this.props.viewType)) {
            await super.updateRecord(newValue);
        } else {
            await this.props.record.update({
                [this.props.name]: newValue,
            });
        }

        // 如果標記為完成，開啟完成 wizard
        if (newValue === 'done') {
            await this.openDoneWizard();
        }
    }

    async openDoneWizard() {
        const activityId = this.props.record.resId;
        const action = await this.env.services.orm.call(
            'mail.activity',
            'action_done_wizard',
            [[activityId]]
        );
        this.env.services.action.doAction(action, {
            onClose: () => {
                this.props.record.load();
            },
        });
    }

    actualizeDoneState(ev) {
        this.stateDone.notReloadState = false;
    }

    freezeDoneState(ev) {
        this.stateDone.notReloadState = true;
    }
}

export const activityDoneCheckmark = {
    ...stateSelectionField,
    component: ActivityDoneCheckmark,
    extractProps: (fieldInfo, dynamicInfo) => {
        const props = stateSelectionField.extractProps(fieldInfo, dynamicInfo);
        props.viewType = fieldInfo.viewType;
        return props;
    },
};

registry.category("fields").add("activity_done_checkmark", activityDoneCheckmark);
```

#### activity_done_checkmark.xml

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="dobtor_mail_activity.ActivityDoneCheckmark">
        <div class="o_activity_done_checkmark d-flex align-items-center"
             t-on-mouseleave="actualizeDoneState"
             t-on-mouseenter="freezeDoneState">
            <button class="btn p-0 border-0"
                    t-att-class="{'text-success': stateDone.isDone, 'text-muted': !stateDone.isDone}"
                    t-on-click="onDoneToggled"
                    title="標記完成">
                <i t-att-class="stateDone.isDone ? 'fa fa-check-circle fa-lg' : 'fa fa-circle-o fa-lg'"/>
            </button>
        </div>
    </t>
</templates>
```

#### activity_done_checkmark.scss

```scss
.o_activity_done_checkmark {
    .btn {
        transition: all 0.2s ease;

        &:hover {
            transform: scale(1.1);
        }

        &.text-success {
            color: #28a745 !important;
        }

        &.text-muted {
            color: #6c757d !important;

            &:hover {
                color: #28a745 !important;
            }
        }
    }
}
```

### 3.2 ActivityChatterPanel (移植自 todo_chatter_panel)

**原始檔案**: `project_todo/static/src/components/todo_chatter_panel/`

**移植後檔案**: `dobtor_mail_activity/static/src/components/activity_chatter_panel/`

#### activity_chatter_panel.js

```javascript
/** @odoo-module */

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { Component, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { useBus } from "@web/core/utils/hooks";

export class ActivityChatterPanel extends Component {
    static template = "dobtor_mail_activity.ActivityChatterPanel";
    static components = { Chatter };
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        this.state = useState({
            displayChatter: this.env.isSmall,
        });
        this.rootRef = useRef("root");
        useBus(this.env.bus, "ACTIVITY:TOGGLE_CHATTER", this.toggleChatter);
    }

    toggleChatter(ev) {
        this.state.displayChatter = ev.detail.displayChatter;
        this.rootRef.el?.parentElement?.classList.toggle('d-none', !this.state.displayChatter);
    }
}

export const activityChatterPanel = {
    component: ActivityChatterPanel,
    additionalClasses: [
        "o_activity_chatter",
        "d-none",
        "position-relative",
        "p-0",
        "overflow-y-auto"
    ],
};

registry.category("view_widgets").add("activity_chatter_panel", activityChatterPanel);
```

#### activity_chatter_panel.xml

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="dobtor_mail_activity.ActivityChatterPanel">
        <div t-ref="root" class="o_activity_chatter_panel h-100">
            <Chatter
                t-if="state.displayChatter"
                threadModel="props.record.resModel"
                threadId="props.record.resId"
                hasActivities="false"
                hasFollowers="false"
                hasMessageList="true"
                isChatterAside="true"/>
        </div>
    </t>
</templates>
```

---

## 4. 系統欄整合設計

### 4.1 ActivityMenuPatch (整合 project_todo 設計)

**檔案**: `static/src/web/activity/activity_menu_patch.js`

```javascript
/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { ActivityMenu } from "@mail/core/web/activity_menu";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { useCommand } from "@web/core/commands/command_hook";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";

// 註冊待辦指令類別
registry.category("command_categories").add("dobtor-activity", {}, { sequence: 105 });

patch(ActivityMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.dialogService = useService("dialog");
        this.actionService = useService("action");

        // 全域快捷鍵 Alt+Shift+A: 新增待辦
        useCommand(
            _t("新增待辦"),
            () => {
                document.body.click(); // 關閉指令面板
                this.createActivity();
            },
            {
                category: "dobtor-activity",
                hotkey: "alt+shift+a",
                global: true,
            }
        );

        // 全域快捷鍵 Alt+Shift+N: 新增筆記
        useCommand(
            _t("新增筆記"),
            () => {
                document.body.click();
                this.createNote();
            },
            {
                category: "dobtor-activity",
                hotkey: "alt+shift+n",
                global: true,
            }
        );
    },

    /**
     * 建立新待辦
     */
    async createActivity() {
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: _t('新增待辦'),
            res_model: 'mail.activity',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: {
                default_user_id: this.userId,
                form_view_ref: 'mail.mail_activity_view_form_popup',
            },
        });
    },

    /**
     * 建立新筆記
     */
    async createNote() {
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: _t('新增筆記'),
            res_model: 'note.note',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
        });
    },

    /**
     * 覆寫：判斷是否為待辦活動群組
     */
    availableViews(group) {
        // dobtor_mail_activity 使用 mail.activity
        // 不需要像 project_todo 那樣使用特殊視圖
        return super.availableViews(group);
    },

    /**
     * 覆寫：活動群組的點擊處理
     */
    async openActivityGroup(group, filter = "all") {
        // 可在此加入自定義邏輯
        return super.openActivityGroup(...arguments);
    },
});
```

---

## 5. 自定義組件

### 5.1 RelatedNotes 組件

**功能**: 在 Chatter 中顯示關聯筆記

#### related_notes.js

```javascript
/** @odoo-module */

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class RelatedNotes extends Component {
    static template = "dobtor_mail_activity.RelatedNotes";
    static props = {
        resModel: { type: String },
        resId: { type: Number },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            isExpanded: true,
            expandedNotes: {},
            notes: [],
            isLoading: true,
        });

        onWillStart(async () => {
            await this.loadNotes();
        });
    }

    async loadNotes() {
        this.state.isLoading = true;
        try {
            const notes = await this.orm.call(
                'mail.activity',
                'get_related_notes',
                [this.props.resModel, this.props.resId]
            );
            this.state.notes = notes;
        } catch (e) {
            console.error('Failed to load related notes:', e);
            this.state.notes = [];
        }
        this.state.isLoading = false;
    }

    toggleSection() {
        this.state.isExpanded = !this.state.isExpanded;
    }

    toggleNoteActivities(noteId) {
        this.state.expandedNotes[noteId] = !this.state.expandedNotes[noteId];
    }

    async openNote(noteId) {
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'note.note',
            res_id: noteId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    async openActivity(activityId) {
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'mail.activity',
            res_id: activityId,
            views: [[false, 'form']],
            target: 'new',
        });
    }
}
```

#### related_notes.xml

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="dobtor_mail_activity.RelatedNotes">
        <div class="o_related_notes" t-if="state.notes.length > 0">
            <!-- 標題列 -->
            <div class="o_related_notes_header d-flex align-items-center p-2 bg-light cursor-pointer"
                 t-on-click="toggleSection">
                <i t-attf-class="fa fa-caret-#{state.isExpanded ? 'down' : 'right'} me-2"/>
                <span class="fw-bold">關聯筆記</span>
                <span class="badge bg-secondary ms-2" t-esc="state.notes.length"/>
            </div>

            <!-- 筆記列表 -->
            <div t-if="state.isExpanded" class="o_related_notes_content">
                <t t-foreach="state.notes" t-as="note" t-key="note.id">
                    <div class="o_related_note_item border-bottom p-2">
                        <!-- 筆記標題 -->
                        <div class="d-flex align-items-center">
                            <i class="fa fa-sticky-note-o me-2 text-muted"/>
                            <a href="#" class="text-decoration-none"
                               t-on-click.prevent="() => this.openNote(note.id)">
                                <t t-esc="note.name"/>
                            </a>
                            <span class="ms-auto">
                                <span t-if="note.is_all_done" class="badge bg-success">
                                    全部完成
                                </span>
                                <span t-else="" class="badge bg-info">
                                    <t t-esc="note.active_count"/>/<t t-esc="note.total_count"/>
                                </span>
                            </span>
                            <button class="btn btn-sm btn-link p-0 ms-2"
                                    t-on-click="() => this.toggleNoteActivities(note.id)">
                                <i t-attf-class="fa fa-chevron-#{state.expandedNotes[note.id] ? 'up' : 'down'}"/>
                            </button>
                        </div>

                        <!-- 待辦列表 -->
                        <div t-if="state.expandedNotes[note.id]" class="o_note_activities mt-2 ps-4">
                            <t t-foreach="note.activities" t-as="activity" t-key="activity.id">
                                <div class="o_activity_item d-flex align-items-center py-1">
                                    <i t-attf-class="fa fa-#{activity.state == 'active' ? 'circle-o' : activity.state == 'done' ? 'check-circle text-success' : 'times-circle text-danger'} me-2"/>
                                    <a href="#" class="text-decoration-none small"
                                       t-att-class="{'text-muted text-decoration-line-through': activity.state != 'active'}"
                                       t-on-click.prevent="() => this.openActivity(activity.id)">
                                        <t t-esc="activity.summary || '(無摘要)'"/>
                                    </a>
                                </div>
                            </t>
                        </div>
                    </div>
                </t>
            </div>
        </div>
    </t>
</templates>
```

### 5.2 WeekSelector 組件

**功能**: 週次選擇器，用於多週預排

#### week_selector.js

```javascript
/** @odoo-module */

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class WeekSelector extends Component {
    static template = "dobtor_mail_activity.WeekSelector";
    static props = {
        onWeekSelect: { type: Function },
        currentWeek: { type: Number, optional: true },
    };

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            weeks: [],
            selectedWeek: this.props.currentWeek || 0,
            isLoading: true,
        });

        onWillStart(async () => {
            await this.loadWeekInfo();
        });
    }

    async loadWeekInfo() {
        this.state.isLoading = true;
        try {
            const weeks = await this.orm.call(
                'mail.activity',
                'get_week_info',
                []
            );
            this.state.weeks = weeks;
        } catch (e) {
            console.error('Failed to load week info:', e);
        }
        this.state.isLoading = false;
    }

    selectWeek(weekNumber) {
        this.state.selectedWeek = weekNumber;
        this.props.onWeekSelect(weekNumber);
    }

    getWeekClass(week) {
        const classes = ['o_week_item', 'p-2', 'rounded', 'cursor-pointer'];
        if (week.number === this.state.selectedWeek) {
            classes.push('bg-primary', 'text-white');
        } else {
            classes.push('bg-light');
        }
        if (week.number === 0) {
            classes.push('fw-bold');
        }
        return classes.join(' ');
    }
}
```

#### week_selector.xml

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="dobtor_mail_activity.WeekSelector">
        <div class="o_week_selector d-flex gap-2 flex-wrap">
            <t t-if="state.isLoading">
                <div class="text-muted">
                    <i class="fa fa-spinner fa-spin"/> 載入中...
                </div>
            </t>
            <t t-else="">
                <t t-foreach="state.weeks" t-as="week" t-key="week.key">
                    <div t-att-class="getWeekClass(week)"
                         t-on-click="() => this.selectWeek(week.number)"
                         t-att-title="week.start_date + ' ~ ' + week.end_date">
                        <div class="small fw-bold" t-esc="week.name"/>
                        <div class="small text-muted">
                            <i class="fa fa-tasks me-1"/>
                            <span t-esc="week.count"/>
                            <i class="fa fa-clock-o ms-2 me-1"/>
                            <span t-esc="week.total_hours + 'h'"/>
                        </div>
                    </div>
                </t>
            </t>
        </div>
    </t>
</templates>
```

#### week_selector.scss

```scss
.o_week_selector {
    .o_week_item {
        min-width: 100px;
        transition: all 0.2s ease;
        border: 1px solid transparent;

        &:hover {
            border-color: var(--primary);
            transform: translateY(-2px);
        }

        &.bg-primary {
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        }
    }
}
```

---

## 6. 視圖擴展

### 6.1 ActivityKanbanController

**檔案**: `static/src/views/activity_kanban/activity_kanban_controller.js`

```javascript
/** @odoo-module */

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";

export class ActivityKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
    }

    /**
     * 批次延期選中的待辦
     */
    async onBatchPostpone() {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            return;
        }

        // 開啟批次延期 wizard
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: '批次延期',
            res_model: 'mail.activity.postpone.wizard',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: {
                default_activity_ids: selectedRecords.map(r => r.resId),
            },
        });
    }

    /**
     * 週次快速切換
     */
    async scheduleToWeek(weekNumber) {
        const selectedRecords = this.model.root.selection;
        if (!selectedRecords.length) {
            return;
        }

        const activityIds = selectedRecords.map(r => r.resId);
        await this.orm.call(
            'mail.activity',
            'action_schedule_to_week',
            [activityIds, weekNumber]
        );

        await this.model.root.load();
    }
}
```

### 6.2 ActivityKanbanView

**檔案**: `static/src/views/activity_kanban/activity_kanban_view.js`

```javascript
/** @odoo-module */

import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { ActivityKanbanController } from "./activity_kanban_controller";

export const activityKanbanView = {
    ...kanbanView,
    Controller: ActivityKanbanController,
};

registry.category("views").add("activity_kanban", activityKanbanView);
```

---

## 7. 快捷鍵配置

### 7.1 全域快捷鍵

| 快捷鍵 | 功能 | 說明 |
|--------|------|------|
| Alt+Shift+A | 新增待辦 | 開啟待辦建立表單 |
| Alt+Shift+N | 新增筆記 | 開啟筆記建立表單 |
| Alt+Shift+W | 開啟週報 | 開啟本週週報告 |

### 7.2 視圖內快捷鍵

| 快捷鍵 | 功能 | 適用視圖 |
|--------|------|---------|
| D | 標記完成 | Kanban/List |
| P | 延期 | Kanban/List |
| T | 轉移 | Form |
| C | 取消 | Form |

---

## 8. 樣式規範

### 8.1 主要 SCSS 變數

```scss
// static/src/scss/_variables.scss
$activity-urgent-color: #dc3545;
$activity-standard-color: #ffc107;
$activity-flexible-color: #28a745;

$activity-important-bg: rgba($activity-urgent-color, 0.1);
$activity-done-opacity: 0.5;

$week-selector-gap: 0.5rem;
$kanban-card-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
```

### 8.2 活動卡片樣式

```scss
// static/src/scss/activity.scss
.o_activity_kanban {
    .o_kanban_record {
        border-radius: 8px;
        transition: all 0.2s ease;

        &:hover {
            box-shadow: $kanban-card-shadow;
            transform: translateY(-2px);
        }
    }

    .o_activity_card {
        &.border-danger {
            border-left: 4px solid $activity-urgent-color !important;
        }

        &.fw-bold {
            background-color: $activity-important-bg;
        }
    }
}

// 完成狀態
.o_activity_done {
    opacity: $activity-done-opacity;
    text-decoration: line-through;
}
```

---

## 9. 測試規範

### 9.1 單元測試結構

```
static/tests/
├── activity_done_checkmark.test.js
├── activity_chatter_panel.test.js
├── related_notes.test.js
├── week_selector.test.js
└── activity_kanban_view.test.js
```

### 9.2 測試範例

```javascript
/** @odoo-module */

import { click, getFixture, mount } from "@web/../tests/helpers/utils";
import { makeTestEnv } from "@web/../tests/helpers/mock_env";
import { ActivityDoneCheckmark } from "@dobtor_mail_activity/components/activity_done_checkmark/activity_done_checkmark";

QUnit.module("ActivityDoneCheckmark", (hooks) => {
    let target;
    let env;

    hooks.beforeEach(async () => {
        target = getFixture();
        env = await makeTestEnv();
    });

    QUnit.test("renders correctly for active state", async (assert) => {
        const mockRecord = {
            data: { activity_state: 'active' },
            resId: 1,
        };

        await mount(ActivityDoneCheckmark, target, {
            env,
            props: {
                record: mockRecord,
                name: 'activity_state',
                viewType: 'kanban',
            },
        });

        assert.containsOnce(target, '.fa-circle-o');
        assert.containsNone(target, '.fa-check-circle');
    });

    QUnit.test("toggles state on click", async (assert) => {
        const mockRecord = {
            data: { activity_state: 'active' },
            resId: 1,
            update: async (vals) => {
                assert.equal(vals.activity_state, 'done');
            },
        };

        await mount(ActivityDoneCheckmark, target, {
            env,
            props: {
                record: mockRecord,
                name: 'activity_state',
                viewType: 'form',
            },
        });

        await click(target, '.btn');
    });
});
```

---

**文件版本**: 1.0.0
**建立日期**: 2026-01-15
