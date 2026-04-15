/** @odoo-module */

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { MeetingRecorder } from "@dobtor_meeting_minutes/components/meeting_recorder/meeting_recorder";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, onWillUnmount } from "@odoo/owl";

/**
 * MeetingRecorderWidget
 *
 * 可嵌入 form view 的錄音 widget。
 * 功能：
 * - 嵌入 MeetingRecorder 錄音元件
 * - 監聽 bus.bus 通知，辨識完成時自動 reload
 */
export class MeetingRecorderWidget extends Component {
    static template = "dobtor_meeting_minutes.MeetingRecorderWidget";
    static components = { MeetingRecorder };
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.busService = useService("bus_service");
        this.notification = useService("notification");

        // 保存 callback 引用以便 unsubscribe
        this._onTranscriptionBound = (payload) => this._onTranscriptionUpdate(payload);
        this._onSummaryBound = (payload) => this._onSummaryUpdate(payload);

        this.busService.subscribe("note_recording/transcription_update", this._onTranscriptionBound);
        this.busService.subscribe("note_recording/summary_update", this._onSummaryBound);

        onWillUnmount(() => {
            this.busService.unsubscribe("note_recording/transcription_update", this._onTranscriptionBound);
            this.busService.unsubscribe("note_recording/summary_update", this._onSummaryBound);
        });
    }

    get noteId() {
        return this.props.record.resId;
    }

    get isReadonly() {
        // 錄音器不受底層 computed 欄位的 readonly 影響
        // 只有會議記錄鎖定時才禁用
        return this.props.record.data.is_locked || false;
    }

    get isMeeting() {
        return this.props.record.data.note_type === "meeting";
    }

    async onRecordingCreated(result) {
        await this.props.record.model.root.load();
    }

    async _onTranscriptionUpdate(payload) {
        // 只處理當前 note 的通知
        if (payload.note_id !== this.noteId) {
            return;
        }

        const done = payload.progress_done || 0;
        const total = payload.progress_total || 1;

        if (payload.state === "error") {
            this.notification.add(
                _t("Transcription failed: ") + (payload.error_message || ""),
                { type: "danger", sticky: true }
            );
        } else if (done < total) {
            // 進度通知
            this.notification.add(
                _t("Transcription progress: %(done)s / %(total)s completed.", { done, total }),
                { type: "info" }
            );
        } else {
            // 全部完成
            this.notification.add(
                _t("All transcriptions completed successfully."),
                { type: "success" }
            );
        }

        // 重新載入 record 以更新所有欄位
        await this.props.record.model.root.load();
    }

    async _onSummaryUpdate(payload) {
        if (payload.note_id !== this.noteId) {
            return;
        }

        if (payload.summary_state === "done") {
            this.notification.add(
                _t("Meeting summary generated successfully."),
                { type: "success" }
            );
        } else if (payload.summary_state === "error") {
            this.notification.add(
                _t("Summary generation failed."),
                { type: "danger", sticky: true }
            );
        }

        await this.props.record.model.root.load();
    }
}

registry.category("fields").add("meeting_recorder_widget", {
    component: MeetingRecorderWidget,
    supportedTypes: ["integer"],
});
