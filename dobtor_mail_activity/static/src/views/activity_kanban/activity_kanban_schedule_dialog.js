/** @odoo-module */

import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

/**
 * 活動 schedule 表單彈窗。
 *
 * 沿用官方 FormViewDialog（含右上角 X 左邊的官方展開鈕 fa-expand），但把展開鈕
 * 的行為從官方預設的「全畫面表單」覆寫為「全畫面 kanban」——導向呼叫端傳入的
 * 當前 kanban action（expandActionId）。未傳時退回官方行為（全畫面表單）。
 */
export class ActivityScheduleFormDialog extends FormViewDialog {
    static props = {
        ...FormViewDialog.props,
        expandActionId: { type: [Number, String, Boolean], optional: true },
    };

    async onExpand() {
        if (!this.props.expandActionId) {
            return super.onExpand();
        }
        // 比照官方 onExpand：離開前先跑 beforeLeave 檢查（未存檔提示），通過才導頁。
        const beforeLeaveCallbacks = this.viewProps.__beforeLeave__.callbacks;
        const res = await Promise.all(beforeLeaveCallbacks.map((cb) => cb()));
        if (!res.includes(false)) {
            this.props.close();
            return this.actionService.doAction(this.props.expandActionId);
        }
    }
}
