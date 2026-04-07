/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { Wysiwyg } from "@html_editor/wysiwyg";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";
import { DocPageLayout } from "../doc_page_layout/doc_page_layout";
import { DocRuler } from "../doc_ruler/doc_ruler";
import { DocOdooFieldPlugin } from "../../js/plugins/doc_odoo_field_plugin";
import { DocPageFormatPlugin } from "../../js/plugins/doc_page_format_plugin";
import { DocExportPlugin } from "../../js/plugins/doc_export_plugin";
import { DocMultiColumnPlugin } from "../../plugins/doc_multi_column_plugin";
import { DocFontFamilyPlugin } from "../../plugins/doc_font_family_plugin";
import { DocLineHeightPlugin } from "../../plugins/doc_line_height_plugin";
import { DocTableMergePlugin } from "../../plugins/doc_table_merge_plugin";
import { AutoSaveManager } from "../../core/auto_save_manager";
import { LeaderElection } from "../../core/leader_election";
import { OfflineManager } from "../../core/offline_manager";

// 頁面寬度對照表（mm）
const PAGE_WIDTH_MM = {
    A4: 210, A3: 297, A5: 148, letter: 216, Letter: 216, legal: 216, Legal: 216,
};

export class DocEditor extends Component {
    static template = "dobtor_doc_editor.DocEditor";
    static components = { DocPageLayout, DocRuler, Wysiwyg };
    static props = ["*"];

    setup() {
        this.notification = useService("notification");
        this.action = useService("action");
        this.dialog = useService("dialog");

        // 嘗試取得 bus_service（多人協作用，可能不存在）
        try {
            this._busService = useService("bus_service");
        } catch (e) {
            this._busService = null;
        }

        this.state = useState({
            docId: null,
            docName: "未命名文件",
            editorReady: false,
            isSaving: false,
            statusMsg: "就緒",
            statusType: "saved",
            pageFormat: "A4",
            marginTop: 96,
            marginBottom: 96,
            marginLeft: 96,
            marginRight: 96,
            headerHtml: "",
            footerHtml: "",
            modelName: "",
            isOnline: true,
            showImportArea: false,
            zoom: 1.0,
        });

        this._currentContent = "";
        this._currentHeader = "";
        this._currentFooter = "";
        this.mainEditorConfig = null;

        // 取得 doc_id
        const context = this.props.action?.context || {};
        const docId = context.doc_id;

        // ── AutoSaveManager ──
        this._autoSave = new AutoSaveManager({
            saveFn: async (html) => {
                if (!this.state.docId) return;
                await rpc("/dobtor_doc/save", {
                    doc_id: this.state.docId,
                    content_html: html,
                    header_html: this._currentHeader,
                    footer_html: this._currentFooter,
                });
            },
            debounceMs: 1500,
            maxWaitMs: 10000,
            idleMs: 3000,
            isLeaderFn: () => this._leaderElection?.isLeader() ?? true,
            onStatusChange: (status) => {
                const msgs = {
                    unsaved: ["未儲存", "saving"],
                    saving:  ["儲存中...", "saving"],
                    saved:   ["已儲存", "saved"],
                    error:   ["儲存失敗", "error"],
                };
                const [msg, type] = msgs[status] || ["就緒", "saved"];
                this.state.statusMsg = msg;
                this.state.statusType = type;
                this.state.isSaving = status === "saving";
            },
        });

        // ── OfflineManager ──
        this._offlineManager = new OfflineManager();
        this._offlineManager.onStatusChange((isOnline) => {
            this.state.isOnline = isOnline;
            if (isOnline) {
                this.notification.add("已恢復連線，正在同步...", { type: "success" });
                this._syncOfflineBuffer();
            } else {
                this.notification.add(
                    "網路已斷線，編輯內容將在恢復後自動同步",
                    { type: "warning", sticky: true }
                );
            }
        });

        // ── LeaderElection（僅在有 bus_service 且有 docId 時啟用） ──
        this._leaderElection = null;

        onMounted(async () => {
            if (docId) {
                await this._loadDocument(docId);
            } else {
                this._initEditorConfig("");
                this.state.editorReady = true;
            }

            // 初始化 Leader Election
            if (this._busService && this.state.docId) {
                const channel = `doc.document_${this.state.docId}`;
                const sessionId = Math.random().toString(36).slice(2);
                this._leaderElection = new LeaderElection(this._busService, channel, sessionId);
            }

            document.addEventListener("doc-export", this._onExportEvent.bind(this));
            document.addEventListener("doc-page-format-change", this._onPageFormatEvent.bind(this));
            document.addEventListener("doc-insert-page-break", this._onInsertPageBreak.bind(this));
        });

        onWillUnmount(async () => {
            await this._autoSave.flush();
            this._autoSave.destroy();
            this._offlineManager.destroy();
            if (this._leaderElection) this._leaderElection.destroy();

            document.removeEventListener("doc-export", this._onExportEvent.bind(this));
            document.removeEventListener("doc-page-format-change", this._onPageFormatEvent.bind(this));
            document.removeEventListener("doc-insert-page-break", this._onInsertPageBreak.bind(this));
        });
    }

    // ─── 資料載入 ────────────────────────────────────────────────

    async _loadDocument(docId) {
        try {
            const data = await rpc("/dobtor_doc/load", { doc_id: docId });
            this.state.docId = data.id;
            this.state.docName = data.name;
            this.state.pageFormat = data.page_format || "A4";
            this.state.marginTop = data.margin_top || 96;
            this.state.marginBottom = data.margin_bottom || 96;
            this.state.marginLeft = data.margin_left || 96;
            this.state.marginRight = data.margin_right || 96;
            this.state.headerHtml = data.header_html || "";
            this.state.footerHtml = data.footer_html || "";
            this.state.modelName = data.model_name || "";

            this._currentContent = data.content_html || "";
            this._currentHeader = data.header_html || "";
            this._currentFooter = data.footer_html || "";

            this._initEditorConfig(this._currentContent);
            this.state.editorReady = true;
            this.state.statusMsg = "已載入";
            this.state.statusType = "saved";
        } catch (error) {
            this.state.statusMsg = `載入失敗：${error.message || error}`;
            this.state.statusType = "error";
            console.error("[DocEditor] Load failed:", error);
        }
    }

    _initEditorConfig(initialContent) {
        this.mainEditorConfig = {
            Plugins: [
                ...MAIN_PLUGINS,
                DocOdooFieldPlugin,
                DocPageFormatPlugin,
                DocExportPlugin,
                DocMultiColumnPlugin,
                DocFontFamilyPlugin,
                DocLineHeightPlugin,
                DocTableMergePlugin,
            ],
            content: initialContent || "",
            onChange: (html) => this._onContentChange(html),
            placeholder: "開始輸入...",
            dobtor_doc_id: this.state.docId,
            dobtor_model_name: this.state.modelName,
        };
    }

    // ─── 內容變更 ─────────────────────────────────────────────────

    _onContentChange(html) {
        this._currentContent = html;
        if (this._offlineManager.isOnline) {
            this._autoSave.onContentChange(html);
        } else {
            this._offlineManager.bufferOperation({ type: "save", html });
            this.state.statusMsg = "離線緩存中";
            this.state.statusType = "saving";
        }
    }

    onHeaderChange(html) {
        this._currentHeader = html;
        this._autoSave.onContentChange(this._currentContent);
    }

    onFooterChange(html) {
        this._currentFooter = html;
        this._autoSave.onContentChange(this._currentContent);
    }

    async _syncOfflineBuffer() {
        const ops = this._offlineManager.drainBuffer();
        if (!ops.length || !this.state.docId) return;
        const lastSave = [...ops].reverse().find(op => op.type === "save");
        if (!lastSave) return;
        try {
            await rpc("/dobtor_doc/save", {
                doc_id: this.state.docId,
                content_html: lastSave.html,
                header_html: this._currentHeader,
                footer_html: this._currentFooter,
            });
            this.state.statusMsg = "已同步";
            this.state.statusType = "saved";
        } catch (e) {
            this.notification.add(`同步失敗：${e.message}`, { type: "danger" });
        }
    }

    // ─── 手動儲存 ────────────────────────────────────────────────

    async onSave() {
        if (!this.state.docId || this.state.isSaving) return;
        this.state.isSaving = true;
        this.state.statusMsg = "儲存中...";
        this.state.statusType = "saving";
        try {
            await rpc("/dobtor_doc/save", {
                doc_id: this.state.docId,
                content_html: this._currentContent,
                header_html: this._currentHeader,
                footer_html: this._currentFooter,
            });
            this.state.statusMsg = "已儲存";
            this.state.statusType = "saved";
        } catch (error) {
            this.state.statusMsg = `儲存失敗：${error.message || error}`;
            this.state.statusType = "error";
            this.notification.add("文件儲存失敗", { type: "danger" });
        } finally {
            this.state.isSaving = false;
        }
    }

    // ─── 匯出 ────────────────────────────────────────────────────

    async onExport(format, quality = "high") {
        if (!this.state.docId) {
            this.notification.add("請先儲存文件", { type: "warning" });
            return;
        }
        await this.onSave();
        this.state.statusMsg = `正在產生 ${format.toUpperCase()}...`;
        this.state.statusType = "saving";
        try {
            const result = await rpc("/dobtor_doc/export", {
                doc_id: this.state.docId,
                format: format,
                quality: quality,
            });
            if (result.error) throw new Error(result.error);
            const blob = this._base64ToBlob(result.data, result.mimetype);
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = result.filename;
            a.click();
            URL.revokeObjectURL(url);
            this.state.statusMsg = "已儲存";
            this.state.statusType = "saved";
            this.notification.add(`${result.filename} 下載中`, { type: "success" });
        } catch (error) {
            this.state.statusMsg = "匯出失敗";
            this.state.statusType = "error";
            this.notification.add(`匯出失敗：${error.message || error}`, { type: "danger" });
        }
    }

    // ─── 匯入 ────────────────────────────────────────────────────

    onImportClick() {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".docx,.odt";
        input.onchange = (ev) => this._handleImportFile(ev.target.files[0]);
        input.click();
    }

    async _handleImportFile(file) {
        if (!file) return;
        this.notification.add("正在匯入，請稍後...", { type: "info" });
        try {
            const formData = new FormData();
            formData.append("file", file);
            const response = await fetch("/dobtor_doc/import", {
                method: "POST",
                body: formData,
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (data.html) {
                this._currentContent = data.html;
                this._initEditorConfig(data.html);
                this._onContentChange(data.html);
                this.notification.add("匯入成功", { type: "success" });
            }
        } catch (e) {
            this.notification.add(`匯入失敗：${e.message}`, { type: "danger" });
        }
    }

    _base64ToBlob(base64, mimeType) {
        const bytes = atob(base64);
        const buf = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i);
        return new Blob([buf], { type: mimeType });
    }

    // ─── Plugin 事件處理 ──────────────────────────────────────────

    _onExportEvent(event) {
        const { action } = event.detail || {};
        if (action === "export-pdf") this.onExport("pdf");
        else if (action === "export-docx-hq") this.onExport("docx", "high");
        else if (action === "import-docx") this.onImportClick();
    }

    _onPageFormatEvent(event) {
        const { format } = event.detail || {};
        if (format && PAGE_WIDTH_MM[format] !== undefined) {
            this.state.pageFormat = format;
            if (this.state.docId) {
                rpc("/dobtor_doc/save_settings", {
                    doc_id: this.state.docId,
                    page_format: format,
                }).catch(() => {});
            }
        }
    }

    _onInsertPageBreak() {
        this._autoSave.onContentChange(this._currentContent);
    }

    // ─── Toolbar 事件 ─────────────────────────────────────────────

    onTitleChange(event) {
        const newName = event.target.value.trim() || "未命名文件";
        this.state.docName = newName;
        if (this.state.docId) {
            rpc("/dobtor_doc/save", {
                doc_id: this.state.docId,
                name: newName,
            }).catch(() => {});
        }
    }

    onPageFormatChange(event) {
        const format = event.target.value;
        this._onPageFormatEvent({ detail: { format } });
    }

    onClose() {
        history.back();
    }

    onZoomChange(event) {
        this.state.zoom = parseFloat(event.target.value) || 1.0;
    }

    // ─── 版本歷史 ─────────────────────────────────────────────────

    async onSaveVersion() {
        if (!this.state.docId) return;
        await this.onSave();
        try {
            await rpc("/dobtor_doc/save_version", { doc_id: this.state.docId });
            this.notification.add("版本已儲存", { type: "success" });
        } catch (e) {
            this.notification.add(`版本儲存失敗：${e.message}`, { type: "danger" });
        }
    }

    // ─── 工具方法 ────────────────────────────────────────────────

    get statusClass() {
        const map = {
            saved:  "doc-statusbar-saved",
            saving: "doc-statusbar-saving",
            error:  "doc-statusbar-error",
        };
        return map[this.state.statusType] || "";
    }

    get pageWidthMm() {
        return PAGE_WIDTH_MM[this.state.pageFormat] || 210;
    }

    get offlineBadge() {
        return !this.state.isOnline;
    }
}

registry.category("actions").add("dobtor_doc_editor.action_doc_editor", DocEditor);
