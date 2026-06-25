/** @odoo-module **/

/**
 * 富文字編輯器工具列「活動時鐘」按鈕。
 *
 * 注意：html_editor 的浮動工具列僅在「選取文字」時出現，故此時鐘為選取時可見、
 * 非永久常駐（永久常駐的檢視面請用「/活動清單」內嵌區塊）。
 *
 * 行為比照原生列表視圖時鐘：依最近 deadline 著色（紅逾期/黃今天/綠已排程），
 * 點擊開啟原生 ActivityListPopover（時鐘清單 + fa-check 標記完成 + 排程）。
 */
import { Component, useState, useRef, onWillStart, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/core/popover/popover_hook";
import { ActivityListPopover } from "@mail/core/web/activity_list_popover";
import {
    getClockCache,
    setClockCache,
    deleteClockCache,
    notifyActivityChanged,
    subscribeActivityChanged,
} from "@dobtor_mail_activity/editor/activity_signal";

export class ActivityClockToolbarButton extends Component {
    static template = "dobtor_mail_activity.ActivityClockToolbarButton";
    static props = {
        getRecordInfo: { type: Function },
        getSelection: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.rootRef = useRef("root");
        this.popover = usePopover(ActivityListPopover, { position: "bottom-start" });
        this.state = useState({ activityIds: [], worst: "none" });
        this._alive = true;
        this._unsubscribe = subscribeActivityChanged(() => this.load());
        onWillStart(() => this.load());
        onWillUnmount(() => {
            this._alive = false;
            this._unsubscribe();
        });
    }

    /** 解析此編輯器所綁定的記錄；無記錄則退回個人待辦筆記。 */
    async resolveRecord() {
        let { resModel, resId } = this.props.getRecordInfo() || {};
        if (!resModel || !resId) {
            resModel = "note.note";
            resId = await this.orm.call("mail.activity", "get_editor_default_note_id", []);
        }
        return { resModel, resId };
    }

    async load() {
        try {
            const { resModel, resId } = await this.resolveRecord();
            this._resModel = resModel;
            this._resId = resId;
            if (!resModel || !resId) {
                this.state.activityIds = [];
                this.state.worst = "none";
                return;
            }
            const key = `${resModel}:${resId}`;
            const cached = getClockCache(key);
            if (cached) {
                this.state.activityIds = cached.activityIds;
                this.state.worst = cached.worst;
                return;
            }
            const bind = resModel === "note.note" ? "note" : "res";
            const noteId = resModel === "note.note" ? resId : false;
            // 輕量查詢：只回 ids + 最嚴重狀態（不組完整清單 dict）。
            const summary = await this.orm.call("mail.activity", "get_editor_activity_summary", [
                bind,
                resModel,
                resId,
                noteId,
            ]);
            if (!this._alive) {
                return;
            }
            const activityIds = summary.ids || [];
            const worst = summary.worst || "none";
            this.state.activityIds = activityIds;
            this.state.worst = worst;
            setClockCache(key, { activityIds, worst });
        } catch (e) {
            // 時鐘失敗不可拖垮整個格式工具列，退回中性狀態。
            this.state.activityIds = [];
            this.state.worst = "none";
        }
    }

    get iconClass() {
        switch (this.state.worst) {
            case "overdue":
                return "text-danger";
            case "today":
                return "text-warning";
            case "planned":
                return "text-success";
            default:
                return "text-muted";
        }
    }

    get title() {
        return this.state.activityIds.length
            ? _t("%s activities", this.state.activityIds.length)
            : _t("Show activities");
    }

    onClick() {
        if (this.popover.isOpen) {
            this.popover.close();
            return;
        }
        if (!this._resModel || !this._resId) {
            return;
        }
        this.popover.open(this.rootRef.el, {
            activityIds: this.state.activityIds,
            resModel: this._resModel,
            resId: this._resId,
            onActivityChanged: () => {
                // 廣播變更：清快取並讓時鐘/清單/膠囊全部重載。
                deleteClockCache(`${this._resModel}:${this._resId}`);
                notifyActivityChanged();
                this.popover.close();
            },
        });
    }
}
