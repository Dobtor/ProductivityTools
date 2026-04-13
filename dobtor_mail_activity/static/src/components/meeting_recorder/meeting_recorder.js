/** @odoo-module */

import { Component, useState, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";

/**
 * MeetingRecorder 組件
 * 提供瀏覽器端錄音功能，用於會議記錄
 *
 * 功能：
 * - 開始/暫停/停止錄音
 * - 即時顯示錄音時間
 * - 上傳錄音至 Odoo
 * - 錄音完成後可觸發語音辨識
 */
export class MeetingRecorder extends Component {
    static template = "dobtor_mail_activity.MeetingRecorder";
    static props = {
        noteId: { type: Number },
        readonly: { type: Boolean, optional: true },
        onRecordingCreated: { type: Function, optional: true },
    };
    static defaultProps = {
        readonly: false,
    };

    // 錄音時長上限（秒）— 與後端 MAX_RECORDING_DURATION 一致
    static MAX_DURATION = 7200; // 2 小時

    setup() {
        this.notification = useService("notification");

        this.state = useState({
            status: "idle", // idle | recording | paused | uploading
            duration: 0,
            error: null,
            supported: this._checkSupport(),
        });

        this.mediaRecorder = null;
        this.audioChunks = [];
        this.timerInterval = null;
        this.recordStartTime = null;
        this.pausedDuration = 0;
        this.pauseStartTime = null;

        onWillUnmount(() => {
            this._cleanup();
        });
    }

    // ===== 瀏覽器支援檢查 =====
    _checkSupport() {
        return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    }

    // ===== 錄音控制 =====
    async startRecording() {
        if (!this.state.supported) {
            this.notification.add(
                _t("Your browser does not support audio recording."),
                { type: "danger" }
            );
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    sampleRate: 44100,
                },
            });

            // 選擇最佳可用格式
            const mimeType = this._getBestMimeType();
            this.mediaRecorder = new MediaRecorder(stream, {
                mimeType,
                audioBitsPerSecond: 128000,
            });

            this.audioChunks = [];
            this.recordStartTime = new Date();
            this.pausedDuration = 0;

            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };

            this.mediaRecorder.onstop = () => {
                this._onRecordingComplete();
            };

            this.mediaRecorder.onerror = (event) => {
                console.error("MediaRecorder error:", event.error);
                this.state.error = event.error?.message || _t("Recording error");
                this.state.status = "idle";
                this._stopTimer();
            };

            this.mediaRecorder.start(1000); // 每秒一個 chunk
            this.state.status = "recording";
            this.state.error = null;
            this._startTimer();
        } catch (err) {
            console.error("getUserMedia error:", err);
            if (err.name === "NotAllowedError") {
                this.state.error = _t("Microphone access denied. Please allow microphone access in your browser settings.");
            } else {
                this.state.error = _t("Failed to access microphone: ") + err.message;
            }
        }
    }

    pauseRecording() {
        if (this.mediaRecorder && this.state.status === "recording") {
            this.mediaRecorder.pause();
            this.state.status = "paused";
            this.pauseStartTime = new Date();
            this._stopTimer();
        }
    }

    resumeRecording() {
        if (this.mediaRecorder && this.state.status === "paused") {
            this.mediaRecorder.resume();
            this.state.status = "recording";
            if (this.pauseStartTime) {
                this.pausedDuration += (new Date() - this.pauseStartTime);
                this.pauseStartTime = null;
            }
            this._startTimer();
        }
    }

    stopRecording() {
        if (this.mediaRecorder && this.state.status !== "idle") {
            if (this.state.status === "paused" && this.pauseStartTime) {
                this.pausedDuration += (new Date() - this.pauseStartTime);
                this.pauseStartTime = null;
            }
            this.mediaRecorder.stop();
            // 停止所有音軌
            this.mediaRecorder.stream.getTracks().forEach((track) => track.stop());
            this._stopTimer();
        }
    }

    // ===== 格式處理 =====
    _getBestMimeType() {
        const types = [
            "audio/webm;codecs=opus",
            "audio/webm",
            "audio/mp4",
            "audio/ogg;codecs=opus",
        ];
        for (const type of types) {
            if (MediaRecorder.isTypeSupported(type)) {
                return type;
            }
        }
        return "";
    }

    _getFileExtension(mimeType) {
        if (mimeType.includes("webm")) return "webm";
        if (mimeType.includes("mp4")) return "mp4";
        if (mimeType.includes("ogg")) return "ogg";
        return "webm";
    }

    // ===== 計時器 =====
    _startTimer() {
        this.timerInterval = setInterval(() => {
            const now = new Date();
            const elapsed = now - this.recordStartTime - this.pausedDuration;
            this.state.duration = Math.floor(elapsed / 1000);

            // 自動停止：超過最大時長
            if (this.state.duration >= MeetingRecorder.MAX_DURATION) {
                this.notification.add(
                    _t("Maximum recording duration reached. Recording stopped automatically."),
                    { type: "warning" }
                );
                this.stopRecording();
            }
        }, 200);
    }

    _stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    }

    // ===== 格式化時間 =====
    get formattedDuration() {
        const total = this.state.duration;
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const seconds = total % 60;
        const pad = (n) => String(n).padStart(2, "0");
        if (hours > 0) {
            return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
        }
        return `${pad(minutes)}:${pad(seconds)}`;
    }

    // ===== 錄音完成處理 =====
    async _onRecordingComplete() {
        const mimeType = this.mediaRecorder?.mimeType || "audio/webm";
        const blob = new Blob(this.audioChunks, { type: mimeType });

        if (blob.size === 0) {
            this.state.error = _t("Recording is empty. Please try again.");
            this.state.status = "idle";
            return;
        }

        this.state.status = "uploading";

        try {
            const base64 = await this._blobToBase64(blob);
            const fileFormat = this._getFileExtension(mimeType);
            const recordEnd = new Date();

            const result = await rpc(
                "/web/dataset/call_kw/note.recording/create_from_browser",
                {
                    model: "note.recording",
                    method: "create_from_browser",
                    args: [{
                        note_id: this.props.noteId,
                        audio_base64: base64,
                        duration: this.state.duration,
                        file_format: fileFormat,
                        record_start: this.recordStartTime.toISOString(),
                        record_end: recordEnd.toISOString(),
                    }],
                    kwargs: {},
                }
            );

            this.notification.add(
                _t("Recording uploaded successfully."),
                { type: "success" }
            );

            if (this.props.onRecordingCreated) {
                this.props.onRecordingCreated(result);
            }
        } catch (err) {
            console.error("Upload error:", err);
            this.state.error = _t("Failed to upload recording: ") + (err.message || err);
        }

        this.state.status = "idle";
        this.state.duration = 0;
        this.audioChunks = [];
    }

    // ===== 工具方法 =====
    _blobToBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => {
                // 移除 data:audio/xxx;base64, 前綴
                const base64 = reader.result.split(",")[1];
                resolve(base64);
            };
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
    }

    _cleanup() {
        this._stopTimer();
        if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
            this.mediaRecorder.stop();
            this.mediaRecorder.stream.getTracks().forEach((track) => track.stop());
        }
    }
}
