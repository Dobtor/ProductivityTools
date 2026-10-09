/** @odoo-module **/
/**
 * DocEditorTemplateUi — 範本設計：欄位調色盤、overlay、拖放、CSV。
 * 
 * ADR-022 的那一套：待填欄位、簽約人、overlay 絕對定位、
 * 模型欄位調色盤、選適用模型、抽取靜態文字與多語 CSV。
 *
 * 這是 doc_editor.js 拆出來的一層（mixin 工廠），由 doc_editor.js
 * 組合。拆的理由不是檔案太大，是**每一層的不變量要寫在自己的檔頭**。
 *
 * ☠️ import 區塊是整份照抄原檔的，沒有裁掉用不到的。理由：少一個 import
 * 的症狀是執行期 ReferenceError，而 OWL 會把它吞成一塊空白面板；
 * 多一個 import 沒有任何代價。**不要在 import {} 裡面加註解**——Odoo 的
 * asset compiler 不會 strip 它，會輸出 require({) 讓整個 bundle 掛掉。
 *
 * 後端對應：models/doc_template_field.py 與 models/render/fields.py。
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

export const DocEditorTemplateUi = (Base) => class extends Base {

    // ─── Phase 8 Template UI Builder（ADR-022）/ Sprint A 收口 ──────
    //
    // Sprint A：4 個分頁全部開放、預覽接後端 template_preview 端點。
    // 各分頁殼內容見 doc_editor.xml 的 doc-subnav-panel 區塊。

    onSubNavClick(tab) {
        const allowed = ["dashboard", "requests", "templates", "settings"];
        if (!allowed.includes(tab)) {
            return;
        }
        this.state.activeSubNav = tab;
        // 切到「請求」時 lazy-load 一次填寫請求清單
        if (tab === "requests" && !this._requestsLoaded) {
            this._loadRequests();
        }
    }

    /**
     * Sprint A：開新分頁顯示填值後的範本內容。
     *
     * 流程：
     *   1. 從 state.contextJson 取 user 提供的填值資料（可選）
     *   2. POST /dobtor_doc/template_preview 取得渲染後 HTML
     *   3. window.open 開新分頁、寫入 HTML
     */
    async onPreviewClick() {
        if (!this.state.docId) {
            this.notification.add("請先儲存文件後再預覽。", { type: "warning" });
            return;
        }
        // L2-v2：當文件綁定具體 record（model_id + res_id）時，走 render_preview
        // 直接用該 record 渲染 alias / Jinja2 變數；否則 fallback 到既有 template_preview
        // （需要 user 在右側填 contextJson）。
        const hasBoundRecord = this._loadedModelName && this._loadedResId;
        try {
            let html;
            if (hasBoundRecord) {
                const result = await rpc("/dobtor_doc/render_preview", {
                    doc_id: this.state.docId,
                    record_model: this._loadedModelName,
                    record_id: this._loadedResId,
                });
                if (!result || result.error) {
                    this.notification.add(
                        `預覽失敗：${(result && result.error) || "未知錯誤"}`,
                        { type: "danger" }
                    );
                    return;
                }
                html = this._wrapPreviewHtml(result.html || "");
            } else {
                // 既有路徑：使用 user 填的 contextJson 走 template_preview
                let contextDict = {};
                const ctxRaw = (this.state.contextJson || "").trim();
                if (ctxRaw) {
                    try {
                        contextDict = JSON.parse(ctxRaw);
                    } catch (e) {
                        this.notification.add(
                            "Context JSON 格式錯誤，將以空填值預覽。",
                            { type: "warning" }
                        );
                    }
                }
                const result = await rpc("/dobtor_doc/template_preview", {
                    doc_id: this.state.docId,
                    context: contextDict,
                });
                if (!result || !result.success) {
                    this.notification.add(
                        `預覽失敗：${(result && result.error) || "未知錯誤"}`,
                        { type: "danger" }
                    );
                    return;
                }
                html = result.html;
            }
            const w = window.open("", "_blank", "noopener,noreferrer");
            if (!w) {
                this.notification.add(
                    "瀏覽器阻擋新分頁。請允許彈出視窗後重試。",
                    { type: "warning" }
                );
                return;
            }
            w.document.open();
            w.document.write(html);
            w.document.close();
            w.document.title = `預覽：${this.state.docName || "文件"}`;
        } catch (e) {
            console.error("[DocEditor] onPreviewClick failed", e);
            this.notification.add(`預覽失敗：${e.message || e}`, { type: "danger" });
        }
    }

    /**
     * render_preview 回傳的是純 body HTML（不含 <html>/<head>），包成完整頁面供新分頁顯示。
     * 樣式對齊 template_preview 的最小版本：A4 寬度、保留列印 margin。
     */
    _wrapPreviewHtml(bodyHtml) {
        const docName = (this.state.docName || "文件").replace(/[<>&"']/g, c => ({
            "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&#39;",
        })[c]);
        return `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>預覽：${docName}</title>
<style>
body { font-family: 'Microsoft JhengHei', 'Noto Sans TC', Arial, sans-serif; padding: 24px; max-width: 820px; margin: auto; }
@media print {
  body { padding: 0; max-width: none; }
  .doc-field-token { background: transparent; border: 0; padding: 0; color: inherit; }
}
.doc-field-token {
  background: #e3f2fd;
  border: 1px solid #90caf9;
  border-radius: 3px;
  padding: 1px 4px;
  color: #1565c0;
  font-size: 0.95em;
  transition: background 0.15s ease;
}
.doc-field-token:hover { background: #bbdefb; }
.doc-field-token:empty::after { content: '（無值）'; color: #999; font-style: italic; }
</style></head><body>${bodyHtml}</body></html>`;
    }

    /**
     * Sprint A：載入此範本的填寫請求清單（lazy，切到 requests tab 時觸發一次）。
     */
    async _loadRequests() {
        if (!this.state.docId) {
            this.state.requests = [];
            this._requestsLoaded = true;
            return;
        }
        this.state.requestsLoading = true;
        try {
            const result = await rpc("/dobtor_doc/template_requests/list", {
                doc_id: this.state.docId,
            });
            this.state.requests = (result && result.requests) || [];
            this._requestsLoaded = true;
        } catch (e) {
            console.error("[DocEditor] load requests failed", e);
            this.state.requests = [];
            this._requestsLoaded = true;
        } finally {
            this.state.requestsLoading = false;
        }
    }

    /**
     * Sprint A：設定分頁 — 切換預設簽約人角色（沿用 onSignerClick 的 state 變動，
     * 但獨立 handler 避免未來分歧）。
     */
    onDefaultSignerChange(event) {
        const newId = parseInt(event.target.value, 10);
        if (!Number.isNaN(newId)) {
            this.state.activeSignerId = newId;
        }
    }


    // ─── Sprint D：Overlay 絕對定位 ──────────────────────────────────

    /**
     * Sprint D：當前頁的 overlay fields（layout_mode='overlay' + page_no=當前）。
     * 依 state.overlayFieldsRev 強制重新計算（OWL 偵測到 state 變動才會 re-render）。
     */
    get overlayFields() {
        // 觸發 OWL 依賴追蹤
        // eslint-disable-next-line no-unused-vars
        const _rev = this.state.overlayFieldsRev;
        const list = this._templateFieldsCache || [];
        const currentPage = this.state.pageNo || 1;
        return list.filter(
            (f) => f.layout_mode === "overlay" && (f.page_no || 1) === currentPage,
        );
    }

    /**
     * Sprint D：切換插入模式（inline / overlay）。
     */
    onLayoutModeToggle(mode) {
        if (mode !== "inline" && mode !== "overlay") return;
        this.state.layoutMode = mode;
        this.notification.add(
            mode === "overlay"
                ? "已切到「浮動」模式：點欄位按鈕後可拖曳到頁面任意位置。"
                : "已切回「行內」模式：點欄位按鈕將插入游標位置。",
            { type: "info" }
        );
    }

    /**
     * Sprint D：overlay field mousedown → 拖曳到新位置 → mouseup 存後端。
     *
     * 設計：拖曳期間直接改 DOM style.left/top（避開 OWL re-render 抖動），
     * mouseup 時才呼叫 save_field 並更新 _templateFieldsCache。
     */
    onOverlayMouseDown(ev, fieldId) {
        ev.stopPropagation();
        ev.preventDefault();
        const overlayEl = ev.currentTarget;
        if (!overlayEl) return;
        const startX = ev.clientX;
        const startY = ev.clientY;
        const origLeft = parseFloat(overlayEl.style.left) || 0;
        const origTop = parseFloat(overlayEl.style.top) || 0;
        const scale = this.state.currentZoomScale || 1;
        // Sprint F：越界 clamp — workspace 邊界相對於 overlay-layer
        const overlayLayer = overlayEl.parentElement;
        const layerRect = overlayLayer?.getBoundingClientRect();
        const fieldW = parseFloat(overlayEl.style.width) || 160;
        const fieldH = parseFloat(overlayEl.style.height) || 32;
        const maxX = layerRect ? Math.max(0, layerRect.width / scale - fieldW) : Number.MAX_VALUE;
        const maxY = layerRect ? Math.max(0, layerRect.height / scale - fieldH) : Number.MAX_VALUE;
        overlayEl.classList.add("is-dragging");
        // 選中該欄位讓 inspector 顯示
        this.state.selectedFieldId = fieldId;

        const clamp = (x, y) => ({
            x: Math.max(0, Math.min(maxX, x)),
            y: Math.max(0, Math.min(maxY, y)),
        });

        const onMove = (mv) => {
            const dx = (mv.clientX - startX) / scale;
            const dy = (mv.clientY - startY) / scale;
            const { x, y } = clamp(origLeft + dx, origTop + dy);
            overlayEl.style.left = `${x}px`;
            overlayEl.style.top = `${y}px`;
        };
        const onUp = async (up) => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            overlayEl.classList.remove("is-dragging");
            const { x: newX, y: newY } = clamp(
                origLeft + (up.clientX - startX) / scale,
                origTop + (up.clientY - startY) / scale,
            );
            // save 到後端 + 更新 cache
            try {
                const result = await rpc("/dobtor_doc/template_fields/save_field", {
                    doc_id: this.state.docId,
                    field: { id: fieldId, pos_x: newX, pos_y: newY },
                });
                if (result?.success) {
                    const f = (this._templateFieldsCache || []).find((x) => x.id === fieldId);
                    if (f) {
                        f.pos_x = newX;
                        f.pos_y = newY;
                    }
                } else {
                    this.notification.add(
                        `儲存位置失敗：${result?.error || "未知錯誤"}`,
                        { type: "warning" }
                    );
                }
            } catch (e) {
                console.warn("[DocEditor] overlay drag save failed", e);
            }
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    }

    /**
     * Sprint D：點 overlay field（不是 drag）→ 設為 selected、inspector 顯示。
     */
    onOverlayFieldClick(fieldId) {
        if (this.state.selectedFieldId !== fieldId) {
            this.state.selectedFieldId = fieldId;
        }
    }

    /**
     * Sprint F：overlay field 右下角 resize handle mousedown → mousemove 改 width/height →
     *           mouseup save_field 持久化。
     *
     * stopPropagation 必要 — 避免冒泡到 .doc-overlay-field 的 onOverlayMouseDown 觸發拖曳。
     */
    onOverlayResizeMouseDown(ev, fieldId) {
        ev.stopPropagation();
        ev.preventDefault();
        const overlayEl = ev.currentTarget.closest(".doc-overlay-field");
        if (!overlayEl) return;
        const startX = ev.clientX;
        const startY = ev.clientY;
        const origWidth = parseFloat(overlayEl.style.width) || 160;
        const origHeight = parseFloat(overlayEl.style.height) || 32;
        const scale = this.state.currentZoomScale || 1;
        const MIN_W = 40;
        const MIN_H = 20;
        overlayEl.classList.add("is-resizing");
        this.state.selectedFieldId = fieldId;

        const onMove = (mv) => {
            const dw = (mv.clientX - startX) / scale;
            const dh = (mv.clientY - startY) / scale;
            overlayEl.style.width = `${Math.max(MIN_W, origWidth + dw)}px`;
            overlayEl.style.height = `${Math.max(MIN_H, origHeight + dh)}px`;
        };
        const onUp = async (up) => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            overlayEl.classList.remove("is-resizing");
            const newW = Math.max(MIN_W, origWidth + (up.clientX - startX) / scale);
            const newH = Math.max(MIN_H, origHeight + (up.clientY - startY) / scale);
            try {
                const result = await rpc("/dobtor_doc/template_fields/save_field", {
                    doc_id: this.state.docId,
                    field: { id: fieldId, width: newW, height: newH },
                });
                if (result?.success) {
                    const f = (this._templateFieldsCache || []).find((x) => x.id === fieldId);
                    if (f) {
                        f.width = newW;
                        f.height = newH;
                    }
                }
            } catch (e) {
                console.warn("[DocEditor] overlay resize save failed", e);
            }
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    }

    /**
     * Sprint A：設定分頁 — 切換自動儲存。
     */
    onAutoSaveToggle(event) {
        const enabled = !!event.target.checked;
        this.state.autoSaveEnabled = enabled;
        // 關閉時取消殘留的 debounce/idle/maxWait 計時器，避免關閉後又自動存一次。
        // 「之後不再自動存」由 contentChange 監聽器檢查 state.autoSaveEnabled 達成
        //（AutoSaveManager 本身無 enable/disable 方法，原本的 this._autoSaveManager 也是錯名）。
        if (!enabled && this._autoSave) {
            this._autoSave.cancel();
        }
        this.notification.add(
            enabled ? "已啟用自動儲存。" : "已關閉自動儲存（請手動按儲存）。",
            { type: "info" }
        );
    }

    /**
     * Phase 2.1：點擊欄位工具列按鈕 → 真實插入 inline control。
     *
     * 流程：
     *   1. 確保有 active signer（若 placeholder 簽約人 id < 0，先在後端建立）
     *   2. POST /dobtor_doc/template_fields/save_field 建立 doc.template.field 紀錄
     *   3. 用 canvas-editor `executeInsertControl` 在游標位置插入 control，
     *      conceptId 寫入 field.id 以便日後對應
     *   4. 更新 state.signers count + state.fieldCount
     */
    async onFieldButtonClick(fieldKey) {
        const field = FIELD_TYPES.find(f => f.key === fieldKey);
        if (!field) return;
        if (!this.editor) {
            this.notification.add("編輯器尚未初始化", { type: "warning" });
            return;
        }
        if (!this.state.docId) {
            this.notification.add("請先儲存文件後再新增欄位", { type: "warning" });
            return;
        }
        if (!this._hasTemplate) {
            this.notification.add(
                "此文件未關聯範本。請先在後台 doc.document.template_id 設定範本後再回來。",
                { type: "warning" }
            );
            return;
        }
        try {
            const signer = await this._ensureSignerExists(this.state.activeSignerId);
            if (!signer) return;

            // Sprint D：依 state.layoutMode 決定 inline 或 overlay
            const isOverlay = this.state.layoutMode === "overlay";
            const fieldPayload = {
                signer_id: signer.id,
                field_type: field.key,
                page_no: this.state.pageNo || 1,
                required: false,
                placeholder_text: field.label,
                font_size: 12,
                layout_mode: isOverlay ? "overlay" : "inline",
                pos_x: isOverlay ? 80 : 0,
                pos_y: isOverlay ? 80 : 0,
                width: 160,
                height: 32,
            };
            const saveResult = await rpc("/dobtor_doc/template_fields/save_field", {
                doc_id: this.state.docId,
                field: fieldPayload,
            });
            if (!saveResult.success) {
                this.notification.add(`新增欄位失敗：${saveResult.error}`, { type: "danger" });
                return;
            }
            // Inline 模式才插入 canvas-editor control；overlay 由 overlay layer 渲染
            if (!isOverlay) {
                this._insertControlForField(saveResult.id, field, signer);
            }

            // 把新建的 field 紀錄 push 進本地 cache
            if (!this._templateFieldsCache) this._templateFieldsCache = [];
            this._templateFieldsCache.push({
                id: saveResult.id,
                ...fieldPayload,
                odoo_field_name: "",
            });

            // 同步 state 計數
            this._applySignerCounts(saveResult.signer_field_counts);
            this.state.fieldCount = saveResult.field_count;
            this.state.selectedFieldId = saveResult.id;
            // 觸發 OWL 重 render overlay layer
            if (isOverlay) {
                this.state.overlayFieldsRev++;
                this.notification.add(
                    `已加入浮動 ${field.label} 欄位，請拖曳到目標位置。`,
                    { type: "info" }
                );
            }
        } catch (e) {
            console.error("[DocEditor] onFieldButtonClick failed", e);
            this.notification.add(`新增欄位失敗：${e.message || e}`, { type: "danger" });
        }
    }


    // ─── Phase 2.2a：HTML5 drag & drop ─────────────────────────────
    //
    // 流程：
    //   1. 從欄位工具列 button 開始拖動 → onFieldDragStart 把 fieldKey 寫進 dataTransfer
    //   2. 滑鼠進入 .doc-workspace → onWorkspaceDragOver 接受 drop（preventDefault）+ highlight
    //   3. 滑鼠在 workspace 內釋放 → onWorkspaceDrop 把滑鼠位置轉成 canvas-editor 游標 + insert
    //   4. dragend / dragleave → 清除 highlight
    //
    // canvas-editor 是文字流編輯器、不支援「在空白處放浮動欄位」，
    // 所以 drop 點會 dispatch mousedown/mouseup 給 canvas、讓 canvas-editor 自己把
    // caret 移到最近的游標位置，然後走既有 onFieldButtonClick 流程插入 inline control。

    onFieldDragStart(ev, fieldKey) {
        ev.dataTransfer.setData("text/x-doc-field-type", fieldKey);
        ev.dataTransfer.effectAllowed = "copy";
        // 自訂拖曳影像：用按鈕本身（瀏覽器預設行為已 OK，留空即可）
    }

    onFieldDragEnd() {
        // 拖曳結束（無論成不成功）都清掉 drop target highlight
        this.state.isDropTarget = false;
    }

    onWorkspaceDragOver(ev) {
        // 只接受我們自己拖出的兩種 payload；其他（外部檔案等）不攔
        const types = ev.dataTransfer && ev.dataTransfer.types;
        const accepted = ["text/x-doc-field-type", "text/x-doc-odoo-field"];
        if (!types || !Array.from(types).some(t => accepted.includes(t))) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "copy";
        if (!this.state.isDropTarget) {
            this.state.isDropTarget = true;
        }
    }

    onWorkspaceDragLeave(ev) {
        // 只在離開 workspace 元素本身（不是進入子元素）時關 highlight
        if (ev.currentTarget === ev.target ||
            !ev.currentTarget.contains(ev.relatedTarget)) {
            this.state.isDropTarget = false;
        }
    }

    async onWorkspaceDrop(ev) {
        // 分支一：模型欄位 → 插入自描述藥丸（不建任何後端記錄）
        const variableRaw = ev.dataTransfer.getData("text/x-doc-odoo-field");
        if (variableRaw) {
            ev.preventDefault();
            this.state.isDropTarget = false;
            let meta;
            try {
                meta = JSON.parse(variableRaw);
            } catch (e) {
                return;
            }
            this._moveCaretToPoint(ev.clientX, ev.clientY);
            this.insertPill(meta);
            return;
        }

        // 分支二：待填欄位型別 → 既有流程（後端建紀錄 + executeInsertControl）
        const fieldKey = ev.dataTransfer.getData("text/x-doc-field-type");
        if (!fieldKey) return;
        ev.preventDefault();
        this.state.isDropTarget = false;

        // 把滑鼠位置映射到 canvas-editor 游標位置
        this._moveCaretToPoint(ev.clientX, ev.clientY);

        await this.onFieldButtonClick(fieldKey);
    }

    /**
     * 把滑鼠座標 (clientX, clientY) 映射到 canvas-editor 內的游標位置。
     * 作法：dispatch synthetic mousedown + mouseup 到 canvas-editor 的內部 canvas，
     *      canvas-editor 自己會處理 hit-test 並把 caret 移到對應位置。
     *
     * 若找不到 canvas（編輯器尚未 ready），不做事；onFieldButtonClick 會自行擋下。
     */
    _moveCaretToPoint(clientX, clientY) {
        const container = this.canvasContainer?.el;
        if (!container) return;
        // canvas-editor 內可能有多個 canvas（主 page / overlay），用 elementFromPoint
        // 找實際在 (x, y) 下方的元素，若是 canvas 就 dispatch
        const target = document.elementFromPoint(clientX, clientY);
        if (!target || target.tagName !== "CANVAS") return;
        if (!container.contains(target)) return;

        const opts = { bubbles: true, cancelable: true, clientX, clientY, button: 0 };
        try {
            target.dispatchEvent(new MouseEvent("mousedown", opts));
            target.dispatchEvent(new MouseEvent("mouseup", opts));
        } catch (e) {
            console.warn("[DocEditor] 模擬點擊定位游標失敗：", e);
        }
    }

    /**
     * 在 canvas-editor 游標處插入對應 field 的 inline control。
     * conceptId = field.id（字串），日後可從 control 反查 doc.template.field。
     *
     * Sprint E：對 Odoo 欄位（field.key === 'odoo_field'）走特殊 placeholder
     *   `{{ partner_id.name }}` 風格，讓 user 在文件上一眼看出這是動態變數
     *   （與既有 docxtpl `{{ object.xxx }}` jinja2 風格一致）。
     */

    // ═══ Phase 6：模型欄位調色盤 ═════════════════════════════════════
    //
    // 使用者要的是「看著關聯模型的欄位清單，把〈客戶名稱〉拖進段落裡」。
    // 資料沿用既有的 /dobtor_doc/fields（已支援 many2one 展開子欄位），
    // 與 DocFieldPickerDialog 共用同一份，不另開端點。

    async loadModelFields() {
        if (this.state.modelFieldsLoading || this.state.modelFields.length) return;
        if (!this._loadedModelName) return;
        this.state.modelFieldsLoading = true;
        try {
            const fields = await rpc("/dobtor_doc/fields", {
                model_name: this._loadedModelName,
                doc_id: this.state.docId || null,
            });
            this.state.modelFields = Array.isArray(fields) ? fields : [];
        } catch (e) {
            console.warn("[DocEditor] 載入模型欄位失敗", e);
            this.notification.add("載入模型欄位失敗", { type: "warning" });
        } finally {
            this.state.modelFieldsLoading = false;
        }
    }

    onLeftPanelTab(tab) {
        if (tab === "fields" && !this.showFieldPalette) return;
        this.state.leftPanelTab = tab;
        if (tab === "fields") this.loadModelFields();
    }

    onModelFieldFilterInput(value) {
        this.state.modelFieldFilter = value;
    }

    toggleRelation(name) {
        const list = this.state.expandedRelations;
        const idx = list.indexOf(name);
        if (idx >= 0) list.splice(idx, 1);
        else list.push(name);
    }

    /**
     * 「主記錄欄位」只列純量。
     *
     * 欄位清單現在也含 one2many / many2many / binary——它們分別餵給
     * 「明細（一對多）」與「圖片」兩組面板。混進純量清單的話，使用者拖一個
     * one2many 進文件只會印出 recordset 的 repr，而那看起來像系統壞了。
     */
    get filteredModelFields() {
        const q = (this.state.modelFieldFilter || "").trim().toLowerCase();
        const list = (this.state.modelFields || []).filter(
            f => SCALAR_FIELD_TYPES.includes(f.type)
        );
        if (!q) return list;
        return list.filter(f =>
            (f.label || "").toLowerCase().includes(q) ||
            (f.name || "").toLowerCase().includes(q)
        );
    }

    /** 圖片藥丸的來源：binary 欄位（客戶簽名、公司 logo…）。 */
    get imageFields() {
        const q = (this.state.modelFieldFilter || "").trim().toLowerCase();
        const list = (this.state.modelFields || []).filter(f => f.type === "binary");
        if (!q) return list;
        return list.filter(f =>
            (f.label || "").toLowerCase().includes(q) ||
            (f.name || "").toLowerCase().includes(q)
        );
    }

    /** 地址 helper 的候選：指向 res.partner 的 many2one。 */
    get partnerFields() {
        return (this.state.modelFields || []).filter(
            f => f.type === "many2one" && f.relation === "res.partner"
        );
    }

    /**
     * 是否在 portal 前台。
     *
     * 沿用本檔 setup 既有的偵測方式：action service 只存在於後台，
     * portal frontend 拿不到（見 setup 內 useService("action") 的 try/catch）。
     */
    get isPortalContext() {
        return !this.action;
    }

    /**
     * 模型欄位是否可拖放。三個否決條件：
     *
     * 1. 唯讀（portal 非協作者 / 公開預覽）
     * 2. overlay 版面——overlay 欄位不在 content_json 裡，_build_full_html 也不
     *    處理它們，放在那裡的模型變數會在畫面上看得好好的、匯出時無聲消失。
     * 3. portal 前台——變數綁定是「設計範本」的動作，不是協作者該做的事；
     *    而且 /dobtor_doc/fields 讀 ir.model.fields，portal 群組多半沒有權限，
     *    真讓他們點下去只會拿到一個永遠空白的清單。
     */
    get canPlaceVariables() {
        return !this._isReadonly
            && !this.isOutputTarget
            && !this.isPortalContext
            && this.state.layoutMode !== "overlay";
    }

    /** 左欄「欄位」分頁是否顯示。portal 與輸出紀錄都不給。 */
    get showFieldPalette() {
        return !this.isPortalContext && !this._isReadonly && !this.isOutputTarget;
    }


    // ─── 選「適用模型」 ───────────────────────────────────────────
    //
    // 範本沒有 model_id 就沒有欄位可拖，而原本編輯器只會叫使用者去表單設。
    // 那個缺口讓範本清單的「新增」沒辦法比照文件直接進編輯器
    //（見 static/src/views/doc_document_list_open_editor.js 的註解）。

    async onOpenModelPicker() {
        this.state.modelPicker.open = true;
        if (!this.state.modelPicker.list.length) {
            await this.loadPickableModels();
        }
    }

    async onModelPickerQuery(value) {
        this.state.modelPicker.query = value || "";
        await this.loadPickableModels();
    }

    async loadPickableModels() {
        this.state.modelPicker.loading = true;
        try {
            const list = await rpc("/dobtor_doc/models", {
                query: this.state.modelPicker.query || null,
            });
            this.state.modelPicker.list = Array.isArray(list) ? list : [];
        } catch (e) {
            console.warn("[DocEditor] 載入模型清單失敗", e);
            this.notification.add("載入模型清單失敗", { type: "warning" });
        } finally {
            this.state.modelPicker.loading = false;
        }
    }

    /** 選定模型 → 寫回後端 → 重新載欄位清單。 */
    async onPickModel(model) {
        try {
            const res = await rpc("/dobtor_doc/set_model", {
                model_id: model.id,
                doc_id: this.state.docId || null,
                template_id: this.state.docId ? null : this.state.templateId,
            });
            this._loadedModelName = res.model;
            this.state.modelPicker.open = false;
            // 欄位清單是按模型 cache 的，換了模型要清掉重載
            this.state.modelFields = [];
            this.state.lineFields = [];
            await this.loadModelFields();
            this.notification.add(`適用模型已設為「${res.name}」`, { type: "success" });
        } catch (e) {
            this.notification.add(
                (e && e.data && e.data.message) || "設定模型失敗", { type: "danger" });
        }
    }

    get isI18nPill() {
        return (this.state.selectedVariable || {}).source === "i18n";
    }

    get isFieldLabelPill() {
        return (this.state.selectedVariable || {}).source === "fieldLabel";
    }

    /** 某個語言的文字（inspector 的輸入框用）。 */
    i18nTextFor(code) {
        const texts = (this.state.selectedVariable || {}).texts || {};
        return texts[code] || "";
    }

    onI18nTextChange(code, value) {
        const cur = this.state.selectedVariable || {};
        const texts = { ...(cur.texts || {}) };
        const text = (value || "").trim();
        if (text) {
            texts[code] = text;
        } else {
            delete texts[code];
        }
        // 標籤文字跟著「預覽語言」走，fallback 到任一有值的——空白的藥丸
        // 在版面上看不見，使用者會以為它消失了
        const shown = texts[this.state.previewLang]
            || Object.values(texts).find(v => v)
            || "多語文字";
        this.updateSelectedPill({ texts, labelText: shown });
    }

    onI18nKeyChange(value) {
        this.updateSelectedPill({ key: (value || "").trim() });
    }

    /**
     * 切換預覽語言：把所有 i18n 藥丸的標籤文字改成該語言。
     *
     * 這是一次真實的編輯（會進存檔與復原），不是純顯示切換。理由：標籤文字
     * 在快照時本來就會被值取代，所以改它沒有副作用；而「純顯示」需要在每次
     * 重繪時覆寫 canvas 內容，那會跟自動存檔打架。
     *
     * 實際價值是版面檢查：中文「報價單」三個字，英文 Quotation 九個字元，
     * 表頭常常會擠破——不切過去看一次不會知道。
     */
    onPreviewLangChange(code) {
        this.state.previewLang = code;
        if (!this.editor || !code) return;
        let data;
        try {
            data = this.editor.command.getValue().data;
        } catch (e) {
            return;
        }
        let touched = 0;
        const visit = (list) => {
            for (const el of list || []) {
                if (!el || typeof el !== "object") continue;
                const meta = this._elementFieldMeta(el);
                if (meta && meta.source === "i18n") {
                    const texts = meta.texts || {};
                    const shown = texts[code]
                        || Object.values(texts).find(v => v)
                        || meta.labelText || "多語文字";
                    if (el.value !== shown) {
                        el.value = shown;
                        meta.labelText = shown;
                        touched += 1;
                    }
                }
                if (Array.isArray(el.valueList)) visit(el.valueList);
                for (const row of el.trList || []) {
                    for (const cell of row.tdList || []) {
                        if (Array.isArray(cell.value)) visit(cell.value);
                    }
                }
            }
        };
        for (const zone of ["header", "main", "footer"]) {
            if (Array.isArray(data[zone])) visit(data[zone]);
        }
        if (!touched) return;
        try {
            this.editor.command.executeSetValue(data);
            this.notification.add(`已切換 ${touched} 個多語文字的顯示語言。`,
                { type: "info" });
        } catch (e) {
            console.error("[DocEditor] 切換預覽語言失敗", e);
        }
    }


    // ─── 抽取靜態文字 ─────────────────────────────────────────────

    async onOpenI18nExtract() {
        if (!this.canPlaceVariables) return;
        this.state.showI18nPanel = true;
        this.state.i18nCandidates = [];
        this.state.i18nSelected = [];
        await this.loadLanguages();
        // 轉換是伺服器端改寫 content_json，所以要先把當前內容存上去，
        // 不然抽到的是上一次存檔的文字
        await this._flushPendingSave();
        try {
            const res = await rpc("/dobtor_doc/i18n/extract", this.targetRpcParams);
            this.state.i18nCandidates = (res && res.texts) || [];
        } catch (e) {
            this.notification.add(`抽取靜態文字失敗：${e.message || e}`,
                { type: "danger" });
        }
    }

    onToggleI18nCandidate(text) {
        const list = this.state.i18nSelected;
        const idx = list.indexOf(text);
        if (idx >= 0) {
            list.splice(idx, 1);
        } else {
            list.push(text);
        }
    }

    onToggleAllI18nCandidates() {
        const all = this.state.i18nCandidates.map(c => c.text);
        this.state.i18nSelected =
            this.state.i18nSelected.length === all.length ? [] : all;
    }

    async onConvertI18nSelected() {
        if (!this.state.i18nSelected.length) {
            this.notification.add("請先勾選要轉換的文字。", { type: "warning" });
            return;
        }
        try {
            const res = await rpc("/dobtor_doc/i18n/convert", {
                ...this.targetRpcParams,
                texts: this.state.i18nSelected,
                lang: this.state.previewLang || null,
            });
            if (res && res.content_json) {
                this.editor.command.executeSetValue(JSON.parse(res.content_json));
            }
            this.notification.add(`已轉換 ${(res && res.converted) || 0} 段文字。`,
                { type: "success" });
            this.state.showI18nPanel = false;
        } catch (e) {
            this.notification.add(`轉換失敗：${e.message || e}`, { type: "danger" });
        }
    }


    // ─── CSV 匯入匯出 ─────────────────────────────────────────────

    async onExportI18nCsv() {
        await this._flushPendingSave();
        try {
            const res = await rpc("/dobtor_doc/i18n/export", this.targetRpcParams);
            if (!res || !res.entries) {
                this.notification.add(
                    "這份範本還沒有多語文字。請先用「抽出靜態文字」轉換。",
                    { type: "warning" }
                );
                return;
            }
            const blob = new Blob([res.csv], { type: "text/csv;charset=utf-8" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${this.state.docName || "template"}-i18n.csv`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            this.notification.add(`匯出失敗：${e.message || e}`, { type: "danger" });
        }
    }

    onImportI18nCsv(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = async () => {
            try {
                const res = await rpc("/dobtor_doc/i18n/import", {
                    ...this.targetRpcParams,
                    csv_content: String(reader.result || ""),
                });
                if (res && res.content_json) {
                    this.editor.command.executeSetValue(JSON.parse(res.content_json));
                }
                let msg = `已回填 ${(res && res.updated) || 0} 個多語文字。`;
                if (res && res.unknown && res.unknown.length) {
                    // 靜默忽略的話，譯者改錯一個 key，使用者只會看到
                    // 「翻譯沒進去」而查不出原因
                    msg += ` 找不到對應的 key：${res.unknown.join("、")}`;
                }
                this.notification.add(msg, {
                    type: (res && res.unknown && res.unknown.length)
                        ? "warning" : "success",
                    sticky: !!(res && res.unknown && res.unknown.length),
                });
            } catch (e) {
                this.notification.add(`匯入失敗：${e.message || e}`,
                    { type: "danger" });
            }
            ev.target.value = "";
        };
        reader.readAsText(file, "utf-8");
    }

    get isColumnPill() {
        return (this.state.selectedVariable || {}).source === "column";
    }

    /** 條件／欄條件共用一組輸入欄位，只有標籤前綴不同。 */
    onColumnExpressionChange(value) {
        const expr = (value || "").trim();
        this.updateSelectedPill({
            expression: expr,
            labelText: expr ? `欄條件：${expr}` : "欄條件（未設定）",
        });
    }

    /** 常用欄條件：原生報表最典型的就是「有折扣才顯示折扣欄」。 */
    get COLUMN_CONDITION_PRESETS() {
        return [
            {
                label: "明細中有折扣",
                expr: "object.order_line|selectattr('discount')|list|length > 0",
            },
            { label: "欄位有值", expr: "object.欄位名" },
        ];
    }

    get isConditionPill() {
        return (this.state.selectedVariable || {}).source === "condition";
    }

    get isRepeatPill() {
        return (this.state.selectedVariable || {}).source === "repeat";
    }

    /** 條件／重複標記的標籤文字隨表達式自動更新，使用者才看得出它在判斷什麼。 */
    onConditionExpressionChange(value) {
        const expr = (value || "").trim();
        this.updateSelectedPill({
            expression: expr,
            labelText: expr ? `條件：${expr}` : "條件（未設定）",
        });
    }

    onRepeatFilterChange(value) {
        const flt = (value || "").trim();
        const cur = this.state.selectedVariable || {};
        const base = cur.path || "";
        this.updateSelectedPill({
            filter: flt,
            labelText: flt ? `明細 × ${base}（已篩選）` : `明細 × ${base}`,
        });
    }

    onKeepEmptyChange(checked) {
        this.updateSelectedPill({ keepEmpty: !!checked });
    }

    onApplyConditionPreset(expr) {
        this.onConditionExpressionChange(expr);
    }

};
