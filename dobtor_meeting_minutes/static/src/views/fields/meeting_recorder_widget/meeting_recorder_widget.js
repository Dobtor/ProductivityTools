/** @odoo-module */

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { MeetingRecorder } from "@dobtor_meeting_minutes/components/meeting_recorder/meeting_recorder";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component } from "@odoo/owl";

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

        this.busService.subscribe("note_recording/transcription_update",
            (payload) => this._onTranscriptionUpdate(payload));
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
            const codeLabels = {
                config_error: _t("Configuration issue — please check Settings."),
                quota_exceeded: _t("Provider quota exceeded."),
                timeout: _t("Request timed out."),
                network_error: _t("Network error."),
                upload_failed: _t("Audio upload failed."),
                parse_error: _t("Unexpected response from provider."),
                http_error: _t("Provider returned an HTTP error."),
                stale_worker: _t("Processing was interrupted."),
                internal_error: _t("Internal error."),
            };
            const hint = codeLabels[payload.error_code] || _t("Transcription failed");
            const detail = payload.error_message || "";
            this.notification.add(
                detail || hint,
                { type: "danger", sticky: true, title: hint }
            );
        } else if (done < total) {
            this.notification.add(
                _t("Transcription progress: %(done)s / %(total)s completed.", { done, total }),
                { type: "info" }
            );
        } else if (payload.transcript_state === "partial") {
            this.notification.add(
                _t("Transcription partially completed. See Recordings for failed segments."),
                { type: "warning", sticky: true }
            );
        } else {
            this.notification.add(
                _t("All transcriptions completed successfully."),
                { type: "success" }
            );
        }

        await this.props.record.model.root.load();
    }
}

registry.category("fields").add("meeting_recorder_widget", {
    component: MeetingRecorderWidget,
    supportedTypes: ["integer"],
});
