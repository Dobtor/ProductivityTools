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
import { browser } from "@web/core/browser/browser";
import {
    notifyActivityChanged,
    subscribeActivityChanged,
} from "@dobtor_mail_activity/editor/activity_signal";

/**
 * 膠囊批次讀取器：同一頁多顆膠囊掛載時，將 50ms 內的單筆 read 合併成一次 RPC，
 * 避免 N 顆膠囊 = N 次往返。回傳該活動的精簡 dict（找不到則 null）。
 */
const CHIP_BATCH_FIELDS = ["summary", "state", "active", "activity_status"];
let _chipPending = new Map(); // id -> [resolve, ...]
let _chipTimer = null;
let _chipOrm = null;

function fetchActivityBrief(orm, id) {
    _chipOrm = orm;
    return new Promise((resolve) => {
        if (!_chipPending.has(id)) {
            _chipPending.set(id, []);
        }
        _chipPending.get(id).push(resolve);
        if (!_chipTimer) {
            _chipTimer = browser.setTimeout(_flushChipBatch, 50);
        }
    });
}

async function _flushChipBatch() {
    const waiters = _chipPending;
    const orm = _chipOrm;
    _chipPending = new Map();
    _chipTimer = null;
    const ids = [...waiters.keys()];
    const byId = {};
    try {
        const recs = await orm.read("mail.activity", ids, CHIP_BATCH_FIELDS, {
            context: { active_test: false },
        });
        for (const r of recs) {
            byId[r.id] = r;
        }
    } catch (e) {
        // 失敗則全部視為缺失（null）
    }
    for (const [id, resolvers] of waiters) {
        resolvers.forEach((resolve) => resolve(byId[id] || null));
    }
}

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
            this.state.missing = false;
        } else {
            this.state.missing = true;
        }
        this.state.loaded = true;
    }

    get chipClass() {
        if (this.state.missing) {
            return "text-muted border-secondary";
        }
        if (!this.state.active) {
            return "o_dobtor_chip_done text-muted border-secondary";
        }
        switch (this.state.state) {
            case "overdue":
                return "text-danger border-danger";
            case "today":
                return "text-warning border-warning";
            default:
                return "text-success border-success";
        }
    }

    get iconClass() {
        if (this.state.missing) {
            return "fa-exclamation-circle";
        }
        return this.state.active ? "fa-clock-o" : "fa-check";
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
        await this.action.doAction(action, {
            onClose: () => notifyActivityChanged(),
        });
    }
}

export const activityChipEmbedding = {
    name: "activityChip",
    Component: EmbeddedActivityChip,
    getProps: (host) => ({ host, ...getEmbeddedProps(host) }),
};

export const readonlyActivityChipEmbedding = activityChipEmbedding;
