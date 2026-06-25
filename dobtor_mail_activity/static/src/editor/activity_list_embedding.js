/** @odoo-module **/

/**
 * 內嵌「即時活動清單」embedded component。
 *
 * 由 powerbox 的「活動清單」指令插入；data-embedded="activityList"。
 * 區塊只持久化「綁定資訊」(bind / noteId / resModel / resId)，活動資料一律
 * 於掛載時即時向後端抓取（get_editor_activities），確保永遠顯示 DB 最新狀態，
 * 不會 stale。可直接勾選完成、可原地新增。
 */
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { getEmbeddedProps } from "@html_editor/others/embedded_component_utils";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import {
    notifyActivityChanged,
    subscribeActivityChanged,
} from "@dobtor_mail_activity/editor/activity_signal";

export class EmbeddedActivityList extends Component {
    static template = "dobtor_mail_activity.EmbeddedActivityList";
    static props = {
        host: { type: Object },
        bind: { type: String, optional: true },
        noteId: { type: [Number, Boolean], optional: true },
        resModel: { type: [String, Boolean], optional: true },
        resId: { type: [Number, Boolean], optional: true },
    };

    static PAGE_SIZE = 20;

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            activities: [],
            loading: true,
            hasMore: false,
            limit: EmbeddedActivityList.PAGE_SIZE,
        });
        this._alive = true;
        this._unsubscribe = subscribeActivityChanged(() => this.load());

        onWillStart(() => this.load());
        onWillUnmount(() => {
            this._alive = false;
            this._unsubscribe();
        });
    }

    get bindParams() {
        return {
            bind: this.props.bind || "personal",
            res_model: this.props.resModel || false,
            res_id: this.props.resId || false,
            note_id: this.props.noteId || false,
        };
    }

    async load() {
        this.state.loading = true;
        try {
            const p = this.bindParams;
            const res = await this.orm.call("mail.activity", "get_editor_activities", [
                p.bind,
                p.res_model,
                p.res_id,
                p.note_id,
                this.state.limit,
            ]);
            if (!this._alive) {
                return;
            }
            this.state.activities = res.activities || [];
            this.state.hasMore = !!res.has_more;
        } catch (e) {
            this.state.activities = [];
            this.state.hasMore = false;
        } finally {
            if (this._alive) {
                this.state.loading = false;
            }
        }
    }

    /** 顯示更多：擴大上限後重抓。 */
    showMore() {
        this.state.limit += EmbeddedActivityList.PAGE_SIZE;
        this.load();
    }

    get activeActivities() {
        return this.state.activities.filter((a) => a.active);
    }

    get doneActivities() {
        return this.state.activities.filter((a) => !a.active);
    }

    /** 依狀態回傳時鐘色點 class（比照原生列表視圖著色）。 */
    stateClass(act) {
        if (!act.active) {
            return "text-muted";
        }
        switch (act.state) {
            case "overdue":
                return "text-danger";
            case "today":
                return "text-warning";
            default:
                return "text-success";
        }
    }

    /** 勾選完成：沿用模組標準完成 wizard（可填工時/回饋）。 */
    async onMarkDone(act) {
        const action = await this.orm.call("mail.activity", "action_done", [[act.id]]);
        await this.action.doAction(action, {
            onClose: () => this._broadcastReload(),
        });
    }

    /** 原地新增待辦：依綁定情境帶入 wizard 預設關聯。 */
    async onAddTodo() {
        const p = this.bindParams;
        const ctx = { default_summary: "" };
        if (p.bind === "res") {
            ctx.default_editor_res_model = p.res_model;
            ctx.default_editor_res_id = p.res_id;
        } else if (p.note_id) {
            ctx.default_editor_res_model = "note.note";
            ctx.default_editor_res_id = p.note_id;
        }
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Create To-do"),
                res_model: "mail.activity.from.editor.wizard",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: ctx,
            },
            { onClose: () => this._broadcastReload() }
        );
    }

    /** 通知所有清單/膠囊/時鐘（含自己）重載。 */
    _broadcastReload() {
        notifyActivityChanged();
    }
}

export const activityListEmbedding = {
    name: "activityList",
    Component: EmbeddedActivityList,
    getProps: (host) => ({ host, ...getEmbeddedProps(host) }),
};

// 唯讀模式沿用同一元件（清單本就即時抓取；完成/新增依使用者權限決定可用性）。
export const readonlyActivityListEmbedding = activityListEmbedding;
