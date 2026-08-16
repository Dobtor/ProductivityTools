/** @odoo-module **/

/**
 * 工具列中央的主題搜尋 / 篩選。
 *
 * 與 MindmapProjectBar、MindmapPager 同樣的理由獨立成子元件：MindmapEditor 是
 * 命令式的 god-component，把 jsMind 掛在原生 DOM ref 上；反應式狀態放在這裡，
 * 變動時只重繪本元件，永遠不會動到畫布。
 *
 * 作用範圍是「當前顯示的這份心智圖的主題」，不是跨工作簿搜尋 —— 命中的主題
 * 高亮、其餘淡化，由父層在畫布上套用（_onSearchChange）。
 *
 * 篩選條件對照 project.task 的搜尋視圖（view_task_search_form_base），只取
 * 在主題上真的有對應資料的那些：主題同步時會帶入 taskId / 負責人 / 進度 /
 * 截止日（見 xmind.workbook._topic_to_jsmind）。刻意不做「分組」——
 * 心智圖的層級本身就是它的分組，重排樹會破壞使用者自己排的版面。
 */
import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

/** 可用的篩選條件。predicate 收到 jsMind 節點的 data 物件。 */
export const MINDMAP_FILTERS = [
    {
        key: "linked",
        label: _t("Linked to a task"),
        predicate: (d) => Boolean(d.taskId),
    },
    {
        key: "unassigned",
        label: _t("Unassigned"),
        predicate: (d) => !(d.assignees && d.assignees.length),
    },
    {
        key: "done",
        label: _t("Done"),
        predicate: (d) => Number(d.taskInfo?.progress || 0) >= 100,
    },
    {
        key: "open",
        label: _t("Not done"),
        predicate: (d) => Number(d.taskInfo?.progress || 0) < 100,
    },
    {
        key: "has_deadline",
        label: _t("Has a deadline"),
        predicate: (d) => Boolean(d.taskInfo?.end),
    },
    {
        key: "overdue",
        label: _t("Overdue"),
        predicate: (d) => {
            const end = d.taskInfo?.end;
            if (!end) {
                return false;
            }
            // 只比日期，不比時分：截止「今天」不算逾期
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            return new Date(end) < today && Number(d.taskInfo?.progress || 0) < 100;
        },
    },
];

export class MindmapSearch extends Component {
    static template = "dobtor_xmind.MindmapSearch";
    static props = {
        /** (query, activeFilterKeys) => void；父層據此在畫布上標示命中。 */
        onSearchChange: { type: Function, optional: true },
        /** 命中數 / 總數，由父層回填顯示。 */
        hitCount: { type: [Number, Boolean], optional: true },
    };

    setup() {
        this.filters = MINDMAP_FILTERS;
        this.state = useState({
            query: "",
            active: [],        // 已選的 filter key
            menuOpen: false,
            hits: null,        // null = 沒在搜尋
            total: 0,
        });
    }

    get hasCriteria() {
        return Boolean(this.state.query.trim()) || this.state.active.length > 0;
    }

    /** 已選條件的 facet（顯示在搜尋框內，可個別移除）。 */
    get activeFacets() {
        return this.filters.filter((f) => this.state.active.includes(f.key));
    }

    _notify() {
        const result = this.props.onSearchChange?.(
            this.state.query.trim(),
            this.state.active
        );
        // 父層回傳 {hits, total} 供顯示計數；沒回傳就不顯示
        if (result && typeof result === "object") {
            this.state.hits = result.hits;
            this.state.total = result.total;
        } else {
            this.state.hits = null;
        }
    }

    onQueryInput(ev) {
        this.state.query = ev.target.value;
        this._notify();
    }

    onToggleFilter(key) {
        const idx = this.state.active.indexOf(key);
        if (idx >= 0) {
            this.state.active.splice(idx, 1);
        } else {
            this.state.active.push(key);
        }
        this._notify();
    }

    onRemoveFacet(key) {
        this.onToggleFilter(key);
    }

    onClear() {
        this.state.query = "";
        this.state.active = [];
        this.state.menuOpen = false;
        this._notify();
    }

    onToggleMenu() {
        this.state.menuOpen = !this.state.menuOpen;
    }

    get countLabel() {
        if (this.state.hits === null || !this.hasCriteria) {
            return "";
        }
        return _t("%(hits)s / %(total)s", {
            hits: this.state.hits,
            total: this.state.total,
        });
    }
}
