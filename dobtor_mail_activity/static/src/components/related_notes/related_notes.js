/** @odoo-module */

import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class RelatedNotes extends Component {
    static template = "dobtor_mail_activity.RelatedNotes";
    static props = {
        resModel: { type: String },
        resId: { type: [Number, { value: false }], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            isExpanded: true,
            expandedNotes: {},
            notes: [],
            isLoading: false,
        });

        onWillStart(async () => {
            if (this.props.resId) {
                await this.loadNotes();
            }
        });

        // Chatter 在表單記錄間切換時是同一實例、只更新 props（不重跑 onWillStart），
        // 故需在 props 變更時重新載入，否則會持續顯示前一筆記錄的關聯筆記。
        onWillUpdateProps(async (nextProps) => {
            if (
                nextProps.resId !== this.props.resId ||
                nextProps.resModel !== this.props.resModel
            ) {
                await this.loadNotes(nextProps.resModel, nextProps.resId);
            }
        });
    }

    /**
     * 載入關聯筆記
     */
    async loadNotes(resModel = this.props.resModel, resId = this.props.resId) {
        if (!resModel || !resId) {
            this.state.notes = [];
            return;
        }

        this.state.isLoading = true;
        try {
            const notes = await this.orm.call(
                'mail.activity',
                'get_related_notes',
                [resModel, resId]
            );
            this.state.notes = notes;
        } catch (e) {
            this.state.notes = [];
            this.notification.add(_t("Failed to load related notes."), { type: "danger" });
        }
        this.state.isLoading = false;
    }

    /**
     * 切換整體區塊展開/摺疊
     */
    toggleSection() {
        this.state.isExpanded = !this.state.isExpanded;
    }

    /**
     * 切換單一筆記的待辦列表展開/摺疊
     */
    toggleNoteActivities(noteId) {
        this.state.expandedNotes[noteId] = !this.state.expandedNotes[noteId];
    }

    /**
     * 開啟筆記表單
     */
    async openNote(noteId) {
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'note.note',
            res_id: noteId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    /**
     * 開啟待辦表單
     */
    async openActivity(activityId) {
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'mail.activity',
            res_id: activityId,
            views: [[false, 'form']],
            target: 'new',
        });
    }

    /**
     * 分母含已合併空殼時的說明文字（hover 顯示）。
     * 已合併者與其主待辦是同一件事，不標示的話會被誤讀成兩件。
     */
    mergedHint(note) {
        if (!note.merged_count) {
            return "";
        }
        return _t(
            "Includes %s merged activity(ies) already represented by their master activity.",
            note.merged_count
        );
    }

    /**
     * 取得待辦狀態圖示 class
     */
    getActivityIconClass(state) {
        switch (state) {
            case 'active':
                return 'fa fa-circle-o text-primary';
            case 'done':
                return 'fa fa-check-circle text-success';
            case 'cancelled':
                return 'fa fa-times-circle text-danger';
            case 'merged':
                // 已併入其他待辦：保留在清單中（顯示但標示），實際內容由主待辦代表
                return 'fa fa-compress text-secondary';
            default:
                return 'fa fa-circle-o text-muted';
        }
    }
}
