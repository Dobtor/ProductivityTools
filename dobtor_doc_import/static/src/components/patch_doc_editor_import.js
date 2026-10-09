/** @odoo-module **/
/**
 * 把兩條「匯入驗收通道」patch 進核心的編輯器。
 *
 * 為什麼用 patch 而不是放在核心：這兩支都依賴本模組的東西——
 *   importViaTsEngine        → POST /dobtor_doc/import?engine=ts
 *                              （路由在本模組，後端跑 tools/dist/parse_docx_cli.cjs）
 *   importViaBrowserParser   → window.DobtorCanvasEditor
 *                              （canvas-editor-custom.umd.js 在本模組的 assets）
 * 沒裝本模組時，核心的編輯器就不該有這兩個方法——有也只會失敗。
 *
 * ☠️ 匯入**按鈕**不在這裡：`onImportClick` → `_handleImportFile` 打的是
 *    `/dobtor_doc/upload_template`（核心路由）＋ canvas-editor 的 docx plugin
 *    （核心資源），**沒裝本模組也完全可用**，所以它留在核心。
 *    拆模組的提案裡我原本以為按鈕打的是 /dobtor_doc/import、需要在這裡
 *    重新注入入口——量過之後發現不是。
 *
 * 兩支都是驗收用途（`window._docEditor.importViaTsEngine(file)`），沒有 UI 入口；
 * 它們存在的意義是「後端 CLI 與瀏覽器 parser 對同一份 docx 的輸出可以當場比對」。
 */
import { patch } from "@web/core/utils/patch";
import { DocEditor } from "@dobtor_doc_editor/components/doc_editor/doc_editor";

patch(DocEditor.prototype, {
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
    },

    /**
     * 用**瀏覽器端**的 OOXML Parser 匯入 .docx（不經後端）。
     *
     * 與 `importViaTsEngine()` 對稱——同一個 parser，兩條執行路徑：
     *   importViaTsEngine        → POST /dobtor_doc/import?engine=ts
     *                              → 後端 node 跑 tools/dist/parse_docx_cli.cjs
     *   importViaBrowserParser   → 直接用 window.DobtorCanvasEditor（本方法）
     *
     * ☠️ 這個方法存在的理由：`canvas-editor-custom.umd.js` 在 2026-10-09 之前
     * **從未掛進 manifest**，所以瀏覽器端的 parser 從頭到尾沒有被執行過。把它
     * 掛進去卻沒有消費者，只是讓每個後台頁面多下載 425KB。這條通道就是它的
     * 消費者，也讓「後端 CLI 與瀏覽器 parser 輸出是否一致」變成可以當場比的事。
     *
     * 驗收用途，與 importViaTsEngine 同級：
     *   `window._docEditor.importViaBrowserParser(file)`
     *
     * **不改預設匯入路徑**：使用者按「匯入」走的仍然是 `_handleImportFile()`
     * （後端 LibreOffice ＋ canvas-editor 的 docx plugin）。
     *
     * @param {File} file 使用者選的 .docx File 物件
     * @returns {Promise<{success: boolean, elementCount?: number, error?: string}>}
     */
    async importViaBrowserParser(file) {
        if (!file) {
            return { success: false, error: "未提供檔案" };
        }
        if (!this.editor) {
            return { success: false, error: "Canvas editor 尚未初始化" };
        }
        const lib = window.DobtorCanvasEditor;
        if (!lib || typeof lib.OoxmlParser !== "function") {
            // 掛載失敗時要講清楚是哪一支沒載到，不要只說「不支援」。
            return {
                success: false,
                error: "window.DobtorCanvasEditor 不存在——"
                     + "canvas-editor-custom.umd.js 沒載入（檢查 manifest assets）",
            };
        }
        if (typeof lib.ToCanvasEditor !== "function") {
            return {
                success: false,
                error: "window.DobtorCanvasEditor.ToCanvasEditor 不存在——bundle 版本不對",
            };
        }
        try {
            const buf = await file.arrayBuffer();
            // ☠️ API 照 tools/parse_docx_cli.ts（唯一的權威用法）：
            //    parse() 是**同步**的、mapper 的方法叫 convert() 不是 toElements()。
            //    旗標與後端 doc_convert.py 送給 CLI 的一致（--svg-graphics 常開，
            //    另兩個預設關），否則兩條通道的輸出不能互相比對。
            const parser = new lib.OoxmlParser();
            const doc = parser.parse(buf);
            const mapper = new lib.ToCanvasEditor({
                renderGraphicsAsSvg: true,
                renderFloatTextBox: false,
                preserveAnchorMetadata: false,
            });
            const elements = mapper.convert(doc);
            if (!Array.isArray(elements)) {
                throw new Error(
                    "ToCanvasEditor.convert() 沒回陣列（取得的是 "
                    + Object.prototype.toString.call(elements) + "）"
                );
            }
            this.editor.command.executeSetValue({ main: elements });
            this.state.statusMsg = `瀏覽器 Parser 匯入成功（${elements.length} elements）`;
            this.state.statusType = "saved";
            this.notification.add(
                `瀏覽器 Parser 匯入成功：${elements.length} 個 IElement`,
                { type: "success" }
            );
            return { success: true, elementCount: elements.length };
        } catch (e) {
            console.error("[DocEditor] importViaBrowserParser 失敗：", e);
            this.notification.add(
                `瀏覽器 Parser 匯入失敗：${e.message || e}`, { type: "danger" });
            return { success: false, error: e.message || String(e) };
        }
    },
});
