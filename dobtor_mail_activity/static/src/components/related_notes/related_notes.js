/** @odoo-module */

import { Component, useState, onWillStart } from "@odoo/owl";
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
    }

    /**
     * 載入關聯筆記
     */
    async loadNotes() {
        if (!this.props.resModel || !this.props.resId) {
            this.state.notes = [];
            return;
        }

        this.state.isLoading = true;
        try {
            const notes = await this.orm.call(
                'mail.activity',
                'get_related_notes',
                [this.props.resModel, this.props.resId]
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
            default:
                return 'fa fa-circle-o text-muted';
        }
    }
}
