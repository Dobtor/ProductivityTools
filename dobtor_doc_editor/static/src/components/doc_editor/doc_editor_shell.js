/** @odoo-module **/
/**
 * DocEditorShell — 外殼：canvas 實例、載入與存檔、工具列與選單。
 * 
 *  * canvas-editor 的實例與生命週期（**不能被 t-if unmount，會炸**）
 *  * 編輯對象的共用存取器（文件／範本／輸出三種 target）
 *  * 離線同步、手動儲存、頁面縮圖
 *  * 功能選單、modal、主題、尋找取代、格式工具列、顏色
 *
 * 這是 doc_editor.js 拆出來的一層（mixin 工廠），由 doc_editor.js
 * 組合。拆的理由不是檔案太大，是**每一層的不變量要寫在自己的檔頭**。
 *
 * ☠️ import 區塊是整份照抄原檔的，沒有裁掉用不到的。理由：少一個 import
 * 的症狀是執行期 ReferenceError，而 OWL 會把它吞成一塊空白面板；
 * 多一個 import 沒有任何代價。**不要在 import {} 裡面加註解**——Odoo 的
 * asset compiler 不會 strip 它，會輸出 require({) 讓整個 bundle 掛掉。
 *
 * 後端對應：controllers/doc_controller.py 的 load / save 端點。
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
} from "./doc_editor_shared";

export const DocEditorShell = (Base) => class extends Base {

    // ─── Canvas 編輯器初始化 ────────────────────────────────────────

    _initCanvasEditor() {
        const container = this.canvasContainer.el;
        if (!container) {
            console.error("[DocEditor] canvasContainer ref 未找到，Canvas 編輯器無法初始化");
            return;
        }

        // 取得全域 Canvas 編輯器建構子
        // @hufe921/canvas-editor UMD 掛載於 window["canvas-editor"].Editor
        const EditorConstructor = window["canvas-editor"]?.Editor;
        if (!EditorConstructor) {
            container.innerHTML =
                '<p style="color:#dc3545;padding:20px;font-size:14px">' +
                '❌ 錯誤：找不到 Canvas 編輯器（window["canvas-editor"].Editor 未定義）。' +
                '請確認 canvas-editor.umd.min.js 已正確載入。' +
                '</p>';
            console.error("[DocEditor] Canvas 編輯器未載入，請確認 __manifest__.py 中的 lib 路徑");
            return;
        }

        // 解析初始資料（空文件時傳入空陣列）
        let initialData = [];
        if (this._loadedContentJson) {
            try {
                initialData = JSON.parse(this._loadedContentJson);
            } catch (e) {
                console.warn("[DocEditor] content_json 解析失敗，以空白開始：", e);
            }
        }

        // 取得 PageMode / EditorMode 列舉（PAGING = 分頁置中模式，類 Google Docs）
        const CE = window["canvas-editor"];
        const PageMode = CE?.PageMode;
        const EditorMode = CE?.EditorMode;

        // 建立 Canvas 編輯器實例
        // readonly mode：portal 公開預覽或無寫入權限時走 EditorMode.READONLY
        const editorOptions = {
            pageMode: PageMode?.PAGING,
            // Phase 4：模型變數藥丸的預設外觀（每個元素可用 element.label 覆寫）
            label: {
                defaultBackgroundColor: PILL_STYLE.backgroundColor,
                defaultColor: PILL_STYLE.color,
                defaultBorderRadius: PILL_STYLE.borderRadius,
                defaultPadding: PILL_STYLE.padding,
            },
            // 待填欄位（control）：拿掉預設的 { } 大括號，改用底色標示。
            // 使用者原本看到的是 {{{ partner_id.name }}}——括號來自 canvas-editor
            // 的 prefix/postfix 預設值，外面再包一層我們寫進 placeholder 的 {{ }}。
            control: {
                prefix: "",
                postfix: "",
                placeholderColor: "#94a3b8",
                bracketColor: "#94a3b8",
                noValueBackgroundColor: "#fff4e5",
                existValueBackgroundColor: "#eef7ee",
                activeBackgroundColor: "#ffe0a3",
            },
        };
        if (this._isReadonly && EditorMode?.READONLY) {
            editorOptions.mode = EditorMode.READONLY;
        }
        this.editor = new EditorConstructor(container, initialData, editorOptions);

        // Sprint 16：content_json 為空但 content_html 有值（template 自動填充常見情境）
        // → 用 canvas-editor 的 executeSetHTML 把 HTML 轉成 IElement[] 灌入。
        // 觸發 contentChange 後 AutoSave 會把產生的 IElement[] 寫回 content_json，
        // 後續開啟就走 content_json 主路徑，本 fallback 不會重複觸發。
        const isEmptyJson = !this._loadedContentJson || initialData.length === 0;
        const html = (this._loadedContentHtml || "").trim();
        const isPlaceholderHtml = html === "" || html === "<p><br></p>" || html === "<p></p>";
        if (isEmptyJson && !isPlaceholderHtml) {
            try {
                if (typeof this.editor.command.executeSetHTML === "function") {
                    this.editor.command.executeSetHTML({ main: html });
                } else {
                    console.warn("[DocEditor] executeSetHTML 不存在，content_html fallback 失效");
                }
            } catch (err) {
                console.warn("[DocEditor] executeSetHTML 失敗，回退空白：", err);
            }
        }

        // 注冊繁體中文 locale，再切換（register.langMap 是 registerLangMap 的 bound 版本）
        this.editor.register.langMap("zhTW", {
            contextmenu: {
                global: { cut: "剪下", copy: "複製", paste: "貼上", selectAll: "全選", print: "列印" },
                table: {
                    insertRowCol: "插入行列",
                    insertTopRow: "上方插入 1 行",
                    insertBottomRow: "下方插入 1 行",
                    insertLeftCol: "左側插入 1 欄",
                    insertRightCol: "右側插入 1 欄",
                    deleteRowCol: "刪除行列",
                    deleteRow: "刪除 1 行",
                    deleteCol: "刪除 1 欄",
                    deleteTable: "刪除整個表格",
                    mergeCell: "合併儲存格",
                    mergeCancelCell: "取消合併",
                    verticalAlign: "垂直對齊",
                    verticalAlignTop: "靠上對齊",
                    verticalAlignMiddle: "垂直置中",
                    verticalAlignBottom: "靠下對齊",
                    border: "表格框線",
                    borderAll: "所有框線",
                    borderEmpty: "無框線",
                    borderDash: "虛線框線",
                    borderExternal: "外側框線",
                    borderInternal: "內側框線",
                    borderTd: "儲存格框線",
                },
                image: { change: "更換圖片", saveAs: "另存圖片", textWrap: "文字環繞" },
                hyperlink: { delete: "刪除連結", cancel: "取消連結", edit: "編輯連結" },
                control: { delete: "刪除控制項" },
            },
            zone: { headerTip: "頁首區域", footerTip: "頁尾區域" },
        });
        this.editor.command.executeSetLocale("zhTW");

        // 載入 DOCX 匯入/匯出 plugin（window.docx 由 canvas-editor-plugin-docx.umd.js 注入）
        if (window.docx) {
            this.editor.use(window.docx);
        } else {
            console.warn("[DocEditor] canvas-editor-plugin-docx 未載入，DOCX 匯入/匯出功能不可用");
        }

        // 暫時掛載全域，方便 DevTools 除錯（console 輸入 window._docEditor.command.getValue().data）
        window._docEditor = this.editor;
        // Sprint T 除錯後保留：暴露 OWL component instance，方便 E2E 探查 state / cache
        // （Playwright spec 可用 window._docEditorCmp.state.docId 等驗證 state）
        window._docEditorCmp = this;

        // Phase 8 Del 鍵同步：追蹤目前文件上所有 control 的 conceptId 集合，
        // contentChange 觸發時 diff 出消失的 id，批次呼叫後端 delete_field 同步紀錄。
        this._lastControlIds = new Set();

        // 監聽內容變更 → 觸發 AutoSave（使用引擎正式 API）
        this.editor.listener.contentChange = () => {
            // L2-v2：「自動進預覽模式」會 executeSetValue 灌入渲染後 content，
            // 這會觸發 contentChange 但屬於程式注入、不是 user 編輯，不該寫回 DB。
            if (this._suppressAutoSave) {
                return;
            }
            try {
                // 自動儲存關閉時不寫回 DB（使用者改用手動儲存）；其餘同步（縮圖、Del 同步）照常
                if (this.state.autoSaveEnabled) {
                    const json = JSON.stringify(this.editor.command.getValue().data);
                    if (this._offlineManager.isOnline) {
                        this._autoSave.onContentChange(json);
                    } else {
                        this._offlineManager.bufferOperation({ type: "save", json });
                        this.state.statusMsg = "離線緩存中";
                        this.state.statusType = "saving";
                    }
                }
            } catch (e) {
                console.error("[DocEditor] contentChange 處理失敗：", e);
            }
            // Phase 8 Del 同步：setTimeout 解耦，先讓 autoSave 入隊再做 diff
            setTimeout(() => this._syncDeletedControls(), 0);
            // Sprint C：debounced 重生縮圖（800ms 避免逐字打抖動）
            this._scheduleRebuildThumbnails(800);
        };

        // Phase 2.1 補項：監聽選區變動 → 反查 control.conceptId → 設 selectedFieldId
        // canvas-editor 在 caret 移動 / 選區變動時觸發 rangeStyleChange listener。
        // 透過 editor.command.getRangeContext() 取當前選區的 element，
        // 再從 element.control.conceptId 反查 doc.template.field.id。
        //
        // 設計：**只在偵測到 control 時 update selectedFieldId，偵測不到時保留現狀**。
        // 不自動 deselect 的原因（E2E 抓到的 bug）：
        //   1. executeInsertControl 後 caret 自動移到 control 之後 → 立刻被誤清為 null
        //   2. user 在 inspector 編輯期間焦點離開 canvas → 不該被誤清
        // user 真要 deselect：點別的 control 切換、或點 inspector 的「刪除」按鈕（內部清）。
        this.editor.listener.rangeStyleChange = () => {
            try {
                const ctx = this.editor.command.getRangeContext();
                if (!ctx) {
                    // 游標移出文件 / 無選區 → 隱藏表格工具列
                    if (this.state.inTable) this.state.inTable = false;
                    return;
                }
                const el = ctx.startElement || ctx.endElement || ctx.element || null;

                // 表格偵測：游標在儲存格內時顯示表格工具列（canvas-editor ctx.isTable）
                const inTable = !!ctx.isTable;
                if (this.state.inTable !== inTable) this.state.inTable = inTable;

                // 既有：control conceptId 反查 → selectedFieldId
                const conceptId = el?.control?.conceptId;
                if (conceptId) {
                    const fieldId = parseInt(conceptId, 10);
                    if (Number.isFinite(fieldId) && this.state.selectedFieldId !== fieldId) {
                        this.state.selectedFieldId = fieldId;
                    }
                }

                // Phase 4：模型變數藥丸 → selectedVariable。
                // 定義直接從元素身上讀（自描述），不需要任何 RPC。
                const meta = this._elementFieldMeta(el);
                if (meta) {
                    this.state.selectedVariable = { ...meta, _elementValue: el.value || "" };
                    this.state.selectedFieldId = null;
                } else if (this.state.selectedVariable) {
                    // 游標離開藥丸就收起面板——與 control 不同，這裡沒有
                    // 「插入後 caret 自動跳到後面」的誤清問題（label 是單一元素）。
                    this.state.selectedVariable = null;
                }

                // Sprint Y7：根據 selection 起點 element 的格式屬性、更新 format toolbar
                // active state。selection 跨多 element 樣式不一時、目前只看起點（簡化）。
                // 未來可改用 ctx 內彙整資料判斷 indeterminate（部分選中）。
                if (el) {
                    const b = el.bold === true;
                    const i = el.italic === true;
                    const u = el.underline === true;
                    const s = el.strikeout === true;
                    if (this.state.activeBold !== b) this.state.activeBold = b;
                    if (this.state.activeItalic !== i) this.state.activeItalic = i;
                    if (this.state.activeUnderline !== u) this.state.activeUnderline = u;
                    if (this.state.activeStrikeout !== s) this.state.activeStrikeout = s;

                    // Sprint Y8：font/size/color/highlight/rowFlex 也同步反映 caret 狀態
                    const font = el.font || '';
                    const sizeStr = el.size != null ? String(el.size) : '16';
                    if (this.state.activeFontFamily !== font) this.state.activeFontFamily = font;
                    if (this.state.activeFontSize !== sizeStr) this.state.activeFontSize = sizeStr;
                    // 字色 / 背景色：caret 文字真實顏色 → swatch + picker 預設值
                    const color = el.color || '#202124';
                    const hl = el.highlight || '#fff176';
                    if (this.state.textColor !== color) this.state.textColor = color;
                    if (this.state.highlightColor !== hl) this.state.highlightColor = hl;
                    // rowFlex 通常在 element 或 row 上、fallback 到 left
                    const rowFlex = el.rowFlex || ctx?.rowFlex || 'left';
                    if (this.state.activeRowFlex !== rowFlex) this.state.activeRowFlex = rowFlex;
                    // 標題樣式 select 同步（el.title = 'first'|'second'|… ；無 = 內文）
                    const title = el.title || '';
                    if (this.state.activeTitle !== title) this.state.activeTitle = title;
                }
            } catch (e) {
                // 不要讓 listener 抛例外破壞 canvas-editor 內部流程
            }
        };

        // Sprint B：同步 canvas-editor 頁碼狀態到 state，讓 pager / dashboard 即時反映。
        //   intersectionPageNoChange → 滾動時 viewport 可見頁變更
        //   pageSizeChange → 文件分頁數變更（新增/刪除內容導致分頁變化）
        //   pageScaleChange → 縮放比例變更（user 操作或 fit 模式觸發）
        this.editor.listener.intersectionPageNoChange = (pageNo) => {
            try {
                // canvas-editor 用 0-based pageNo；UI 顯示 1-based
                const oneBased = typeof pageNo === "number" ? pageNo + 1 : 1;
                if (this.state.pageNo !== oneBased) {
                    this.state.pageNo = oneBased;
                }
            } catch (e) {
                // 不要讓 listener 抛例外破壞 canvas-editor 內部流程
            }
        };
        this.editor.listener.pageSizeChange = () => {
            try {
                const total = typeof this.editor.command.getPageCount === "function"
                    ? this.editor.command.getPageCount()
                    : null;
                if (typeof total === "number" && total >= 1 && this.state.totalPages !== total) {
                    this.state.totalPages = total;
                }
            } catch (e) {
                // 容錯：API 不存在或拋例外時保留現有 state.totalPages
            }
            // Sprint C：分頁數變更時必更新縮圖
            this._scheduleRebuildThumbnails(600);
        };
        this.editor.listener.pageScaleChange = (scale) => {
            try {
                if (typeof scale === "number" && Number.isFinite(scale)) {
                    this.state.currentZoomScale = scale;
                }
            } catch (e) {
                // 容錯
            }
        };
        // 初始化時讀一次總頁數（避免 listener 沒觸發前 dashboard 顯示 1）
        try {
            const total = typeof this.editor.command.getPageCount === "function"
                ? this.editor.command.getPageCount()
                : 1;
            this.state.totalPages = total || 1;
            const cur = typeof this.editor.command.getPageNo === "function"
                ? this.editor.command.getPageNo()
                : 0;
            this.state.pageNo = (cur || 0) + 1;
        } catch (e) {
            // 容錯
        }

        // Sprint C：縮圖 panel 初始化 + 後續變更時 debounce 重生
        this._scheduleRebuildThumbnails(50);  // 初次延遲 50ms 等 canvas 真渲染
    }


    // ─── Sprint C：頁面縮圖（debounced）─────────────────────────────
    //
    // 設計：每頁 canvas-editor 渲染為獨立 <canvas> 元素，直接用 toDataURL
    // 取縮圖（壓縮品質 0.5 + max 200x283 ≈ A4 縮影）。
    // 重生時機：
    //   1. 初次 _initCanvasEditor 完（50ms 延遲等 canvas 真渲染）
    //   2. contentChange listener 觸發後（已內部 debounce、再加 thumbnail 自家 800ms debounce 避免抖動）
    //   3. pageSizeChange listener（分頁數變更時必更新）

    _scheduleRebuildThumbnails(delayMs = 800) {
        if (this._thumbnailTimer) {
            clearTimeout(this._thumbnailTimer);
        }
        this._thumbnailTimer = setTimeout(() => {
            this._thumbnailTimer = null;
            this._rebuildThumbnails();
        }, delayMs);
    }

    _rebuildThumbnails() {
        if (!this.canvasContainer?.el) {
            return;
        }
        try {
            const pageCanvases = this.canvasContainer.el.querySelectorAll("canvas");
            const MAX_W = 200;
            const thumbs = [];
            for (let i = 0; i < pageCanvases.length; i++) {
                const c = pageCanvases[i];
                // 跳過 0-size canvas（cursor canvas、隱藏 canvas）
                if (!c.width || !c.height) continue;
                let dataUrl;
                try {
                    // canvas-editor 主 page canvas 通常很大（A4 @ 96DPI × pixelRatio）
                    // 直接 toDataURL 對 100 頁文件會卡 UI；用 OffscreenCanvas 縮小
                    if (typeof OffscreenCanvas !== "undefined") {
                        const ratio = MAX_W / c.width;
                        const w = Math.max(1, Math.floor(c.width * ratio));
                        const h = Math.max(1, Math.floor(c.height * ratio));
                        const off = new OffscreenCanvas(w, h);
                        const ctx = off.getContext("2d");
                        ctx.drawImage(c, 0, 0, w, h);
                        // OffscreenCanvas.convertToBlob 是 async；用 toDataURL 退而求其次
                        // → 走 sync 路徑：建臨時 HTMLCanvasElement
                        const tmp = document.createElement("canvas");
                        tmp.width = w;
                        tmp.height = h;
                        tmp.getContext("2d").drawImage(c, 0, 0, w, h);
                        dataUrl = tmp.toDataURL("image/jpeg", 0.5);
                    } else {
                        dataUrl = c.toDataURL("image/jpeg", 0.3);
                    }
                } catch (toDataErr) {
                    // SecurityError / tainted canvas：跳過該頁
                    continue;
                }
                thumbs.push({
                    pageNo: thumbs.length + 1,
                    dataUrl: dataUrl,
                    fieldCount: 0,  // 後續可從 _templateFieldsCache 對應頁數 group by 算
                });
            }
            this.state.thumbnails = thumbs;
        } catch (e) {
            console.warn("[DocEditor] _rebuildThumbnails failed", e);
        }
    }


    // ─── 資料載入 ────────────────────────────────────────────────────


    // ─── Phase 1：編輯對象（文件 / 範本）共用存取器 ────────────────
    //
    // 所有以「編輯對象」為單位的 RPC（load / save / template_fields / versions）
    // 一律展開 targetRpcParams，不要各自寫 doc_id。後端 _resolve_edit_target
    // 拒絕同時收到兩個 id，這裡保證只送一個。

    get targetId() {
        if (this.state.editTarget === "output") return this.state.outputId;
        if (this.state.editTarget === "template") return this.state.templateId;
        return this.state.docId;
    }

    get targetRpcParams() {
        if (this.state.editTarget === "output") {
            return { output_id: this.state.outputId };
        }
        if (this.state.editTarget === "template") {
            return { template_id: this.state.templateId };
        }
        return { doc_id: this.state.docId };
    }

    get isTemplateTarget() {
        return this.state.editTarget === "template";
    }

    // 遙測用的識別。兩個遙測 model 的 doc_id 都是 doc.document 的外鍵，
    // 所以編範本／編輸出時不能把 targetId 當 doc_id 送——那會違反外鍵。
    // 編輯對象改放 extra（reportMetric/reportError 只認 docId/pageCount/extra，
    // 之前直接傳 editTarget 其實是被丟掉的）。
    get telemetryParams() {
        return {
            docId: this.state.editTarget === "doc" ? this.state.docId : null,
            extra: {
                editTarget: this.state.editTarget,
                targetId: this.targetId || null,
            },
        };
    }

    /** 輸出紀錄模式：唯讀瀏覽已產生的成品。 */
    get isOutputTarget() {
        return this.state.editTarget === "output";
    }

    /**
     * 載入當前編輯對象。取代舊的 _loadDocument(docId)——id 一律從 state 取，
     * 避免呼叫端在範本模式下誤傳 docId=null。
     */
    async _loadTarget() {
        const stopLoadTimer = mark("load_doc_ms");
        try {
            const data = await rpc("/dobtor_doc/load", this.targetRpcParams);
            this._loadFailed = false;
            if (data.edit_target === "output") {
                this.state.editTarget = "output";
                this.state.outputId = data.id;
                this.state.templateId = null;
                this.state.docId = null;
                this.state.outputMeta = data.output_meta || null;
                this._isReadonly = true;
            } else if (data.edit_target === "template") {
                this.state.editTarget = "template";
                this.state.templateId = data.id;
                this.state.docId = null;
            } else {
                this.state.editTarget = "document";
                this.state.docId = data.id;
                this.state.templateId = null;
            }
            this.state.docName = data.name;
            // F5 恢復用（帶 kind 前綴，避免範本 id 與文件 id 撞號）
            sessionStorage.setItem(
                "dobtor_doc_editor_last_id",
                `${this.state.editTarget}:${data.id}`
            );
            this.state.pageFormat = data.page_format || "A4";

            // 暫存 content_json，供 _initCanvasEditor 使用
            this._loadedContentJson = data.content_json || null;
            // Sprint 16：暫存 content_html，當 content_json 空但 HTML 有值（如 template
            // 自動填充情境）時，editor init 後 fallback 用 executeSetHTML 灌入。
            this._loadedContentHtml = data.content_html || "";
            // Phase 8：暫存目標 model_name，供 DocFieldPickerDialog 使用（onOdooFieldClick）
            this._loadedModelName = data.model_name || null;
            // L2-v2：暫存綁定 record（res_id 是不可變的 instance prop）
            this._loadedResId = data.res_id || null;
            // L2-v2：alias map 進 reactive state，供 sidebar 管理面板與插入流程共享
            this.state.fieldAliases = data.field_aliases || {};
            this.state.templateFieldAliases = data.template_field_aliases || {};
            this.state.templateName = data.template_name || "";
            // Phase 3 快照狀態（工具列顯示用）
            this.state.snapshotDate = data.snapshot_date || null;
            this.state.snapshotIsStale = !!data.snapshot_is_stale;
            // P2-2 樂觀鎖：記下伺服器當前 write_date
            this._lastSyncedWriteDate = data.write_date || null;
            // Phase 8 Template UI Builder（ADR-022）—— 載入範本 signer/field 狀態
            await this._loadTemplateFields();

            // DOCX 模板引擎狀態恢復（與範本編輯模式無關）
            if (data.has_template) {
                this.state.hasDocxTemplate = true;
                this.state.templateVariables = data.template_variables || [];
                this.state.templateFilename = data.template_filename || "";
            }

            this.state.editorReady = true;
            this.state.statusMsg = "已載入";
            this.state.statusType = "saved";
            stopLoadTimer(this.telemetryParams);
        } catch (error) {
            // 標記載入失敗：擋住 autosave，避免把空白編輯器內容寫回既有記錄
            this._loadFailed = true;
            this.state.statusMsg = `載入失敗：${error.message || error}`;
            this.state.statusType = "error";
            this.state.editorReady = true; // 避免永遠顯示載入中
            console.error("[DocEditor] Load failed:", error);
            // P2-4 上報 load 失敗
            reportError({
                type: "other",
                message: `Load failed: ${error.message || error}`,
                stackTrace: error?.stack || "",
                ...this.telemetryParams,
            });
        }
    }


    // ─── 離線同步 ────────────────────────────────────────────────────

    async _syncOfflineBuffer() {
        const ops = this._offlineManager.drainBuffer();
        if (!ops.length || !this.targetId) return;
        const lastSave = [...ops].reverse().find(op => op.type === "save");
        if (!lastSave) return;
        try {
            const result = await rpc("/dobtor_doc/save", {
                ...this.targetRpcParams,
                content_json: lastSave.json,
                if_unmodified_since: this._lastSyncedWriteDate,
            });
            this._handleSaveResult(result, lastSave.json);
            this.state.statusMsg = "已同步";
            this.state.statusType = "saved";
        } catch (e) {
            this.notification.add(`同步失敗：${e.message}`, { type: "danger" });
        }
    }

    /**
     * P2-2 樂觀鎖：處理 save 結果
     *  - 成功 → 更新 _lastSyncedWriteDate
     *  - 衝突 → 暫存到 IndexedDB（offline_manager），提示使用者，自動 reload
     */
    _handleSaveResult(result, jsonAttempted) {
        if (!result) return;
        if (result.conflict) {
            // 衝突：把當前未存的內容塞進 offline buffer 保留
            try {
                this._offlineManager?.bufferOperation?.({
                    type: "save",
                    json: jsonAttempted,
                    reason: "conflict",
                    ts: new Date().toISOString(),
                });
            } catch (e) {
                console.error("[DocEditor] buffer on conflict failed:", e);
            }
            this.state.statusMsg = "與他人編輯衝突";
            this.state.statusType = "error";
            const author = result.server_author_name || "他人";
            this.notification.add(
                `文件已被「${author}」修改（v${result.server_version_number}）。將重新載入最新內容；您剛才編輯的內容已暫存於離線緩衝。`,
                { type: "warning", sticky: true }
            );
            // 自動 reload 後端最新內容
            if (this.state.docId) {
                this._loadTarget().then(() => {
                    if (this.editor && this._loadedContentJson) {
                        try {
                            const data = JSON.parse(this._loadedContentJson);
                            this.editor.command.executeSetValue(data);
                        } catch (e) {
                            console.error("[DocEditor] reload after conflict failed:", e);
                        }
                    }
                });
            }
            return;
        }
        if (result.success && result.write_date) {
            this._lastSyncedWriteDate = result.write_date;
        }
    }


    // ─── 手動儲存 ────────────────────────────────────────────────────

    async onSave() {
        if (!this.state.docId || this.state.isSaving) return;
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return;
        }
        sessionStorage.setItem(
            "dobtor_doc_editor_last_id",
            `${this.state.editTarget}:${this.targetId}`
        );
        this.state.isSaving = true;
        this.state.statusMsg = "儲存中...";
        this.state.statusType = "saving";
        const stopSaveTimer = mark("save_latency_ms");
        try {
            const json = JSON.stringify(this.editor.command.getValue().data);
            const result = await rpc("/dobtor_doc/save", {
                ...this.targetRpcParams,
                content_json: json,
                content_html: this._mainHtml(),
                if_unmodified_since: this._lastSyncedWriteDate,
            });
            // P2-2: 衝突時 _handleSaveResult 會處理 reload + 警示
            this._handleSaveResult(result, json);
            if (!result?.conflict) {
                this.state.statusMsg = "已儲存";
                this.state.statusType = "saved";
            }
            stopSaveTimer(this.telemetryParams);
        } catch (error) {
            this.state.statusMsg = `儲存失敗：${error.message || error}`;
            this.state.statusType = "error";
            this.notification.add("文件儲存失敗", { type: "danger" });
            reportError({
                type: "save_failure",
                message: error.message || String(error),
                stackTrace: error?.stack || "",
                docId: this.state.docId,
            });
        } finally {
            this.state.isSaving = false;
        }
    }


    // ─── Toolbar 事件 ────────────────────────────────────────────────

    /**
     * 標題欄（檔名）改名。
     *
     * ☠️ 原本這支也叫 onTitleChange，而下面「格式列補充功能」那一段也有一支
     * onTitleChange（套標題樣式）。同一個 class 裡同名方法，**後面那個無聲
     * 覆蓋前面那個**——於是標題欄打完字送出時跑的是 executeTitle(檔名)，
     * 改名完全沒有作用，而且不會報錯。
     * 2026-10-09 拆檔時逐一比對成員才發現（名稱集合出現重複）。
     */
    onDocNameChange(event) {
        const newName = event.target.value.trim() || "未命名文件";
        this.state.docName = newName;
        if (this.targetId) {
            rpc("/dobtor_doc/save", { ...this.targetRpcParams, name: newName })
                .catch(() => {});
        }
    }

    onZoomChange(event) {
        if (!this.editor) return;
        const scale = parseFloat(event.target.value);
        if (!isNaN(scale)) {
            this.editor.command.executePageScale(scale);
        }
    }

    onPageFormatChange(event) {
        if (!this.editor) return;
        // A4 size in pixels @ 96 DPI
        const PAGE_SIZES = {
            A4:     [794,  1123],
            A3:     [1123, 1587],
            A5:     [559,  794],
            letter: [816,  1056],
            legal:  [816,  1344],
        };
        const format = event.target.value;
        const size = PAGE_SIZES[format];
        if (size) {
            this.editor.command.executePaperSize(size[0], size[1]);
            this.state.pageFormat = format;
        }
    }


    // ─── 左右側面板收合 ───────────────────────────────────────────
    //
    // 為什麼不用 t-if 整個拿掉：canvas-editor 的實例掛在工作區裡，而
    // 「t-if 把 canvas-editor unmount 會炸」是這個檔案開頭就記著的既有限制。
    // 側面板本身 t-if 掉是安全的（它們沒有 canvas），但 grid 的欄寬要跟著變，
    // 否則收合後中間不會變寬——所以用 style 綁 grid-template-columns。

    get leftPanelWidth() {
        return this.state.leftPanelCollapsed ? '28px' : '';
    }

    get rightPanelWidth() {
        return this.state.rightPanelCollapsed ? '28px' : '';
    }

    /** .doc-main 的 grid 欄寬。空字串＝用 CSS 的預設值（含 media query）。 */
    get mainGridStyle() {
        const l = this.state.leftPanelCollapsed;
        const r = this.state.rightPanelCollapsed;
        if (!l && !r) {
            return this.state.activeSubNav === 'templates'
                ? '' : 'display: none;';
        }
        const cols = `${l ? '28px' : '180px'} 1fr ${r ? '28px' : '280px'}`;
        const hidden = this.state.activeSubNav === 'templates'
            ? '' : 'display: none;';
        return `grid-template-columns: ${cols}; ${hidden}`;
    }

    onToggleLeftPanel() {
        this.state.leftPanelCollapsed = !this.state.leftPanelCollapsed;
        _lsSet('dobtor_doc_editor_left_collapsed',
               this.state.leftPanelCollapsed ? '1' : '0');
    }

    onToggleRightPanel() {
        this.state.rightPanelCollapsed = !this.state.rightPanelCollapsed;
        _lsSet('dobtor_doc_editor_right_collapsed',
               this.state.rightPanelCollapsed ? '1' : '0');
    }


    // ─── 工具方法 ────────────────────────────────────────────────────

    get statusClass() {
        const map = {
            saved:  "doc-statusbar-saved",
            saving: "doc-statusbar-saving",
            error:  "doc-statusbar-error",
        };
        return map[this.state.statusType] || "";
    }

    get offlineBadge() {
        return !this.state.isOnline;
    }


    // ─── Sprint Y2：ruler 動態跟 paper size + zoom 同步 ──────────────
    /**
     * 目前 paper width（公分）。1cm = 96/2.54 ≈ 37.795 px @ 96 DPI；
     * 反算現有 onPageFormatChange 的 PAGE_SIZES px → cm。
     */
    get _paperWidthCm() {
        const PAPER_W_CM = {
            A4: 21.0,
            A3: 29.7,
            A5: 14.8,
            letter: 21.59,
            legal: 21.59,
        };
        return PAPER_W_CM[this.state.pageFormat] || 21.0;
    }

    /**
     * ruler tick label 陣列（1, 2, ..., ceil(paperWidthCm)）。
     * 取整數公分，最後一格可能略超出紙張寬（視覺無妨）。
     */
    get rulerTicks() {
        const n = Math.ceil(this._paperWidthCm);
        const out = [];
        for (let i = 1; i <= n; i++) out.push(i);
        return out;
    }

    /**
     * ruler inline style：`--ruler-cm-px` 跟 zoom scale 同步（37.8px × zoom）。
     * CSS 用 `flex: 0 0 var(--ruler-cm-px)` 撐每個 tick 寬、整個 ruler 寬度
     * = ticks × cm-px = 跟 canvas 紙張視覺寬同步。
     */
    get rulerStyle() {
        const CM_PX_BASE = 37.795;   // 96 DPI / 2.54
        const scale = this.state.currentZoomScale || 1;
        const cmPx = (CM_PX_BASE * scale).toFixed(2);
        return `--ruler-cm-px: ${cmPx}px;`;
    }


    // ─── Sprint Y3：Google Docs 風 功能 menu bar ──────────────────
    // 6 個下拉 menu（檔案/編輯/查看/插入/格式/工具），互動：
    //   1. 點 trigger 開/關 dropdown
    //   2. dropdown 開著時 hover 其他 trigger → 切換到該 menu（Google Docs 行為）
    //   3. 點 menu-item → 跑 action 後關閉
    //   4. 點外 / 按 Escape → 關閉（listener 在 setup 註冊）

    onMenuTriggerClick(name) {
        this.state.openMenu = (this.state.openMenu === name) ? null : name;
        // Sprint Y14：mouse 開 dropdown 時不預設 focus（user 通常會繼續用滑鼠）
        this.state.menuFocusIndex = -1;
    }

    onMenuTriggerHover(name) {
        // 只在已有 menu 開著時才 hover-switch（避免單純滑過 trigger 就自動展開）
        if (this.state.openMenu && this.state.openMenu !== name) {
            this.state.openMenu = name;
            this.state.menuFocusIndex = -1;  // Y14：切 menu 重置 focus
        }
    }


    // ─── Sprint Y14：menu dropdown 鍵盤導航 ─────────────────────────
    // 找出目前開啟 menu 的 items 陣列（用在鍵盤導航計算 prev/next）
    _currentMenuItems() {
        if (!this.state.openMenu) return [];
        const menu = this.menuConfig.find(m => m.name === this.state.openMenu);
        return menu?.items || [];
    }

    // skipDirection：+1=下一個、-1=前一個。從 fromIdx 出發找下一個非 separator/disabled 的 index。
    // 找不到時回 fromIdx（保持原焦點）。處理 wrap：到底翻到第一個、到頂翻到最後一個。
    _nextFocusableMenuIndex(fromIdx, dir) {
        const items = this._currentMenuItems();
        if (items.length === 0) return -1;
        const n = items.length;
        let i = fromIdx;
        for (let step = 0; step < n; step++) {
            i = (i + dir + n) % n;
            const it = items[i];
            if (it && it.type !== 'separator' && !it.disabled) return i;
        }
        return fromIdx;
    }

    // 跳到第 1 個 / 最後一個可聚焦 item
    _firstFocusableMenuIndex() { return this._nextFocusableMenuIndex(-1, +1); }
    _lastFocusableMenuIndex()  { return this._nextFocusableMenuIndex( 0, -1); }

    // Mouse hover dropdown item → 同步 focus index（鍵盤與滑鼠不打架）
    onMenuItemHover(idx) {
        this.state.menuFocusIndex = idx;
    }

    // ←→ 切換到 prev/next menu（wrap）；切換時 focus 重置回 -1（mouse 取得）或 0（鍵盤剛切的）
    _switchMenuByOffset(offset, focusFirst) {
        const menus = this.menuConfig;
        const curIdx = menus.findIndex(m => m.name === this.state.openMenu);
        if (curIdx < 0) return;
        const next = menus[(curIdx + offset + menus.length) % menus.length];
        this.state.openMenu = next.name;
        this.state.menuFocusIndex = focusFirst ? this._firstFocusableMenuIndex() : -1;
    }

    onMenuItemClick(action) {
        this.state.openMenu = null;
        this.state.menuFocusIndex = -1;
        if (!action) return;
        try {
            switch (action) {
                case 'file:rename': this._focusTitleInput(); break;
                case 'file:import': this.onImportClick(); break;
                case 'file:export-pdf': this.onExportPdf(); break;
                case 'file:export-docx': this.onExportDocx(); break;
                case 'file:print': this._executeCmd('executePrint'); break;
                case 'file:preview': this.onPreviewClick(); break;
                case 'file:toggle-preview-mode': this.onTogglePreviewMode(); break;
                case 'file:save': this.onSave(); break;
                case 'file:close': this.onClose(); break;

                case 'edit:undo': this._executeCmd('executeUndo'); break;
                case 'edit:redo': this._executeCmd('executeRedo'); break;
                case 'edit:cut': this._tryExecCommand('cut'); break;
                case 'edit:copy': this._tryExecCommand('copy'); break;
                case 'edit:paste': this._tryExecCommand('paste'); break;
                case 'edit:find': this.openFindReplace('find'); break;
                case 'edit:replace': this.openFindReplace('replace'); break;

                case 'view:toggle-ruler': this.state.showRuler = !this.state.showRuler; break;
                case 'view:toggle-legacy-toolbar':
                    this.state.showLegacyToolbar = !this.state.showLegacyToolbar;
                    _lsSet('dobtor_doc_editor_show_legacy_toolbar',
                           this.state.showLegacyToolbar ? '1' : '0');
                    break;
                case 'view:toggle-thumbnails': this.state.showThumbnails = !this.state.showThumbnails; break;
                case 'view:cycle-theme': this.onCycleTheme(); break;
                // Sprint Y11：紙張格式從 menubar 直接套用（取代被 hide 的 Row 3 toolbar select）
                case 'view:paper-A4':     this.onPageFormatChange({ target: { value: 'A4' } }); break;
                case 'view:paper-A3':     this.onPageFormatChange({ target: { value: 'A3' } }); break;
                case 'view:paper-A5':     this.onPageFormatChange({ target: { value: 'A5' } }); break;
                case 'view:paper-letter': this.onPageFormatChange({ target: { value: 'letter' } }); break;
                case 'view:paper-legal':  this.onPageFormatChange({ target: { value: 'legal' } }); break;
                case 'view:zoom-50': this._setZoom(0.5); break;
                case 'view:zoom-100': this._setZoom(1); break;
                case 'view:zoom-150': this._setZoom(1.5); break;
                case 'view:zoom-200': this._setZoom(2); break;
                case 'view:zoom-fit': this.onZoomFitChange({ target: { value: 'width' } }); break;
                case 'view:fullscreen': this._requestFullscreen(); break;

                case 'insert:table': this.state.showTablePicker = true; break;
                case 'insert:image': this._insertImagePicker(); break;
                case 'insert:var-text': this.onFieldButtonClick('text'); break;
                case 'insert:var-date': this.onFieldButtonClick('date'); break;
                case 'insert:var-checkbox': this.onFieldButtonClick('checkbox'); break;
                case 'insert:alias-field': this.onInsertAliasClick(); break;

                case 'format:bold': this._executeCmd('executeBold'); break;
                case 'format:italic': this._executeCmd('executeItalic'); break;
                case 'format:underline': this._executeCmd('executeUnderline'); break;
                case 'format:strikeout': this._executeCmd('executeStrikeout'); break;
                case 'format:align-left': this._executeCmd('executeRowFlex', 'left'); break;
                case 'format:align-center': this._executeCmd('executeRowFlex', 'center'); break;
                case 'format:align-right': this._executeCmd('executeRowFlex', 'right'); break;
                case 'format:align-justify': this._executeCmd('executeRowFlex', 'alignment'); break;
                case 'format:clear-format': this._executeCmd('executePainterStyle', {}); break;
                case 'format:line-spacing': this.onOpenLineSpacing(); break;

                case 'tools:scan-vars': this.onScanVariablesClick(); break;
                case 'tools:scan-replace': this.onScanAndReplaceClick(); break;
                case 'tools:preview-vars': this.onPreviewVariablesClick(); break;
                case 'tools:rollback': this.onRollbackScanReplaceClick(); break;
                case 'tools:word-count': this._countWords(); break;
                case 'tools:version-history': this.onShowVersionPanel(); break;
                case 'tools:doc-settings': this.onOpenDocSettings(); break;

                case 'panel:templates': this.onSubNavClick('templates'); break;
                case 'panel:dashboard': this.onSubNavClick('dashboard'); break;
                case 'panel:requests': this.onSubNavClick('requests'); break;
                case 'panel:settings': this.onSubNavClick('settings'); break;
            }
        } catch (e) {
            console.error('[DocEditor.menubar] action failed:', action, e);
            this.notification?.add?.(`動作執行失敗：${action}`, { type: 'warning' });
        }
    }


    // ─── menu 動作底層 helpers ───
    _executeCmd(name, ...args) {
        try {
            const fn = this.editor?.command?.[name];
            if (typeof fn === 'function') {
                fn.apply(this.editor.command, args);
                return true;
            }
            this.notification?.add?.(`canvas-editor 不支援命令：${name}`, { type: 'warning' });
            return false;
        } catch (e) {
            console.error('[DocEditor._executeCmd]', name, e);
            this.notification?.add?.(`命令執行失敗：${name}`, { type: 'warning' });
            return false;
        }
    }

    _tryExecCommand(cmd) {
        try {
            const ok = document.execCommand(cmd);
            if (!ok) {
                this.notification?.add?.(`瀏覽器拒絕執行：${cmd}（請改用快捷鍵）`, { type: 'info' });
            }
        } catch (e) { /* ignore */ }
    }

    _setZoom(scale) {
        try {
            if (this.editor?.command?.executePageScale) {
                this.editor.command.executePageScale(scale);
            }
            this.state.currentZoomScale = scale;
        } catch (e) {
            console.error('[DocEditor._setZoom]', e);
        }
    }

    _countWords() {
        try {
            const data = this.editor?.command?.getValue?.()?.data;
            if (!data) return;
            const flat = flattenElementsToText(data.main || []);
            const chars = flat.length;
            const words = flat.trim().split(/\s+/).filter(Boolean).length;
            this.notification?.add?.(`字數統計：${chars} 字（含空白）／${words} 詞`, { type: 'info' });
        } catch (e) {
            console.error('[DocEditor._countWords]', e);
        }
    }

    _focusTitleInput() {
        try {
            const el = document.querySelector('.o_dobtor_doc_editor .doc-header-title');
            el?.focus?.();
            el?.select?.();
        } catch (e) { /* ignore */ }
    }


    // ─── Sprint Y17：文件設定 modal ───
    // canvas-editor 提供 executePaperSize(w,h) / executePaperDirection('vertical'|'horizontal')
    // / executeSetPaperMargin([top,right,bottom,left])，全用 px @ 96 DPI。modal form 用 mm
    // 顯示給 user（更直觀）、apply 時轉 px 寫回去。
    _mmToPx(mm) { return Math.round(Number(mm) * 96 / 25.4); }
    _pxToMm(px) { return Math.round(Number(px) * 25.4 / 96); }

    onOpenDocSettings() {
        // 從目前 canvas-editor state hydrate form
        const margins = this.editor?.command?.getPaperMargin?.();
        const f = this.state.docSettingsForm;
        f.format = this.state.pageFormat || 'A4';
        // direction 沒有 getter；保留上次選擇即可
        if (Array.isArray(margins) && margins.length === 4) {
            f.marginTopMm = this._pxToMm(margins[0]);
            f.marginRightMm = this._pxToMm(margins[1]);
            f.marginBottomMm = this._pxToMm(margins[2]);
            f.marginLeftMm = this._pxToMm(margins[3]);
        }
        this.state.openMenu = null;
        this.state.menuFocusIndex = -1;
        this.state.showDocSettings = true;
    }

    onCloseDocSettings() {
        this.state.showDocSettings = false;
    }

    onDocSettingsSet(field, value, ev = null) {
        // input change handler — Numeric clamped to [0, 80] mm；format/direction 直接套
        if (field === 'format' || field === 'direction') {
            this.state.docSettingsForm[field] = value;
            return;
        }
        const n = Number(value);
        if (isNaN(n)) return;
        const clamped = Math.max(0, Math.min(80, n));
        this.state.docSettingsForm[field] = clamped;
        // Sprint Y29：margin input clamp UX — 沿用 Y28 motif、user 打超範圍立刻看到
        // clamp 值。OWL t-att-value 不會覆蓋 user typing 後的 .value property、手動寫。
        if (ev?.target && String(clamped) !== String(value)) {
            ev.target.value = String(clamped);
        }
    }

    onApplyDocSettings() {
        const f = this.state.docSettingsForm;
        const PAGE_SIZES = {
            A4: [794, 1123], A3: [1123, 1587], A5: [559, 794],
            letter: [816, 1056], legal: [816, 1344],
        };
        try {
            const [w, h] = PAGE_SIZES[f.format] || PAGE_SIZES.A4;
            // 方向 = horizontal 時長寬互換
            const [pw, ph] = f.direction === 'horizontal' ? [h, w] : [w, h];
            this.editor?.command?.executePaperSize?.(pw, ph);
            this.editor?.command?.executePaperDirection?.(f.direction);
            this.editor?.command?.executeSetPaperMargin?.([
                this._mmToPx(f.marginTopMm),
                this._mmToPx(f.marginRightMm),
                this._mmToPx(f.marginBottomMm),
                this._mmToPx(f.marginLeftMm),
            ]);
            this.state.pageFormat = f.format;
            this.state.showDocSettings = false;

            // 寫回後端。原本只套用到記憶體中的 canvas，重新載入就沒了——
            // 而報表引擎以範本的 page_format / margin_* 當列印依據，
            // 存不進去的話使用者調完邊距列印出來會不一樣，且沒有任何錯誤訊息。
            if (this.targetId && !this._isReadonly) {
                rpc("/dobtor_doc/save_settings", {
                    ...this.targetRpcParams,
                    page_format: f.format,
                    margin_top: this._mmToPx(f.marginTopMm),
                    margin_right: this._mmToPx(f.marginRightMm),
                    margin_bottom: this._mmToPx(f.marginBottomMm),
                    margin_left: this._mmToPx(f.marginLeftMm),
                }).catch((e) => {
                    console.warn("[DocEditor] 文件設定寫回後端失敗", e);
                    this.notification?.add?.(
                        '版面已套用到畫面，但儲存失敗——重新載入後會回到舊設定。',
                        { type: 'warning' }
                    );
                });
            }
            this.notification?.add?.('文件設定已套用', { type: 'success' });
        } catch (e) {
            console.error('[DocEditor.onApplyDocSettings]', e);
            this.notification?.add?.('套用文件設定失敗', { type: 'danger' });
        }
    }


    // ─── Sprint Y18：行距 modal ───
    // canvas-editor `executeRowMargin(payload)` 將 payload 寫到 rangeRowElement.rowMargin，
    // dom 渲染時用作 lineHeight（default = 1）。modal 用 number input + 6 個 preset 按鈕。
    LINE_SPACING_PRESETS = [1.0, 1.15, 1.5, 2.0, 2.5, 3.0];

    onOpenLineSpacing() {
        this.state.openMenu = null;
        this.state.menuFocusIndex = -1;
        this.state.showLineSpacing = true;
    }

    onCloseLineSpacing() {
        this.state.showLineSpacing = false;
    }

    onLineSpacingSet(value, ev = null) {
        const n = Number(value);
        if (isNaN(n)) return;
        // canvas-editor 對 rowMargin 沒做上下界、但 < 0.5 視覺破壞、> 5 浪費 — clamp 安全範圍
        const clamped = Math.max(0.5, Math.min(5, n));
        this.state.lineSpacingValue = clamped;
        // Sprint Y28：user 打超過上下界時 input UI 也立刻反映 clamp 值
        // OWL `t-att-value` 只寫 attribute、不會覆蓋 user input 的 .value property、
        // 必須手動 set .value 才看得到 clamp。preset 按鈕走另一條（沒 ev）、不影響。
        if (ev?.target && String(clamped) !== String(value)) {
            ev.target.value = String(clamped);
        }
    }

    onApplyLineSpacing() {
        try {
            const val = Number(this.state.lineSpacingValue);
            if (isNaN(val)) {
                this.notification?.add?.('行距數值無效', { type: 'warning' });
                return;
            }
            this.editor?.command?.executeRowMargin?.(val);
            this.state.showLineSpacing = false;
            this.notification?.add?.(`行距已設為 ${val}`, { type: 'success' });
        } catch (e) {
            console.error('[DocEditor.onApplyLineSpacing]', e);
            this.notification?.add?.('套用行距失敗', { type: 'danger' });
        }
    }


    // ─── Sprint Y19：三段 themeMode（auto / light / dark）─────────
    _themeLabel() {
        const m = this.state?.themeMode;
        if (m === 'dark') return '深色';
        if (m === 'light') return '淺色';
        return '跟系統';
    }

    _recomputeDarkMode() {
        const mode = this.state?.themeMode;
        let dark = false;
        if (mode === 'dark') dark = true;
        else if (mode === 'light') dark = false;
        else {
            // auto：跟 system prefers-color-scheme
            try { dark = !!window.matchMedia?.('(prefers-color-scheme: dark)')?.matches; }
            catch (e) { dark = false; }
        }
        if (this.state && this.state.darkMode !== dark) {
            this.state.darkMode = dark;
        }
    }

    onCycleTheme() {
        // 循環 auto → light → dark → auto
        const cur = this.state.themeMode;
        const next = cur === 'auto' ? 'light' : cur === 'light' ? 'dark' : 'auto';
        this.state.themeMode = next;
        _lsSet('dobtor_doc_editor_theme_mode', next);
        this._recomputeDarkMode();
        this.notification?.add?.(`外觀：${this._themeLabel()}`, { type: 'info' });
    }


    // ─── Sprint Y18：清除最近用色（Y13 留尾巴）
    onClearRecentColors(kind) {
        // kind = 'text' | 'highlight'；只清那一組、不動另一組
        if (kind !== 'text' && kind !== 'highlight') return;
        this.state.recentColors[kind] = [];
        _lsSet('dobtor_doc_editor_recent_colors', this.state.recentColors, { json: true });
    }

    _requestFullscreen() {
        try {
            if (document.fullscreenElement) {
                document.exitFullscreen?.();
            } else {
                document.documentElement.requestFullscreen?.();
            }
        } catch (e) { /* ignore */ }
    }

    _insertImagePicker() {
        try {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*';
            input.onchange = () => {
                const file = input.files?.[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = () => {
                    const dataUrl = reader.result;
                    const fn = this.editor?.command?.executeInsertImage;
                    if (typeof fn !== 'function') {
                        this.notification?.add?.('canvas-editor 不支援插入圖片', { type: 'warning' });
                        return;
                    }
                    const img = new Image();
                    img.onload = () => {
                        const maxW = 600;
                        const w = Math.min(img.naturalWidth, maxW);
                        const h = (img.naturalHeight / img.naturalWidth) * w;
                        try {
                            this.editor.command.executeInsertImage({ value: dataUrl, width: w, height: h });
                        } catch (e) {
                            console.error('[DocEditor._insertImagePicker] insert failed', e);
                        }
                    };
                    img.src = dataUrl;
                };
                reader.readAsDataURL(file);
            };
            input.click();
        } catch (e) {
            console.error('[DocEditor._insertImagePicker]', e);
        }
    }


    // ─── Sprint Y4：尋找／取代 panel handlers ─────────────────────
    // canvas-editor API：executeSearch(text|null) / executeReplace(newText) /
    // executeSearchNavigateNext / executeSearchNavigatePre
    openFindReplace(mode) {
        this.state.findReplaceMode = mode;
        this.state.openMenu = null;
        // OWL render 是非同步 — 用 setTimeout 跳到下一輪 macrotask 才 focus 到新 DOM。
        // Promise.resolve().then() 在 OWL commit 之前就執行了、抓不到 input。
        setTimeout(() => {
            const el = document.querySelector('.o_dobtor_doc_editor .doc-find-input');
            if (el) { el.focus(); el.select(); }
        }, 50);
        if (this.state.findText) {
            try { this.editor?.command?.executeSearch?.(this.state.findText); } catch (e) { /* ignore */ }
            this._updateMatchInfo();
        }
    }


    // ─── Sprint Y10：讀 canvas-editor getSearchNavigateInfo 同步 match count
    _updateMatchInfo() {
        try {
            const info = this.editor?.command?.getSearchNavigateInfo?.();
            const count = info?.count ?? 0;
            const idx = info?.index ?? -1;
            this.state.findMatchCount = count;
            this.state.findMatchIndex = (count > 0 && idx >= 0) ? (idx + 1) : 0;
        } catch (e) {
            this.state.findMatchCount = 0;
            this.state.findMatchIndex = 0;
        }
    }

    closeFindReplace() {
        this.state.findReplaceMode = false;
        try { this.editor?.command?.executeSearch?.(null); } catch (e) { /* ignore */ }
        this.state.findMatchCount = 0;
        this.state.findMatchIndex = 0;
    }

    onFindTextInput(ev) {
        this.state.findText = ev.target.value;
        try {
            this.editor?.command?.executeSearch?.(this.state.findText || null);
        } catch (e) { /* ignore */ }
        this._updateMatchInfo();
    }

    onReplaceTextInput(ev) {
        this.state.replaceText = ev.target.value;
    }

    onFindNext() {
        if (!this.state.findText) return;
        // Sprint Y38：0 match 時鍵盤 Enter 也短路、跟 Y33 button disabled 行為一致
        //   button click 在 disabled 時被擋、但鍵盤 Enter 走的是 onFindInputKeyDown → onFindNext
        //   path、handler 本身得自防衛、避免在 stale state 下 call canvas-editor
        //   executeSearchNavigateNext（可能 throw / 跳到不存在位置）。
        if (this.state.findMatchCount === 0) return;
        this._executeCmd('executeSearchNavigateNext');
        this._updateMatchInfo();
    }

    onFindPrev() {
        if (!this.state.findText) return;
        if (this.state.findMatchCount === 0) return;  // Y38: 同上
        this._executeCmd('executeSearchNavigatePre');
        this._updateMatchInfo();
    }

    onReplaceOnce() {
        if (!this.state.findText) return;
        // Sprint Y30：runtime probe 發現 canvas-editor 的 `replace(payload)` 不傳 option
        // 時是 replaceAll、不是「取代一個」（我們的 `onReplaceOnce` 從 Y4 就誤命名）。
        // 走 `executeReplace(text, { index: 0 })` 才會只替換第 0 個 matchGroup（單一 match）。
        // 之後再用 flat text indexOf 算剩餘 count、UI 顯「1 / n-1」連貫不跳「無結果」。
        try {
            this.editor?.command?.executeSearch?.(this.state.findText);
            this.editor?.command?.executeReplace?.(this.state.replaceText || '', { index: 0 });
        } catch (e) {
            console.error('[DocEditor] replace once failed', e);
            this.notification?.add?.(`取代失敗：${e.message || e}`, { type: 'warning' });
        }
        // refresh count via flat text（不靠 canvas-editor stale getSearchNavigateInfo）
        try {
            const data = this.editor?.command?.getValue?.()?.data;
            const flat = data ? flattenElementsToText(data.main || []) : '';
            const needle = this.state.findText;
            let count = 0;
            let pos = 0;
            while (needle && (pos = flat.indexOf(needle, pos)) !== -1) {
                count++;
                pos += needle.length;
            }
            this.state.findMatchCount = count;
            this.state.findMatchIndex = count > 0 ? 1 : 0;
            // Sprint Y31：剩餘 match > 0 時、re-search refresh canvas-editor 內部 search
            // 狀態（讓 highlight 重新指向新 doc 內的第一個 match）— 等效 user click
            // 「下一個」按鈕、Google Docs / VS Code 同樣 UX。
            if (count > 0) {
                try { this.editor?.command?.executeSearch?.(this.state.findText); }
                catch (e) { /* ignore */ }
            }
        } catch (e) {
            this._updateMatchInfo();
        }
    }

    // executeReplace 只取代當前一個 match，要 replaceAll 須 loop。
    // 用 flatten text indexOf 判斷停止條件 + SAFE_GUARD 避免無限 loop（同 Sprint W 模式）。
    onReplaceAll() {
        if (!this.state.findText) return;
        const SAFE_GUARD = 500;
        // Sprint Y34：pre-scan flat indexOf 算 count
        //   Y30 揭露 executeReplace 不傳 { index } = replaceAll；舊 loop count++ 假設
        //   每 iteration 替換 1 個、實際每 iteration 替換 N 個（loop 通常只跑 1 次）、
        //   notification 顯「已取代 1 個項目」但 user 實際替換了 N 個。
        //   改用原文 flat 預掃 needle 出現次數 = user 看到的真實 N。
        let count = 0;
        try {
            const initialData = this.editor?.command?.getValue?.()?.data;
            const initialFlat = initialData ? flattenElementsToText(initialData.main || []) : '';
            const needle = this.state.findText;
            let pos = 0;
            while (needle && (pos = initialFlat.indexOf(needle, pos)) !== -1) {
                count++;
                pos += needle.length;
            }
            // 仍保留 loop 執行替換、defensive 處理 lib 萬一沒一次替換完的 edge case
            for (let i = 0; i < SAFE_GUARD; i++) {
                const data = this.editor?.command?.getValue?.()?.data;
                if (!data) break;
                const flat = flattenElementsToText(data.main || []);
                if (flat.indexOf(this.state.findText) < 0) break;
                this.editor.command.executeSearch(this.state.findText);
                this.editor.command.executeReplace(this.state.replaceText || '');
            }
            this.notification?.add?.(`已取代 ${count} 個項目`, { type: 'info' });
            try { this.editor?.command?.executeSearch?.(null); } catch (e) { /* ignore */ }
        } catch (e) {
            console.error('[DocEditor] replace all failed', e);
            this.notification?.add?.(`取代失敗：${e.message || e}`, { type: 'warning' });
        }
        // 全部取代後 match count 應歸零（cmd.executeSearch(null) 已清高亮）
        this.state.findMatchCount = 0;
        this.state.findMatchIndex = 0;
    }


    // ─── Sprint Y5：格式化工具列 handlers ─────────────────────────
    // 字型 / 字號 select 變動時直接接 canvas-editor cmd；按鈕（B/I/U/align/clear）
    // 在 XML 用 inline t-on-click="() => this._executeCmd(...)" 不用獨立 method。

    onFontFamilyChange(ev) {
        const v = ev.target.value;
        if (!v) return;
        this._executeCmd('executeFont', v);
    }

    onFontSizeChange(ev) {
        const s = parseInt(ev.target.value, 10);
        if (!s || s <= 0) return;
        this._executeCmd('executeSize', s);
    }


    // ─── Sprint Y13：把一個色 push 到 recent list 前端、dedup、限 6 個、寫 localStorage
    _pushRecentColor(type, color) {
        if (!color || !this.state.recentColors) return;
        const norm = String(color).toLowerCase();
        const list = this.state.recentColors[type] || [];
        // 移除重複
        const filtered = list.filter(c => String(c).toLowerCase() !== norm);
        // 前端 push、限 6 個（OWL reactive：整個替換 array 才會觸發 re-render）
        this.state.recentColors[type] = [color, ...filtered].slice(0, 6);
        _lsSet('dobtor_doc_editor_recent_colors', this.state.recentColors, { json: true });
    }


    // ─── Sprint Y6：字色 / 背景色（保留：「自訂色」逃生口仍用 native input）───
    onTextColorChange(ev) {
        const c = ev.target.value;
        if (!c) return;
        this.state.textColor = c;       // 同步 UI swatch
        this._executeCmd('executeColor', c);
        this._pushRecentColor('text', c);     // Y13
        this.state.showColorPalette = null;   // 自訂色完成後關 palette
    }

    onHighlightColorChange(ev) {
        const c = ev.target.value;
        if (!c) return;
        this.state.highlightColor = c;
        this._executeCmd('executeHighlight', c);
        this._pushRecentColor('highlight', c);    // Y13
        this.state.showColorPalette = null;
    }


    // ─── Sprint Y12：24 色 palette dropdown ───
    // 4 排 × 6 色：第 1 排灰階、第 2-4 排主色（淺/正/深三段）— Google Docs 風配置
    get COLOR_PALETTE() {
        return [
            // 第 1 排：灰階（白 → 黑）
            ['#ffffff', '#f1f3f4', '#bdc1c6', '#80868b', '#3c4043', '#000000'],
            // 第 2 排：主色（淺）
            ['#fce8e6', '#fce5cd', '#fff2cc', '#d9ead3', '#d0e0e3', '#cfe2f3'],
            // 第 3 排：主色（正）
            ['#ea4335', '#fbbc04', '#fff176', '#34a853', '#46bdc6', '#4285f4'],
            // 第 4 排：主色（深）
            ['#a52714', '#b45f06', '#bf9000', '#0f9d58', '#134f5c', '#0b5394'],
        ];
    }

    // 點 swatch trigger / 下拉箭頭 → 開/關 palette
    onColorTriggerClick(type, ev) {
        // 阻止冒泡到 outside-click 立即關回去
        if (ev) ev.stopPropagation();
        this.state.showColorPalette = (this.state.showColorPalette === type) ? null : type;
    }

    // 點 palette 內某個色塊
    onColorSwatchPick(type, color, ev) {
        if (ev) ev.stopPropagation();
        if (type === 'text') {
            this.state.textColor = color;
            this._executeCmd('executeColor', color);
        } else if (type === 'highlight') {
            this.state.highlightColor = color;
            this._executeCmd('executeHighlight', color);
        } else if (type === 'cellbg') {
            // 表格儲存格底色（重用色盤 popover）
            this._executeCmd('executeTableTdBackgroundColor', color);
        }
        if (type !== 'cellbg') this._pushRecentColor(type, color);    // Y13
        this.state.showColorPalette = null;
    }

    // 「重設」link：清除色（傳 null 給 canvas-editor 清除 style）
    onColorReset(type, ev) {
        if (ev) ev.stopPropagation();
        if (type === 'text') {
            this.state.textColor = '#202124';
            this._executeCmd('executeColor', null);
        } else if (type === 'highlight') {
            this.state.highlightColor = '#fff176';
            this._executeCmd('executeHighlight', null);
        }
        this.state.showColorPalette = null;
    }

    // 「自訂色」link：dispatch click 到隱藏的 native color input（保留 Y6 既有逃生口）
    onColorCustom(type, ev) {
        if (ev) ev.stopPropagation();
        // 不關 palette；等 onTextColorChange/onHighlightColorChange 接到 input event 後關
        const sel = type === 'text' ? '.doc-color-custom-text' : '.doc-color-custom-highlight';
        try {
            const input = document.querySelector(sel);
            if (input) input.click();
        } catch (e) { /* ignore */ }
    }

    onFindInputKeyDown(ev) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            if (ev.shiftKey) this.onFindPrev();
            else this.onFindNext();
        } else if (ev.key === 'Escape') {
            ev.preventDefault();
            this.closeFindReplace();
        }
    }


    // ─── 格式列補充功能（Google Docs 化）──────────────────────────────
    // 標題樣式 select：''=內文（executeTitle(null)）、first/second/third
    onTitleChange(ev) {
        const v = ev?.target?.value || '';
        this.state.activeTitle = v;
        this._executeCmd('executeTitle', v || null);
    }

    // 項目符號 / 編號清單（canvas-editor executeList(type, style)）
    onInsertList(type) {
        if (type === 'ul') this._executeCmd('executeList', 'ul', 'disc');
        else if (type === 'ol') this._executeCmd('executeList', 'ol', 'decimal');
    }

    // 插入超連結：取選取文字當顯示文字（無選取則用 URL），prompt 輸入網址
    onInsertHyperlink() {
        const url = window.prompt('輸入連結網址（URL）：', 'https://');
        if (!url) return;
        let text = '';
        try { text = this.editor?.command?.getRangeText?.() || ''; } catch (e) { /* ignore */ }
        if (!text) text = url;
        const size = Number(this.state.activeFontSize) || 16;
        this._executeCmd('executeHyperlink', {
            type: 'hyperlink',
            value: '',
            url,
            valueList: Array.from(text).map((ch) => ({ value: ch, size })),
        });
    }


    // ─── 表格網格插入 picker（Google Docs 風 hover 選列×欄）──────────────
    get TABLE_PICKER_MAX_ROWS() { return 10; }
    get TABLE_PICKER_MAX_COLS() { return 8; }
    // XML t-foreach 用：[1..max] 陣列
    get tablePickerRowRange() {
        return Array.from({ length: this.TABLE_PICKER_MAX_ROWS }, (_, i) => i + 1);
    }
    get tablePickerColRange() {
        return Array.from({ length: this.TABLE_PICKER_MAX_COLS }, (_, i) => i + 1);
    }
    onTablePickerToggle(ev) {
        if (ev) ev.stopPropagation();
        this.state.showTablePicker = !this.state.showTablePicker;
        if (!this.state.showTablePicker) {
            this.state.tablePickerRows = 0;
            this.state.tablePickerCols = 0;
        }
    }
    onTablePickerHover(rows, cols) {
        this.state.tablePickerRows = rows;
        this.state.tablePickerCols = cols;
    }
    onTablePickerPick(rows, cols, ev) {
        if (ev) ev.stopPropagation();
        this._executeCmd('executeInsertTable', rows, cols);
        this.state.showTablePicker = false;
        this.state.tablePickerRows = 0;
        this.state.tablePickerCols = 0;
    }


    // ─── 欄位/簽名/掃描下拉（工具列收合）────────────────────────────────
    onToolbarMenuToggle(name, ev) {
        if (ev) ev.stopPropagation();
        this.state.openToolbarMenu = (this.state.openToolbarMenu === name) ? null : name;
    }
    // 點下拉項目後執行並關閉下拉
    onToolbarMenuAction(fn) {
        try { fn?.(); } catch (e) { console.error('[DocEditor] toolbar menu action', e); }
        this.state.openToolbarMenu = null;
    }

    // 6 個 menu × N item 的設定表；XML 用 t-foreach 渲染
    get menuConfig() {
        return [
            {
                name: 'file', label: '檔案',
                items: [
                    { label: '新增空白文件', disabled: true },
                    { label: '開啟最近文件...', disabled: true },
                    { label: '重新命名', action: 'file:rename' },
                    { type: 'separator' },
                    { label: '匯入 DOCX...', action: 'file:import' },
                    { label: '匯出為 PDF', action: 'file:export-pdf' },
                    { label: '匯出為 DOCX', action: 'file:export-docx' },
                    { type: 'separator' },
                    { label: '列印', action: 'file:print' },
                    { label: '預覽', action: 'file:preview' },
                    { label: this.state.previewMode ? '✓ 預覽模式（編輯器內顯示實際值）' : '   預覽模式（編輯器內顯示實際值）', action: 'file:toggle-preview-mode' },
                    { label: '儲存', action: 'file:save', shortcut: 'Ctrl+S' },
                    { label: '關閉', action: 'file:close' },
                ],
            },
            {
                name: 'edit', label: '編輯',
                items: [
                    { label: '復原', action: 'edit:undo', shortcut: 'Ctrl+Z' },
                    { label: '重做', action: 'edit:redo', shortcut: 'Ctrl+Y' },
                    { type: 'separator' },
                    { label: '剪下', action: 'edit:cut', shortcut: 'Ctrl+X' },
                    { label: '複製', action: 'edit:copy', shortcut: 'Ctrl+C' },
                    { label: '貼上', action: 'edit:paste', shortcut: 'Ctrl+V' },
                    { type: 'separator' },
                    { label: '尋找', action: 'edit:find', shortcut: 'Ctrl+F' },
                    { label: '取代', action: 'edit:replace', shortcut: 'Ctrl+H' },
                ],
            },
            {
                name: 'view', label: '查看',
                items: [
                    { label: this.state.showRuler ? '✓ 顯示尺規' : '   顯示尺規', action: 'view:toggle-ruler' },
                    { label: this.state.showThumbnails ? '✓ 顯示縮圖' : '   顯示縮圖', action: 'view:toggle-thumbnails' },
                    { label: this.state.showLegacyToolbar ? '✓ 顯示舊版工具列' : '   顯示舊版工具列', action: 'view:toggle-legacy-toolbar' },
                    { label: `外觀：${this._themeLabel()}`, action: 'view:cycle-theme' },
                    { type: 'separator' },
                    { label: '縮放 50%', action: 'view:zoom-50' },
                    { label: '縮放 100%', action: 'view:zoom-100' },
                    { label: '縮放 150%', action: 'view:zoom-150' },
                    { label: '縮放 200%', action: 'view:zoom-200' },
                    { label: '符合寬度', action: 'view:zoom-fit' },
                    { type: 'separator' },
                    // Sprint Y11：紙張格式（取代被 hide 的 Row 3 toolbar）
                    { label: (this.state.pageFormat === 'A4'     ? '✓ ' : '   ') + '紙張 A4',     action: 'view:paper-A4' },
                    { label: (this.state.pageFormat === 'A3'     ? '✓ ' : '   ') + '紙張 A3',     action: 'view:paper-A3' },
                    { label: (this.state.pageFormat === 'A5'     ? '✓ ' : '   ') + '紙張 A5',     action: 'view:paper-A5' },
                    { label: (this.state.pageFormat === 'letter' ? '✓ ' : '   ') + '紙張 Letter', action: 'view:paper-letter' },
                    { label: (this.state.pageFormat === 'legal'  ? '✓ ' : '   ') + '紙張 Legal',  action: 'view:paper-legal' },
                    { type: 'separator' },
                    { label: '全螢幕', action: 'view:fullscreen', shortcut: 'F11' },
                ],
            },
            {
                name: 'insert', label: '插入',
                items: [
                    { label: '表格…', action: 'insert:table' },
                    { label: '圖片...', action: 'insert:image' },
                    { type: 'separator' },
                    { label: '變數欄位（文字）', action: 'insert:var-text' },
                    { label: '變數欄位（日期）', action: 'insert:var-date' },
                    { label: '變數欄位（核取方塊）', action: 'insert:var-checkbox' },
                    { type: 'separator' },
                    { label: '插入 Odoo 欄位（中文 token）', action: 'insert:alias-field' },
                    { type: 'separator' },
                    { label: '簽名欄位', disabled: true },
                    { label: '頁碼', disabled: true },
                    { label: '頁首／頁尾', disabled: true },
                ],
            },
            {
                name: 'format', label: '格式',
                items: [
                    { label: '粗體', action: 'format:bold', shortcut: 'Ctrl+B' },
                    { label: '斜體', action: 'format:italic', shortcut: 'Ctrl+I' },
                    { label: '底線', action: 'format:underline', shortcut: 'Ctrl+U' },
                    { label: '刪除線', action: 'format:strikeout' },
                    { type: 'separator' },
                    { label: '靠左對齊', action: 'format:align-left' },
                    { label: '置中對齊', action: 'format:align-center' },
                    { label: '靠右對齊', action: 'format:align-right' },
                    { label: '兩端對齊', action: 'format:align-justify' },
                    { type: 'separator' },
                    { label: '段落間距', disabled: true },
                    { label: '行距...', action: 'format:line-spacing' },
                    { label: '清除格式', action: 'format:clear-format' },
                ],
            },
            {
                name: 'tools', label: '工具',
                items: [
                    { label: '掃描變數', action: 'tools:scan-vars' },
                    { label: '掃描並替換變數', action: 'tools:scan-replace' },
                    { label: '預覽變數效果', action: 'tools:preview-vars' },
                    { label: '復原變數替換', action: 'tools:rollback' },
                    { type: 'separator' },
                    { label: '字數統計', action: 'tools:word-count' },
                    { label: '拼字檢查', disabled: true },
                    { type: 'separator' },
                    { label: '版本歷史', action: 'tools:version-history', shortcut: 'Alt+H' },
                    { label: '文件設定', action: 'tools:doc-settings' },
                ],
            },
            {
                // 面板：把次要分頁（儀表板/請求/設定）收進此下拉，
                // 編輯器預設停在「範本（編輯）」主畫面，更像 Google Docs。
                name: 'panel', label: '面板',
                items: [
                    { label: (this.state.activeSubNav === 'templates' ? '✓ ' : '   ') + '範本（編輯）', action: 'panel:templates' },
                    { type: 'separator' },
                    { label: (this.state.activeSubNav === 'dashboard' ? '✓ ' : '   ') + '儀表板', action: 'panel:dashboard' },
                    { label: (this.state.activeSubNav === 'requests'  ? '✓ ' : '   ') + '填寫請求', action: 'panel:requests' },
                    { label: (this.state.activeSubNav === 'settings'  ? '✓ ' : '   ') + '設定', action: 'panel:settings' },
                ],
            },
        ];
    }
};
