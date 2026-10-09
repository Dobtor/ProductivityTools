/** @odoo-module **/
/**
 * DocEditorIo — 進出：匯入 DOCX、匯出 PDF／DOCX、下載、版本。
 * 
 * 這一層的共同點是「跨出編輯器」：每一支都會打後端或產生檔案，
 * 所以失敗處理要給使用者看得懂的訊息，不能只 console.warn。
 *
 * 這是 doc_editor.js 拆出來的一層（mixin 工廠），由 doc_editor.js
 * 組合。拆的理由不是檔案太大，是**每一層的不變量要寫在自己的檔頭**。
 *
 * ☠️ import 區塊是整份照抄原檔的，沒有裁掉用不到的。理由：少一個 import
 * 的症狀是執行期 ReferenceError，而 OWL 會把它吞成一塊空白面板；
 * 多一個 import 沒有任何代價。**不要在 import {} 裡面加註解**——Odoo 的
 * asset compiler 不會 strip 它，會輸出 require({) 讓整個 bundle 掛掉。
 *
 * 後端對應：models/render/output.py（flatten / HTML / DOCX）。
 */
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { AutoSaveManager } from "../../core/auto_save_manager";
import { LeaderElection } from "../../core/leader_election";
import { OfflineManager } from "../../core/offline_manager";
import { installGlobalErrorReporting, mark, reportError } from "../../core/telemetry";
import { DocVersionPanel } from "../doc_version_panel/doc_version_panel";
import { DocFieldPickerDialog } from "../doc_field_picker/doc_field_picker";
import {
    scanJinja2Variables,
    scanJinja2VariablesWithPositions,
    scanJinja2VariablesInTables,
    analyzeScanResults,
    computeOrphanRecordIds,
    findMarkerPositionsInMain,
    rewriteTdValueWithControls,
    flattenElementsToText,
} from "./jinja2_scanner";
import {
    FONT_OPTIONS,
    FONT_SIZE_OPTIONS,
    _lsGet,
    _lsSet,
    DOBTOR_FIELD_KEY,
    DOBTOR_BLOCK_KEY,
    I18N_PILL_STYLE,
    SCALAR_FIELD_TYPES,
    PILL_STYLE,
    SIGNER_COLORS,
    signerColor,
    VALUE_SOURCES,
    FIELD_TYPES,
    isSessionExpiredResponse,
} from "./doc_editor_shared";

export const DocEditorIo = (Base) => class extends Base {

    // ─── 匯入 DOCX ───────────────────────────────────────────────────

    onImportClick() {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".docx";
        input.onchange = (ev) => this._handleImportFile(ev.target.files[0]);
        input.click();
    }

    /**
     * 安全解析 fetch 回應為 JSON。
     *
     * 「回應不是 JSON」只有兩個可能來源，這裡各給一條路：
     *
     *   1. **auth 層**——session 逾時。Odoo 對 SessionExpiredException 是
     *      303 轉址到 /web/login，fetch 跟過去之後拿到登入頁 HTML、
     *      status 200。給明確的「請重新登入」，使用者才知道要做什麼。
     *   2. **handler**——已經不可能了。`DocControllerBase.json_http_route`
     *      讓那些路由任何漏出來的例外都變成帶 error 的 JSON，且有一則測試
     *      讀原始碼擋「新增 type='http' JSON 路由忘記掛 decorator」。
     *
     * 底下剝標籤那段因此是**真正的最後一道**（反向代理的錯誤頁、
     * 不經 Odoo 的 502…），不再是日常路徑。保留它是因為它不花成本，
     * 而拿掉之後同一個症狀會退回「Unexpected token '<'」。
     */
    async _readJsonResponse(resp) {
        if (isSessionExpiredResponse(resp)) {
            throw new Error("連線已逾時，請重新登入後再試。");
        }
        const text = await resp.text();
        try {
            return JSON.parse(text);
        } catch (e) {
            const snippet = (text || "")
                .replace(/<[^>]*>/g, " ")
                .replace(/\s+/g, " ")
                .trim()
                .slice(0, 200);
            throw new Error(
                `伺服器錯誤 (HTTP ${resp.status})${snippet ? "：" + snippet : ""}`
            );
        }
    }

    async _handleImportFile(file) {
        if (!file) return;

        // 若有 docId，走後端高保真模板路線
        if (this.state.docId) {
            this.state.statusMsg = "上傳模板中...";
            this.state.statusType = "saving";
            try {
                const formData = new FormData();
                formData.append("doc_id", String(this.state.docId));
                formData.append("docx_file", file);

                const resp = await fetch("/dobtor_doc/upload_template", {
                    method: "POST",
                    body: formData,
                });
                const result = await this._readJsonResponse(resp);

                if (!result.success) throw new Error(result.error || "上傳失敗");

                this.state.hasDocxTemplate = true;
                this.state.templateVariables = result.variables || [];
                this.state.templateFilename = file.name;
                this.state.statusMsg = `模板就緒（${result.variables.length} 個變數）`;
                this.state.statusType = "saved";
                this.notification.add(
                    `模板上傳成功，偵測到：${result.variables.join(", ") || "（無變數）"}`,
                    { type: "success" }
                );
            } catch (e) {
                this.state.statusMsg = "就緒";
                this.state.statusType = "saved";
                this.notification.add(`上傳失敗：${e.message || e}`, { type: "danger" });
                return;
            }
        }

        // 同時用 canvas-editor 顯示預覽（接受格式偏差，僅供參考）
        if (this.editor && window.docx) {
            try {
                const ab = await file.arrayBuffer();
                await this.editor.command.executeImportDocx({ arrayBuffer: ab });
            } catch (e) {
                console.warn("[DocEditor] canvas 預覽失敗（不影響後端模板功能）：", e);
            }
        }
    }

    /**
     * 用本模組的 TS OOXML Parser（Phase E 並行通道）匯入 .docx。
     *
     * 與 _handleImportFile 的差異：
     *   - _handleImportFile 走 canvas-editor 的 docx plugin（@hufe921 內建）
     *   - importViaTsEngine 走後端 /dobtor_doc/import?engine=ts → 我們自寫的 OoxmlParser → IElement[]
     *
     * 驗收用途：
     *   chichi 在 DevTools 跑 `window._docEditor.importViaTsEngine(file)`
     *   比對兩條解析路徑對同一份 .docx 的渲染差異。
     *
     * @param {File} file 使用者上傳的 .docx File 物件
     * @param {Object} [options] 預留選項，目前無
     * @returns {Promise<{success: boolean, elementCount?: number, error?: string}>}
     */
    async importViaTsEngine(file) {
        if (!file) {
            return { success: false, error: "未提供檔案" };
        }
        if (!this.editor) {
            return { success: false, error: "Canvas editor 尚未初始化" };
        }
        try {
            const formData = new FormData();
            formData.append("file", file);
            formData.append("engine", "ts");

            const resp = await fetch("/dobtor_doc/import", {
                method: "POST",
                body: formData,
            });
            const result = await this._readJsonResponse(resp);
            if (result.error) throw new Error(result.error);
            if (!Array.isArray(result.elements)) {
                throw new Error("Backend 未回傳 elements 陣列（engine=ts 可能 fallback 到 libreoffice）");
            }

            // 用 canvas-editor 的 setValue 命令直接餵 IElement[]
            this.editor.command.executeSetValue({ main: result.elements });

            this.state.statusMsg = `TS Parser 匯入成功（${result.elements.length} elements）`;
            this.state.statusType = "saved";
            this.notification.add(
                `TS Parser 匯入成功：${result.elements.length} 個 IElement`,
                { type: "success" }
            );
            return { success: true, elementCount: result.elements.length };
        } catch (e) {
            console.error("[DocEditor] importViaTsEngine 失敗：", e);
            this.notification.add(`TS Parser 匯入失敗：${e.message || e}`, { type: "danger" });
            return { success: false, error: e.message || String(e) };
        }
    }


    // ─── 匯出 PDF ────────────────────────────────────────────────────

    _promptTemplateContext() {
        const raw = this.state.contextJson.trim();
        if (!raw) return {};
        try {
            return JSON.parse(raw);
        } catch {
            this.notification.add("Context JSON 格式錯誤，請檢查輸入", { type: "warning" });
            return null;
        }
    }

    async onExportPdf() {
        // 模板模式：後端 docxtpl + LibreOffice headless → 高保真 PDF
        if (this.state.hasDocxTemplate && this.state.docId) {
            const ctx = this._promptTemplateContext();
            if (ctx === null) return;
            this.state.statusMsg = "匯出 PDF 中...";
            this.state.statusType = "saving";
            try {
                const result = await rpc("/dobtor_doc/fill_template", {
                    doc_id: this.state.docId,
                    context: ctx,
                    output_format: "pdf",
                });
                if (!result.success) throw new Error(result.error);
                this._downloadBase64(result.content, result.filename, result.mimetype);
                this.state.statusMsg = "就緒";
                this.state.statusType = "saved";
            } catch (e) {
                this.state.statusMsg = "就緒";
                this.state.statusType = "saved";
                this.notification.add(`PDF 匯出失敗：${e.message || e}`, { type: "danger" });
            }
            return;
        }
        // 非模板模式：canvas-editor 列印
        if (this.editor) this.editor.command.executePrint();
    }


    // ─── 匯出 DOCX ───────────────────────────────────────────────────

    async onExportDocx() {
        // 模板模式：後端 docxtpl → 填充後原始 DOCX（100% 保真）
        if (this.state.hasDocxTemplate && this.state.docId) {
            const ctx = this._promptTemplateContext();
            if (ctx === null) return;
            this.state.statusMsg = "匯出 DOCX 中...";
            this.state.statusType = "saving";
            try {
                const result = await rpc("/dobtor_doc/fill_template", {
                    doc_id: this.state.docId,
                    context: ctx,
                    output_format: "docx",
                });
                if (!result.success) throw new Error(result.error);
                this._downloadBase64(result.content, result.filename, result.mimetype);
                this.state.statusMsg = "就緒";
                this.state.statusType = "saved";
            } catch (e) {
                this.state.statusMsg = "就緒";
                this.state.statusType = "saved";
                this.notification.add(`DOCX 匯出失敗：${e.message || e}`, { type: "danger" });
            }
            return;
        }
        // 非 DOCX-模板模式：改走伺服器匯出（補遺一）。
        //
        // 原本呼叫 canvas-editor plugin 的 executeExportDocx()，那條路徑完全
        // 繞過伺服器的 _flatten_content_json()——plugin 遇到非標準的 label
        // 元素會怎麼處理（原樣輸出網底？丟棄？）沒有保證。決策四要求匯出只
        // 輸出值、不帶網底，只有伺服器那條路能保證做到。
        if (!this.state.docId) {
            this.notification.add(
                "範本模式不支援 DOCX 匯出，請從使用此範本的文件匯出。",
                { type: "warning" }
            );
            return;
        }
        this.state.statusMsg = "匯出 DOCX 中...";
        this.state.statusType = "saving";
        try {
            await this._flushPendingSave();
            const result = await rpc("/dobtor_doc/export", {
                doc_id: this.state.docId,
                format: "docx",
                quality: "high",
            });
            if (!result?.success) throw new Error(result?.error || "匯出失敗");
            this._downloadBase64(result.content, result.filename, result.mimetype);
            this.state.statusMsg = "就緒";
            this.state.statusType = "saved";
        } catch (e) {
            this.state.statusMsg = "就緒";
            this.state.statusType = "saved";
            this.notification.add(`DOCX 匯出失敗：${e.message || e}`, { type: "danger" });
        }
    }

    /**
     * 匯出前把未存的內容先寫回後端。
     * 伺服器匯出讀的是 DB 裡的 content_json，不先 flush 會匯出到舊版本。
     */
    async _flushPendingSave() {
        if (this._isReadonly || !this.targetId || !this.editor) return;
        try {
            const json = JSON.stringify(this.editor.command.getValue().data);
            const result = await rpc("/dobtor_doc/save", {
                ...this.targetRpcParams,
                content_json: json,
                content_html: this._mainHtml(),
                if_unmodified_since: this._lastSyncedWriteDate,
            });
            this._handleSaveResult(result, json);
        } catch (e) {
            console.warn("[DocEditor] 匯出前存檔失敗，將匯出伺服器上的既有版本", e);
        }
    }


    // ─── 下載工具 ────────────────────────────────────────────────────

    _downloadBase64(b64, filename, mimetype) {
        const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: mimetype });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);
    }

    onClose() {
        history.back();
    }


    // ─── 版本管理（W7-8 P1-1）─────────────────────────────────────

    async onSaveVersion() {
        if (!this.state.docId) return;
        const label = prompt("請輸入版本標籤（可空白）：") || "";
        try {
            const result = await rpc("/dobtor_doc/save_version", {
                doc_id: this.state.docId,
                label: label,
            });
            if (result?.success) {
                this.notification.add(
                    `版本 v${result.version_number} 已儲存`,
                    { type: "success" }
                );
            }
        } catch (e) {
            this.notification.add(`版本儲存失敗：${e.message || e}`, { type: "danger" });
        }
    }

    onShowVersionPanel() {
        if (!this.state.docId) {
            this.notification.add("請先儲存文件後再查看版本歷史。", { type: "warning" });
            return;
        }
        this.state.showVersionPanel = true;
    }

    onCloseVersionPanel() {
        this.state.showVersionPanel = false;
    }

    async onVersionRestored(result) {
        // 還原成功後重新載入文件內容
        this.state.showVersionPanel = false;
        this.notification.add(
            `已還原至 v${result.restored_version}（當前 v${result.new_current_version}）`,
            { type: "success" }
        );
        if (this.state.docId) {
            await this._loadTarget();
            // 用新內容重新初始化 canvas-editor
            if (this.editor && this._loadedContentJson) {
                try {
                    const data = JSON.parse(this._loadedContentJson);
                    this.editor.command.executeSetValue(data);
                } catch (e) {
                    console.error("[DocEditor] 還原後重設 canvas content 失敗", e);
                }
            }
        }
    }

};
