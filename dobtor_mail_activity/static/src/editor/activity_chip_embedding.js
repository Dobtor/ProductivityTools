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
 * 膠囊批次讀取器：同一頁多顆膠囊掛載時，將 50ms 內的單筆讀取合併成一次 RPC，
 * 避免 N 顆膠囊 = N 次往返。回傳該活動的精簡 dict（找不到則 null）。
 *
 * 走 get_chip_data 而非直接 orm.read：合併過的待辦會由後端沿 merged_into_id
 * 解析到最終主待辦再回傳。膠囊在 HTML 裡只存原始 activityId，靠這層轉向就能
 * 顯示／開啟主待辦 —— 不必改寫散落在各 html 欄位裡的膠囊，解除合併也自動復原。
 */
/** 整批查詢失敗的哨符：與「查得到但沒這筆」(null) 區分，避免暫時性錯誤被顯示成已刪除。 */
export const CHIP_LOAD_ERROR = Symbol("chipLoadError");

const fetchActivityBrief = createBatchLoader(
    async (orm, ids) => {
        // 回傳的 key 是字串（後端 dict key 經 JSON 序列化），轉回數字對齊 loader
        const byStrId = await orm.call("mail.activity", "get_chip_data", [ids]);
        const byId = {};
        for (const [key, rec] of Object.entries(byStrId || {})) {
            byId[Number(key)] = rec;
        }
        return byId;
    },
    { fallback: null, errorValue: CHIP_LOAD_ERROR }
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
            // 載入失敗（網路/伺服器錯誤）——與 missing（記錄真的不存在）分開
            failed: false,
            // 合併轉向後實際顯示／操作的待辦 id（未合併時等於 props.activityId）
            resolvedId: false,
            redirected: false,
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
            rec = CHIP_LOAD_ERROR;
        }
        if (!this._alive) {
            return;
        }
        if (rec === CHIP_LOAD_ERROR) {
            // 暫時性失敗：保留上一次成功的內容（若有），只標記失敗供樣式與 tooltip 使用
            this.state.failed = true;
            this.state.loaded = true;
            return;
        }
        this.state.failed = false;
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
            // 被併入者的膠囊：後端已解析到主待辦，之後的操作一律針對主待辦
            this.state.resolvedId = rec.id || this.props.activityId;
            this.state.redirected = Boolean(rec.redirected_from);
        } else {
            this.state.missing = true;
            this.state.resolvedId = false;
            this.state.redirected = false;
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
        if (this.state.failed) {
            return "o_chip_failed";
        }
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
        if (this.state.failed) {
            return _t("(load failed)");
        }
        if (this.state.missing) {
            return _t("(deleted)");
        }
        return this.state.summary || _t("To-do");
    }

    /** hover 提示：摘要；被合併轉向時附註實際指向的是主待辦。 */
    get tooltip() {
        if (this.state.failed) {
            return _t("Could not load this to-do. Click to retry.");
        }
        if (this.state.redirected) {
            return _t("Merged — now points to: %s", this.state.summary || "");
        }
        return this.state.summary;
    }

    async onClick() {
        // 載入失敗 → 點擊即重試（而非什麼都不做，使用者才有出路）
        if (this.state.failed) {
            this.state.failed = false;
            return this.load();
        }
        // 一律操作 resolvedId：膠囊指向的待辦若已被合併，這裡是主待辦的 id
        if (this.state.missing || !this.state.resolvedId || !this.state.active) {
            return;
        }
        const action = await this.orm.call("mail.activity", "action_done", [
            [this.state.resolvedId],
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
