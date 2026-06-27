/** @odoo-module **/

/**
 * Inline「活動膠囊」embedded component。
 *
 * 由「/建立待辦」建立成功後，於原游標處插入；data-embedded="activityChip"。
 * 只持久化 activityId，狀態即時抓取：顯示時鐘色點 + 摘要；點擊可開啟完成 wizard。
 * 完成後自動淡化（打勾、刪除線），並監聽重載事件保持與內嵌清單同步。
 */
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { getEmbeddedProps } from "@html_editor/others/embedded_component_utils";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import {
    notifyActivityChanged,
    notifyActivityDeleted,
    subscribeActivityChanged,
} from "@dobtor_mail_activity/editor/activity_signal";
import { ensureActionViews } from "@dobtor_mail_activity/editor/activity_action";
import { createBatchLoader } from "@dobtor_mail_activity/utils/batch_loader";

/**
 * 膠囊批次讀取器：同一頁多顆膠囊掛載時，將 50ms 內的單筆 read 合併成一次 RPC，
 * 避免 N 顆膠囊 = N 次往返。回傳該活動的精簡 dict（找不到則 null）。
 */
const CHIP_BATCH_FIELDS = [
    "summary",
    "state",
    "active",
    "activity_status",
    "user_id",
    "urgency",
    "importance",
    "date_deadline",
];
const fetchActivityBrief = createBatchLoader(
    async (orm, ids) => {
        const recs = await orm.read("mail.activity", ids, CHIP_BATCH_FIELDS, {
            context: { active_test: false },
        });
        const byId = {};
        for (const r of recs) {
            byId[r.id] = r;
        }
        return byId;
    },
    { fallback: null }
);

export class EmbeddedActivityChip extends Component {
    static template = "dobtor_mail_activity.EmbeddedActivityChip";
    static props = {
        host: { type: Object },
        activityId: { type: [Number, Boolean], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            summary: "",
            state: "planned",
            active: true,
            status: "active",
            userId: false,
            urgency: false,
            importance: false,
            dateDeadline: false,
            loaded: false,
            missing: false,
        });
        this._alive = true;
        this._unsubscribe = subscribeActivityChanged(() => this.load());

        onWillStart(() => this.load());
        onWillUnmount(() => {
            this._alive = false;
            this._unsubscribe();
        });
    }

    async load() {
        if (!this.props.activityId) {
            this.state.loaded = true;
            this.state.missing = true;
            return;
        }
        let rec = null;
        try {
            rec = await fetchActivityBrief(this.orm, this.props.activityId);
        } catch (e) {
            rec = null;
        }
        if (!this._alive) {
            return;
        }
        if (rec) {
            this.state.summary = rec.summary || "";
            this.state.state = rec.state || "planned";
            this.state.active = rec.active;
            this.state.status = rec.activity_status;
            this.state.userId = rec.user_id ? rec.user_id[0] : false;
            this.state.urgency = rec.urgency;
            this.state.importance = rec.importance;
            this.state.dateDeadline = rec.date_deadline || false;
            this.state.missing = false;
        } else {
            this.state.missing = true;
        }
        this.state.loaded = true;
    }

    get avatarUrl() {
        return this.state.userId
            ? `/web/image/res.users/${this.state.userId}/avatar_128`
            : false;
    }

    /**
     * 膠囊語意配色 class（外框線＋淡色底）。優先序：優先狀態 > 緊急程度。
     *   刪除/取消 → 灰；完成 → 綠；逾期 → 深紅；
     *   其餘依緊急程度：緊急 → 深橘、標準 → 深藍、彈性 → 深綠。
     * （颜色定義集中在 activity_editor.scss 的 o_chip_* class）
     */
    get chipClass() {
        if (this.state.missing) {
            return "o_chip_deleted";
        }
        if (!this.state.active) {
            return this.state.status === "cancelled" ? "o_chip_cancelled" : "o_chip_done";
        }
        if (this.state.state === "overdue") {
            return "o_chip_overdue";
        }
        switch (this.state.urgency) {
            case "urgent":
                return "o_chip_urgent";
            case "flexible":
                return "o_chip_flexible";
            default: // standard 或未設定
                return "o_chip_standard";
        }
    }

    get label() {
        if (this.state.missing) {
            return _t("(deleted)");
        }
        return this.state.summary || _t("To-do");
    }

    async onClick() {
        if (this.state.missing || !this.props.activityId || !this.state.active) {
            return;
        }
        const action = await this.orm.call("mail.activity", "action_done", [
            [this.props.activityId],
        ]);
        await this.action.doAction(ensureActionViews(action), {
            // 完成 wizard 內按「刪除」會回傳 deleted_activity_id：
            // 廣播刪除訊號讓所有編輯器移除對應膠囊；否則僅一般重載。
            onClose: (infos) => {
                if (infos && infos.deleted_activity_id) {
                    notifyActivityDeleted(infos.deleted_activity_id);
                } else {
                    notifyActivityChanged();
                }
            },
        });
    }
}

export const activityChipEmbedding = {
    name: "activityChip",
    Component: EmbeddedActivityChip,
    getProps: (host) => ({ host, ...getEmbeddedProps(host) }),
};

export const readonlyActivityChipEmbedding = activityChipEmbedding;
