/** @odoo-module **/

/**
 * 「關聯待辦」選擇對話框。
 *
 * 由 powerbox 的「關聯待辦」指令開啟，列出目前文件（note_id / res_id / 個人筆記）
 * 既有的活動，供使用者挑選一筆，將其膠囊重新插回游標處 —— 用於膠囊在編輯器中
 * 被誤刪後，想把已建立的待辦重新加回文字後方的情境。
 *
 * 純選擇 UI：資料一律即時向後端抓取（get_editor_activities，與內嵌清單同源），
 * 不持久化任何狀態；選定後由呼叫端（plugin）負責插入膠囊。
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { activityStateClass } from "@dobtor_mail_activity/utils/activity_state";

export class ActivityPickerDialog extends Component {
    static template = "dobtor_mail_activity.ActivityPickerDialog";
    static components = { Dialog };
    static props = {
        close: { type: Function },
        onSelect: { type: Function },
        bind: { type: String, optional: true },
        noteId: { type: [Number, Boolean], optional: true },
        resModel: { type: [String, Boolean], optional: true },
        resId: { type: [Number, Boolean], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.title = _t("Link a To-do");
        this.state = useState({ activities: [], loading: true });
        onWillStart(() => this.load());
    }

    async load() {
        try {
            // limit=0 → 全部（選擇情境一次性開啟，不分頁）。
            const res = await this.orm.call("mail.activity", "get_editor_activities", [
                this.props.bind || "personal",
                this.props.resModel || false,
                this.props.resId || false,
                this.props.noteId || false,
                0,
            ]);
            this.state.activities = res.activities || [];
        } catch (e) {
            this.state.activities = [];
        } finally {
            this.state.loading = false;
        }
    }

    /** 依狀態回傳時鐘色點 class（比照內嵌清單 / 原生列表視圖著色）。 */
    stateClass(act) {
        return activityStateClass(act.state, { active: act.active });
    }

    onSelect(act) {
        this.props.onSelect(act.id);
        this.props.close();
    }
}
