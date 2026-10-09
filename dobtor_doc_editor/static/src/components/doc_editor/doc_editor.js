/** @odoo-module **/

/**
 * DocEditor — Canvas 引擎版主編輯器 (Phase 1)
 *
 * 架構：Odoo Owl Component + canvas-editor.umd.min.js (window.CanvasEditor)
 * 資料流：content_json (Text) 為主要儲存與讀取欄位
 * AutoSave：Debounce(1.5s) + MaxWait(10s) + Idle(3s)
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
// 注意：normalizeMultiCharElements{,InTables} 留在 scanner module 內供未來重啟此方向時使用
// （目前 Sprint T 因 canvas-editor auto-merge 無法用、見 onScanAndReplaceClick 內註解
//  與 docs/phase8_sprint_t_2026-05-24.md）
// IMPORTANT：不要把以上註解搬回 import {} 內部 — Odoo asset compiler 解析 import 解構
// 賦值時不會 strip 行內註解，會輸出 `require({)` 直接讓整個 web.assets_web bundle parse fail
// （Sprint V 才發現的；症狀 = SPA 完全不啟動、console 只有 "Unexpected token ')'"）。
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

/**
 * Phase 8 Template UI Builder（ADR-022）— Phase 1 視覺風格靠攏。
 *
 * 範本欄位類型清單（Phase 2 接 canvas-editor executeInsertControl 用）。
 * Phase 1 只渲染按鈕、點擊只彈 toast，欄位插入行為留到 Phase 2。
 */
// Sprint Y5：格式化工具列字型 / 字號清單（Google Docs 風）
import { DocEditorShell } from "./doc_editor_shell";
import { DocEditorIo } from "./doc_editor_io";
import { DocEditorPills } from "./doc_editor_pills";
import { DocEditorTemplateUi } from "./doc_editor_templateui";
export {
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
// setup() 留在這裡，而它用到的不只是 static 欄位那幾個常數
// （_lsGet 讀收合狀態、PILL_STYLE…）。少一個的症狀是執行期
// ReferenceError，而 OWL 會把它吞成一塊空白面板——實測就是這樣
// 掛掉的（tour 第 1 步就停住）。所以整組都收進來。
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

/**
 * DocEditor — 編輯器的組合點。
 *
 * 實作分成四層（見同目錄的 doc_editor_*.js）：
 *
 *     shell       canvas 實例、載入存檔、工具列與選單
 *     io          匯入匯出、下載、版本
 *     pills       藥丸（取值／標記／條件／重複／分組／檢視器）
 *     templateui  範本設計（欄位、overlay、拖放、CSV）
 *
 * 用 mixin 工廠而不是四個 Component 再組合：這是**一個** OWL 元件，
 * 四層共用同一個 this.state 與同一個 canvas 實例。拆成四個元件就要
 * 在它們之間同步狀態，那比現在這樣糟得多。
 *
 * static 欄位與 setup() 留在這裡：模板是用 component 的 static
 * 欄位取 FIELD_TYPES / VALUE_SOURCES 的，而 setup() 是四層的共同前提。
 */
export class DocEditor extends DocEditorShell(DocEditorIo(
        DocEditorPills(DocEditorTemplateUi(Component)))) {
    static template = "dobtor_doc_editor.DocEditor";
    static components = { DocVersionPanel };
    static props = ["*"];

    static FIELD_TYPES = FIELD_TYPES;

    // Phase 6：inspector 的「值來源」下拉用（QWeb 以 constructor.VALUE_SOURCES 取用）
    static VALUE_SOURCES = VALUE_SOURCES;

    setup() {
        this.notification = useService("notification");

        // action service 在 portal frontend 環境不存在；目前 DocEditor 內部沒呼叫任何
        // this.action 方法（只在 setup 時拿了 service），包 try/catch 才能在 portal mount。
        try {
            this.action = useService("action");
        } catch (e) {
            this.action = null;
        }

        // 嘗試取得 bus_service（多人協作用，可能不存在）
        try {
            this._busService = useService("bus_service");
        } catch (e) {
            this._busService = null;
        }

        // dialog service：用來開啟 DocFieldPickerDialog（Phase 8）
        // portal frontend 環境同 action service 可能不存在，包 try/catch。
        try {
            this.dialog = useService("dialog");
        } catch (e) {
            this.dialog = null;
        }

        // 暴露 FIELD_TYPES 給 template 使用（QWeb t-foreach）
        this.FIELD_TYPES = FIELD_TYPES;
        // 同上：OWL 模板的 bare name 解析成 this.X，static 不在 prototype 上，
        // 所以要在 instance 上掛一份（沿用本檔既有慣例）
        this.VALUE_SOURCES = VALUE_SOURCES;
        this.CONDITION_PRESETS = this.constructor.CONDITION_PRESETS;
        // Sprint Y5：暴露字型 / 字號清單給格式化工具列 t-foreach 使用
        this.FONT_OPTIONS = FONT_OPTIONS;
        this.FONT_SIZE_OPTIONS = FONT_SIZE_OPTIONS;

        // Portal mount 模式：<owl-component name="..." props='{"docId":123,"readonly":true}'>
        // public_component_service 會把 JSON 解析後當 props 傳進來。
        // backend client action 模式則走 this.props.action.context.doc_id（見下方）。
        this._isReadonly = this.props.readonly === true;
        // 載入失敗旗標：擋住 autosave，避免用空白編輯器內容覆蓋既有記錄
        this._loadFailed = false;

        // Canvas 編輯器容器 ref（始終存在於 DOM，不包在 t-if 內）
        this.canvasContainer = useRef("canvasContainer");

        this.state = useState({
            docId: null,
            docName: "未命名文件",
            editorReady: false,
            isSaving: false,
            statusMsg: "就緒",
            statusType: "saved",
            pageFormat: "A4",
            isOnline: true,
            // 模板引擎狀態
            // Phase 1（藥丸改版）編輯對象：'document' 編文件、'template' 編範本本身。
            // 與下面的 hasDocxTemplate 是兩件事——後者指「這份文件上傳了 .docx 模板檔」。
            editTarget: "document",
            templateId: null,
            // 報表引擎：唯讀的輸出紀錄。載入後 _isReadonly 會被設為 true，
            // autosave 關閉、工具列與兩側面板收斂。
            outputId: null,
            outputMeta: null,
            // 舊名 isTemplateMode。正名原因：與新的「範本編輯模式」撞名，
            // 兩個布林在同一個 component 裡會互相污染。
            hasDocxTemplate: false,
            templateVariables: [],
            templateFilename: "",
            contextJson: "",
            // 版本歷史面板（W7-8 P1-1）
            showVersionPanel: false,
            // ─── Phase 8 Template UI Builder（ADR-022） ───
            // Sub-nav tab：dashboard / requests / templates / settings
            // Phase 1 預設停在 templates，其他 disabled（WIP）。
            activeSubNav: "templates",
            // 當前選中的範本欄位 id（Phase 2 接 doc.template.field）。
            // Phase 1 始終為 null，inspector 顯示「未選取」狀態。
            selectedFieldId: null,
            // 頁碼導航（canvas-editor 多頁狀態，Phase 1 placeholder）。
            pageNo: 1,
            totalPages: 1,
            // 簽約人 chip（Phase 2 從 doc.template.signer 載入）。
            // Phase 1 用空陣列＋預設兩個 placeholder（房東/業務），純視覺。
            signers: [
                { id: -1, name: "房東", color: "#2c2c2c", count: 0 },
                { id: -2, name: "業務", color: "#22c55e", count: 0 },
            ],
            activeSignerId: -1,
            // 已放置欄位計數（Phase 2 接 doc.template.field）。
            fieldCount: 0,
            // Zoom 模式 placeholder（Phase 1 只是視覺，不接 executePageScale）。
            zoomFit: "auto",
            // Phase 2.2a 拖放新增欄位：當前是否有欄位被拖入 workspace
            isDropTarget: false,
            // ─── L2-v2：中文欄位別名對映（doc.field_aliases）───────────
            // key=中文 token（不含《》）/ value=Jinja2 expression（如 object.project_id.name）
            // 由 _loadDocument 從後端載入、onInsertAliasClick 寫入、onDeleteAlias 刪除
            fieldAliases: {},
            // template 級全域 alias（doc 預覽時自動繼承）
            templateFieldAliases: {},
            templateName: "",
            // L2-v2 預覽模式：true 時編輯器內 token 暫時替換成實際值（不存回 content_json）
            previewMode: false,
            // ─── Sprint A：Sub-nav 分頁殼資料 ───────────────────────
            // 設定分頁：自動儲存開關（預設啟用）
            autoSaveEnabled: true,
            // 請求分頁：填寫請求清單（lazy-load）
            requests: [],
            requestsLoading: false,
            // ─── Sprint B：canvas-editor 當前縮放比例（由 pageScaleChange listener 同步） ───
            currentZoomScale: 1,
            // ─── Sprint C：頁面縮圖清單（debounced，由 _rebuildThumbnails 維護）───
            thumbnails: [],
            // ─── Sprint D：當前欄位插入模式（inline / overlay）───
            layoutMode: "inline",
            // overlay field 變動計數器：push/drag-end/load 時 ++ 強制 OWL re-render
            // （drag 過程不更新此值，靠 DOM transform 避免高頻 render）
            overlayFieldsRev: 0,
            // ─── Sprint N：最近一次「掃描並替換」的 snapshot（供 rollback）───
            // null = 沒可復原的操作；object = {docData, createdFieldIds, replacedCount, timestamp}
            // 覆蓋式單層 undo；rollback 成功 / 再次掃描並替換時被覆蓋
            lastScanReplaceSnapshot: null,
            // ─── Sprint O：inspector 欄位列表 search filter（substring，case-insensitive）───
            // 空字串 = 不過濾；對 odoo_field_name / placeholder_text / field_type 做包含比對
            fieldListFilter: "",
            // ─── Sprint P：inspector 列表的鍵盤焦點 index（在 filteredFieldsList 中）───
            // -1 = 沒焦點；0..length-1 = 對應 row。filter/cache 變動時要 reset
            focusedListIndex: -1,
            // ─── Sprint Y3：Google Docs 風 menu bar ───
            // null = 全部關閉；'file'|'edit'|'view'|'insert'|'format'|'tools' = 該 menu 展開中
            openMenu: null,
            // ─── Sprint Y14：menu dropdown 鍵盤導航焦點 index
            // -1 = 無焦點（mouse 開啟時）；>=0 = 該 menu items 陣列內第 N 個（含 separator/disabled）
            menuFocusIndex: -1,
            // 查看 menu 的兩個 toggle（初始 true 維持現狀）
            showRuler: true,
            showThumbnails: true,
            // ─── Sprint Y4：尋找／取代 panel ───
            findReplaceMode: false,
            findText: '',
            replaceText: '',
            // ─── Sprint Y10：find/replace match count（Google Docs 風「3 / 12」顯示）
            findMatchCount: 0,        // 總比對數（canvas-editor getSearchNavigateInfo().count）
            findMatchIndex: 0,        // 1-based 當前 highlight 序號（0 = 無 match 或未搜尋）
            // ─── Sprint Y6：字色 / 背景色 picker（記住上次選色顯示在 swatch）
            textColor: '#202124',         // 預設黑灰（同 --gd-text）
            highlightColor: '#fff176',    // 預設淡黃（Google Docs 風）
            // ─── Sprint Y12：24 色 palette dropdown 開啟狀態
            // null = 關閉；'text' = 字色 palette 開；'highlight' = 背景色 palette 開
            showColorPalette: null,
            // ─── Sprint Y13：最近用色（各最多 6 個、localStorage 持久化）
            //     Sprint Y25：改走 _lsGet helper
            recentColors: (() => {
                const parsed = _lsGet('dobtor_doc_editor_recent_colors', { json: true });
                return {
                    text: Array.isArray(parsed?.text) ? parsed.text.slice(0, 6) : [],
                    highlight: Array.isArray(parsed?.highlight) ? parsed.highlight.slice(0, 6) : [],
                };
            })(),
            // ─── Sprint Y7：format toolbar active state（caret/selection 反映目前格式）
            activeBold: false,
            activeItalic: false,
            activeUnderline: false,
            activeStrikeout: false,
            // ─── Sprint Y8：format toolbar active state 延伸（font/size/align/color swatch）
            activeFontFamily: '',           // 空字串 = 預設字型
            activeFontSize: '16',           // canvas-editor 預設 16；select option value 是字串
            activeRowFlex: 'left',          // 'left'|'center'|'right'|'alignment'
            // ─── Sprint Y9：dark mode（UI shell 深色化；canvas 紙張仍白色保持列印 WYSIWYG）
            //     Sprint Y19：升級為三段 themeMode（auto / light / dark）
            // darkMode = 實際渲染用的 boolean（reactive、由 _recomputeDarkMode 維護）
            // themeMode = user 偏好（'auto' | 'light' | 'dark'）；'auto' 跟系統 prefers-color-scheme
            // Sprint Y25：改走 _lsGet helper（含 Y9 legacy migration）
            themeMode: (() => {
                const v = _lsGet('dobtor_doc_editor_theme_mode');
                if (v === 'auto' || v === 'light' || v === 'dark') return v;
                // Y9 legacy migration：明確存過 '1' → 'dark'、'0' → 'light'、其他（含 null）→ 'auto'
                const legacy = _lsGet('dobtor_doc_editor_dark_mode');
                if (legacy === '1') return 'dark';
                if (legacy === '0') return 'light';
                return 'auto';
            })(),
            darkMode: (() => {
                // initial 估算（setup 內 _recomputeDarkMode 會 reconcile）
                const v = _lsGet('dobtor_doc_editor_theme_mode');
                const legacy = _lsGet('dobtor_doc_editor_dark_mode');
                let mode = v;
                if (!mode) {
                    if (legacy === '1') mode = 'dark';
                    else if (legacy === '0') mode = 'light';
                    else mode = 'auto';
                }
                if (mode === 'dark') return true;
                if (mode === 'light') return false;
                try { return !!window.matchMedia?.('(prefers-color-scheme: dark)')?.matches; }
                catch (e) { return false; }
            })(),
            // ─── Sprint Y17：文件設定 modal（紙張尺寸 / 方向 / margin）
            // showDocSettings = 是否開啟 modal；docSettingsForm = modal 內 form state
            // margin 值在 modal 內以 mm 顯示（user-friendly），存的時候轉 px 給 canvas-editor
            showDocSettings: false,
            docSettingsForm: {
                format: 'A4',
                direction: 'vertical',
                marginTopMm: 26,
                marginRightMm: 32,
                marginBottomMm: 26,
                marginLeftMm: 32,
            },
            // ─── Sprint Y18：行距 modal（接 canvas-editor executeRowMargin）
            // value 是 line-height 倍數（canvas-editor default = 1）；preset 1.0/1.15/1.5/2.0/2.5/3.0
            showLineSpacing: false,
            lineSpacingValue: 1.0,
            // ─── Sprint Y23：舊版 Row 3 工具列可選顯示（Y11 hide 後 default 仍隱藏；user 可 opt-in）
            // localStorage 存 '1' 顯示、'0' 或 null 隱藏
            // Sprint Y25：改走 _lsGet helper
            showLegacyToolbar: _lsGet('dobtor_doc_editor_show_legacy_toolbar') === '1',
            // ─── 表格編輯（Google Docs 化）───
            // inTable：游標是否在表格儲存格內（由 rangeStyleChange 偵測 ctx.isTable）→ 控制表格工具列顯示
            inTable: false,
            // 網格插入表格 picker（hover 選列×欄，最大 10×8）
            showTablePicker: false,
            tablePickerRows: 0,
            tablePickerCols: 0,
            // ─── 工具列下拉（欄位/簽名/掃描收合，Google Docs 風）───
            // null = 全關；'fields'|'signature'|'scan' = 該下拉展開
            openToolbarMenu: null,
            // 標題樣式 select 當前值（''=內文；'first'|'second'|'third'）
            activeTitle: '',
            // Phase 3：值凍結時間與過期旗標。攤在工具列上，因為快照語意最容易
            // 造成的誤解就是「我改了來源記錄，怎麼文件沒變」。
            snapshotDate: null,
            snapshotIsStale: false,
            // ─── Phase 6：模型欄位調色盤 ───────────────────────────
            // 左欄兩個分頁：'pages' 頁面縮圖（原有）／'fields' 模型欄位清單（新增）
            leftPanelTab: "pages",
            // i18n：已安裝語言、預覽語言、抽取面板狀態
            languages: [],
            previewLang: "",
            showI18nPanel: false,
            i18nCandidates: [],
            i18nSelected: [],
            modelFields: [],
            modelFieldsLoading: false,
            modelFieldFilter: "",
            expandedRelations: [],
            // 重複列（表格明細）：使用者把某一列設為「對 order_line 重複」後，
            // 左欄會多一組「明細欄位」，從那裡拖出的藥丸是 source='line'。
            //   { path, model, label }  null = 尚未設定重複列
            repeatContext: null,
            lineFields: [],
            lineFieldsLoading: false,
            // Phase 4：目前選中的模型變數藥丸的綁定定義（extension.dobtorField 的複本）。
            // 與 selectedFieldId（待填欄位的後端記錄 id）互斥——兩類欄位的定義
            // 存在不同地方，inspector 也因此分兩區顯示。
            selectedVariable: null,
            // ─── 左右側面板收合 ───
            // 編輯區在 1366 寬的筆電上只剩 900px——左 180 + 右 280 幾乎是
            // 整個紙張寬度的三分之一。收合狀態存 localStorage：這是「每個人
            // 自己的看法偏好」，不是文件內容，不該進資料庫。
            // 選「適用模型」（左欄在沒有模型時顯示）。沒有這個介面的話，
            // 一張新範本進編輯器第一件事是離開編輯器去表單設模型。
            modelPicker: { open: false, query: "", list: [], loading: false },
            leftPanelCollapsed: _lsGet('dobtor_doc_editor_left_collapsed') === '1',
            rightPanelCollapsed: _lsGet('dobtor_doc_editor_right_collapsed') === '1',
        });
        // Sprint C：縮圖重生 timer（debounce、避免每次 contentChange 都全頁 toDataURL）
        this._thumbnailTimer = null;
        // 切到 requests tab 時才 load 一次
        this._requestsLoaded = false;

        // 暫存從後端載入的 content_json，供 _initCanvasEditor 使用
        this._loadedContentJson = null;
        // Canvas 編輯器實例
        this.editor = null;
        this._leaderElection = null;
        // P2-2 樂觀鎖：load 時記下後端 write_date，save 時帶回比對
        this._lastSyncedWriteDate = null;

        // P2-4 監控與遙測：掛全域 error / Web Vitals 監聽
        this._uninstallTelemetry = installGlobalErrorReporting({
            docIdGetter: () => this.state?.docId || null,
        });

        // P3-2 鍵盤導航
        // Sprint Y15.1：發現 Y3 起就有的 bug — 從 window listener 改 state 不會自動觸發
        // OWL re-render（OWL 18 reactive proxy 在 window scope 外的 mutation 沒 transaction
        // context）。所有 mutation 點末段都要 manually call this.render() 才生效。
        // 既有 Escape close menu / Esc close version panel / Esc close color palette 從
        // 來都「靜默失效」— 只有點外面（mousedown listener mutation 也壞、但接的是 OWL
        // outside-click handler、會被某個其他地方 re-render 救回）才關得起來。
        this._onGlobalKey = (event) => {
            let dirty = false;
            // Alt+H：開啟版本歷史
            if (event.altKey && !event.ctrlKey && !event.metaKey
                && (event.key === 'h' || event.key === 'H')) {
                event.preventDefault();
                this.onShowVersionPanel?.();
            }
            // Ctrl+Shift+S：手動建立版本快照
            if ((event.ctrlKey || event.metaKey) && event.shiftKey
                && (event.key === 'S' || event.key === 's')) {
                event.preventDefault();
                this.onSaveVersion?.();
            }
            // Esc：關閉版本面板（若開啟）
            if (event.key === 'Escape' && this.state?.showVersionPanel) {
                this.state.showVersionPanel = false;
                dirty = true;
            }
            // Sprint Y17：Esc 關閉文件設定 modal（優先於 menu 的 Esc handling）
            if (event.key === 'Escape' && this.state?.showDocSettings) {
                this.state.showDocSettings = false;
                dirty = true;
            }
            // Sprint Y18：Esc 關閉行距 modal
            if (event.key === 'Escape' && this.state?.showLineSpacing) {
                this.state.showLineSpacing = false;
                dirty = true;
            }
            // Sprint Y21：Esc 關閉 find panel（focus 在 input 內走 inline keydown；
            //          focus 在外面才會走這條 _onGlobalKey path）
            if (event.key === 'Escape' && this.state?.findReplaceMode) {
                this.closeFindReplace();
                dirty = true;
            }
            // Sprint Y3：Esc 關閉 menu bar dropdown
            if (event.key === 'Escape' && this.state?.openMenu) {
                this.state.openMenu = null;
                this.state.menuFocusIndex = -1;   // Y14
                dirty = true;
            }
            // Sprint Y14：menu dropdown 開啟時的鍵盤導航
            if (this.state?.openMenu) {
                const key = event.key;
                if (key === 'ArrowDown') {
                    event.preventDefault();
                    this.state.menuFocusIndex = this._nextFocusableMenuIndex(
                        this.state.menuFocusIndex < 0 ? -1 : this.state.menuFocusIndex,
                        +1
                    );
                    dirty = true;
                } else if (key === 'ArrowUp') {
                    event.preventDefault();
                    this.state.menuFocusIndex = this._nextFocusableMenuIndex(
                        this.state.menuFocusIndex < 0 ? this._currentMenuItems().length : this.state.menuFocusIndex,
                        -1
                    );
                    dirty = true;
                } else if (key === 'ArrowRight') {
                    event.preventDefault();
                    this._switchMenuByOffset(+1, this.state.menuFocusIndex >= 0);
                    dirty = true;
                } else if (key === 'ArrowLeft') {
                    event.preventDefault();
                    this._switchMenuByOffset(-1, this.state.menuFocusIndex >= 0);
                    dirty = true;
                } else if (key === 'Home') {
                    event.preventDefault();
                    this.state.menuFocusIndex = this._firstFocusableMenuIndex();
                    dirty = true;
                } else if (key === 'End') {
                    event.preventDefault();
                    this.state.menuFocusIndex = this._lastFocusableMenuIndex();
                    dirty = true;
                } else if (key === 'Enter' || key === ' ') {
                    if (this.state.menuFocusIndex >= 0) {
                        event.preventDefault();
                        const item = this._currentMenuItems()[this.state.menuFocusIndex];
                        if (item && item.action && !item.disabled) {
                            this.onMenuItemClick(item.action);
                            dirty = true;
                        }
                    }
                }
            }
            // Sprint Y12：Esc 關閉色彩 palette dropdown
            if (event.key === 'Escape' && this.state?.showColorPalette) {
                this.state.showColorPalette = null;
                dirty = true;
            }
            // Esc 關閉表格網格 picker / 工具列下拉
            if (event.key === 'Escape' && this.state?.showTablePicker) {
                this.state.showTablePicker = false;
                dirty = true;
            }
            if (event.key === 'Escape' && this.state?.openToolbarMenu) {
                this.state.openToolbarMenu = null;
                dirty = true;
            }
            // Sprint Y4：Ctrl/Cmd+F 開尋找、Ctrl/Cmd+H 開取代
            if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey
                && (event.key === 'f' || event.key === 'F')) {
                event.preventDefault();
                this.openFindReplace?.('find');
            }
            if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey
                && (event.key === 'h' || event.key === 'H')) {
                event.preventDefault();
                this.openFindReplace?.('replace');
            }
            // Sprint Y15.1：force OWL re-render after window-listener state mutation
            if (dirty) {
                try { this.render?.(); } catch (e) { /* unmounted */ }
            }
        };
        // Sprint Y15.1：keydown listener 改掛 document（不是 window）。實測 Odoo/canvas-editor
        // 在 body→window 之間有 stopPropagation、keydown 永遠到不了 window listener。
        // 所有 Y3 Esc close / Y14 ↑↓ Arrow keys 一路被吃掉、只是 Cmd+F 等碰巧能 work（也吃但
        // ChromeDevTools 的 keypress 走另一條 path）。document listener 在 body 之上、Odoo
        // 沒在這層 stopPropagation。Y4 早就記過這教訓、但忘了套用到既有 listener。
        if (typeof document !== 'undefined') {
            document.addEventListener('keydown', this._onGlobalKey);
        }

        // Sprint Y3：menu bar 外部點擊關閉（mousedown 比 click 早觸發，避免 trigger 自身競態）
        // Sprint Y12：同一 listener 順便處理色彩 palette dropdown
        // Sprint Y15.1：window-listener mutation 同樣需要手動 render（見 _onGlobalKey 註解）
        this._onGlobalClick = (ev) => {
            if (!this.state) return;
            let dirty = false;
            try {
                if (this.state.openMenu && !ev.target.closest('.doc-menubar')) {
                    this.state.openMenu = null;
                    this.state.menuFocusIndex = -1;   // Y14
                    dirty = true;
                }
                if (this.state.showColorPalette && !ev.target.closest('.doc-format-color-wrap')) {
                    this.state.showColorPalette = null;
                    dirty = true;
                }
                // 表格網格 picker：點外關閉
                if (this.state.showTablePicker && !ev.target.closest('.doc-table-picker-wrap')) {
                    this.state.showTablePicker = false;
                    dirty = true;
                }
                // 欄位/簽名/掃描下拉：點外關閉
                if (this.state.openToolbarMenu && !ev.target.closest('.doc-toolbar-dropdown-wrap')) {
                    this.state.openToolbarMenu = null;
                    dirty = true;
                }
            } catch (e) { /* ignore */ }
            if (dirty) {
                try { this.render?.(); } catch (e) { /* unmounted */ }
            }
        };
        if (typeof document !== 'undefined') {
            document.addEventListener('mousedown', this._onGlobalClick);
        }

        // Sprint Y19：themeMode='auto' 時跟系統 prefers-color-scheme 同步
        // 任何時候系統偏好變動 → _recomputeDarkMode（內部判斷僅 auto 模式才生效）
        try {
            this._mediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)');
            this._onSystemThemeChange = () => this._recomputeDarkMode();
            this._mediaQuery?.addEventListener?.('change', this._onSystemThemeChange);
        } catch (e) { /* unsupported environment */ }
        // 確保初始 darkMode 與 themeMode + system pref 一致
        this._recomputeDarkMode();

        // 取得 doc_id 優先順序：
        //   1. this.props.docId — portal mount 模式（<owl-component props='{"docId":...}'>）
        //   2. backend client action context.doc_id
        //   3. URL query string ?doc_id=N — Sprint V：給 E2E / bookmark / share 用
        //      （client action URL 預設不接 context，這層 fallback 讓
        //       /odoo/action-dobtor_doc_editor.action_doc_editor?doc_id=N 能 work）
        //   4. sessionStorage F5 恢復（backend 內按 F5 刷新時用）
        const context = this.props.action?.context || {};
        const _SESSION_KEY = "dobtor_doc_editor_last_id";
        // Phase 1：解析「編輯哪一個對象」。template_id 優先於 doc_id——
        // 兩者同時出現只可能是狀態殘留（例如 sessionStorage 舊值撞上新的 context），
        // 後端 _resolve_edit_target 會直接擋下同時指定，所以這裡必須擇一送出。
        const _urlParam = (key) => {
            try {
                const v = new URLSearchParams(window.location.search).get(key);
                const n = v ? parseInt(v, 10) : 0;
                return n > 0 ? n : null;
            } catch (e) {
                return null;  // 非瀏覽器環境或 URL 異常 → 交給下一層 fallback
            }
        };
        // sessionStorage 格式："template:45" / "document:123"；
        // 舊格式是裸數字，視為 document 以相容既有分頁。
        let _storedTarget = null;
        const _stored = sessionStorage.getItem(_SESSION_KEY);
        if (_stored) {
            const [a, b] = _stored.includes(":") ? _stored.split(":") : ["document", _stored];
            const n = parseInt(b, 10);
            if (n > 0) {
                _storedTarget = { kind: a === "template" ? "template" : "document", id: n };
            }
        }
        // output 優先於 template 優先於 doc：三者擇一，後端會擋同時指定。
        const outputId =
            this.props.outputId || context.output_id || _urlParam("output_id") ||
            (_storedTarget?.kind === "output" ? _storedTarget.id : null);
        const templateId = outputId ? null : (
            this.props.templateId || context.template_id || _urlParam("template_id") ||
            (_storedTarget?.kind === "template" ? _storedTarget.id : null));
        const docId = (outputId || templateId)
            ? null
            : (this.props.docId || context.doc_id || _urlParam("doc_id") ||
               (_storedTarget?.kind === "document" ? _storedTarget.id : null));
        if (outputId) {
            this.state.editTarget = "output";
            this.state.outputId = outputId;
            // 唯讀在載入前就要成立——否則 canvas-editor 會以可編輯模式初始化，
            // 使用者打得下字（存不回去，但會以為自己改到了）
            this._isReadonly = true;
        } else if (templateId) {
            this.state.editTarget = "template";
            this.state.templateId = templateId;
        } else if (docId) {
            // 先寫進 state 讓 targetRpcParams 在首次載入時就可用。
            // 載入失敗時 _loadFailed 會擋住 autosave，避免用空內容覆蓋既有文件。
            this.state.docId = docId;
        }

        // ── AutoSaveManager（以 content_json 為儲存單位）──
        this._autoSave = new AutoSaveManager({
            saveFn: async (json) => {
                if (!this.targetId || this._loadFailed) return;
                // Readonly 模式（portal 唯讀 / 公開預覽）：不觸發後端寫入。
                if (this._isReadonly) return;
                const result = await rpc("/dobtor_doc/save", {
                    ...this.targetRpcParams,
                    content_json: json,
                    // 同步攤平後的 content_html（含 control 已填值），供匯出/預覽鏈讀取
                    content_html: this._mainHtml(),
                    // P2-2 樂觀鎖
                    if_unmodified_since: this._lastSyncedWriteDate,
                });
                this._handleSaveResult(result, json);
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

        onMounted(async () => {
            // 1. 載入編輯對象（文件 / 範本 / 輸出紀錄）
            if (docId || templateId || outputId) {
                await this._loadTarget();
            } else {
                this.state.editorReady = true;
            }

            // 2. 初始化 Canvas 編輯器（資料已暫存於 this._loadedContentJson）
            this._initCanvasEditor();

            // L2-v2 自動預覽模式：當 doc 同時有 res_id 與 alias 對映時，預設進入預覽模式，
            // 使用者一進來就看實際值而不是 token 原文。
            // 等 canvas-editor 真正 ready 再切（500ms 與 _initCanvasEditor 的 50ms 延遲對齊 + 緩衝）。
            const hasBoundRecord = this._loadedModelName && this._loadedResId;
            const hasAlias =
                Object.keys(this.state.fieldAliases || {}).length > 0 ||
                Object.keys(this.state.templateFieldAliases || {}).length > 0;
            const hasControlSpecs = Object.keys(this._controlSpecByVar || {}).length > 0;
            if (hasControlSpecs || (hasBoundRecord && hasAlias)) {
                setTimeout(async () => {
                    if (!this.editor) return;
                    // Phase 5：先把殘餘 alias token 升級成藥丸並存回。
                    // 這是只有 content_html 的舊資料唯一的升級管道——
                    // 伺服器端 migration 碰不到它們。
                    // 從既有內容復原重複列情境，否則重開範本後左欄不會出現「明細欄位」
                    this._recoverRepeatContext();
                    // 語言清單：i18n 藥丸的 inspector 與預覽語言切換都靠它。
                    // 不等它完成——載不到時 inspector 會顯示提示而不是空白。
                    this.loadLanguages();
                    const upgraded = this.upgradeTokensToPills();
                    if (upgraded > 0) {
                        this.notification.add(
                            `已將 ${upgraded} 個變數升級為標籤，請確認後儲存。`,
                            { type: "info" }
                        );
                    }
                    // 1) 先把已設定 control 的 token 升級成可互動 chip（含 《中文》 與 {{ var }} 兩格式，帶 record 當前值）
                    if (hasControlSpecs) {
                        await this._autoUpgradeConfiguredControls();
                    }
                    // 2) 再進預覽：把「殘餘」token（未設 control 的）換成實際值。
                    //    preview 傳入當前內容、且只替換 token 文字，故已建的 chip 會被保留 → chip 與值共存。
                    // 已快照的文件內容就是實際值，不必再跑一次即時渲染；
                    // 這條保留給尚未遷移／尚未快照的舊文件。
                    if (hasBoundRecord && hasAlias && !this.state.previewMode
                        && !this.state.snapshotDate) {
                        this.onTogglePreviewMode().catch(e => {
                            console.warn("[DocEditor] auto preview mode failed", e);
                        });
                    }
                }, 600);
            }

            // 3. 初始化 LeaderElection（多人協作防止重複存檔）
            if (this._busService && this.state.docId) {
                const channel = `doc.document_${this.state.docId}`;
                const sessionId = Math.random().toString(36).slice(2);
                this._leaderElection = new LeaderElection(
                    this._busService, channel, sessionId
                );
            }
        });

        onWillUnmount(async () => {
            // W4 P0-4：完整記憶體釋放，避免 portal user 反覆開關文件爆 RAM
            // 順序：flush 未存資料 → 解除全域引用 → 解除 listener closure → destroy 子系統
            try {
                await this._autoSave.flush();
            } catch (e) {
                // flush 失敗不應擋住 destroy，但要 log
                console.warn("[DocEditor] flush before unmount failed:", e);
            }
            this._autoSave.destroy();
            this._offlineManager.destroy();
            if (this._leaderElection) this._leaderElection.destroy();

            // 解除全域 DevTools 引用（避免 GC root 持有 editor → 整個文件 retain）
            if (window._docEditor === this.editor) {
                delete window._docEditor;
            }

            // 解除 listener closure（contentChange 內 closure 引用 this，會把 component 整個 retain）
            if (this.editor?.listener) {
                this.editor.listener.contentChange = null;
            }

            // 銷毀 Canvas 編輯器實例（v0.9.128 已提供 destroy 官方 API）
            this.editor?.destroy?.();

            // 清空成員引用，幫助 GC 識別此 component 已不可達
            this.editor = null;
            this._loadedContentJson = null;
            this._lastSyncedWriteDate = null;
            this._autoSave = null;
            this._offlineManager = null;
            this._leaderElection = null;

            // P2-4：卸載 telemetry listener
            try {
                this._uninstallTelemetry?.();
            } catch (e) {
                console.warn("[DocEditor] uninstall telemetry failed:", e);
            }
            this._uninstallTelemetry = null;

            // P3-2：解除鍵盤監聽（Y15.1：改掛 document）
            if (typeof document !== 'undefined' && this._onGlobalKey) {
                document.removeEventListener('keydown', this._onGlobalKey);
            }
            this._onGlobalKey = null;

            // Sprint Y3：解除 menu bar 外部點擊監聽
            if (typeof document !== 'undefined' && this._onGlobalClick) {
                document.removeEventListener('mousedown', this._onGlobalClick);
            }
            this._onGlobalClick = null;

            // Sprint Y19：解除 prefers-color-scheme listener
            if (this._mediaQuery && this._onSystemThemeChange) {
                this._mediaQuery.removeEventListener?.('change', this._onSystemThemeChange);
            }
            this._mediaQuery = null;
            this._onSystemThemeChange = null;
        });
    }

}

registry.category("actions").add("dobtor_doc_editor.action_doc_editor", DocEditor);
