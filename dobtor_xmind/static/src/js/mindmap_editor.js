/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { router } from "@web/core/browser/router";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { usePopover } from "@web/core/popover/popover_hook";
import { ActivityListPopover } from "@mail/core/web/activity_list_popover";
import { getMindmapTemplates } from "@dobtor_xmind/js/mindmap_templates_data";
import { MindmapPromptDialog } from "@dobtor_xmind/js/mindmap_prompt_dialog";
import { MindmapContextMenu } from "@dobtor_xmind/js/mindmap_context_menu";
import { MindmapSheetTabs } from "@dobtor_xmind/js/mindmap_sheet_tabs";
import {
    CommandStack,
    AddNodeCommand,
    RemoveNodeCommand,
    UpdateNodeCommand,
    UpdateNodeStyleCommand,
    ToggleExpandCommand,
} from "@dobtor_xmind/js/command_stack";
import {
    BoundaryRenderer,
    SummaryRenderer,
    CalloutRenderer,
    MarkerBadgeRenderer,
    LabelRenderer,
    NoteIndicator,
    ImageRenderer,
    HyperlinkIndicator,
    AttachmentIndicator,
} from "@dobtor_xmind/js/xmind_features";
import { DragDropManager } from "@dobtor_xmind/js/drag_drop_manager";
import { RelationshipManager } from "@dobtor_xmind/js/relationship_manager";
import { MindmapProjectBar } from "@dobtor_xmind/js/mindmap_project_bar";
import { MindmapPager } from "@dobtor_xmind/js/mindmap_pager";
import { MindmapSearch, MINDMAP_FILTERS } from "@dobtor_xmind/js/mindmap_search";

/**
 * Style Mind Map Editor for Odoo 18
 * OWL Component with Command Pattern
 */
export class MindmapEditor extends Component {
    static template = "dobtor_xmind.MindmapEditor";
    static components = { MindmapProjectBar, MindmapPager, MindmapSearch, MindmapSheetTabs };
    static props = ["*"];

    setup() {
        // rpc is imported directly from @web/core/network/rpc (not a service in Odoo 18)
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.action = useService("action");
        // Official Odoo activity list popover (same UI as the chatter clock button).
        this.activityPopover = usePopover(ActivityListPopover, { position: "bottom-start" });

        this.canvasRef = useRef("canvas");
        this.containerRef = useRef("jsmindContainer");
        this.sidebarRef = useRef("sidebar");

        // Read-only mode: when mounted as a sub-component (e.g. embedded into another
        // record's HTML field), suppress ALL editing affordances (toolbar, sidebar,
        // status bar, autosave, keyboard, drag/drop, context menus, URL hijack) while
        // keeping the full faithful rendering pipeline (_renderAllFeatures) intact.
        // Strictly additive: the client-action path never sets this, so its behaviour
        // is unchanged.
        this.readonly = !!(this.props && this.props.readonly);

        // Read workbook_id from a direct prop (embedded), else action params (normal
        // open) or router state (page refresh).
        this.workbookId =
            (this.props && this.props.workbookId) ||
            (this.props.action && this.props.action.params && this.props.action.params.workbook_id) ||
            router.current.workbook_id ||
            null;
        if (this.workbookId) {
            this.workbookId = parseInt(this.workbookId, 10) || null;
        }
        this.jm = null;
        this.projectInfo = null;   // 連結的專案 {id,name,last_sync_direction}
        this.partnerInfo = null;   // 客戶 {id,name}
        this.embedsInfo = [];      // 關聯物件名稱清單（嵌入此圖的記錄）
        this.commandStack = new CommandStack(200);
        this.selectedNode = null;
        this.autoSaveTimer = null;
        this.markers = [];
        this.relationshipMode = false;
        this.relationshipSource = null;

        // Feature Renderers
        this.boundaryRenderer = null;
        this.summaryRenderer = null;
        this.calloutRenderer = null;
        this.markerBadgeRenderer = new MarkerBadgeRenderer();
        this.labelRenderer = new LabelRenderer();
        this.noteIndicator = new NoteIndicator();
        this.imageRenderer = new ImageRenderer();
        this.hyperlinkIndicator = new HyperlinkIndicator();
        this.attachmentIndicator = new AttachmentIndicator();

        // Feature data
        this.boundaries = [];
        this.summaries = [];
        this.relationships = [];
        this.callouts = [];
        this.floatingTopics = [];
        this.boundarySelectionMode = false;
        this.summarySelectionMode = false;
        this.selectedTopicsForFeature = [];

        // 右鍵選單：547 行的命令分派表，抽到 mindmap_context_menu.js。
        // 它只讀編輯器的公開命令，所以相依是建構子參數而不是隱式的 this。
        this.contextMenu = new MindmapContextMenu(this);

        // 分頁列的狀態。改成 useState 是為了讓 MindmapSheetTabs 這個子元件能
        // 自己重繪 —— 以前是 _renderSheetTabs() 每次把整條列 innerHTML 清空
        // 重建（連事件監聽器一起重綁）。
        //
        // `_currentSheetId` / `_sheets` 全檔有十幾處讀寫，所以不改名，而是用
        // getter/setter 轉接到這份狀態上：任何一處指派都會自動同步，不會漏。
        // currentId 用 false 而不是 null 表示「未載入」—— props 宣告是
        // [Number, Boolean]，OWL 的型別檢查不接受 null。
        this.sheetState = useState({ sheets: [], currentId: false });

        // Drag and Drop Manager
        this.dragDropManager = null;

        // Format settings state
        this.formatState = {
            bold: false,
            italic: false,
            underline: false,
            strikethrough: false
        };

        // Branch/line style settings
        this.branchStyleSettings = {
            lineType: 'curved',
            lineWidth: 1,
            lineColor: '#558ED5',
            lineStyle: 'solid'
        };

        // Multi-selection state
        this.multiSelectMode = false;
        this.selectedNodes = [];
        this.rectangleSelector = null;

        // Mindmap and sheet data
        this.mindmapData = null;
        this.sheetSettings = { layout: 'map', theme: 'primary' };

        // Keyboard handler reference for cleanup
        // 這是每次按鍵都會跑的 handler，不是初始化函式（名稱曾為 _setupKeyboardShortcuts，
        // 看起來像 setup 而被誤讀）。
        this._boundKeydownHandler = this._onDocumentKeydown.bind(this);

        onMounted(async () => {
            // Show the record name in the toolbar breadcrumb ASAP (from the action's
            // name); _loadWorkbookData refreshes it from the DB afterwards.
            this._setRecordName((this.props.action && this.props.action.name) || '');
            // Persist workbook_id into the action's controller state so a browser
            // refresh reopens the SAME mind map. NB: a bare router.pushState() is
            // wiped by action_service's own pushState({replace:true}) (it rebuilds
            // the URL from the controller state); updateActionState writes into that
            // controller state so the id lands in the URL and survives refresh.
            // Skip when embedded/read-only — an inline map must not hijack the URL.
            if (this.workbookId && !this.readonly && this.props.updateActionState) {
                this.props.updateActionState({ workbook_id: this.workbookId });
            }
            await this._loadData();
            const jmInitSuccess = this._initJsMind();
            if (!jmInitSuccess) {
                this._updateStatus(_t('Initialization failed'));
                return;
            }
            this._initFeatures();
            // Editing-only wiring: skipped entirely in read-only/embedded mode so
            // multiple inline maps never register duplicate timers/handlers.
            if (!this.readonly) {
                this._setupCommandStackListener();
                this.contextMenu.setup();
                document.addEventListener('keydown', this._boundKeydownHandler);
                this._setupAutoSave();
                this._initFormatMenu();
                this._initRectangleSelector();
                this._initWheelZoom();       // Fix #9: Ctrl+scroll zoom
                this._initSpacePan();        // Fix #10: Space+drag pan
                this._loadSheets(); // Feature 4: Multi-Sheet tabs
            }
            this._zoomLevel = 1;
            this._copiedStyle = null;
            this._numberingEnabled = false;
            this._updateStatus(_t('Ready'));
        });

        onWillUnmount(() => {
            if (this.autoSaveTimer) {
                clearInterval(this.autoSaveTimer);
            }
            clearTimeout(this._featureRelayoutTimer);
            // Auto-save + thumbnail on exit if dirty. Never persist from a read-only
            // embed — inline navigation (expand/collapse) must not write to the DB.
            if (!this.readonly && this.commandStack && this.commandStack.isDirty && this.workbookId) {
                this._saveData().then(() => this._saveThumbnail()).catch(() => {});
            }
            if (this.dragDropManager) {
                this.dragDropManager.destroy();
            }
            if (this.advancedRelationshipManager && this.advancedRelationshipManager.destroy) {
                this.advancedRelationshipManager.destroy();
            }
            document.removeEventListener('keydown', this._boundKeydownHandler);
            // Remove every tracked document-level listener (space-pan, rectangle
            // select, relationship drag previews…) to avoid leaking the whole
            // component closure each time the editor is reopened.
            this._removeAllDocListeners();
        });
    }

    get _sheets() {
        return this.sheetState.sheets;
    }

    set _sheets(value) {
        this.sheetState.sheets = value || [];
    }

    get _currentSheetId() {
        return this.sheetState.currentId;
    }

    set _currentSheetId(value) {
        this.sheetState.currentId = value || false;
    }

    // ===== Helper: DOM query within this component =====
    get el() {
        // OWL Component root element — available after mount
        return this.__owl__ && this.__owl__.bdom ? this.__owl__.bdom.el : null;
    }

    _el(selector) {
        const root = this.el;
        return root ? root.querySelector(selector) : document.querySelector(`.o_mindmap_editor_container ${selector}`);
    }

    _elAll(selector) {
        const root = this.el;
        return root ? root.querySelectorAll(selector) : document.querySelectorAll(`.o_mindmap_editor_container ${selector}`);
    }

    // ===== Data Loading =====
    async _loadData() {
        await Promise.all([
            this._loadWorkbookData(),
            this._loadMarkers(),
        ]);
    }

    async _loadWorkbookData() {
        // Reset the load-failure guard on every (re)load attempt; a later success
        // re-enables saving that a prior failed load had blocked.
        this._loadFailed = false;
        if (!this.workbookId) {
            this.mindmapData = this._getDefaultData();
            this.sheetSettings = { layout: 'map', theme: 'primary' };
            return;
        }

        try {
            const result = await rpc('/xmind/workbook/' + this.workbookId + '/data', {});
            if (result.error) {
                this._showError(result.error);
                this.mindmapData = this._getDefaultData();
            } else {
                this.mindmapData = result.mindmap_data;
                this.sheetSettings = result.sheet_settings || { layout: 'map', theme: 'primary' };
                this._setRecordName(result.name);
                this.projectInfo = result.project || null;
                // 專案/客戶/關聯物件的顯示與編輯已移入 MindmapProjectBar 子元件，
                // 由子元件自行載入；此處僅保留 projectInfo 供同步/開啟專案的守衛使用。

                this._applyFeaturePayload(result);
            }
        } catch (e) {
            // A load failure must NOT masquerade as a new empty map — otherwise a
            // subsequent save would overwrite the real (un-loaded) data. Flag it,
            // surface it, and block saving until a successful reload.
            console.error('[MindmapEditor] Failed to load mindmap data:', e);
            this._loadFailed = true;
            if (this.notification) {
                this.notification.add(
                    _t('Failed to load mind map. Editing is disabled to protect your data — please reload.'),
                    { type: 'danger', sticky: true });
            }
            this.mindmapData = this._getDefaultData();
        }
    }

    /**
     * 套用一份「單一分頁」的特徵層載荷（關聯線／總結／外框／標註／浮動主題）。
     *
     * 初次載入（/data）與切換分頁（/sheet/<id>/data）共用。**一律賦值**，
     * 沒有資料就設空陣列 —— 舊寫法是 `if (result.x && x.length) {...}`，
     * 於是切到一張沒有關聯線的分頁時，上一張的關聯線會留在記憶體裡被重畫，
     * 而且下一次存檔就寫進新分頁，造成跨分頁污染。
     */
    _applyFeaturePayload(result) {
        const rnd = () => Math.random().toString(36).substr(2, 9);

        this.relationships = (result.relationships || []).map(r => ({
            id: 'rel_' + Date.now() + '_' + rnd(),
            sourceId: r.sourceId,
            targetId: r.targetId,
            options: r.options || {},
            controlPoints: r.controlPoints || [],
            // If CPs came from import, they are relative offsets from midpoint
            _cpIsRelativeOffset: r.cpIsRelativeOffset || false,
        }));
        this._hadRelationshipsOnLoad = this.relationships.length > 0;

        this.summaries = (result.summaries || []).map(s => ({
            id: 'sum_' + Date.now() + '_' + rnd(),
            topicIds: s.topicIds || [],
            summaryNodeId: s.summaryNodeId || '',
            options: s.options || {},
        }));

        this.boundaries = (result.boundaries || []).map(b => ({
            id: 'bnd_' + Date.now() + '_' + rnd(),
            topicIds: b.topicIds || [],
            options: b.options || {},
        }));

        this.callouts = (result.callouts || []).map(c => ({
            parentNodeId: c.parentNodeId,
            options: c.options || {},
        }));

        this.floatingTopics = (result.floating_topics || []).map(ft => ({
            id: ft.component_id || ('ft_' + ft.id),
            component_id: ft.component_id,
            title: ft.title,
            note: ft.note || '',
            x: ft.x,
            y: ft.y,
            style: ft.style || {},
        }));
    }

    async _loadMarkers() {
        try {
            const m = await rpc('/xmind/markers', {});
            this.markers = Array.isArray(m) ? m : [];
        } catch (e) {
            this.markers = [];
        }
    }

    _getDefaultData() {
        const rootDefaults = this._getDefaultsForDepth(0);
        return {
            meta: {
                name: 'New Mind Map',
                author: '',
                version: '1.0'
            },
            format: 'node_tree',
            data: {
                id: 'root',
                topic: _t('Central Topic'),
                expanded: true,
                children: [],
                data: {
                    shape: rootDefaults.shape,
                    style: { ...rootDefaults.style },
                }
            }
        };
    }

    // ===== render-engine Initialization =====
    _initJsMind() {
        const container = this.containerRef.el;

        if (!container) {
            console.error('[MindmapEditor] Container #jsmind_container not found.');
            this.notification.add(_t('Mind map container not found. Please refresh the page.'), { type: 'danger' });
            return false;
        }

        if (!window.OdooMindMap) {
            console.error('[MindmapEditor] Mind map render library not loaded.');
            this.notification.add(_t('Mind map library not loaded. Please clear cache and refresh.'), { type: 'danger' });
            return false;
        }

        const MindMapClass = window.OdooMindMap;

        const options = {
            container: container,
            theme: this.sheetSettings.theme || 'primary',
            editable: !this.readonly,
            mode: 'full',
            support_html: false,
            view: {
                engine: 'canvas',
                hmargin: 100,
                vmargin: 50,
                line_width: 2,
                line_color: '#555',
                draggable: true,
                hide_scrollbars_when_draggable: false,
            },
            layout: {
                hspace: this.sheetSettings.spacing_major || 30,
                vspace: this.sheetSettings.spacing_minor || 8,
                pspace: 13,
            },
            shortcut: {
                enable: false,
            },
        };

        this._applyLayoutSettings(options);

        try {
            this.jm = new MindMapClass(options);

            const layoutMode = this.sheetSettings.layout || 'map';
            if (this.jm.layout && this.jm.layout.setLayoutMode) {
                this.jm.layout.setLayoutMode(layoutMode);
            }

            // Inject floating topics as children of root with _isFloatingTopic flag
            if (this.floatingTopics.length > 0 && this.mindmapData && this.mindmapData.data) {
                if (!this.mindmapData.data.children) this.mindmapData.data.children = [];
                for (const ft of this.floatingTopics) {
                    // Avoid duplicates if already in tree
                    if (this.mindmapData.data.children.some(c => c.id === ft.id)) continue;
                    this.mindmapData.data.children.push({
                        id: ft.id || ft.component_id,
                        topic: ft.title,
                        expanded: true,
                        children: [],
                        data: {
                            _isFloatingTopic: true,
                            _ftX: ft.x,
                            _ftY: ft.y,
                            note: ft.note || '',
                            style: ft.style || { background: '#FFFFFF', color: '#303030', fontSize: '13', bold: true },
                            shape: { type: 'rounded', fillColor: '#FFFFFF', borderColor: '#558ED5', borderWidth: 2 },
                        },
                    });
                }
            }

            this.jm.show(this.mindmapData, () => {
                // Called after DOM is fully rendered + layout complete.
                // resetRelationships=true → on initial load, re-optimise relationship
                // control points for the current layout (matches layout-switch behaviour),
                // so a page refresh also lands the green connectors at optimal positions.
                this._renderAllFeatures(true);
            });
        } catch (error) {
            console.error('[MindmapEditor] Failed to initialize render-engine:', error);
            this.notification.add(_t('Failed to initialize mind map: ') + error.message, { type: 'danger' });
            return false;
        }

        // Event handlers
        this.jm.add_event_listener((type, data) => {
            this._onJsMindEvent(type, data);
        });

        // Update theme/layout selectors
        const themeSelect = this._el('.o_mindmap_theme_select');
        if (themeSelect) themeSelect.value = this.sheetSettings.theme || 'primary';
        const layoutSelect = this._el('.o_mindmap_layout_select');
        if (layoutSelect) layoutSelect.value = this.sheetSettings.layout || 'map';

        return true;
    }

    _applyLayoutSettings(options) {
        const layout = this.sheetSettings.layout || 'map';

        // spacing: tight layout, offset_x already accounts for node width
        switch (layout) {
            case 'tree_right':
            case 'tree_left':
                options.layout.hspace = 20;
                options.layout.vspace = 4;
                break;
            case 'logic_right':
                options.layout.hspace = 25;
                options.layout.vspace = 4;
                break;
            case 'org_chart_down':
                options.layout.hspace = 15;
                options.layout.vspace = 20;
                break;
            case 'fishbone_left':
                options.layout.hspace = 20;
                options.layout.vspace = 10;
                break;
            default: // map
                options.layout.hspace = 30;
                options.layout.vspace = 8;
        }
    }

    // ===== Command Stack =====
    _setupCommandStackListener() {
        this.commandStack.addListener((state) => {
            this._updateUndoRedoButtons(state);
            this._updateCommandCount(state.commandCount);
            if (state.isDirty) {
                this._updateStatus(_t('Modified'));
                // Update boundary/summary positions after any tree modification
                clearTimeout(this._featureUpdateTimer);
                this._featureUpdateTimer = setTimeout(() => this._updateFeaturePositions(), 50);
            }
        });
    }

    _updateUndoRedoButtons(state) {
        const undoBtn = this._el('.o_mindmap_btn_undo');
        const redoBtn = this._el('.o_mindmap_btn_redo');
        if (undoBtn) {
            undoBtn.disabled = !state.canUndo;
            if (state.canUndo) undoBtn.title = _t('Undo: ') + state.undoLabel;
        }
        if (redoBtn) {
            redoBtn.disabled = !state.canRedo;
            if (state.canRedo) redoBtn.title = _t('Redo: ') + state.redoLabel;
        }
    }

    /** Status bar「N 個指令」— CommandStack（可復原步數）計數。 */
    _updateCommandCount(count) {
        const el = this._el('.o_mindmap_command_count');
        if (el) el.textContent = '  ·  ' + (count || 0) + ' 個指令';
    }

    // ===== Keyboard Shortcuts =====
    _onDocumentKeydown(e) {
        if (this._isInputFocused()) return;

        // Escape cancels any active mode
        if (e.key === 'Escape') {
            if (this.relationshipMode) {
                this._exitRelationshipMode();
                e.preventDefault();
                return;
            }
            if (this._pendingFeatureMode) {
                this._pendingFeatureMode = null;
                const canvas = this.canvasRef.el;
                if (canvas) canvas.style.cursor = '';
                this._updateStatus(_t('Ready'));
                e.preventDefault();
                return;
            }
            // Deselect relationship control points
            this._deselectRelationship();
            e.preventDefault();
            return;
        }

        if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
            e.preventDefault();
            this.onUndo();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'y' || (e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'Z') {
            e.preventDefault();
            this.onRedo();
        } else if (e.key === 'Tab' && !e.shiftKey) {
            e.preventDefault();
            this.onAddChild();
        } else if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey) {
            e.preventDefault();
            if (this._hasSelectedRelationship()) {
                this._deselectRelationship();
            } else {
                this.onAddSibling();
            }
        } else if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault();
            this.onDelete();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            this.onSave();
        } else if (e.key === 'F2') {
            e.preventDefault();
            this._editSelectedNode();
        } else if (e.key.startsWith('Arrow') && !e.altKey && !e.ctrlKey && !e.metaKey) {
            this._handleArrowNavigation(e);
        } else if (e.key === ' ') {
            e.preventDefault();
            this._toggleSelectedExpand();
        } else if (e.shiftKey && e.key === 'Enter') {
            e.preventDefault();
            this.onAddTopicBefore();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            this.onAddParentTopic();
        } else if (e.altKey && e.key === 'ArrowUp') {
            e.preventDefault();
            this.onMoveUp();
        } else if (e.altKey && e.key === 'ArrowDown') {
            e.preventDefault();
            this.onMoveDown();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'x' && this.selectedNode) {
            e.preventDefault();
            this.onCutTopic();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'c' && this.selectedNode) {
            e.preventDefault();
            this.onCopyTopic();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'v' && this._clipboardTopic) {
            e.preventDefault();
            this.onPasteTopic();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'd' && this.selectedNode) {
            e.preventDefault();
            this.onDuplicateTopic();
        } else if ((e.ctrlKey || e.metaKey) && (e.key === '=' || e.key === '+')) {
            e.preventDefault();
            this.onZoomIn();
        } else if ((e.ctrlKey || e.metaKey) && e.key === '-') {
            e.preventDefault();
            this.onZoomOut();
        } else if ((e.ctrlKey || e.metaKey) && e.key === '0') {
            e.preventDefault();
            this.onZoomReset();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
            e.preventDefault();
            this.onFindReplace();
        // --- Fix #4: Ctrl+Alt+Arrow scrolls canvas ---
        } else if ((e.ctrlKey || e.metaKey) && e.altKey && e.key.startsWith('Arrow')) {
            e.preventDefault();
            const canvas = this.canvasRef.el;
            if (canvas) {
                const step = 60;
                if (e.key === 'ArrowUp') canvas.scrollTop -= step;
                else if (e.key === 'ArrowDown') canvas.scrollTop += step;
                else if (e.key === 'ArrowLeft') canvas.scrollLeft -= step;
                else if (e.key === 'ArrowRight') canvas.scrollLeft += step;
            }
        // --- Fix #1: Direct typing starts edit (printable char) ---
        } else if (this.selectedNode && e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
            // Single printable character → start edit and replace text
            this._editSelectedNode(e.key);
        }
    }

    _isInputFocused() {
        const activeElement = document.activeElement;
        if (!activeElement) return false;
        // Block shortcuts when any input, textarea, or render-engine edit input is active
        if (activeElement.tagName === 'INPUT' ||
            activeElement.tagName === 'TEXTAREA' ||
            activeElement.contentEditable === 'true' ||
            activeElement.classList.contains('xmind-edit-input')) {
            return true;
        }
        // Also check if render-engine is in editing mode
        if (this.jm && this.jm.view && this.jm.view.editing_node) {
            return true;
        }
        return false;
    }

    _handleArrowNavigation(e) {
        if (!this.selectedNode) return;

        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        let targetNode = null;

        switch (e.key) {
            case 'ArrowUp':
                if (node.parent) {
                    const siblings = node.parent.children;
                    const index = siblings.indexOf(node);
                    if (index > 0) targetNode = siblings[index - 1];
                }
                break;
            case 'ArrowDown':
                if (node.parent) {
                    const siblings = node.parent.children;
                    const index = siblings.indexOf(node);
                    if (index < siblings.length - 1) targetNode = siblings[index + 1];
                }
                break;
            case 'ArrowLeft':
                if (node.parent) targetNode = node.parent;
                break;
            case 'ArrowRight':
                if (node.children && node.children.length > 0) targetNode = node.children[0];
                break;
        }

        if (targetNode) {
            e.preventDefault();
            this.jm.select_node(targetNode.id);
        }
    }

    // ===== Auto Save =====
    _setupAutoSave() {
        this.autoSaveTimer = setInterval(() => {
            if (this.commandStack.isDirty && this.workbookId) {
                this._autoSave();
            }
        }, 60000);
    }

    async _autoSave() {
        this._updateStatus(_t('Auto-saving...'));
        const indicator = this._el('.o_mindmap_autosave_indicator');
        if (indicator) indicator.textContent = _t('Saving...');

        await this._saveData(true);
        this._saveThumbnail();

        if (indicator) {
            indicator.textContent = _t('Auto-saved');
            setTimeout(() => { indicator.textContent = ''; }, 3000);
        }
    }

    // ===== render-engine Events =====
    _onJsMindEvent(type, data) {
        if (type === 1 && (data.evt === 'expand' || data.evt === 'collapse')) {
            // Expand/collapse: reposition floating subtrees, rebuild features
            this._renderAllFloatingTopics();
            this._rebuildBoundaries();
            this._rebuildSummaries();
            if (this.jm && this.jm.view) this.jm.view.draw_lines();
            // 展開／收合不會重建節點元素，所以只要平移既有的線就好 ——
            // 使用者拖過的控制點得以保留，也省掉整組 SVG 的重建。
            this._refreshRelationshipPositions();
            // Deferred second pass for floating topic summaries
            if (this.floatingTopics.length > 0) {
                requestAnimationFrame(() => {
                    this._renderAllFloatingTopics();
                    this._rebuildBoundaries();
                    this._rebuildSummaries();
                    if (this.jm && this.jm.view) this.jm.view.draw_lines();
                    this._refreshRelationshipPositions();
                });
            }
            return;
        }
        if (type === 1) { // select
            this.selectedNode = data.node;

            if (this.relationshipMode) {
                if (!this.relationshipSource) {
                    // Step 1: source clicked — start preview line
                    this.relationshipSource = data.node;
                    const world = this.jm.view.world;
                    // Create preview SVG if not exists
                    let previewSvg = world.querySelector('.rel-preview-svg');
                    if (!previewSvg) {
                        this._setupRelationshipModeListeners();
                        previewSvg = world.querySelector('.rel-preview-svg');
                    }
                    const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    line.setAttribute('stroke', '#77933C');
                    line.setAttribute('stroke-width', '3');
                    line.setAttribute('stroke-dasharray', '6,4');
                    line.setAttribute('fill', 'none');
                    line.setAttribute('stroke-linecap', 'round');
                    line.setAttribute('marker-end', 'url(#rel-preview-arrow)');
                    previewSvg.appendChild(line);
                    this._relPreviewLine = line;
                    this._relPreviewSvg = previewSvg;
                    this._updateStatus(_t('Now click target topic... (Esc/Right-click to cancel)'));
                    return; // Don't open sidebar during relationship creation
                } else {
                    // Step 2: target clicked — create relationship
                    this._createRelationship(this.relationshipSource, data.node);
                    this._exitRelationshipMode();
                    return;
                }
            }

            this._updateSidebar(data.node);
            this._openSidebar();
        } else if (type === 2) { // update
            this._updateFeaturePositions();
        } else if (type === 3) { // show — features already rendered via show() callback
            // No-op: rendering is done in the onReady callback passed to jm.show()
        } else if (type === 4) { // resize
            setTimeout(() => this._updateFeaturePositions(), 100);
        }
    }

    _updateFeaturePositions(resetRelationshipCp = false) {
        // 1. Rebuild summaries (positions summary nodes + their children)
        this._rebuildSummaries();

        // 2. Redraw all render-engine branch lines
        if (this.jm && this.jm.view) {
            this.jm.view.draw_lines();
        }

        // 3. Rebuild boundaries
        this._rebuildBoundaries();

        // 4. Rebuild relationships (not just refresh — re-create if source/target now available)
        this._rebuildRelationships(resetRelationshipCp);
    }

    // resetControlPoints: discard saved (absolute) control points and let each
    // relationship regenerate fresh defaults from the CURRENT node positions.
    // Used on layout switch so the green connector re-optimises for the new
    // structure instead of staying anchored to the previous layout's geometry.
    /**
     * 只把既有的關連線平移到節點的新位置（不清空重建）。
     *
     * 展開／收合走的是 jsMind 的 `view.refresh()`，它只重新排版與定位，
     * **不會重建節點元素**（`_createAllNodes` 只在 `show()` 呼叫）——所以
     * `relData.sourceElement` 仍然有效，用增量平移就夠了，而且會保留使用者
     * 手動拖過的控制點；全刪重建則要重算每條線的預設幾何。
     *
     * 節點元素真的被重建過的場合（`jm.show()`、切換版面）仍必須走
     * `_rebuildRelationships()`。
     */
    _refreshRelationshipPositions() {
        if (!this.advancedRelationshipManager) return;
        this.advancedRelationshipManager.refreshPositions();
    }

    _rebuildRelationships(resetControlPoints = false) {
        if (!this.advancedRelationshipManager) return;
        // Sync control points from manager before clearing (preserves user drags).
        // Skipped when resetting: we intentionally drop the old geometry.
        if (!resetControlPoints) {
            this._syncRelationshipControlPoints();
        }
        this.advancedRelationshipManager.clear();
        for (const rel of this.relationships) {
            const sourceElement = this.jm.view.get_node_element(rel.sourceId);
            const targetElement = this.jm.view.get_node_element(rel.targetId);
            if (sourceElement && targetElement) {
                const opts = { ...rel.options };
                if (resetControlPoints) {
                    // Drop stale absolute control points → addRelationship will
                    // build defaults relative to the new source/target positions.
                    rel.controlPoints = null;
                    delete rel._cpIsRelativeOffset;
                } else if (rel.controlPoints && rel.controlPoints.length > 0) {
                    // Convert relative offsets to absolute on first load
                    if (rel._cpIsRelativeOffset) {
                        const scx = sourceElement.offsetLeft + sourceElement.offsetWidth / 2;
                        const scy = sourceElement.offsetTop + sourceElement.offsetHeight / 2;
                        const tcx = targetElement.offsetLeft + targetElement.offsetWidth / 2;
                        const tcy = targetElement.offsetTop + targetElement.offsetHeight / 2;
                        const midX = (scx + tcx) / 2;
                        const midY = (scy + tcy) / 2;
                        rel.controlPoints = rel.controlPoints.map(cp => ({
                            x: midX + (cp.x || 0),
                            y: midY + (cp.y || 0),
                        }));
                        delete rel._cpIsRelativeOffset;
                    }
                    opts.controlPoints = rel.controlPoints;
                }
                const newId = this.advancedRelationshipManager.addRelationship(sourceElement, targetElement, opts);
                // Update stored ID to match new manager ID (so future syncs work)
                if (newId) rel.id = newId;
            }
        }
        // Capture the freshly generated control points so they persist and so
        // subsequent (non-reset) rebuilds reuse the new layout's geometry.
        if (resetControlPoints) {
            this._syncRelationshipControlPoints();
        }

        // 端點若在收合的分支裡就把整條線收起來，避免留下指向 (0,0) 的殘線。
        this.advancedRelationshipManager.syncVisibility();
    }

    _collectSummaryElements(summary) {
        // Expand topicIds to include siblings BETWEEN first and last original topic
        // (newly inserted between them are included, but NOT siblings outside the range)
        if (!summary.topicIds || summary.topicIds.length === 0) return [];

        const firstNode = this.jm.get_node(summary.topicIds[0]);
        if (!firstNode || !firstNode.parent) return this._collectBoundaryElements(summary.topicIds);

        const parent = firstNode.parent;
        const siblings = parent.children.filter(c =>
            !(c.data && (c.data._isSummaryNode || c.data._isFloatingTopic)));

        // Find the range of original topicIds within current siblings
        const origSet = new Set(summary.topicIds);
        let startIdx = siblings.length, endIdx = -1;
        for (let i = 0; i < siblings.length; i++) {
            if (origSet.has(siblings[i].id)) {
                startIdx = Math.min(startIdx, i);
                endIdx = Math.max(endIdx, i);
            }
        }

        if (endIdx < 0) return this._collectBoundaryElements(summary.topicIds);

        // Collect siblings in range [startIdx, endIdx] — includes newly inserted between
        const rangeIds = [];
        for (let i = startIdx; i <= endIdx; i++) {
            rangeIds.push(siblings[i].id);
        }

        // Update stored topicIds to the current range
        summary.topicIds = rangeIds;

        return this._collectBoundaryElements(rangeIds);
    }

    _rebuildSummaries() {
        if (!this.summaryRenderer) return;
        this.summaryRenderer.clear();

        if (!this.summaries || this.summaries.length === 0) return;

        // Sort: outermost (shallowest) first — outer summaries position their children
        // before inner summaries can use those children's positions
        const sorted = [...this.summaries].sort((a, b) => {
            const dA = this._getSummaryDepth(a);
            const dB = this._getSummaryDepth(b);
            return dA - dB; // shallowest first
        });

        // Single pass: position node → draw bracket (per summary, inner first)
        for (const summary of sorted) {
            const topicElements = this._collectSummaryElements(summary);
            if (topicElements.length === 0) continue;

            // Check if any summarized topic is visible (skip if all collapsed/hidden)
            const visibleTopics = topicElements.filter(el => el && el.style.display !== 'none');
            if (visibleTopics.length === 0) {
                // Hide the summary node itself
                if (summary.summaryNodeId) {
                    const sEl = this.jm.view.get_node_element(summary.summaryNodeId);
                    if (sEl) sEl.style.display = 'none';
                    const sNode = this.jm.get_node(summary.summaryNodeId);
                    if (sNode && sNode._expander) sNode._expander.style.display = 'none';
                }
                continue;
            }

            // 1. Position summary render-engine node at bracket endpoint
            if (summary.summaryNodeId) {
                this._positionSummaryNode(summary.summaryNodeId, summary.topicIds);
            }

            // 2. Re-collect elements AFTER positioning (children positions updated)
            const freshElements = this._collectBoundaryElements(summary.topicIds);
            if (freshElements.length === 0) continue;

            // 3. Draw SVG bracket
            const summaryEl = summary.summaryNodeId
                ? this.jm.view.get_node_element(summary.summaryNodeId) : null;

            const currentLayout = (this.jm && this.jm.view && this.jm.view.layout && this.jm.view.layout._currentMode) || '';
            // nested summaries follow the SAME direction as parent layout
            const effectiveLayout = currentLayout;
            this.summaryRenderer.addSummary(freshElements, summaryEl, {
                lineType: summary.options.lineType || 'square',
                lineColor: summary.options.lineColor || '#C3D69B',
                lineWidth: summary.options.lineWidth || 5,
                summaryTitle: summary.options.topicText || summary.options.summaryTitle || 'Summary',
                summaryFill: summary.options.topicFillColor || summary.options.summaryFill || '#77933C',
                summaryColor: summary.options.topicTextColor || summary.options.summaryColor || '#FFFFFF',
                summaryFontSize: summary.options.topicFontSize || summary.options.summaryFontSize || 10,
                summaryItalic: summary.options.topicItalic || summary.options.summaryItalic || true,
                layoutMode: effectiveLayout,
            });
        }

        // Post-layout: resolve overlaps between summary elements and regular topics
        // Only for vertical layouts, and only on first pass (prevent infinite recursion)
        if (!this._isResolvingOverlaps) {
            const postLayout = (this.jm && this.jm.view && this.jm.view.layout && this.jm.view.layout._currentMode) || '';
            if (postLayout === 'org_chart_up' || postLayout === 'org_chart_down') {
                this._isResolvingOverlaps = true;
                this._resolveVerticalOverlaps();
                this._isResolvingOverlaps = false;
            }
        }
    }

    /**
     * After summaries are positioned, detect overlaps between all visible subtrees
     * and shift apart to resolve. Multiple passes to handle cascading overlaps.
     */
    _resolveVerticalOverlaps() {
        if (!this.jm || !this.jm.mind) return;
        const nodes = this.jm.mind.nodes;

        // Get bounding box of a node's entire visual subtree (including summary descendants)
        const getSubtreeBounds = (node) => {
            if (!node._w || !node._h || isNaN(node._x) || isNaN(node._y)) return null;
            let left = node._x - node._w / 2;
            let right = node._x + node._w / 2;
            let top = node._y - node._h / 2;
            let bottom = node._y + node._h / 2;
            if (node.expanded && node.children) {
                for (const c of node.children) {
                    if (!c._el || c._el.style.display === 'none') continue;
                    const cb = getSubtreeBounds(c);
                    if (!cb) continue;
                    left = Math.min(left, cb.left);
                    right = Math.max(right, cb.right);
                    top = Math.min(top, cb.top);
                    bottom = Math.max(bottom, cb.bottom);
                }
            }
            return { left, right, top, bottom };
        };

        const padding = 12;
        let anyShifted = false;

        // Check siblings at every level, bottom-up then top-down
        const checkSiblings = (parent) => {
            if (!parent || !parent.expanded) return;
            const children = parent.children.filter(c =>
                c._el && c._el.style.display !== 'none' && !(c.data && c.data._isSummaryNode));

            // Recurse into children FIRST (bottom-up: fix inner overlaps before outer)
            children.forEach(c => checkSiblings(c));

            if (children.length < 2) return;

            // Sort by X position
            const sorted = [...children].sort((a, b) => a._x - b._x);

            for (let i = 0; i < sorted.length - 1; i++) {
                const leftBounds = getSubtreeBounds(sorted[i]);
                const rightBounds = getSubtreeBounds(sorted[i + 1]);
                if (!leftBounds || !rightBounds) continue;

                const overlap = leftBounds.right + padding - rightBounds.left;
                if (overlap > 0) {
                    // Shift right sibling and all its descendants to the right
                    for (let j = i + 1; j < sorted.length; j++) {
                        this._shiftEntireSubtree(sorted[j], overlap, 0);
                    }
                    anyShifted = true;
                }
            }

            // Re-center children under parent after shifting
            if (anyShifted && children.length > 0) {
                const firstBounds = getSubtreeBounds(sorted[0]);
                const lastBounds = getSubtreeBounds(sorted[sorted.length - 1]);
                if (firstBounds && lastBounds) {
                    const currentCenter = (firstBounds.left + lastBounds.right) / 2;
                    const shiftToCenter = parent._x - currentCenter;
                    if (Math.abs(shiftToCenter) > 1) {
                        for (const c of children) {
                            this._shiftEntireSubtree(c, shiftToCenter, 0);
                        }
                    }
                }
            }
        };

        const root = this.jm.mind.root;
        if (root) checkSiblings(root);

        // Reposition ALL DOM elements after shifts (including summary nodes)
        if (anyShifted) {
            const isUp = (this.jm.view.layout && this.jm.view.layout._currentMode) === 'org_chart_up';
            for (const id in nodes) {
                const n = nodes[id];
                if (!n._el || n._el.style.display === 'none') continue;
                if (isNaN(n._x) || isNaN(n._y)) continue;

                // Update ALL node positions (including summary nodes)
                n._el.style.left = (n._x - n._w / 2) + 'px';
                n._el.style.top = (n._y - n._h / 2) + 'px';

                if (n._expander) {
                    const d = n.direction || 1;
                    if (d === 2) {
                        n._expander.style.left = (n._x - 6) + 'px';
                        n._expander.style.top = isUp
                            ? (n._y - n._h / 2 - 13) + 'px'
                            : (n._y + n._h / 2 + 2) + 'px';
                    } else if (d === -1) {
                        n._expander.style.left = (n._x - n._w / 2 - 15) + 'px';
                        n._expander.style.top = (n._y - 6) + 'px';
                    } else {
                        n._expander.style.left = (n._x + n._w / 2 + 3) + 'px';
                        n._expander.style.top = (n._y - 6) + 'px';
                    }
                }
            }
            // Redraw lines
            if (this.jm.view) this.jm.view.draw_lines();
            // Re-run summary positioning (summaries may have shifted with their parent subtrees)
            if (this.summaryRenderer) {
                this.summaryRenderer.clear();
            }
            this._rebuildSummaries();
        }
    }

    _shiftEntireSubtree(node, dx, dy) {
        node._x += dx;
        node._y += dy;
        if (node.expanded && node.children) {
            for (const c of node.children) {
                this._shiftEntireSubtree(c, dx, dy);
            }
        }
    }

    _getSummaryDepth(summary) {
        if (!summary.topicIds || summary.topicIds.length === 0) return 0;
        const node = this.jm.get_node(summary.topicIds[0]);
        return node ? (node._depth || 0) : 0;
    }

    _positionSummaryNode(summaryNodeId, topicIds) {
        const node = this.jm.get_node(summaryNodeId);
        const el = this.jm.view.get_node_element(summaryNodeId);
        if (!node || !el) return;

        const topicElements = this._collectBoundaryElements(topicIds);
        if (topicElements.length === 0) return;

        const layoutMode = (this.jm.view.layout && this.jm.view.layout._currentMode) || '';
        // ALL summaries in org_chart layouts follow the same vertical direction
        const isVertical = layoutMode === 'org_chart_up' || layoutMode === 'org_chart_down';

        if (isVertical) {
            // algorithm: summary positioned in same direction as parent layout
            // org_chart_down → summary SOUTH (below children)
            // org_chart_up → summary NORTH (above children)

            // Use SAME elements as SVG bracket (topicElements includes descendants)
            // This ensures summary node is centered at the bracket stub line
            let minY = Infinity, maxY = -Infinity, leftX = Infinity, rightX = -Infinity;
            for (const te of topicElements) {
                leftX = Math.min(leftX, te.offsetLeft);
                rightX = Math.max(rightX, te.offsetLeft + te.offsetWidth);
                minY = Math.min(minY, te.offsetTop);
                maxY = Math.max(maxY, te.offsetTop + te.offsetHeight);
            }
            const midX = (leftX + rightX) / 2;

            const isUp = layoutMode === 'org_chart_up';

            // Position summary node at bracket stub endpoint
            // SVG bracket uses same topicElements, so bracketY matches
            const stubEndY = isUp ? (minY - 10 - 38) : (maxY + 10 + 38);
            const nodeY = isUp
                ? stubEndY - el.offsetHeight  // node bottom at stubEndY
                : stubEndY;                    // node top at stubEndY

            const posLeft = midX - el.offsetWidth / 2;
            el.style.left = posLeft + 'px';
            el.style.top = nodeY + 'px';

            node._x = midX;
            node._y = nodeY + el.offsetHeight / 2;
            node.direction = 2; // vertical (same as parent org_chart direction)

            // Summary children use the SAME org_chart layout (behavior)
            if (node.children && node.children.length > 0) {
                if (!node.expanded) {
                    this.jm.view._hideDescendants(node);
                } else {
                    for (const c of node.children) {
                        if (c._el) {
                            const ow = c._el.offsetWidth;
                            const oh = c._el.offsetHeight;
                            if (ow > 1) { c._w = ow; c._h = oh; }
                        }
                    }

                    // Use the SAME org_chart layout for children (not logic_right)
                    const layout = this.jm.view.layout;
                    if (isUp) {
                        layout._layoutVerticalUpChildren(node);
                    } else {
                        layout._layoutVerticalChildren(node);
                    }

                    this._positionSummaryChildren(node, 2);
                }
            }
        } else {
            let minY = Infinity, maxY = -Infinity, leftX = Infinity, rightX = -Infinity;
            for (const te of topicElements) {
                leftX = Math.min(leftX, te.offsetLeft);
                rightX = Math.max(rightX, te.offsetLeft + te.offsetWidth);
                minY = Math.min(minY, te.offsetTop);
                maxY = Math.max(maxY, te.offsetTop + te.offsetHeight);
            }

            const dir = topicElements[0].offsetLeft < -50 ? -1 : 1;
            const bracketX = dir > 0 ? rightX + 20 : leftX - 20;
            // Align with SVG stub line endpoint: bracketX + dir * 38
            const nodeX = bracketX + dir * 38;
            const midY = (minY + maxY) / 2;

            const posLeft = dir < 0 ? nodeX - el.offsetWidth : nodeX;
            el.style.left = posLeft + 'px';
            el.style.top = (midY - el.offsetHeight / 2) + 'px';

            node._x = posLeft + el.offsetWidth / 2;
            node._y = midY;
            node.direction = dir;

            // Layout summary's children branching from summary
            if (node.children && node.children.length > 0) {
                if (!node.expanded) {
                    this.jm.view._hideDescendants(node);
                } else {
                    for (const c of node.children) {
                        if (c._el) {
                            const ow = c._el.offsetWidth;
                            const oh = c._el.offsetHeight;
                            if (ow > 1) { c._w = ow; c._h = oh; }
                        }
                    }
                    const layout = this.jm.view.layout;
                    const savedMode = layout._currentMode;
                    layout._currentMode = 'logic_right';
                    layout._layoutBranch(node, node.children, dir);
                    layout._currentMode = savedMode;
                    this._positionSummaryChildren(node, dir);
                }
            }
        }

        // Reposition summary's own expander
        if (node._expander) {
            node._expander.style.display = node.children.length > 0 ? '' : 'none';
            if (isVertical) {
                const isUp = layoutMode === 'org_chart_up';
                node._expander.style.left = (node._x - 6) + 'px';
                node._expander.style.top = isUp
                    ? (node._y - node._h / 2 - 13) + 'px'
                    : (node._y + node._h / 2 + 2) + 'px';
            } else {
                const d = node.direction || 1;
                if (d === -1) {
                    node._expander.style.left = (node._x - node._w / 2 - 15) + 'px';
                } else {
                    node._expander.style.left = (node._x + node._w / 2 + 3) + 'px';
                }
                node._expander.style.top = (node._y - 6) + 'px';
            }
        }
    }

    _positionSummaryChildren(node, dir) {
        const jmView = this.jm.view;
        const posAll = (n) => {
            if (!n._el) return;
            if (!(n.data && n.data._isSummaryNode)) {
                n._el.style.left = (n._x - n._w / 2) + 'px';
                n._el.style.top = (n._y - n._h / 2) + 'px';
                n._el.style.display = '';
            }
            if (n._expander) {
                const d = n.direction || dir;
                if (d === -1) {
                    n._expander.style.left = (n._x - n._w / 2 - 15) + 'px';
                    n._expander.style.top = (n._y - 6) + 'px';
                } else {
                    n._expander.style.left = (n._x + n._w / 2 + 3) + 'px';
                    n._expander.style.top = (n._y - 6) + 'px';
                }
                n._expander.style.display = n.children.length > 0 ? '' : 'none';
            }
            if (n.expanded) {
                n.children.forEach(c => posAll(c));
            } else if (n.children.length > 0) {
                // Collapsed: hide all descendants
                jmView._hideDescendants(n);
            }
        };
        node.children.forEach(c => posAll(c));
    }

    _rebuildBoundaries() {
        if (!this.boundaryRenderer) return;
        this.boundaryRenderer.clear();

        // Compute raw bounds for each boundary
        const boundsData = this.boundaries.map(boundary => {
            const elements = this._collectBoundaryElements(boundary.topicIds);
            if (elements.length === 0) return null;
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            let visibleCount = 0;
            for (const el of elements) {
                if (!el || el.style.display === 'none') continue;
                visibleCount++;
                minX = Math.min(minX, el.offsetLeft);
                minY = Math.min(minY, el.offsetTop);
                maxX = Math.max(maxX, el.offsetLeft + el.offsetWidth);
                maxY = Math.max(maxY, el.offsetTop + el.offsetHeight);
            }
            if (visibleCount === 0) return null;
            return { boundary, elements, minX, minY, maxX, maxY };
        }).filter(b => b !== null);

        if (boundsData.length === 0) return;

        // Sort by minY then minX (top-to-bottom, left-to-right)
        boundsData.sort((a, b) => a.minY - b.minY || a.minX - b.minX);

        const padding = 14;
        const minGap = 2; // minimum visible gap between adjacent boundary frames

        for (const bd of boundsData) {
            bd.padTop = padding;
            bd.padRight = padding;
            bd.padBottom = padding;
            bd.padLeft = padding;
        }

        // Prevent adjacent boundaries from overlapping by shrinking shared-edge padding.
        // Title pills are now fully inside the frame, so no extra room needed above.
        for (let i = 0; i < boundsData.length; i++) {
            for (let j = i + 1; j < boundsData.length; j++) {
                const a = boundsData[i];
                const b = boundsData[j];

                // Must share X range to be vertically adjacent
                if (!(a.maxX > b.minX && b.maxX > a.minX)) continue;

                const space = b.minY - a.maxY;
                const needed = padding + minGap + padding;
                if (space < needed) {
                    const half = Math.max(0, (space - minGap) / 2);
                    a.padBottom = Math.min(a.padBottom, half);
                    b.padTop = Math.min(b.padTop, half);
                }

                // Horizontal adjacency
                if (!(a.maxY > b.minY && b.maxY > a.minY)) continue;
                const hSpace = b.minX - a.maxX;
                if (hSpace < needed) {
                    const half = Math.max(0, (hSpace - minGap) / 2);
                    a.padRight = Math.min(a.padRight, half);
                    b.padLeft = Math.min(b.padLeft, half);
                }
            }
        }

        // Render each boundary with its computed per-side padding
        for (const bd of boundsData) {
            const opts = {
                ...bd.boundary.options,
                _padTop: bd.padTop,
                _padRight: bd.padRight,
                _padBottom: bd.padBottom,
                _padLeft: bd.padLeft,
            };
            this.boundaryRenderer.addBoundary(bd.elements, opts);
        }
    }

    _collectBoundaryElements(topicIds) {
        // Collect elements for specified topic IDs plus ALL their descendants
        const elements = [];
        const seen = new Set();

        const collectDescendants = (nodeId) => {
            if (seen.has(nodeId)) return;
            seen.add(nodeId);
            const el = this.jm.view.get_node_element(nodeId);
            if (el) elements.push(el);

            const node = this.jm.get_node(nodeId);
            if (node && node.expanded && node.children) {
                for (const child of node.children) {
                    collectDescendants(child.id);
                }
            }
        };

        for (const nodeId of topicIds) {
            collectDescendants(nodeId);
        }
        return elements;
    }

    // ===== Features Init =====
    _initFeatures() {
        if (!this.jm) return;

        const canvas = this.canvasRef.el;
        if (!canvas) return;

        // Use renderer's world div so features follow pan/zoom transform
        const world = this.jm.view.world || canvas;

        this.advancedRelationshipManager = new RelationshipManager(world);
        this.boundaryRenderer = new BoundaryRenderer(world);
        this.summaryRenderer = new SummaryRenderer(world);
        this.calloutRenderer = new CalloutRenderer(world);

        // Read-only/embedded: the overlay renderers above are all that _renderAllFeatures
        // needs to faithfully draw relationships/boundaries/summaries/callouts. Skip every
        // editing interaction below (drag/drop, dblclick-to-edit, relationship editing,
        // summary context menus).
        if (this.readonly) {
            return;
        }

        this.summaryRenderer.setContextMenuCallback((summaryId, event) => {
            this._showSummaryContextMenu(summaryId, event);
        });

        this.summaryRenderer.setClickCallback((summaryId, event) => {
            this._updateStatus(_t('Summary selected: ') + summaryId);
        });

        this.dragDropManager = new DragDropManager(this.jm, this);
        this.dragDropManager.init();

        // Fix #1: Intercept dblclick on nodes to go through _editSelectedNode (undo support)
        world.addEventListener('dblclick', (e) => {
            const nodeEl = e.target.closest('.xmind-node');
            if (nodeEl) {
                e.stopPropagation();
                e.preventDefault();
                const nodeId = nodeEl.getAttribute('data-nodeid');
                if (nodeId) {
                    this.selectedNode = nodeId;
                    this._editSelectedNode();
                }
            }
        }, true); // capture phase to run before render-engine's own dblclick

        // Hook relationship click → show control points; double-click → edit dialog
        this._setupRelationshipInteraction();

        // Drag-to-connect: Alt+drag from topic to topic creates relationship
        this._setupDragToConnect();

        // Relationship button mode: click source → preview → click target
        this._setupRelationshipModeListeners();
    }

    _setupRelationshipInteraction() {
        if (!this.advancedRelationshipManager) return;
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        // Double-click on relationship path → open edit dialog
        canvas.addEventListener('dblclick', (e) => {
            const pathEl = e.target.closest('.relationship-path');
            if (!pathEl) return;
            const group = pathEl.closest('g[data-rel-id]');
            if (!group) return;
            const relId = group.getAttribute('data-rel-id');
            const relData = this.relationships.find(r => r.id === relId);
            if (relData) {
                e.stopPropagation();
                this._showRelationshipPropertiesDialog(relData.sourceId, relData.targetId, relId);
            }
        });

        // When a control-point/endpoint drag ends → sync CPs back + mark dirty.
        // (Previously this monkey-patched _onMouseUp, but the document listener was
        //  bound to the ORIGINAL method so the patch never ran and curve edits were
        //  silently lost. The manager now invokes this callback directly on drag end.)
        this.advancedRelationshipManager.onControlPointChange = () => {
            this._syncRelationshipControlPoints();
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Curve adjusted'));
        };
    }

    _hasSelectedRelationship() {
        return this.advancedRelationshipManager &&
            this.advancedRelationshipManager.selectedRelationship != null;
    }

    _deselectRelationship() {
        if (!this.advancedRelationshipManager) return;
        if (this.advancedRelationshipManager.selectedRelationship) {
            // Sync control points before deselecting
            this._syncRelationshipControlPoints();
            this.advancedRelationshipManager._hideControlPoints(
                this.advancedRelationshipManager.selectedRelationship
            );
            this.advancedRelationshipManager.selectedRelationship = null;
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
        }
    }

    _syncRelationshipControlPoints() {
        // Pull latest control point positions from the manager back into our data
        const managerData = this.advancedRelationshipManager.getRelationshipData();
        for (const mRel of managerData) {
            const storedRel = this.relationships.find(r => r.id === mRel.id);
            if (storedRel) {
                storedRel.controlPoints = mRel.controlPoints;
            }
        }
    }

    _setupDragToConnect() {
        // Alt+drag from a topic draws a preview line; release on another topic creates relationship
        const world = this.jm.view.world;
        if (!world) return;

        let isDragging = false;
        let sourceNode = null;
        let previewLine = null;

        // Create persistent SVG for preview line
        const previewSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        previewSvg.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;overflow:visible;pointer-events:none;z-index:20;';
        world.appendChild(previewSvg);

        world.addEventListener('mousedown', (e) => {
            // Ctrl+drag (Windows) or Cmd+drag (Mac) on a node starts drag-to-connect
            if (!(e.ctrlKey || e.metaKey)) return;
            const nodeEl = e.target.closest('.xmind-node');
            if (!nodeEl) return;

            const nodeId = nodeEl.getAttribute('data-nodeid');
            sourceNode = this.jm.get_node(nodeId);
            if (!sourceNode) return;

            isDragging = true;
            e.preventDefault();
            e.stopPropagation();

            // Create preview line
            previewLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            previewLine.setAttribute('stroke', '#0068cf');
            previewLine.setAttribute('stroke-width', '3');
            previewLine.setAttribute('stroke-dasharray', '6,4');
            previewLine.setAttribute('fill', 'none');
            previewLine.setAttribute('stroke-linecap', 'round');
            previewSvg.appendChild(previewLine);

            this._updateStatus(_t('Drag to target topic to create relationship...'));
        });

        this._addDocListener('mousemove', (e) => {
            if (!isDragging || !sourceNode || !previewLine) return;

            const srcEl = sourceNode._el;
            if (!srcEl) return;

            // Source center (local coords)
            const sx = srcEl.offsetLeft + srcEl.offsetWidth / 2;
            const sy = srcEl.offsetTop + srcEl.offsetHeight / 2;

            // Mouse in world coords
            const worldRect = world.getBoundingClientRect();
            const zoom = this.jm.view.getZoom ? this.jm.view.getZoom() : 1;
            const mx = (e.clientX - worldRect.left) / zoom;
            const my = (e.clientY - worldRect.top) / zoom;

            // Bezier preview
            const ctrl = Math.abs(mx - sx) * 0.4;
            previewLine.setAttribute('d', `M${sx},${sy} C${sx + ctrl},${sy} ${mx - ctrl},${my} ${mx},${my}`);

            // Highlight nearest target node
            const targetEl = document.elementFromPoint(e.clientX, e.clientY);
            const targetNodeEl = targetEl ? targetEl.closest('.xmind-node') : null;

            // Remove previous highlights
            world.querySelectorAll('.xmind-node.rel-drop-target').forEach(el => el.classList.remove('rel-drop-target'));

            if (targetNodeEl && targetNodeEl !== srcEl) {
                targetNodeEl.classList.add('rel-drop-target');
            }
        });

        this._addDocListener('mouseup', (e) => {
            if (!isDragging) return;
            isDragging = false;

            // Remove preview
            if (previewLine && previewLine.parentNode) {
                previewLine.parentNode.removeChild(previewLine);
                previewLine = null;
            }

            // Remove highlights
            world.querySelectorAll('.xmind-node.rel-drop-target').forEach(el => el.classList.remove('rel-drop-target'));

            // Find target
            const targetEl = document.elementFromPoint(e.clientX, e.clientY);
            const targetNodeEl = targetEl ? targetEl.closest('.xmind-node') : null;

            if (targetNodeEl && sourceNode) {
                const targetId = targetNodeEl.getAttribute('data-nodeid');
                if (targetId && targetId !== sourceNode.id) {
                    // Create relationship via properties dialog
                    this._showRelationshipPropertiesDialog(sourceNode.id, targetId, null);
                }
            }

            sourceNode = null;
            this._updateStatus(_t('Ready'));
        });
    }

    _initFormatMenu() {
        const formatMenu = this._el('.o_format_menu');
        if (formatMenu) {
            formatMenu.addEventListener('click', (e) => e.stopPropagation());
        }
        const hSpaceVal = this._el('.o_format_h_space_val');
        const hSpace = this._el('.o_format_h_space');
        if (hSpaceVal && hSpace) hSpaceVal.textContent = hSpace.value + 'px';
        const vSpaceVal = this._el('.o_format_v_space_val');
        const vSpace = this._el('.o_format_v_space');
        if (vSpaceVal && vSpace) vSpaceVal.textContent = vSpace.value + 'px';
    }

    _initRectangleSelector() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        this.selectionRect = document.createElement('div');
        this.selectionRect.className = 'selection-rectangle';
        this.selectionRect.style.cssText = 'position: absolute; border: 2px dashed #007bff; background: rgba(0, 123, 255, 0.1); pointer-events: none; display: none; z-index: 1000;';
        canvas.appendChild(this.selectionRect);

        let isSelecting = false;
        let startX, startY;

        canvas.addEventListener('mousedown', (e) => {
            const clickedNode = e.target.closest('.xmind-node');
            const clickedExpander = e.target.closest('.xmind-expander');
            const clickedFloating = e.target.closest('.xmind-floating-topic');
            if (!clickedNode && !clickedExpander && !clickedFloating && e.button === 0) {
                // Left-click on empty area: clear selection + deselect relationship
                this._clearMultiSelection();
                this._deselectRelationship();
                isSelecting = true;
                e.stopPropagation(); // Prevent render-engine panel drag
                const rect = canvas.getBoundingClientRect();
                startX = e.clientX - rect.left;
                startY = e.clientY - rect.top;
                this.selectionRect.style.left = startX + 'px';
                this.selectionRect.style.top = startY + 'px';
                this.selectionRect.style.width = '0px';
                this.selectionRect.style.height = '0px';
                this.selectionRect.style.display = 'block';
                e.preventDefault();
            }
        });

        this._addDocListener('mousemove', (e) => {
            if (!isSelecting) return;
            const rect = canvas.getBoundingClientRect();
            const currentX = e.clientX - rect.left;
            const currentY = e.clientY - rect.top;
            this.selectionRect.style.left = Math.min(currentX, startX) + 'px';
            this.selectionRect.style.top = Math.min(currentY, startY) + 'px';
            this.selectionRect.style.width = Math.abs(currentX - startX) + 'px';
            this.selectionRect.style.height = Math.abs(currentY - startY) + 'px';
        });

        this._addDocListener('mouseup', (e) => {
            if (!isSelecting) return;
            isSelecting = false;
            const selRect = this.selectionRect.getBoundingClientRect();
            const rectW = parseFloat(this.selectionRect.style.width);
            const rectH = parseFloat(this.selectionRect.style.height);
            this.selectionRect.style.display = 'none';

            // Only select if drag area is meaningful (> 5px)
            if (rectW > 5 && rectH > 5) {
                // Clear previous selection before new rectangle select
                this._clearMultiSelection();
                this._selectNodesInRect(selRect);

                // Auto-create feature if in pending mode
                if (this._pendingFeatureMode && this.selectedNodes.length > 0) {
                    const mode = this._pendingFeatureMode;
                    this._pendingFeatureMode = null;
                    const canvas = this.canvasRef.el;
                    if (canvas) canvas.style.cursor = '';

                    if (mode === 'boundary') {
                        this.selectedTopicsForFeature = this.selectedNodes.map(n => n.id || n);
                        this._createBoundaryWithDefaults();
                    } else if (mode === 'summary') {
                        const ids = this.selectedNodes.map(n => n.id || n);
                        const node = this.jm.get_node(ids[0]);
                        if (node && node.parent) {
                            this._createSummary(ids, {
                                lineType: 'square', lineWidth: 5, lineColor: '#C3D69B',
                                topicText: _t('Summary'), topicFillColor: '#77933C',
                                topicTextColor: '#FFFFFF', topicFontSize: 10,
                                topicShape: 'rounded', topicBorderColor: 'transparent',
                                topicBorderWidth: 0, topicBold: false, topicItalic: true,
                                branchType: 'curved', branchEndMarker: 'none',
                                branchWidth: 1, branchColor: '#C3D69B',
                            });
                        }
                    }
                }
            }
        });

        canvas.addEventListener('click', (e) => {
            const nodeElement = e.target.closest('.xmind-node');
            if (nodeElement) {
                const nodeId = nodeElement.getAttribute('data-nodeid');
                const node = this.jm.get_node(nodeId);
                if (e.ctrlKey || e.metaKey || this.multiSelectMode) {
                    // Fix #2: Ctrl+Click toggles individual node in multi-selection
                    this._toggleNodeSelection(node);
                } else if (e.shiftKey && this.selectedNode) {
                    // Fix #2: Shift+Click selects range of siblings
                    this._selectSiblingRange(this.selectedNode, nodeId);
                } else {
                    this._clearMultiSelection();
                    this._addNodeToSelection(node);
                }
            }
        });
    }

    // ===== Ctrl+Scroll / Pinch Zoom — sync zoom level display =====
    _initWheelZoom() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        // Sync the zoom level display when jsmind handles zoom internally
        canvas.addEventListener('wheel', (e) => {
            if (e.ctrlKey || e.metaKey) {
                // jsmind._onWheel handles the actual zoom; we just sync the display
                setTimeout(() => {
                    if (this.jm && this.jm.view) {
                        this._zoomLevel = this.jm.view.getZoom();
                        // Sync all zoom readouts + slider (toolbar + status bar).
                        const pct = Math.round(this._zoomLevel * 100);
                        this._elAll('.o_mindmap_zoom_level').forEach(el => { el.textContent = pct + '%'; });
                        const slider = this._el('.o_mindmap_zoom_slider');
                        if (slider) slider.value = pct;
                    }
                }, 10);
            }
        }, { passive: true });
    }

    // ===== Space+Drag Pan =====
    /**
     * Register a document-level listener and remember it so onWillUnmount can
     * remove it. Returns nothing; cleanup is automatic. Use this for every
     * `document.addEventListener` in the component to avoid leaking listeners
     * (and the whole component closure) each time the editor is reopened.
     */
    _addDocListener(type, handler, options) {
        if (!this._docListeners) this._docListeners = [];
        document.addEventListener(type, handler, options);
        this._docListeners.push([type, handler, options]);
    }

    _removeAllDocListeners() {
        if (!this._docListeners) return;
        for (const [type, handler, options] of this._docListeners) {
            document.removeEventListener(type, handler, options);
        }
        this._docListeners = [];
    }

    _initSpacePan() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        let isPanning = false;
        let panStartX = 0, panStartY = 0;
        let savedPanX = 0, savedPanY = 0;
        let spaceDown = false;

        // Track Space key state — only activate pan cursor if no node is selected
        this._addDocListener('keydown', (e) => {
            if (e.key === ' ' && !this._isInputFocused() && !this.selectedNode) {
                spaceDown = true;
                canvas.style.cursor = 'grab';
            }
        });
        this._addDocListener('keyup', (e) => {
            if (e.key === ' ') {
                spaceDown = false;
                if (!isPanning) canvas.style.cursor = '';
            }
        });

        canvas.addEventListener('mousedown', (e) => {
            // Space+Left-click starts panning (via jsmind's transform system)
            if (spaceDown && e.button === 0) {
                isPanning = true;
                panStartX = e.clientX;
                panStartY = e.clientY;
                savedPanX = this.jm.view._panX;
                savedPanY = this.jm.view._panY;
                canvas.style.cursor = 'grabbing';
                e.preventDefault();
                e.stopPropagation();
            }
        });

        this._addDocListener('mousemove', (e) => {
            if (!isPanning) return;
            this.jm.view._panX = savedPanX + (e.clientX - panStartX);
            this.jm.view._panY = savedPanY + (e.clientY - panStartY);
            this.jm.view._applyTransform();
        });

        this._addDocListener('mouseup', (e) => {
            if (!isPanning) return;
            isPanning = false;
            canvas.style.cursor = spaceDown ? 'grab' : '';
        });
    }

    // ===== Sidebar =====
    _updateSidebar(nodeId) {
        if (!nodeId) {
            this._closeSidebar();
            return;
        }

        const node = this.jm.get_node(nodeId);
        if (!node) return;

        const data = node.data || {};
        const style = data.style || {};

        const setVal = (sel, val) => { const el = this._el(sel); if (el) el.value = val; };
        setVal('.o_topic_child_structure', data.childStructure || '');
        const shape = data.shape || {};
        setVal('.o_topic_shape_type', shape.type || 'rounded');
        // Border width may live on shape.borderWidth (sidebar) or style['border-width']
        // (format panel) — read back from either so the control reflects reality.
        const bwVal = (shape.borderWidth != null) ? shape.borderWidth : (parseInt(style['border-width']) || '2');
        setVal('.o_topic_border_width', bwVal);
        const branch = data.branchStyle || {};
        setVal('.o_topic_line_type', branch.lineType || 'curved');
        setVal('.o_topic_line_width', branch.lineWidth || '1');
        setVal('.o_topic_numbering', data.numbering || 'none');
        setVal('.o_topic_bg_color', style.background || '#ffffff');
        setVal('.o_topic_text_color', style.color || '#333333');
        setVal('.o_topic_font_size', parseInt(style['font-size']) || 14);
        setVal('.o_topic_font_weight', style['font-weight'] || 'normal');
        setVal('.o_topic_note', data.note || '');
        setVal('.o_topic_labels', (data.labels || []).join(', '));
        setVal('.o_topic_hyperlink', data.hyperlink || '');
        setVal('.o_topic_hyperlink_title', data.hyperlinkTitle || '');

        // Task Info
        const task = data.taskInfo || {};
        setVal('.o_topic_task_start', task.start || '');
        setVal('.o_topic_task_end', task.end || '');
        setVal('.o_topic_task_end_time', task.endTime || '');
        setVal('.o_topic_task_progress', task.progress || 0);
        setVal('.o_topic_task_assignee', task.assignee || '');
        const tpv = this._el('.o_topic_task_progress_val');
        if (tpv) tpv.textContent = (task.progress || 0) + '%';

        const noteCount = this._el('.o_topic_note_count');
        if (noteCount) noteCount.textContent = (data.note || '').length + ' ' + _t('characters');

        this._updateImagePreview(data.image);
        this._updateAttachmentsList(data.attachments || []);
        this._updateMarkersDisplay(data.markers || []);
    }

    _updateImagePreview(imageData) {
        const preview = this._el('.o_topic_image_preview');
        if (!preview) return;
        preview.innerHTML = '';

        if (imageData && imageData.data) {
            const thumbnail = this.imageRenderer.createThumbnail(imageData.data, 120);
            preview.appendChild(thumbnail);
            const info = document.createElement('div');
            info.className = 'mt-1 text-muted small';
            info.textContent = _t('Position: ') + (imageData.options.position || 'above');
            preview.appendChild(info);
            const removeBtn = this._el('.o_topic_remove_image');
            if (removeBtn) removeBtn.style.display = '';
        } else {
            preview.innerHTML = '<span class="text-muted">' + _t('No image attached') + '</span>';
            const removeBtn = this._el('.o_topic_remove_image');
            if (removeBtn) removeBtn.style.display = 'none';
        }
    }

    _updateAttachmentsList(attachments) {
        const list = this._el('.o_topic_attachments');
        if (!list) return;
        list.innerHTML = '';

        if (!attachments || attachments.length === 0) {
            list.innerHTML = '<small class="text-muted">' + _t('No attachments') + '</small>';
            return;
        }

        for (let att of attachments) {
            const item = document.createElement('div');
            item.className = 'd-flex align-items-center mb-1';
            item.innerHTML = '<i class="fa fa-file me-2 text-muted"/><span class="flex-grow-1">' + att.name + '</span><button class="btn btn-sm btn-link text-danger p-0"><i class="fa fa-trash"/></button>';
            list.appendChild(item);
        }
    }

    _updateMarkersDisplay(markerCodes) {
        const container = this._el('.o_topic_markers');
        if (!container) return;
        container.innerHTML = '';

        for (let code of markerCodes) {
            const marker = this.markers.find(m => m.code === code);
            if (marker) {
                const badge = document.createElement('span');
                badge.className = 'badge text-bg-light me-1';
                badge.innerHTML = '<i class="' + marker.icon + '" style="color:' + marker.color + '"></i> ' + marker.name;
                const removeBtn = document.createElement('button');
                removeBtn.className = 'btn btn-link btn-sm p-0 ms-1';
                removeBtn.innerHTML = '<i class="fa fa-times"></i>';
                removeBtn.addEventListener('click', () => this._removeMarker(code));
                badge.appendChild(removeBtn);
                container.appendChild(badge);
            }
        }
    }

    _openSidebar() {
        const sidebar = this.sidebarRef.el;
        if (sidebar) sidebar.classList.add('open');
    }

    _closeSidebar() {
        const sidebar = this.sidebarRef.el;
        if (sidebar) sidebar.classList.remove('open');
    }

    // ===== Toolbar Event Handlers (called from template) =====
    onUndo() {
        if (this.commandStack.canUndo()) {
            const cmd = this.commandStack.undo();
            this._updateStatus(_t('Undone: ') + cmd.getLabel());
        }
    }

    onRedo() {
        if (this.commandStack.canRedo()) {
            const cmd = this.commandStack.redo();
            this._updateStatus(_t('Redone: ') + cmd.getLabel());
        }
    }

    _getDefaultsForDepth(depth) {
        // Match Professional theme (style table)
        if (depth === 0) {
            return {
                shape: { type: 'rounded', borderWidth: 5 },
                style: { background: '#DCE6F2', color: '#376092', 'font-size': '18px', 'font-weight': 'bold' },
            };
        } else if (depth === 1) {
            return {
                shape: { type: 'rounded', borderWidth: 2 },
                style: { background: '#DCE6F2', color: '#17375E', 'font-size': '13px', 'font-weight': 'normal' },
            };
        }
        return {
            shape: { type: 'underline', borderWidth: 3 },
            style: { background: 'transparent', color: '#000000', 'font-size': '10px', 'font-weight': 'normal' },
        };
    }

    onAddChild() {
        const parentNode = this.selectedNode ? this.jm.get_node(this.selectedNode) : this.jm.get_root();
        const parentId = parentNode.id;
        const nodeId = this._generateNodeId();
        const topic = _t('New Topic');

        const childDepth = (parentNode._depth || 0) + 1;
        const defaults = this._getDefaultsForDepth(childDepth);
        const inheritedData = { shape: defaults.shape, style: { ...defaults.style } };

        const cmd = new AddNodeCommand(this.jm, parentId, nodeId, topic, inheritedData);
        this.commandStack.execute(cmd);

        const newNode = this.jm.get_node(nodeId);
        const newElement = this.jm.view.get_node_element(nodeId);
        if (newNode && newElement) {
            if (inheritedData.shape) this._applyShapeToNode(newElement, inheritedData.shape);
        }

        this.jm.select_node(nodeId);
        this._updateStatus(_t('Added child node'));
    }

    onAddSibling() {
        if (!this.selectedNode) return;

        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) return;

        const parentNode = node.parent;
        const parentId = parentNode.id;
        const nodeId = this._generateNodeId();
        const topic = _t('New Topic');

        const siblingDepth = node._depth || 1;
        const defaults = this._getDefaultsForDepth(siblingDepth);
        const inheritedData = { shape: defaults.shape, style: { ...defaults.style } };

        const cmd = new AddNodeCommand(this.jm, parentId, nodeId, topic, inheritedData);
        this.commandStack.execute(cmd);

        const newElement = this.jm.view.get_node_element(nodeId);
        if (newElement) {
            if (inheritedData.shape) this._applyShapeToNode(newElement, inheritedData.shape);
        }

        this.jm.select_node(nodeId);
        this._updateStatus(_t('Added sibling node'));
    }

    onDelete() {
        if (!this.selectedNode) return;

        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) {
            this._showWarning(_t('Cannot delete root node'));
            return;
        }

        // Determine next selection target before deletion:
        // previous sibling → next sibling → parent
        const parent = node.parent;
        const siblings = parent.children || [];
        const idx = siblings.indexOf(node);
        let nextSelectId = null;
        if (idx > 0) {
            nextSelectId = siblings[idx - 1].id;
        } else if (idx < siblings.length - 1) {
            nextSelectId = siblings[idx + 1].id;
        } else {
            nextSelectId = parent.id;
        }

        const cmd = new RemoveNodeCommand(this.jm, this.selectedNode);
        this.commandStack.execute(cmd);

        // Auto-select nearest topic
        if (nextSelectId) {
            const nextNode = this.jm.get_node(nextSelectId);
            if (nextNode) {
                this.jm.select_node(nextSelectId);
                this.selectedNode = nextSelectId;
                this._updateSidebar(nextSelectId);
                this._updateStatus(_t('Deleted node'));
                return;
            }
        }

        this.selectedNode = null;
        this._closeSidebar();
        this._updateStatus(_t('Deleted node'));
    }

    onExpandAll() {
        this.jm.expand_all();
        this._updateStatus(_t('Expanded all nodes'));
    }

    onCollapseAll() {
        this.jm.collapse_all();
        this._updateStatus(_t('Collapsed all nodes'));
    }

    // ===== P1: Insert Before / Insert Parent / Move Up-Down =====
    onAddTopicBefore() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) return;

        const parentId = node.parent.id;
        const nodeId = this._generateNodeId();
        const topic = _t('New Topic');

        const siblingDepth = node._depth || 1;
        const defaults = this._getDefaultsForDepth(siblingDepth);
        const inheritedData = { shape: defaults.shape, style: { ...defaults.style } };

        // Add as child of parent, then move before current node
        const cmd = new AddNodeCommand(this.jm, parentId, nodeId, topic, inheritedData);
        this.commandStack.execute(cmd);

        const newElement = this.jm.view.get_node_element(nodeId);
        if (newElement && inheritedData.shape) {
            this._applyShapeToNode(newElement, inheritedData.shape);
        }

        // Move it before the selected node
        try {
            this.jm.move_node(nodeId, this.selectedNode, parentId);
        } catch (e) { /* render-engine may not support beforeId in all layouts */ }

        this.jm.select_node(nodeId);
        this._updateStatus(_t('Added topic before'));
    }

    onAddParentTopic() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) return;

        const grandParentId = node.parent.id;
        const newParentId = this._generateNodeId();
        const topic = _t('New Topic');

        // New parent takes the same depth as current node (it replaces current's position)
        const newParentDepth = node._depth || 1;
        const defaults = this._getDefaultsForDepth(newParentDepth);
        const inheritedData = { shape: defaults.shape, style: { ...defaults.style } };

        // 1. Create new node as sibling of current
        const cmd = new AddNodeCommand(this.jm, grandParentId, newParentId, topic, inheritedData);
        this.commandStack.execute(cmd);

        const newElement = this.jm.view.get_node_element(newParentId);
        if (newElement && inheritedData.shape) {
            this._applyShapeToNode(newElement, inheritedData.shape);
        }

        // 2. Move current node under new parent
        try {
            this.jm.move_node(this.selectedNode, null, newParentId);
        } catch (e) { /* fallback: just created a sibling */ }

        this.jm.select_node(newParentId);
        this._updateStatus(_t('Added parent topic'));
    }

    onMoveUp() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) return;

        const siblings = node.parent.children;
        const idx = siblings.indexOf(node);
        if (idx <= 0) return;

        const beforeNode = idx >= 2 ? siblings[idx - 2] : null;
        const beforeId = beforeNode ? beforeNode.id : '_first_';
        try {
            this.jm.move_node(this.selectedNode, beforeId === '_first_' ? null : beforeId, node.parent.id);
            this.jm.view.refresh();
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Moved up'));
        } catch (e) {
            // Fallback: swap in children array
            siblings.splice(idx, 1);
            siblings.splice(idx - 1, 0, node);
            this.jm.view.refresh();
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Moved up'));
        }
    }

    onMoveDown() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) return;

        const siblings = node.parent.children;
        const idx = siblings.indexOf(node);
        if (idx >= siblings.length - 1) return;

        const afterNode = siblings[idx + 1];
        try {
            this.jm.move_node(this.selectedNode, afterNode.id, node.parent.id);
            this.jm.view.refresh();
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Moved down'));
        } catch (e) {
            siblings.splice(idx, 1);
            siblings.splice(idx + 1, 0, node);
            this.jm.view.refresh();
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Moved down'));
        }
    }

    // ===== P2: Copy/Paste Topic, Drill Down/Up =====
    onCopyTopic() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;
        this._clipboardTopic = this._serializeNode(node);
        this._updateStatus(_t('Topic copied'));
    }

    onPasteTopic() {
        if (!this._clipboardTopic) {
            this._showWarning(_t('Nothing to paste'));
            return;
        }
        const parentNode = this.selectedNode ? this.jm.get_node(this.selectedNode) : this.jm.get_root();
        this._deserializeNode(this._clipboardTopic, parentNode.id);
        this.jm.view.refresh();
        setTimeout(() => this._renderAllFeatures(), 100);
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Topic pasted'));
    }

    onCutTopic() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) {
            this._showWarning(_t('Cannot cut root node'));
            return;
        }
        this._clipboardTopic = this._serializeNode(node);
        const cmd = new RemoveNodeCommand(this.jm, this.selectedNode);
        this.commandStack.execute(cmd);
        this.selectedNode = null;
        this._closeSidebar();
        this._updateStatus(_t('Topic cut'));
    }

    onDuplicateTopic() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) return;
        const serialized = this._serializeNode(node);
        this._deserializeNode(serialized, node.parent.id);
        this.jm.view.refresh();
        setTimeout(() => this._renderAllFeatures(), 100);
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Topic duplicated'));
    }

    onResetStyle() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;
        // Clear all custom styles
        if (node.data) {
            delete node.data.style;
            delete node.data.shape;
            delete node.data.branchStyle;
        }
        // Re-render with defaults
        const element = this.jm.view.get_node_element(this.selectedNode);
        if (element) {
            element.style.cssText = '';
            element.className = `xmind-node xmind-level-${Math.min(node._depth, 3)}`;
            if (node.isroot) element.classList.add('xmind-root');
        }
        this.jm.view.refresh();
        setTimeout(() => this._renderAllFeatures(), 100);
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Style reset to default'));
    }

    onExpandAllFromNode() {
        if (!this.selectedNode) return;
        const expandAll = (node) => {
            if (!node) return;
            node.expanded = true;
            for (const c of node.children) expandAll(c);
        };
        expandAll(this.jm.get_node(this.selectedNode));
        this.jm.view.refresh();
        this._updateStatus(_t('Expanded all from selected'));
    }

    onCollapseAllFromNode() {
        if (!this.selectedNode) return;
        const collapseAll = (node) => {
            if (!node) return;
            for (const c of node.children) {
                c.expanded = false;
                collapseAll(c);
            }
        };
        collapseAll(this.jm.get_node(this.selectedNode));
        this.jm.view.refresh();
        this._updateStatus(_t('Collapsed all from selected'));
    }

    _serializeNode(node) {
        return {
            topic: node.topic,
            data: JSON.parse(JSON.stringify(node.data || {})),
            expanded: node.expanded,
            children: (node.children || []).map(c => this._serializeNode(c)),
        };
    }

    _deserializeNode(data, parentId) {
        const nodeId = this._generateNodeId();
        const cmd = new AddNodeCommand(this.jm, parentId, nodeId, data.topic, data.data || {});
        this.commandStack.execute(cmd);
        if (!data.expanded) {
            try { this.jm.collapse_node(nodeId); } catch (e) {}
        }
        for (const child of data.children || []) {
            this._deserializeNode(child, nodeId);
        }
    }

    onDrillDown() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.children || node.children.length === 0) return;

        // Save breadcrumb
        this._drillStack = this._drillStack || [];
        this._drillStack.push(this.jm.get_data('node_tree'));

        // Build new data with selected node as root
        const subData = {
            meta: { name: node.topic, author: '', version: '1.0' },
            format: 'node_tree',
            data: this._serializeNodeForJsMind(node),
        };

        this.jm.show(subData, () => this._renderAllFeatures());
        this._updateStatus(_t('Drill down: ') + node.topic);
    }

    onDrillUp() {
        if (!this._drillStack || this._drillStack.length === 0) {
            this._showWarning(_t('Already at top level'));
            return;
        }
        const prevData = this._drillStack.pop();
        this.jm.show(prevData, () => this._renderAllFeatures());
        this._updateStatus(_t('Drill up'));
    }

    _serializeNodeForJsMind(node) {
        return {
            id: node.id,
            topic: node.topic,
            expanded: node.expanded,
            children: (node.children || []).map(c => this._serializeNodeForJsMind(c)),
            data: node.data ? JSON.parse(JSON.stringify(node.data)) : {},
        };
    }

    // ===== P2: Text Alignment =====
    onTextAlignLeft() { this._setTextAlign('left'); }
    onTextAlignCenter() { this._setTextAlign('center'); }
    onTextAlignRight() { this._setTextAlign('right'); }

    _setTextAlign(align) {
        if (!this.selectedNode) return;
        const el = this.jm.view.get_node_element(this.selectedNode);
        if (el) {
            el.style.textAlign = align;
            const node = this.jm.get_node(this.selectedNode);
            if (node) {
                node.data = node.data || {};
                node.data.textAlign = align;
            }
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Text align: ') + align);
        }
    }

    // ===== P4: Overview Thumbnail =====
    onToggleOverview() {
        let overview = this._el('.o_mindmap_overview');
        if (overview) {
            overview.style.display = overview.style.display === 'none' ? 'block' : 'none';
            return;
        }

        // Create overview panel
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        overview = document.createElement('div');
        overview.className = 'o_mindmap_overview';
        overview.style.cssText = 'position:absolute;bottom:40px;right:10px;width:200px;height:150px;background:white;border:1px solid #dee2e6;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,0.15);z-index:100;overflow:hidden;';

        const miniCanvas = document.createElement('div');
        miniCanvas.style.cssText = 'width:100%;height:100%;transform:scale(0.15);transform-origin:top left;pointer-events:none;';

        // Clone the render-engine panel content
        const panel = this.jm.view.e_panel;
        if (panel) {
            const clone = panel.cloneNode(true);
            clone.style.position = 'relative';
            clone.style.left = '0';
            clone.style.top = '0';
            miniCanvas.appendChild(clone);
        }

        overview.appendChild(miniCanvas);

        // Close button
        const closeBtn = document.createElement('button');
        closeBtn.style.cssText = 'position:absolute;top:2px;right:4px;border:none;background:transparent;font-size:12px;cursor:pointer;color:#999;';
        closeBtn.innerHTML = '&times;';
        closeBtn.addEventListener('click', () => { overview.style.display = 'none'; });
        overview.appendChild(closeBtn);

        canvas.appendChild(overview);
    }

    // ===== P4: Outline View =====
    onToggleOutline() {
        let outline = this._el('.o_mindmap_outline');
        if (outline) {
            outline.style.display = outline.style.display === 'none' ? 'block' : 'none';
            return;
        }

        const canvas = this.canvasRef.el;
        if (!canvas) return;

        outline = document.createElement('div');
        outline.className = 'o_mindmap_outline';
        outline.style.cssText = 'position:absolute;top:0;left:0;width:260px;height:100%;background:white;border-right:1px solid #dee2e6;box-shadow:2px 0 12px rgba(0,0,0,0.1);z-index:100;overflow-y:auto;padding:12px;';

        this._renderOutline(outline);
        canvas.appendChild(outline);
    }

    _renderOutline(container) {
        container.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <h6 style="margin:0;">${_t('Outline')}</h6>
            <button class="btn btn-sm btn-link" style="padding:0;">&times;</button>
        </div>`;
        container.querySelector('button').addEventListener('click', () => { container.style.display = 'none'; });

        const root = this.jm.get_root();
        if (!root) return;

        const list = document.createElement('div');
        this._renderOutlineNode(root, list, 0);
        container.appendChild(list);
    }

    _renderOutlineNode(node, container, depth) {
        const item = document.createElement('div');
        item.style.cssText = `padding:3px 4px 3px ${depth * 16 + 4}px;cursor:pointer;border-radius:4px;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;`;

        const hasChildren = node.children && node.children.length > 0;
        const arrow = hasChildren ? (node.expanded ? '▾ ' : '▸ ') : '  ';
        item.textContent = arrow + (node.topic || '');

        item.addEventListener('mouseenter', () => { item.style.background = '#f0f4ff'; });
        item.addEventListener('mouseleave', () => { item.style.background = ''; });
        item.addEventListener('click', () => {
            this.jm.select_node(node.id);
            this.selectedNode = node.id;
        });

        container.appendChild(item);

        if (hasChildren && node.expanded) {
            for (const child of node.children) {
                this._renderOutlineNode(child, container, depth + 1);
            }
        }
    }

    // ===== P4: Resource Manager (Simple Theme/Style Manager) =====
    onManageThemes() {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

        const themes = [
            { id: 'primary', name: 'Primary', color: '#428bca' },
            { id: 'success', name: 'Success', color: '#5cb85c' },
            { id: 'danger', name: 'Danger', color: '#d9534f' },
            { id: 'warning', name: 'Warning', color: '#f0ad4e' },
            { id: 'info', name: 'Info', color: '#5bc0de' },
            { id: 'greensea', name: 'Green Sea', color: '#16a085' },
            { id: 'nephrite', name: 'Nephrite', color: '#27ae60' },
            { id: 'belizehole', name: 'Belize Hole', color: '#2980b9' },
            { id: 'wisteria', name: 'Wisteria', color: '#8e44ad' },
            { id: 'asphalt', name: 'Asphalt', color: '#34495e' },
            { id: 'orange', name: 'Orange', color: '#f39c12' },
            { id: 'pumpkin', name: 'Pumpkin', color: '#d35400' },
            { id: 'pomegranate', name: 'Pomegranate', color: '#c0392b' },
        ];

        const dialog = document.createElement('div');
        dialog.style.cssText = 'background:white;border-radius:12px;padding:24px;max-width:500px;width:90%;box-shadow:0 16px 48px rgba(0,0,0,0.3);';
        dialog.innerHTML = `<h5 style="margin-bottom:16px;">${_t('Theme Manager')}</h5>`;

        const grid = document.createElement('div');
        grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:10px;';

        const currentTheme = this.sheetSettings.theme || 'primary';
        for (const theme of themes) {
            const card = document.createElement('div');
            const isActive = theme.id === currentTheme;
            card.style.cssText = `border:2px solid ${isActive ? '#007bff' : '#dee2e6'};border-radius:8px;padding:10px;text-align:center;cursor:pointer;transition:all 0.2s;`;
            card.innerHTML = `<div style="width:40px;height:40px;border-radius:50%;background:${theme.color};margin:0 auto 6px;"></div><span style="font-size:12px;">${theme.name}</span>`;
            if (isActive) card.innerHTML += `<div style="font-size:10px;color:#007bff;">✓ ${_t('Active')}</div>`;
            card.addEventListener('click', () => {
                this.sheetSettings.theme = theme.id;
                this.jm.set_theme(theme.id);
                this._saveSettings();
                overlay.remove();
                this._updateStatus(_t('Theme changed to: ') + theme.name);
            });
            grid.appendChild(card);
        }

        dialog.appendChild(grid);
        const closeBtn = document.createElement('button');
        closeBtn.className = 'btn btn-secondary btn-sm mt-3';
        closeBtn.textContent = _t('Close');
        closeBtn.addEventListener('click', () => overlay.remove());
        dialog.appendChild(closeBtn);

        overlay.appendChild(dialog);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
        document.body.appendChild(overlay);
    }

    // ===== Sort Topics =====
    onSortAscending() {
        this._sortSelectedChildren((a, b) => (a.topic || '').localeCompare(b.topic || ''));
    }

    onSortDescending() {
        this._sortSelectedChildren((a, b) => (b.topic || '').localeCompare(a.topic || ''));
    }

    onSortByPriority() {
        const priorityOrder = (node) => {
            const markers = (node.data && node.data.markers) || [];
            for (const m of markers) {
                const match = m.match(/priority-(\d+)/);
                if (match) return parseInt(match[1]);
            }
            return 999;
        };
        this._sortSelectedChildren((a, b) => priorityOrder(a) - priorityOrder(b));
    }

    _sortSelectedChildren(compareFn) {
        const parentNode = this.selectedNode
            ? this.jm.get_node(this.selectedNode)
            : this.jm.get_root();
        if (!parentNode || !parentNode.children || parentNode.children.length < 2) {
            this._showWarning(_t('Select a topic with 2+ children to sort'));
            return;
        }

        // Sort in place
        parentNode.children.sort(compareFn);

        // Refresh view
        this.jm.view.refresh();
        setTimeout(() => this._renderAllFeatures(), 100);

        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Children sorted'));
    }

    // ===== Select Siblings / Children =====
    onSelectSiblings() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) return;

        this._clearMultiSelection();
        for (const sibling of node.parent.children) {
            this._addNodeToSelection(sibling);
        }
        this._updateStatus(_t('Selected ') + node.parent.children.length + _t(' siblings'));
    }

    onSelectChildren() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.children || node.children.length === 0) return;

        this._clearMultiSelection();
        for (const child of node.children) {
            this._addNodeToSelection(child);
        }
        this._updateStatus(_t('Selected ') + node.children.length + _t(' children'));
    }

    // ===== Fit Selection =====
    onZoomFitSelection() {
        if (this.selectedNodes.length === 0 && !this.selectedNode) {
            this._showWarning(_t('Select one or more topics first'));
            return;
        }

        const nodesToFit = this.selectedNodes.length > 0
            ? this.selectedNodes
            : [this.jm.get_node(this.selectedNode)];

        const panel = this.jm.view.e_panel;
        if (!panel) return;
        const panelRect = panel.getBoundingClientRect();

        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const node of nodesToFit) {
            const el = this.jm.view.get_node_element(node.id || node);
            if (!el) continue;
            const rect = el.getBoundingClientRect();
            const x = rect.left - panelRect.left;
            const y = rect.top - panelRect.top;
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, x + rect.width);
            maxY = Math.max(maxY, y + rect.height);
        }

        if (minX === Infinity) return;

        const contentW = maxX - minX + 100;
        const contentH = maxY - minY + 100;
        const canvas = this.canvasRef.el;
        if (!canvas) return;
        const containerW = canvas.offsetWidth;
        const containerH = canvas.offsetHeight - 60;

        const scaleX = containerW / contentW;
        const scaleY = containerH / contentH;
        this._zoomLevel = Math.min(scaleX, scaleY, 3);
        this._zoomLevel = Math.max(this._zoomLevel, 0.3);
        this._applyZoom();
        this._updateStatus(_t('Fit selection: ') + Math.round(this._zoomLevel * 100) + '%');
    }

    // ===== Revisions Panel =====
    async onToggleRevisions() {
        let panel = this._el('.o_mindmap_revisions');
        if (panel) {
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
            if (panel.style.display === 'block') await this._refreshRevisions(panel);
            return;
        }

        const canvas = this.canvasRef.el;
        if (!canvas || !this.workbookId) return;

        panel = document.createElement('div');
        panel.className = 'o_mindmap_revisions';
        panel.style.cssText = 'position:absolute;top:0;right:0;width:280px;height:100%;background:white;border-left:1px solid #dee2e6;box-shadow:-2px 0 12px rgba(0,0,0,0.1);z-index:100;overflow-y:auto;padding:12px;';

        panel.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <h6 style="margin:0;"><i class="fa fa-history me-1"></i>${_t('Revisions')}</h6>
            <button class="btn btn-sm btn-link" style="padding:0;">&times;</button>
        </div><div class="o_revision_list"></div>`;
        panel.querySelector('button').addEventListener('click', () => { panel.style.display = 'none'; });

        canvas.appendChild(panel);
        await this._refreshRevisions(panel);
    }

    async _refreshRevisions(panel) {
        const list = panel.querySelector('.o_revision_list');
        if (!list) return;
        list.innerHTML = `<div class="text-center text-muted py-3"><i class="fa fa-spinner fa-spin"></i></div>`;

        try {
            // 帶上目前分頁：快照是單一分頁的樹，混列會讓使用者不知道還原會動到哪張
            const revisions = await rpc('/xmind/workbook/' + this.workbookId + '/revisions', {
                sheet_id: this._currentSheetId || false,
            });
            if (!revisions || revisions.error) {
                list.innerHTML = `<div class="text-muted">${_t('No revisions yet')}</div>`;
                return;
            }

            list.innerHTML = '';
            if (revisions.length === 0) {
                list.innerHTML = `<div class="text-muted small">${_t('No revisions yet. Revisions are created when you save.')}</div>`;
                return;
            }

            for (const rev of revisions) {
                const item = document.createElement('div');
                item.style.cssText = 'padding:8px;border:1px solid #eee;border-radius:6px;margin-bottom:6px;cursor:pointer;transition:all 0.15s;';
                item.innerHTML = `
                    <div style="font-size:12px;font-weight:600;">${rev.name}</div>
                    <div style="font-size:11px;color:#888;">${rev.user} · ${rev.topic_count} topics</div>
                    <div class="mt-1">
                        <button class="btn btn-outline-primary btn-sm py-0 px-2 me-1" style="font-size:11px;" data-action="restore">${_t('Restore')}</button>
                        <button class="btn btn-outline-secondary btn-sm py-0 px-2" style="font-size:11px;" data-action="preview">${_t('Preview')}</button>
                    </div>`;

                item.addEventListener('mouseenter', () => { item.style.borderColor = '#007bff'; item.style.background = '#f8f9ff'; });
                item.addEventListener('mouseleave', () => { item.style.borderColor = '#eee'; item.style.background = ''; });

                item.querySelector('[data-action="restore"]').addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.dialog.add(ConfirmationDialog, {
                        body: _t('Restore this revision? Current changes will be lost.'),
                        confirm: async () => {
                            await rpc('/xmind/workbook/' + this.workbookId + '/revisions/' + rev.id + '/restore', {});
                            // Reload mindmap
                            await this._loadWorkbookData();
                            this.jm.show(this.mindmapData, () => this._renderAllFeatures());
                            this._updateStatus(_t('Revision restored: ') + rev.name);
                        },
                    });
                });

                item.querySelector('[data-action="preview"]').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const result = await rpc('/xmind/workbook/' + this.workbookId + '/revisions/' + rev.id + '/preview', {});
                    if (result && result.data) {
                        // Temporarily show the revision data
                        this.jm.show(result.data, () => this._renderAllFeatures());
                        this._updateStatus(_t('Previewing: ') + rev.name + _t(' (not saved)'));
                    }
                });

                list.appendChild(item);
            }
        } catch (e) {
            list.innerHTML = `<div class="text-danger small">${_t('Error loading revisions')}</div>`;
        }
    }

    onOpenNote() {
        if (!this.selectedNode) {
            this._showWarning(_t('Please select a topic first'));
            return;
        }
        this._openSidebar();
        const noteEl = this._el('.o_topic_note');
        if (noteEl) noteEl.focus();
    }

    onOpenMarker() {
        if (!this.selectedNode) {
            this._showWarning(_t('Please select a topic first'));
            return;
        }
        this._showMarkerDialog();
    }

    onAddRelationship() {
        // Enter relationship mode: step 1 = click source, step 2 = click target
        this.relationshipMode = true;
        this.relationshipSource = null;
        this._relPreviewLine = null;
        this._relPreviewSvg = null;
        const canvas = this.canvasRef.el;
        if (canvas) canvas.style.cursor = 'crosshair';
        this._updateStatus(_t('Click source topic... (Esc/Right-click to cancel)'));
    }

    _exitRelationshipMode() {
        this.relationshipMode = false;
        this.relationshipSource = null;
        // Clean up preview line
        if (this._relPreviewLine && this._relPreviewLine.parentNode) {
            this._relPreviewLine.parentNode.removeChild(this._relPreviewLine);
        }
        if (this._relPreviewSvg && this._relPreviewSvg.parentNode) {
            this._relPreviewSvg.parentNode.removeChild(this._relPreviewSvg);
        }
        this._relPreviewLine = null;
        this._relPreviewSvg = null;
        // Remove target highlights
        const world = this.jm.view.world;
        if (world) {
            world.querySelectorAll('.xmind-node.rel-drop-target').forEach(el => el.classList.remove('rel-drop-target'));
        }
        const canvas = this.canvasRef.el;
        if (canvas) canvas.style.cursor = '';
        this._updateStatus(_t('Ready'));
    }

    _setupRelationshipModeListeners() {
        const world = this.jm.view.world;
        if (!world) return;

        // Create SVG layer for preview line
        const previewSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        previewSvg.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;overflow:visible;pointer-events:none;z-index:20;';
        previewSvg.classList.add('rel-preview-svg');
        world.appendChild(previewSvg);

        // Arrow marker definition for preview
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
        marker.setAttribute('id', 'rel-preview-arrow');
        marker.setAttribute('viewBox', '0 0 10 10');
        marker.setAttribute('refX', '10');
        marker.setAttribute('refY', '5');
        marker.setAttribute('markerWidth', '8');
        marker.setAttribute('markerHeight', '8');
        marker.setAttribute('orient', 'auto');
        const arrowPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        arrowPath.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
        arrowPath.setAttribute('fill', '#77933C');
        marker.appendChild(arrowPath);
        defs.appendChild(marker);
        previewSvg.appendChild(defs);

        // Mouse move → update preview line from source to cursor
        this._addDocListener('mousemove', (e) => {
            if (!this.relationshipMode || !this.relationshipSource || !this._relPreviewLine) return;

            const srcEl = this.jm.get_node(this.relationshipSource)?._el;
            if (!srcEl) return;

            const sx = srcEl.offsetLeft + srcEl.offsetWidth / 2;
            const sy = srcEl.offsetTop + srcEl.offsetHeight / 2;

            const worldRect = world.getBoundingClientRect();
            const zoom = this.jm.view.getZoom ? this.jm.view.getZoom() : 1;
            const mx = (e.clientX - worldRect.left) / zoom;
            const my = (e.clientY - worldRect.top) / zoom;

            // Snap to target node center if hovering over one
            const targetEl = document.elementFromPoint(e.clientX, e.clientY);
            const targetNodeEl = targetEl ? targetEl.closest('.xmind-node') : null;
            let ex = mx, ey = my;

            // Highlight/unhighlight
            world.querySelectorAll('.xmind-node.rel-drop-target').forEach(el => el.classList.remove('rel-drop-target'));
            if (targetNodeEl && targetNodeEl.getAttribute('data-nodeid') !== this.relationshipSource) {
                targetNodeEl.classList.add('rel-drop-target');
                ex = targetNodeEl.offsetLeft + targetNodeEl.offsetWidth / 2;
                ey = targetNodeEl.offsetTop + targetNodeEl.offsetHeight / 2;
            }

            // Bezier preview with arrow
            const ctrl = Math.abs(ex - sx) * 0.33;
            this._relPreviewLine.setAttribute('d',
                `M${sx},${sy} C${sx + ctrl},${sy} ${ex - ctrl},${ey} ${ex},${ey}`);
        });
    }

    onSave() {
        this._updateStatus(_t('Saving...'));
        this._saveData().then((ok) => {
            // _saveData reports failure via return value (it no longer throws);
            // only mark clean / show success when the save actually landed.
            if (ok === false) {
                this._updateStatus(_t('Save failed'));
                return;
            }
            this.commandStack.markSaved();
            this._updateStatus(_t('Saved successfully'));
            // Capture thumbnail in background (non-blocking)
            this._saveThumbnail();
        }).catch((error) => {
            this._showError(_t('Save failed: ') + error);
        });
    }

    // ===== Project integration (mind map → project) =====
    /** Toolbar icon: create the project if none is linked yet, else sync to it. */
    onSyncOrCreateProject() { this._doProjectSync(!this.projectInfo); }

    /** Fill the toolbar breadcrumb record name (imperative — component is non-reactive). */
    _setRecordName(name) {
        this.workbookName = name || '';
        const el = this._el('.o_mindmap_record_name');
        if (el) {
            el.textContent = this.workbookName;
            el.title = this.workbookName;
        }
    }

    /** Breadcrumb gear: open this mind map's form view (customer/project/visibility…). */
    onOpenForm() {
        if (!this.workbookId) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'xmind.workbook',
            res_id: this.workbookId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    /** Breadcrumb text / switcher list button: back to the workbook list view (with
     *  its search panel & filters). viewType forces the list over the action's
     *  default kanban. */
    onOpenList() {
        this.action.doAction('dobtor_xmind.action_xmind_workbook', {
            viewType: 'list',
            clearBreadcrumbs: true,
        });
    }

    /** Pager (child MindmapPager) → open another workbook. This is a heavy imperative
     *  god-component, so instead of an error-prone in-place teardown we re-dispatch
     *  the SAME client action on the new id with stackPosition 'replaceCurrentAction':
     *  onWillUnmount runs (autosave-on-exit if dirty, listeners cleaned up) and the
     *  editor mounts fresh — the cleanest, safest reload. Breadcrumb is replaced, not
     *  stacked. */
    _navigateToRecord(newId) {
        if (!newId || newId === this.workbookId || this.readonly) return;
        this.action.doAction(
            {
                type: 'ir.actions.client',
                tag: 'dobtor_xmind.mindmap_editor',
                params: { workbook_id: newId },
            },
            { stackPosition: 'replaceCurrentAction' },
        );
    }

    async onOpenProject() {
        if (!this.projectInfo || !this.projectInfo.id || !this.workbookId) return;
        // Open the project's Gantt (tasks) view directly, not the project form.
        // Route through the workbook server method so active_id is injected into
        // the action context (the tasks action's domain relies on active_id).
        const action = await this.orm.call(
            'xmind.workbook', 'action_open_project', [[this.workbookId]]
        );
        if (action) {
            this.action.doAction(action);
        }
    }

    /** MindmapProjectBar 子元件掛載時回註冊其 API，供建立/同步專案後刷新。 */
    _registerProjectBarApi(api) {
        this._projectBarApi = api;
    }

    /** 子元件變更專案時回報，讓 projectInfo 保持最新（供同步警示/開啟專案守衛）。 */
    /**
     * 工具列中央搜尋 / 篩選的回呼（子元件 MindmapSearch 呼叫）。
     *
     * 直接操作畫布 DOM 而不重建 jsMind 樹：命中的節點加 .o_mindmap_hit，
     * 容器加 .o_mindmap_searching 讓 CSS 把未命中的淡化。這樣搜尋不會動到
     * 資料、不會觸發存檔，清除條件即完全復原。
     *
     * @param {string} query 主題標題的子字串比對（不分大小寫）
     * @param {string[]} filterKeys 已選的篩選 key（見 MINDMAP_FILTERS）
     * @returns {{hits: number, total: number}} 供搜尋框顯示計數
     */
    _onSearchChange(query, filterKeys) {
        // this.el 就是 .o_mindmap_editor_container 本身（模板的根節點）；
        // 沿用既有的 _el() 慣例處理 this.el 尚未就緒的情況。
        const container = this.el?.classList?.contains('o_mindmap_editor_container')
            ? this.el
            : this.canvasRef.el?.closest('.o_mindmap_editor_container');
        const nodes = (this.jm && this.jm.mind && this.jm.mind.nodes) || {};
        const preds = MINDMAP_FILTERS
            .filter((f) => filterKeys.includes(f.key))
            .map((f) => f.predicate);
        const needle = (query || '').trim().toLowerCase();
        const hasCriteria = Boolean(needle) || preds.length > 0;

        let hits = 0;
        let total = 0;
        for (const id in nodes) {
            const node = nodes[id];
            const el = node._el;
            if (!el) {
                continue;
            }
            total += 1;
            const data = node.data || {};
            // 標題比對 + 所有已選篩選皆須成立（篩選之間是 AND）
            const matchText = !needle
                || String(node.topic || '').toLowerCase().includes(needle);
            const matchFilters = preds.every((fn) => {
                try {
                    return fn(data);
                } catch {
                    return false;
                }
            });
            const hit = hasCriteria && matchText && matchFilters;
            el.classList.toggle('o_mindmap_hit', hit);
            if (hit) {
                hits += 1;
            }
        }
        if (container) {
            container.classList.toggle('o_mindmap_searching', hasCriteria);
        }
        return { hits, total };
    }

    _onProjectBarChanged(info) {
        this.projectInfo = info || null;
    }

    /** 建立/同步專案改動後，請子元件重讀專案/客戶/關聯物件。 */
    _reloadProjectBar() {
        if (this._projectBarApi && this._projectBarApi.reload) {
            this._projectBarApi.reload();
        }
    }

    _doProjectSync(create, confirmed = false) {
        if (!this.workbookId) return;
        // Warn if the last sync was the OTHER direction (this one overwrites it).
        // `confirmed` 是「封存任務」那道確認的旗標（要送到後端），與這裡的方向
        // 警告無關 —— 所以確認之後仍原值傳下去，行為與改寫前一致。
        if (!confirmed && this.projectInfo && this.projectInfo.last_sync_direction === 'to_mindmap') {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Overwrite the project?"),
                body: _t('The last sync was Project → Mind Map. Syncing now overwrites the project with this mind map.'),
                confirmLabel: _t("Overwrite"),
                confirmClass: "btn-danger",
                confirm: () => this._runProjectSync(create, confirmed),
                cancel: () => this._updateStatus(_t('Project sync cancelled.')),
            });
            return;
        }
        this._runProjectSync(create, confirmed);
    }

    /** _doProjectSync 通過確認之後真正執行的部分。 */
    _runProjectSync(create, confirmed) {
        // Save first so the backend syncs from the persisted topic tree.
        this._saveData().then((ok) => {
            if (ok === false) {
                this._showError(_t('Could not save before syncing the project.'));
                return;
            }
            this._updateStatus(create ? _t('Creating project...') : _t('Syncing project...'));
            rpc('/xmind/workbook/' + this.workbookId + '/project_sync', { create, confirmed }).then(async (r) => {
                if (r && r.error) { this._showError(r.error); return; }
                if (r && r.needs_confirm) {
                    // Removed topics → their tasks would be archived. Ask first.
                    // ConfirmationDialog 的 body 是 text-prewrap，換行會保留，
                    // 所以這份條列可以照原樣呈現。
                    const names = (r.archive_names || []).join('\n  • ');
                    const msg = _t('%s task(s) will be archived (their topic was removed):')
                        .replace('%s', r.archive_count) + '\n  • ' + names;
                    this.dialog.add(ConfirmationDialog, {
                        title: _t("Archive tasks?"),
                        body: msg,
                        confirmLabel: _t("Archive and sync"),
                        confirmClass: "btn-danger",
                        confirm: () => this._doProjectSync(create, true),
                        cancel: () => this._updateStatus(_t('Project sync cancelled.')),
                    });
                    return;
                }
                const name = (r && r.project_name) || '';
                this.projectInfo = { id: r.project_id, name, last_sync_direction: 'to_project' };
                this._reloadProjectBar();
                this._updateStatus(_t('Project synced: ') + name);
                if (this.notification) {
                    const detail = _t('Created %s, updated %s, archived %s.')
                        .replace('%s', r.created || 0).replace('%s', r.updated || 0).replace('%s', r.removed || 0);
                    this.notification.add(_t('Project synced: ') + name + ' — ' + detail, { type: 'success' });
                }
                // Refresh the current view so freshly linked tasks (activity
                // clocks, task links) appear without a manual reload.
                await this._loadWorkbookData();
                this.jm.show(this.mindmapData, () => this._renderAllFeatures());
            }).catch(() => this._showError(_t('Project sync failed.')));
        });
    }

    _drawNodesOnCanvas(ctx, nodes, minX, minY, padding, callback) {
        // Simple text rendering of nodes onto canvas
        nodes.forEach(n => {
            const l = (parseInt(n.style.left) || 0) - minX + padding;
            const t = (parseInt(n.style.top) || 0) - minY + padding;
            const w = n.offsetWidth;
            const h = n.offsetHeight;
            const bg = n.style.backgroundColor || '#DCE6F2';
            const color = n.style.color || '#17375E';
            const fontSize = parseInt(n.style.fontSize) || 13;
            const borderRadius = parseInt(n.style.borderRadius) || 5;
            const border = n.style.border || '';

            // Draw background
            ctx.fillStyle = bg;
            ctx.beginPath();
            ctx.roundRect(l, t, w, h, borderRadius);
            ctx.fill();

            // Draw border
            if (border && border !== 'none') {
                const parts = border.split(' ');
                ctx.strokeStyle = parts[2] || '#558ED5';
                ctx.lineWidth = parseInt(parts[0]) || 1;
                ctx.stroke();
            }

            // Draw text
            const textSpan = n.querySelector('.xmind-topic-text');
            if (textSpan) {
                ctx.fillStyle = color;
                ctx.font = `${n.style.fontWeight || 'normal'} ${fontSize}px ${n.style.fontFamily || "'Open Sans', sans-serif"}`;
                ctx.textBaseline = 'middle';
                ctx.fillText(textSpan.textContent, l + 8, t + h / 2);
            }
        });
        if (callback) callback();
    }

    // ===== Feature 8: Export SVG =====
    onExportSVG() {
        if (!this.jm || !this.jm.view) return;
        const panel = this.jm.view.e_panel;
        const world = this.jm.view.world;
        if (!panel || !world) return;

        // Collect all nodes' bounding box
        const nodes = panel.querySelectorAll('.xmind-node');
        if (nodes.length === 0) return;

        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        nodes.forEach(n => {
            const l = parseInt(n.style.left) || 0;
            const t = parseInt(n.style.top) || 0;
            minX = Math.min(minX, l);
            minY = Math.min(minY, t);
            maxX = Math.max(maxX, l + n.offsetWidth);
            maxY = Math.max(maxY, t + n.offsetHeight);
        });

        const pad = 40;
        const w = maxX - minX + pad * 2;
        const h = maxY - minY + pad * 2;
        const offsetX = -minX + pad;
        const offsetY = -minY + pad;

        // Build SVG document
        let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`;
        svg += `<rect width="${w}" height="${h}" fill="#FFFFFF"/>`;
        svg += `<g transform="translate(${offsetX},${offsetY})">`;

        // Copy branch lines from the SVG layer
        const lineSvg = this.jm.view.e_lines;
        if (lineSvg) {
            svg += lineSvg.innerHTML;
        }

        // Render nodes as SVG rectangles + text
        nodes.forEach(n => {
            const x = parseInt(n.style.left) || 0;
            const y = parseInt(n.style.top) || 0;
            const nw = n.offsetWidth;
            const nh = n.offsetHeight;
            const bg = n.style.backgroundColor || '#DCE6F2';
            const color = n.style.color || '#17375E';
            const fs = parseInt(n.style.fontSize) || 13;
            const br = parseInt(n.style.borderRadius) || 5;
            const border = n.style.border || '';
            const bParts = border.split(' ');
            const bWidth = parseInt(bParts[0]) || 1;
            const bColor = bParts[2] || '#558ED5';

            svg += `<rect x="${x}" y="${y}" width="${nw}" height="${nh}" rx="${br}" fill="${bg}" stroke="${bColor}" stroke-width="${bWidth}"/>`;
            const textSpan = n.querySelector('.xmind-topic-text');
            if (textSpan) {
                svg += `<text x="${x + 8}" y="${y + nh / 2 + fs * 0.35}" font-size="${fs}" fill="${color}" font-family="'Open Sans',sans-serif">${this._escapeXml(textSpan.textContent)}</text>`;
            }
        });

        svg += '</g></svg>';

        const blob = new Blob([svg], { type: 'image/svg+xml' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = (this.workbookName || 'mindmap') + '.svg';
        a.click();
        URL.revokeObjectURL(a.href);
        this._updateStatus(_t('SVG exported'));
    }

    _escapeXml(str) {
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ===== Feature 9: Toggle Line Tapering =====
    onToggleTapering() {
        if (!this.jm || !this.jm.view) return;
        this.jm.view._tapered = !this.jm.view._tapered;
        this.jm.view.draw_lines();
        this._updateStatus(this.jm.view._tapered ? _t('Tapered lines ON') : _t('Tapered lines OFF'));
    }

    // ===== Feature 12: Resource Manager =====
    onShowResourceManager() {
        document.querySelectorAll('.o_xmind_resource_manager').forEach(el => el.remove());

        const overlay = document.createElement('div');
        overlay.className = 'o_xmind_resource_manager';
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

        const dialog = document.createElement('div');
        dialog.style.cssText = 'background:white;border-radius:12px;padding:0;width:700px;max-width:90vw;max-height:85vh;overflow:hidden;box-shadow:0 16px 48px rgba(0,0,0,0.3);display:flex;flex-direction:column;';

        // Header
        dialog.innerHTML = `<div style="padding:16px 20px;border-bottom:1px solid #dee2e6;display:flex;justify-content:space-between;align-items:center;">
            <h5 style="margin:0;"><i class="fa fa-th-large"></i> ${_t('Resource Manager')}</h5>
            <button class="btn btn-sm btn-link o_rm_close" style="padding:0;"><i class="fa fa-times"></i></button>
        </div>`;

        // Tab bar + content
        const body = document.createElement('div');
        body.style.cssText = 'display:flex;flex:1;overflow:hidden;';

        const tabs = [
            { id: 'themes', icon: 'fa-paint-brush', label: _t('Themes') },
            { id: 'markers', icon: 'fa-flag', label: _t('Markers') },
            { id: 'styles', icon: 'fa-magic', label: _t('Styles') },
            { id: 'templates', icon: 'fa-file-text-o', label: _t('Templates') },
        ];

        const tabBar = document.createElement('div');
        tabBar.style.cssText = 'width:140px;background:#f8f9fa;border-right:1px solid #dee2e6;padding:10px 0;flex-shrink:0;';

        const content = document.createElement('div');
        content.style.cssText = 'flex:1;overflow-y:auto;padding:16px;';

        for (const tab of tabs) {
            const btn = document.createElement('div');
            btn.className = 'o_rm_tab';
            btn.dataset.tab = tab.id;
            btn.style.cssText = 'padding:8px 16px;cursor:pointer;font-size:13px;';
            btn.innerHTML = `<i class="fa ${tab.icon} me-2"></i>${tab.label}`;
            btn.addEventListener('click', () => {
                tabBar.querySelectorAll('.o_rm_tab').forEach(t => t.style.background = '');
                btn.style.background = '#e9ecef';
                this._renderResourceTab(tab.id, content);
            });
            tabBar.appendChild(btn);
        }

        body.appendChild(tabBar);
        body.appendChild(content);
        dialog.appendChild(body);

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // Activate first tab
        tabBar.querySelector('.o_rm_tab').click();

        dialog.querySelector('.o_rm_close').addEventListener('click', () => overlay.remove());
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    }

    _renderResourceTab(tabId, container) {
        container.innerHTML = '';

        if (tabId === 'themes') {
            const themes = [
                { id: 'primary', name: 'Primary', color: '#428bca' },
                { id: 'success', name: 'Success', color: '#5cb85c' },
                { id: 'danger', name: 'Danger', color: '#d9534f' },
                { id: 'warning', name: 'Warning', color: '#f0ad4e' },
                { id: 'info', name: 'Info', color: '#5bc0de' },
                { id: 'greensea', name: 'Green Sea', color: '#16a085' },
                { id: 'nephrite', name: 'Nephrite', color: '#27ae60' },
                { id: 'belizehole', name: 'Belize Hole', color: '#2980b9' },
                { id: 'wisteria', name: 'Wisteria', color: '#8e44ad' },
                { id: 'asphalt', name: 'Asphalt', color: '#34495e' },
                { id: 'orange', name: 'Orange', color: '#f39c12' },
                { id: 'pumpkin', name: 'Pumpkin', color: '#d35400' },
                { id: 'pomegranate', name: 'Pomegranate', color: '#c0392b' },
            ];
            const grid = document.createElement('div');
            grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:10px;';
            const current = this.sheetSettings.theme || 'primary';
            for (const t of themes) {
                const card = document.createElement('div');
                const active = t.id === current;
                card.style.cssText = `text-align:center;padding:10px;border:2px solid ${active ? '#007bff' : '#dee2e6'};border-radius:8px;cursor:pointer;`;
                card.innerHTML = `<div style="width:36px;height:36px;border-radius:50%;background:${t.color};margin:0 auto 4px;"></div><small>${t.name}</small>${active ? '<br><small style="color:#007bff;">✓</small>' : ''}`;
                card.addEventListener('click', () => {
                    this.sheetSettings.theme = t.id;
                    this.jm.set_theme(t.id);
                    this._saveSettings();
                    this._renderResourceTab('themes', container);
                });
                grid.appendChild(card);
            }
            container.appendChild(grid);
        } else if (tabId === 'markers') {
            // Group markers by category
            const categories = {};
            for (const m of this.markers) {
                if (!categories[m.category]) categories[m.category] = [];
                categories[m.category].push(m);
            }
            for (const [cat, items] of Object.entries(categories)) {
                const section = document.createElement('div');
                section.innerHTML = `<h6 class="text-muted text-uppercase" style="font-size:10px;margin:12px 0 6px;">${cat}</h6>`;
                const grid = document.createElement('div');
                grid.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;';
                for (const m of items) {
                    const badge = document.createElement('span');
                    badge.style.cssText = `width:28px;height:28px;display:inline-flex;align-items:center;justify-content:center;border:1px solid #dee2e6;border-radius:4px;cursor:default;`;
                    badge.innerHTML = `<i class="${m.icon}" style="color:${m.color};" title="${m.name}"></i>`;
                    badge.title = m.name + ' (' + m.code + ')';
                    grid.appendChild(badge);
                }
                section.appendChild(grid);
                container.appendChild(section);
            }
        } else if (tabId === 'styles') {
            container.innerHTML = `<div class="text-center text-muted" style="padding:40px;">
                <i class="fa fa-magic fa-3x" style="color:#ddd;"></i>
                <p class="mt-3">${_t('Custom style presets')}</p>
                <p class="small">${_t('Use Format menu to customize styles per topic. Copy Style / Paste Style to reuse.')}</p>
            </div>`;
        } else if (tabId === 'templates') {
            // _getTemplates() 是同步的 —— 原本寫成 .then() 會對陣列取 .then，
            // 直接 TypeError，「範本」分頁其實從來沒有內容。
            const templates = this._getTemplates();
            const grid = document.createElement('div');
            grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;';
            for (const t of templates) {
                const card = document.createElement('div');
                card.style.cssText = 'border:1px solid #dee2e6;border-radius:8px;padding:12px;cursor:pointer;text-align:center;';
                card.innerHTML = `<i class="fa fa-sitemap" style="font-size:24px;color:#558ED5;"></i><div style="font-size:12px;margin-top:6px;">${t.name}</div><small class="text-muted">${t.category || ''}</small>`;
                card.addEventListener('click', () => {
                    this._applyTemplate(t);
                    document.querySelector('.o_xmind_resource_manager')?.remove();
                });
                grid.appendChild(card);
            }
            container.appendChild(grid);
        }
    }

    // ===== Feature 1: Find & Replace =====
    onFindReplace() {
        // Remove existing dialog
        document.querySelectorAll('.o_xmind_find_dialog').forEach(el => el.remove());

        const overlay = document.createElement('div');
        overlay.className = 'o_xmind_find_dialog';
        overlay.style.cssText = 'position:fixed;top:60px;right:20px;z-index:10001;background:#fff;border:1px solid #dee2e6;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.15);padding:16px;width:320px;';
        overlay.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <h6 style="margin:0;"><i class="fa fa-search"></i> ${_t('Find & Replace')}</h6>
                <button class="btn btn-sm btn-link o_find_close" style="padding:0;"><i class="fa fa-times"></i></button>
            </div>
            <div class="mb-2">
                <input type="text" class="form-control form-control-sm o_find_input" placeholder="${_t('Find...')}" autofocus/>
            </div>
            <div class="mb-2">
                <input type="text" class="form-control form-control-sm o_replace_input" placeholder="${_t('Replace with...')}"/>
            </div>
            <div class="d-flex gap-1 mb-2">
                <button class="btn btn-sm btn-outline-primary o_find_prev flex-fill"><i class="fa fa-arrow-up"></i> ${_t('Prev')}</button>
                <button class="btn btn-sm btn-outline-primary o_find_next flex-fill"><i class="fa fa-arrow-down"></i> ${_t('Next')}</button>
                <button class="btn btn-sm btn-outline-success o_replace_one flex-fill">${_t('Replace')}</button>
                <button class="btn btn-sm btn-success o_replace_all flex-fill">${_t('All')}</button>
            </div>
            <small class="text-muted o_find_status"></small>
        `;
        document.body.appendChild(overlay);

        const findInput = overlay.querySelector('.o_find_input');
        const replaceInput = overlay.querySelector('.o_replace_input');
        const statusEl = overlay.querySelector('.o_find_status');
        let matches = [];
        let currentIdx = -1;

        const doFind = () => {
            const term = findInput.value.trim().toLowerCase();
            matches = [];
            currentIdx = -1;
            // Clear previous highlights
            document.querySelectorAll('.xmind-node.find-highlight').forEach(el => {
                el.classList.remove('find-highlight');
                el.style.outline = '';
            });
            if (!term) { statusEl.textContent = ''; return; }

            const nodes = this.jm.mind.nodes;
            for (const id in nodes) {
                if (nodes[id].topic.toLowerCase().includes(term)) {
                    matches.push(id);
                    const el = this.jm.view.get_node_element(id);
                    if (el) { el.classList.add('find-highlight'); el.style.outline = '2px solid #ffc107'; }
                }
            }
            statusEl.textContent = matches.length + _t(' found');
            if (matches.length > 0) goNext();
        };

        const goNext = () => {
            if (matches.length === 0) return;
            // Remove current highlight
            if (currentIdx >= 0) {
                const prev = this.jm.view.get_node_element(matches[currentIdx]);
                if (prev) prev.style.outline = '2px solid #ffc107';
            }
            currentIdx = (currentIdx + 1) % matches.length;
            const el = this.jm.view.get_node_element(matches[currentIdx]);
            if (el) {
                el.style.outline = '3px solid #dc3545';
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            this.jm.select_node(matches[currentIdx]);
            statusEl.textContent = `${currentIdx + 1} / ${matches.length}`;
        };

        const goPrev = () => {
            if (matches.length === 0) return;
            if (currentIdx >= 0) {
                const prev = this.jm.view.get_node_element(matches[currentIdx]);
                if (prev) prev.style.outline = '2px solid #ffc107';
            }
            currentIdx = (currentIdx - 1 + matches.length) % matches.length;
            const el = this.jm.view.get_node_element(matches[currentIdx]);
            if (el) {
                el.style.outline = '3px solid #dc3545';
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            this.jm.select_node(matches[currentIdx]);
            statusEl.textContent = `${currentIdx + 1} / ${matches.length}`;
        };

        const doReplaceOne = () => {
            if (currentIdx < 0 || !matches[currentIdx]) return;
            const term = findInput.value.trim();
            const replacement = replaceInput.value;
            const node = this.jm.get_node(matches[currentIdx]);
            if (node && term) {
                const newTopic = node.topic.replace(new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'), replacement);
                this.jm.view._updateNodeTopic(node, newTopic);
                this.commandStack.isDirty = true;
                this.commandStack._notifyListeners();
            }
            doFind(); // Re-search
        };

        const doReplaceAll = () => {
            const term = findInput.value.trim();
            const replacement = replaceInput.value;
            if (!term) return;
            const regex = new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
            let count = 0;
            const nodes = this.jm.mind.nodes;
            for (const id in nodes) {
                if (nodes[id].topic.toLowerCase().includes(term.toLowerCase())) {
                    const newTopic = nodes[id].topic.replace(regex, replacement);
                    this.jm.view._updateNodeTopic(nodes[id], newTopic);
                    count++;
                }
            }
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            statusEl.textContent = count + _t(' replaced');
            doFind();
        };

        const closeDialog = () => {
            document.querySelectorAll('.xmind-node.find-highlight').forEach(el => {
                el.classList.remove('find-highlight');
                el.style.outline = '';
            });
            overlay.remove();
        };

        findInput.addEventListener('input', doFind);
        findInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.shiftKey ? goPrev() : goNext(); e.preventDefault(); }
            if (e.key === 'Escape') closeDialog();
        });
        overlay.querySelector('.o_find_next').addEventListener('click', goNext);
        overlay.querySelector('.o_find_prev').addEventListener('click', goPrev);
        overlay.querySelector('.o_replace_one').addEventListener('click', doReplaceOne);
        overlay.querySelector('.o_replace_all').addEventListener('click', doReplaceAll);
        overlay.querySelector('.o_find_close').addEventListener('click', closeDialog);

        findInput.focus();
    }

    // ===== Feature 2: Legend (Marker Index) =====
    onToggleLegend() {
        const existing = document.querySelector('.o_xmind_legend');
        if (existing) { existing.remove(); return; }

        // Collect all markers used in the map
        const usedMarkers = new Map(); // code → { marker, count }
        const nodes = this.jm.mind.nodes;
        for (const id in nodes) {
            const markerCodes = nodes[id].data && nodes[id].data.markers || [];
            for (const code of markerCodes) {
                if (usedMarkers.has(code)) {
                    usedMarkers.get(code).count++;
                } else {
                    const marker = this.markers.find(m => m.code === code);
                    if (marker) usedMarkers.set(code, { marker, count: 1 });
                }
            }
        }

        if (usedMarkers.size === 0) {
            this._showWarning(_t('No markers used in this map'));
            return;
        }

        const legend = document.createElement('div');
        legend.className = 'o_xmind_legend';
        legend.style.cssText = 'position:absolute;bottom:40px;right:20px;z-index:100;background:#fff;border:1px solid #dee2e6;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.1);padding:12px;min-width:160px;max-width:240px;';
        legend.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <strong style="font-size:12px;"><i class="fa fa-list-ul"></i> ${_t('Legend')}</strong>
            <button class="btn btn-sm btn-link" style="padding:0;" onclick="this.closest('.o_xmind_legend').remove()"><i class="fa fa-times"></i></button>
        </div>`;

        // Group by category
        const categories = {};
        for (const [code, { marker, count }] of usedMarkers) {
            const cat = marker.category || 'other';
            if (!categories[cat]) categories[cat] = [];
            categories[cat].push({ marker, count });
        }

        for (const [cat, items] of Object.entries(categories)) {
            const catDiv = document.createElement('div');
            catDiv.style.marginBottom = '6px';
            catDiv.innerHTML = `<small class="text-muted text-uppercase" style="font-size:9px;">${cat}</small>`;
            for (const { marker, count } of items) {
                const row = document.createElement('div');
                row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:2px 0;font-size:11px;';
                row.innerHTML = `<i class="${marker.icon}" style="color:${marker.color};width:14px;text-align:center;"></i>
                    <span style="flex:1;">${marker.name}</span>
                    <span class="badge text-bg-secondary" style="font-size:9px;">${count}</span>`;
                catDiv.appendChild(row);
            }
            legend.appendChild(catDiv);
        }

        const canvas = this.canvasRef.el;
        if (canvas) canvas.appendChild(legend);
    }

    // ===== Feature 3: Numbering (Auto-number) =====
    onToggleNumbering() {
        this._numberingEnabled = !this._numberingEnabled;
        this._applyNumbering();
        this._updateStatus(this._numberingEnabled ? _t('Numbering enabled') : _t('Numbering disabled'));
    }

    _applyNumbering() {
        const nodes = this.jm.mind.nodes;
        for (const id in nodes) {
            const element = this.jm.view.get_node_element(id);
            if (!element) continue;
            // Remove existing number prefix
            const existing = element.querySelector('.xmind-number-prefix');
            if (existing) existing.remove();

            if (!this._numberingEnabled) continue;

            const node = nodes[id];
            if (node.isroot) continue;

            // Calculate number string (e.g., "1.2.3")
            const numStr = this._getNodeNumberString(node);
            if (numStr) {
                const prefix = document.createElement('span');
                prefix.className = 'xmind-number-prefix';
                prefix.style.cssText = 'margin-right:4px;color:#888;font-size:0.85em;';
                prefix.textContent = numStr;
                const textSpan = element.querySelector('.xmind-topic-text');
                const markers = element.querySelector('.xmind-markers');
                if (markers) {
                    markers.parentNode.insertBefore(prefix, markers);
                } else if (textSpan) {
                    element.insertBefore(prefix, textSpan);
                }
            }
        }
    }

    _getNodeNumberString(node) {
        const path = [];
        let current = node;
        while (current && !current.isroot) {
            const parent = current.parent;
            if (!parent) break;
            const idx = parent.children.indexOf(current);
            path.unshift(idx + 1);
            current = parent;
        }
        return path.join('.');
    }

    /**
     * 開一個輸入對話框（取代 `window.prompt`）。
     *
     * 回呼式而非 await 式：`prompt()` 是同步的，原本的呼叫端都寫成
     * 「拿到值就往下做」的形狀；用回呼替換可以一比一對應，不必把每個
     * 呼叫端都改成 async（那會連帶影響它們自己的呼叫者）。
     */
    _promptDialog({ title, fields, confirmLabel, onConfirm }) {
        this.dialog.add(MindmapPromptDialog, {
            title,
            fields,
            confirmLabel,
            onConfirm,
        });
    }

    // ===== Feature 4: Multi-Sheet Tab Bar =====
    onAddSheet() {
        if (!this.workbookId) return;
        this._promptDialog({
            title: _t("New Sheet"),
            fields: [{
                name: 'name',
                label: _t("Sheet name"),
                value: _t('Sheet ') + ((this._sheets || []).length + 1),
            }],
            confirmLabel: _t("Create"),
            onConfirm: ({ name }) => {
                const trimmed = (name || '').trim();
                if (!trimmed) {
                    return false;   // 空白名稱：留在對話框裡讓使用者補
                }
                rpc('/xmind/workbook/' + this.workbookId + '/sheet/create', { name: trimmed })
                    .then(result => {
                        if (result.success) {
                            this._loadSheets();
                            this._updateStatus(_t('Sheet created: ') + trimmed);
                        }
                    })
                    .catch(() => this._showError(_t('Failed to create sheet.')));
            },
        });
    }

    /**
     * 把某張分頁的資料讀進畫布。**不會先存檔** —— 呼叫端自己決定要不要存。
     *
     * 抽出來是因為有兩個呼叫端，而它們對「要不要先存」的答案相反：
     * 切換分頁必須先存（不然當前分頁的編輯會被覆蓋掉），刪除當前分頁則
     * 絕對不能存（那份畫布屬於已經不存在的分頁，存下去會寫進別張）。
     *
     * @returns {Promise<Object|false>} 後端回傳的 payload，失敗時 false
     */
    async _loadSheetIntoCanvas(sheetId) {
        const result = await rpc(
            '/xmind/workbook/' + this.workbookId + '/sheet/' + sheetId + '/data', {}
        );
        if (!result || !result.mindmap_data) {
            return false;
        }
        this._loadFailed = false;   // a good sheet load re-enables saving
        this.mindmapData = result.mindmap_data;
        // 特徵層必須跟著換 —— 不換的話畫布是新分頁的樹、關聯線卻是
        // 上一張的，且下一次存檔會把它們寫進新分頁。
        this._applyFeaturePayload(result);
        if (result.sheet_settings) {
            this.sheetSettings = result.sheet_settings;
        }
        this.jm.show(this.mindmapData, () => this._renderAllFeatures());
        // 分頁列的高亮跟著 sheetState.currentId 走，OWL 自己會重繪，
        // 不再需要手動叫它重畫。
        return result;
    }

    onSwitchSheet(sheetId) {
        if (!this.workbookId || this._currentSheetId === sheetId) return;
        // Save current sheet first; abort the switch if it failed so the
        // current sheet's unsaved edits are not lost by the reload.
        this._saveData().then((ok) => {
            if (ok === false) {
                this._showError(_t('Could not save the current sheet — staying here to avoid losing changes.'));
                return;
            }
            const prevSheetId = this._currentSheetId;
            this._currentSheetId = sheetId;
            this._loadSheetIntoCanvas(sheetId).then((result) => {
                if (result) {
                    this._updateStatus(_t('Switched to sheet: ') + result.name);
                }
            }).catch(() => {
                // Revert so the UI doesn't sit on a sheet whose data never loaded.
                this._currentSheetId = prevSheetId;
                this._showError(_t('Failed to load sheet.'));
            });
        }).catch(() => this._showError(_t('Failed to switch sheet.')));
    }

    onRenameSheet(sheetId) {
        const current = (this._sheets || []).find(sh => sh.id === sheetId);
        this._promptDialog({
            title: _t("Rename Sheet"),
            // 帶入現有名稱：原本的 prompt() 沒有預設值，改名等於重打一次。
            fields: [{ name: 'name', label: _t("Sheet name"), value: (current && current.name) || '' }],
            confirmLabel: _t("Rename"),
            onConfirm: ({ name }) => {
                const trimmed = (name || '').trim();
                if (!trimmed) {
                    return false;
                }
                rpc('/xmind/workbook/' + this.workbookId + '/sheet/' + sheetId + '/rename', { name: trimmed })
                    .then(result => {
                        if (result.success) this._loadSheets();
                    })
                    .catch(() => this._showError(_t('Failed to rename sheet.')));
            },
        });
    }

    onDeleteSheet(sheetId) {
        if (!this._sheets || this._sheets.length <= 1) {
            this._showWarning(_t('Cannot delete the last sheet'));
            return;
        }
        const target = (this._sheets || []).find(sh => sh.id === sheetId);
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete Sheet"),
            body: target
                ? _t('Delete sheet "%s"? Everything on it is removed.', target.name)
                : _t("Delete this sheet? Everything on it is removed."),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: async () => {
                const wasCurrent = this._currentSheetId === sheetId;
                if (wasCurrent) {
                    // 畫布上還是這張（即將消失的）分頁的樹，而 _currentSheetId
                    // 馬上會指向別張 —— 這中間只要自動存檔醒來，就會把被刪分頁
                    // 的內容寫進另一張分頁。_loadFailed 是既有的「畫布與伺服器
                    // 狀態不一致，禁止存檔」旗標，正好用來擋住這個空窗。
                    this._loadFailed = true;
                }
                try {
                    const result = await rpc(
                        '/xmind/workbook/' + this.workbookId + '/sheet/' + sheetId + '/delete', {}
                    );
                    if (!result.success) {
                        this._loadFailed = false;
                        this._showError(result.error || _t('Failed to delete sheet.'));
                        return;
                    }
                    if (wasCurrent) {
                        this._currentSheetId = null;
                    }
                    await this._loadSheets();   // 這裡會把 _currentSheetId 補成第一張
                    if (wasCurrent && this._currentSheetId) {
                        // 換上新的當前分頁；成功載入會把 _loadFailed 解除。
                        await this._loadSheetIntoCanvas(this._currentSheetId);
                    }
                    this._updateStatus(_t('Sheet deleted'));
                } catch {
                    this._loadFailed = false;
                    this._showError(_t('Failed to delete sheet.'));
                }
            },
            cancel: () => {},
        });
    }

    async _loadSheets() {
        if (!this.workbookId) return;
        try {
            const result = await rpc('/xmind/workbook/' + this.workbookId + '/sheets', {});
            this._sheets = result.sheets || [];
            if (!this._currentSheetId && this._sheets.length > 0) {
                this._currentSheetId = this._sheets[0].id;
            }
        } catch (e) {
            this._sheets = [];
        }
    }

    onSidebarClose() {
        this._closeSidebar();
    }

    onLayoutChange(ev) {
        const layout = ev.target.value;
        this.sheetSettings.layout = layout;
        this._saveSettings();
        this._updateStatus(_t('Layout changed to: ') + layout);

        if (this.jm && this.jm.layout && this.jm.view) {
            this.jm.layout.setLayoutMode(layout);
            this.jm.view.refresh();
            // Rebuild all features after layout change, then fit the new layout
            // into view so the user always sees the whole map after switching.
            // Pass reset=true so relationship connectors re-optimise for the new
            // structure instead of staying pinned to the old layout's geometry.
            setTimeout(() => {
                this._updateFeaturePositions(true);
                this.onZoomFit();
            }, 120);
        }
    }

    onThemeChange(ev) {
        const theme = ev.target.value;
        this.sheetSettings.theme = theme;
        this.jm.set_theme(theme);
        this._saveSettings();
        this._updateStatus(_t('Theme changed to: ') + theme);
    }

    onTopicPropertyChange() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        const noteEl = this._el('.o_topic_note');
        const labelsEl = this._el('.o_topic_labels');

        const note = noteEl ? noteEl.value : '';
        const labels = labelsEl ? labelsEl.value.split(',').map(l => l.trim()).filter(l => l) : [];

        node.data = node.data || {};
        node.data.note = note;
        node.data.labels = labels;
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
    }

    onTopicStyleChange() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        const oldStyle = (node.data && node.data.style) ? JSON.parse(JSON.stringify(node.data.style)) : {};
        const bgEl = this._el('.o_topic_bg_color');
        const colorEl = this._el('.o_topic_text_color');
        const sizeEl = this._el('.o_topic_font_size');
        const weightEl = this._el('.o_topic_font_weight');

        const newStyle = {
            background: bgEl ? bgEl.value : '#ffffff',
            color: colorEl ? colorEl.value : '#333333',
            'font-size': (sizeEl ? sizeEl.value : '14') + 'px',
            'font-weight': weightEl ? weightEl.value : 'normal',
        };

        const cmd = new UpdateNodeStyleCommand(this.jm, this.selectedNode, newStyle, oldStyle);
        this.commandStack.execute(cmd);
        this._updateStatus(_t('Updated style'));
    }

    onTopicShapeChange() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        const shapeTypeEl = this._el('.o_topic_shape_type');
        const borderWidthEl = this._el('.o_topic_border_width');

        const shapeType = shapeTypeEl ? shapeTypeEl.value : 'rounded';
        const borderWidth = borderWidthEl ? parseInt(borderWidthEl.value) : 2;

        node.data = node.data || {};
        const currentShape = node.data.shape || {};
        node.data.shape = {
            ...currentShape,
            type: shapeType,
            borderWidth: borderWidth,
        };

        const element = this.jm.view.get_node_element(this.selectedNode);
        if (element) {
            this._applyShapeToNode(element, node.data.shape);
        }

        this.jm.view.refresh();
        setTimeout(() => this._updateFeaturePositions(), 50);
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Shape updated'));
    }

    onTopicChildStructureChange() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        const structureEl = this._el('.o_topic_child_structure');
        const value = structureEl ? structureEl.value : '';

        node.data = node.data || {};
        if (value) {
            node.data.childStructure = value;
        } else {
            delete node.data.childStructure;
        }

        // Re-layout to apply the new child structure
        if (this.jm && this.jm.view) {
            this.jm.view.refresh();
            // reset=true → relationship connectors re-optimise for the new structure
            setTimeout(() => this._updateFeaturePositions(true), 100);
        }
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(value ? _t('Child structure: ') + value : _t('Child structure reset to default'));
    }

    onTopicBranchStyleChange() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        const lineTypeEl = this._el('.o_topic_line_type');
        const lineWidthEl = this._el('.o_topic_line_width');

        const lineType = lineTypeEl ? lineTypeEl.value : 'curved';
        const lineWidth = lineWidthEl ? parseInt(lineWidthEl.value) : 1;

        node.data = node.data || {};
        node.data.branchStyle = {
            ...(node.data.branchStyle || {}),
            lineType: lineType,
            lineWidth: lineWidth,
            // Mark this as a deliberate per-topic choice so the renderer honours it
            // over the layout-mode default — even when the chosen type is 'curved'.
            lineTypeExplicit: true,
        };

        this.jm.view.draw_lines();
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Branch line style updated'));
    }

    onTopicNumberingChange() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        const numberingEl = this._el('.o_topic_numbering');
        const value = numberingEl ? numberingEl.value : 'none';

        node.data = node.data || {};
        if (value && value !== 'none') {
            node.data.numbering = value;
        } else {
            delete node.data.numbering;
        }

        this._applyPerTopicNumbering(node);
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(value !== 'none' ? _t('Numbering: ') + value : _t('Numbering disabled'));
    }

    /**
     * Apply numbering to children of a specific topic based on its numbering setting.
     * Format types: '1' (numeric), 'a'/'A' (alpha), 'i'/'I' (roman), '1.1' (hierarchical)
     */
    _applyPerTopicNumbering(parentNode) {
        if (!parentNode) return;
        const fmt = (parentNode.data && parentNode.data.numbering) || 'none';

        // Clear existing numbering from all children recursively
        const clearNumbering = (node) => {
            const el = this.jm.view.get_node_element(node.id);
            if (el) {
                const existing = el.querySelector('.xmind-number-prefix');
                if (existing) existing.remove();
            }
            for (const c of node.children) clearNumbering(c);
        };
        for (const child of parentNode.children) clearNumbering(child);

        if (fmt === 'none') return;

        // Apply numbering to direct children
        const layoutChildren = parentNode.children.filter(c => !(c.data && c.data._isSummaryNode));
        for (let i = 0; i < layoutChildren.length; i++) {
            const child = layoutChildren[i];
            const el = this.jm.view.get_node_element(child.id);
            if (!el) continue;

            let numStr = '';
            if (fmt === '1') {
                numStr = String(i + 1) + '.';
            } else if (fmt === 'a') {
                numStr = String.fromCharCode(97 + (i % 26)) + '.';
            } else if (fmt === 'A') {
                numStr = String.fromCharCode(65 + (i % 26)) + '.';
            } else if (fmt === 'i') {
                numStr = this._toRoman(i + 1).toLowerCase() + '.';
            } else if (fmt === 'I') {
                numStr = this._toRoman(i + 1) + '.';
            } else if (fmt === '1.1') {
                // Hierarchical: build parent chain number
                numStr = this._getHierarchicalNumber(child) + '.';
            }

            if (numStr) {
                const prefix = document.createElement('span');
                prefix.className = 'xmind-number-prefix';
                prefix.style.cssText = 'margin-right:4px;color:#888;font-size:0.85em;';
                prefix.textContent = numStr;
                const textSpan = el.querySelector('.xmind-topic-text');
                const markers = el.querySelector('.xmind-markers');
                if (markers) {
                    markers.parentNode.insertBefore(prefix, markers);
                } else if (textSpan) {
                    el.insertBefore(prefix, textSpan);
                }
            }

            // Recurse: if this child also has numbering, apply it too
            if (child.data && child.data.numbering && child.data.numbering !== 'none') {
                this._applyPerTopicNumbering(child);
            }
        }
    }

    _toRoman(num) {
        const lookup = [
            ['M', 1000], ['CM', 900], ['D', 500], ['CD', 400],
            ['C', 100], ['XC', 90], ['L', 50], ['XL', 40],
            ['X', 10], ['IX', 9], ['V', 5], ['IV', 4], ['I', 1]
        ];
        let result = '';
        for (const [letter, value] of lookup) {
            while (num >= value) { result += letter; num -= value; }
        }
        return result;
    }

    _getHierarchicalNumber(node) {
        const path = [];
        let current = node;
        while (current && !current.isroot) {
            const parent = current.parent;
            if (!parent) break;
            const siblings = parent.children.filter(c => !(c.data && c.data._isSummaryNode));
            const idx = siblings.indexOf(current);
            path.unshift(idx + 1);
            // Stop if parent doesn't have hierarchical numbering
            if (!parent.data || parent.data.numbering !== '1.1') break;
            current = parent;
        }
        return path.join('.');
    }

    onTopicNoteChange() {
        const noteEl = this._el('.o_topic_note');
        if (noteEl) this._setTopicNote(noteEl.value);
    }

    onTopicNoteInput() {
        const noteEl = this._el('.o_topic_note');
        const countEl = this._el('.o_topic_note_count');
        if (noteEl && countEl) countEl.textContent = noteEl.value.length + ' ' + _t('characters');
    }

    onTopicHyperlinkChange() {
        const urlEl = this._el('.o_topic_hyperlink');
        const titleEl = this._el('.o_topic_hyperlink_title');
        this._setTopicHyperlink(
            urlEl ? urlEl.value.trim() : '',
            titleEl ? titleEl.value.trim() : ''
        );
    }

    /** Task Info — write start/end/progress/assignee into node data. */
    onTopicTaskChange() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        const start = (this._el('.o_topic_task_start') || {}).value || '';
        const end = (this._el('.o_topic_task_end') || {}).value || '';
        const endTime = (this._el('.o_topic_task_end_time') || {}).value || '';
        const progEl = this._el('.o_topic_task_progress');
        const progress = progEl ? (parseInt(progEl.value, 10) || 0) : 0;
        const assigneeEl = this._el('.o_topic_task_assignee');
        const assignee = assigneeEl ? assigneeEl.value.trim() : '';

        const tpv = this._el('.o_topic_task_progress_val');
        if (tpv) tpv.textContent = progress + '%';

        node.data = node.data || {};
        if (start || end || endTime || progress || assignee) {
            node.data.taskInfo = { start, end, endTime, progress, assignee };
        } else {
            delete node.data.taskInfo;
        }

        const nodeElement = this.jm.view.get_node_element(this.selectedNode);
        if (nodeElement) this._renderTaskIndicator(nodeElement, node.data.taskInfo);

        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Task info updated'));
    }

    /** Render a small inline progress badge on a node (re-applied on render).
     *  Only shown when there is real progress (>0). The old "○" no-progress circle
     *  was removed — the assignee is now shown as an avatar next to the clock. */
    _renderTaskIndicator(nodeElement, taskInfo) {
        if (!nodeElement) return;
        let badge = nodeElement.querySelector('.xmind-task-badge');
        const pct = (taskInfo && taskInfo.progress) || 0;
        if (!pct) {
            if (badge) badge.remove();
            return;
        }
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'xmind-task-badge';
            nodeElement.appendChild(badge);
        }
        badge.textContent = pct + '%';
        badge.title = [
            taskInfo.assignee && (_t('Assignee: ') + taskInfo.assignee),
            (taskInfo.start || taskInfo.end) && ((taskInfo.start || '?') + ' → ' + (taskInfo.end || '?')),
        ].filter(Boolean).join('\n');
    }

    /** Render assignee avatar(s) right AFTER the activity clock (before the text),
     *  mirroring how dobtor_project shows task assignees. `assignees` = [{id,name}]. */
    _renderAssignee(nodeElement, assignees) {
        if (!nodeElement) return;
        let wrap = nodeElement.querySelector('.xmind-assignee');
        if (!assignees || !assignees.length) {
            if (wrap) wrap.remove();
            return;
        }
        if (!wrap) {
            wrap = document.createElement('span');
            wrap.className = 'xmind-assignee';
            wrap.style.cssText = 'display:inline-flex;align-items:center;margin-right:5px;';
            // After the clock (if any), before the topic title text.
            const titleEl = nodeElement.querySelector('.xmind-topic-text');
            if (titleEl) nodeElement.insertBefore(wrap, titleEl);
            else nodeElement.insertBefore(wrap, nodeElement.firstChild);
        }
        wrap.innerHTML = '';
        for (const u of assignees.slice(0, 3)) {
            const img = document.createElement('img');
            img.className = 'xmind-assignee-avatar';
            img.src = '/web/image/res.users/' + u.id + '/avatar_128';
            img.title = u.name || '';
            img.alt = u.name || '';
            img.style.cssText =
                'width:18px;height:18px;border-radius:50%;object-fit:cover;' +
                'margin-left:-4px;border:1px solid #fff;vertical-align:middle;';
            wrap.appendChild(img);
        }
        if (wrap.firstChild) wrap.firstChild.style.marginLeft = '0';
    }

    // ===== Activity clock (schedule a mail.activity on the linked task) =====
    /** FA icon classes mirroring the official mail.ActivityButton (state colour +
     *  exception icon / activity type icon / clock). Matches dobtor_project's gantt. */
    getActivityButtonClass(activity) {
        const classes = [];
        switch (activity.state) {
            case 'overdue': classes.push('text-danger'); break;
            case 'today': classes.push('text-warning'); break;
            case 'planned': classes.push('text-success'); break;
        }
        switch (activity.exception_decoration) {
            case 'warning':
                classes.push('text-warning', activity.exception_icon || 'fa-clock-o'); break;
            case 'danger':
                classes.push('text-danger', activity.exception_icon || 'fa-clock-o'); break;
            default:
                if (activity.ids && activity.ids.length) {
                    classes.push(activity.type_icon || 'fa-tasks');
                } else {
                    classes.push('fa-clock-o');
                }
        }
        return classes.join(' ');
    }

    /** Activity clock on task-linked topics: same icon + popover UI as the chatter. */
    _renderActivityClock(element, nodeId, taskId, activity) {
        if (!element) return;
        let clock = element.querySelector('.xmind-activity-clock');
        if (!clock) {
            clock = document.createElement('span');
            clock.className = 'xmind-activity-clock';
            clock.style.cssText = 'cursor:pointer;margin-right:5px;';
            clock.title = _t('Activities');
            clock.addEventListener('click', (e) => {
                e.stopPropagation();
                this._onActivityClick(clock, nodeId, taskId);
            });
            // Place the clock BEFORE the topic title text.
            const titleEl = element.querySelector('.xmind-topic-text');
            if (titleEl) element.insertBefore(clock, titleEl);
            else element.insertBefore(clock, element.firstChild);
        }
        clock._activity = activity || {};
        clock.innerHTML = '<i class="fa fa-fw ' + this.getActivityButtonClass(clock._activity) + '"/>';
    }

    _onActivityClick(clockEl, nodeId, taskId) {
        if (this.activityPopover.isOpen) {
            this.activityPopover.close();
            return;
        }
        const activity = clockEl._activity || {};
        const node = this.jm.get_node(nodeId);
        this.activityPopover.open(clockEl, {
            activityIds: activity.ids || [],
            resId: taskId,
            resModel: 'project.task',
            // Pre-fill the "Schedule Activity" wizard summary with the node's
            // (task's) title. Consumed by activity_popover_summary_patch.js.
            scheduleDefaultSummary: (node && node.topic) || '',
            onActivityChanged: () => {
                this.activityPopover.close();
                this._refreshActivityClock(nodeId, taskId);
            },
        });
    }

    _refreshActivityClock(nodeId, taskId) {
        // Re-read the task's activity decoration fields and repaint the clock icon.
        this.orm.read('project.task', [taskId],
            ['activity_ids', 'activity_state', 'activity_exception_decoration',
             'activity_exception_icon', 'activity_type_icon']).then((recs) => {
            const r = recs && recs[0];
            if (!r) return;
            const activity = {
                ids: r.activity_ids || [],
                state: r.activity_state || '',
                exception_decoration: r.activity_exception_decoration || '',
                exception_icon: r.activity_exception_icon || '',
                type_icon: r.activity_type_icon || '',
            };
            const node = this.jm.get_node(nodeId);
            if (node) { node.data = node.data || {}; node.data.activity = activity; }
            const el = this.jm.view.get_node_element(nodeId);
            if (el) this._renderActivityClock(el, nodeId, taskId, activity);
        }).catch(() => {});
    }

    onOpenHyperlink() {
        const urlEl = this._el('.o_topic_hyperlink');
        if (urlEl && urlEl.value.trim()) {
            window.open(urlEl.value.trim(), '_blank');
        }
    }

    onChangeImage() { this.onAddImage(); }

    onRemoveImage() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        node.data = node.data || {};
        delete node.data.image;

        const nodeElement = this.jm.view.get_node_element(this.selectedNode);
        if (nodeElement) {
            const img = nodeElement.querySelector('.xmind-image');
            if (img) img.remove();
        }

        this._updateImagePreview(null);
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Image removed'));
    }

    // ===== Insert Menu =====
    onInsertImage(ev) {
        ev.preventDefault();
        this.onAddImage();
    }

    onInsertHyperlink(ev) {
        ev.preventDefault();
        if (!this.selectedNode) {
            this._showWarning(_t('Please select a topic first'));
            return;
        }
        const node = this.jm.get_node(this.selectedNode);
        // 一張表單問完網址與標題。原本連彈兩次 prompt()：在第一次按取消，
        // 第二次照樣會跳出來。
        this._promptDialog({
            title: _t("Hyperlink"),
            fields: [
                {
                    name: 'url',
                    label: _t("URL"),
                    value: (node.data && node.data.hyperlink) || '',
                    placeholder: 'https://',
                },
                {
                    name: 'title',
                    label: _t("Title (optional)"),
                    value: (node.data && node.data.hyperlinkTitle) || '',
                },
            ],
            confirmLabel: _t("Apply"),
            onConfirm: ({ url, title }) => {
                // 空網址 = 移除連結（與原本傳空字串給 _setTopicHyperlink 一致）
                this._setTopicHyperlink((url || '').trim(), (title || '').trim());
            },
        });
    }

    onInsertNote(ev) {
        ev.preventDefault();
        if (!this.selectedNode) {
            this._showWarning(_t('Please select a topic first'));
            return;
        }
        this._openSidebar();
        const noteEl = this._el('.o_topic_note');
        if (noteEl) noteEl.focus();
    }

    onInsertComment(ev) {
        if (ev && ev.preventDefault) ev.preventDefault();
        this._showWarning(_t('Comments feature coming soon'));
    }

    onInsertAttachment(ev) {
        ev.preventDefault();
        if (!this.selectedNode) {
            this._showWarning(_t('Please select a topic first'));
            return;
        }
        // Create file input and trigger — allow selecting MULTIPLE files at once.
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.multiple = true;
        fileInput.addEventListener('change', () => {
            const files = fileInput.files ? Array.from(fileInput.files) : [];
            if (!files.length) return;
            for (const f of files) {
                this._addAttachment(f, f.name);
            }
            if (files.length > 1) {
                this._updateStatus(_t('Added %s attachments').replace('%s', files.length));
            }
        });
        fileInput.click();
    }

    // ===== Format Menu =====
    onFormatBold(e) {
        e.preventDefault(); e.stopPropagation();
        this.formatState.bold = !this.formatState.bold;
        e.currentTarget.classList.toggle('active', this.formatState.bold);
    }

    onFormatItalic(e) {
        e.preventDefault(); e.stopPropagation();
        this.formatState.italic = !this.formatState.italic;
        e.currentTarget.classList.toggle('active', this.formatState.italic);
    }

    onFormatUnderline(e) {
        e.preventDefault(); e.stopPropagation();
        this.formatState.underline = !this.formatState.underline;
        e.currentTarget.classList.toggle('active', this.formatState.underline);
    }

    onFormatStrikethrough(e) {
        e.preventDefault(); e.stopPropagation();
        this.formatState.strikethrough = !this.formatState.strikethrough;
        e.currentTarget.classList.toggle('active', this.formatState.strikethrough);
    }

    onFormatHSpaceChange(e) {
        const val = this._el('.o_format_h_space_val');
        if (val) val.textContent = e.target.value + 'px';
    }

    onFormatVSpaceChange(e) {
        const val = this._el('.o_format_v_space_val');
        if (val) val.textContent = e.target.value + 'px';
    }

    onFormatStructureChange(e) {
        this._applyLayoutType(e.target.value);
    }

    onFormatApply(e) {
        e.preventDefault(); e.stopPropagation();
        const styleData = this._collectFormatSettings();

        if (this.selectedNodes.length > 0) {
            for (let nodeId of this.selectedNodes) {
                this._applyStyleToNode(nodeId, styleData);
                this._applyBranchStyles(nodeId, styleData.branch);
            }
            this._updateStatus(_t('Style applied to ') + this.selectedNodes.length + _t(' topics'));
        } else if (this.selectedNode) {
            this._applyStyleToNode(this.selectedNode, styleData);
            this._applyBranchStyles(this.selectedNode, styleData.branch);
            this._updateStatus(_t('Style applied'));
        } else {
            this.notification.add(_t('Please select at least one topic first'), { type: 'warning' });
            return;
        }
        // Shape/style changes may alter node dimensions → re-measure + re-layout + redraw lines
        this.jm.view.refresh();
        setTimeout(() => this._updateFeaturePositions(), 50);
    }

    onFormatApplyAll(e) {
        e.preventDefault(); e.stopPropagation();
        const styleData = this._collectFormatSettings();
        const nodes = this.jm.mind.nodes;
        for (let id in nodes) {
            this._applyStyleToNode(nodes[id], styleData);
        }
        this._applyGlobalBranchStyles(styleData.branch);
        this._applyLayoutSpacing(styleData.layout);
        this._updateStatus(_t('Style applied to all topics'));
    }

    onFormatReset(e) {
        e.preventDefault(); e.stopPropagation();
        this.formatState = { bold: false, italic: false, underline: false, strikethrough: false };
        this._elAll('.o_format_bold, .o_format_italic, .o_format_underline, .o_format_strikethrough').forEach(el => el.classList.remove('active'));
        this._updateStatus(_t('Format settings reset to default'));
    }

    // Multi-select
    onToggleMultiSelect() {
        this.multiSelectMode = !this.multiSelectMode;
        const btn = this._el('.o_mindmap_btn_multiselect');
        if (btn) {
            btn.classList.toggle('active', this.multiSelectMode);
            btn.classList.toggle('btn-primary', this.multiSelectMode);
        }
        this._updateStatus(this.multiSelectMode ? _t('Multi-select mode enabled') : _t('Multi-select mode disabled'));
    }

    // ===== Boundary =====
    onAddBoundary() {
        // If topics already selected, create immediately
        let topicIds = [];
        if (this.selectedNodes.length > 1) {
            topicIds = this.selectedNodes.map(n => n.id || n);
        } else if (this.selectedNode) {
            topicIds = [this.selectedNode];
        }

        if (topicIds.length > 0) {
            this.selectedTopicsForFeature = topicIds;
            this._createBoundaryWithDefaults();
        } else {
            // Enter boundary selection mode: drag to select → auto create
            this._pendingFeatureMode = 'boundary';
            const canvas = this.canvasRef.el;
            if (canvas) canvas.style.cursor = 'crosshair';
            this._updateStatus(_t('Drag to select topics for boundary... (Esc to cancel)'));
        }
    }

    _createBoundaryWithDefaults() {
        const options = {
            shape: 'rounded',
            fillColor: 'rgba(195, 214, 155, 0.2)',
            borderColor: '#77933C',
            borderWidth: 3,
            borderStyle: 'dotted',
            title: '',
        };
        this._createBoundary(options);
    }

    _createBoundary(options) {
        // Collect topic elements including all descendants
        const topicElements = this._collectBoundaryElements(this.selectedTopicsForFeature);

        if (topicElements.length > 0) {
            this.boundaryRenderer.addBoundary(topicElements, options);
            this.boundaries.push({ topicIds: this.selectedTopicsForFeature.slice(), options });
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Boundary created'));
        }

        this.boundarySelectionMode = false;
        this.selectedTopicsForFeature = [];
    }

    // ===== Summary =====
    onAddSummary() {
        let topicIds = [];
        if (this.selectedNodes.length > 1) {
            topicIds = this.selectedNodes.map(n => n.id || n);
        } else if (this.selectedNode) {
            topicIds = [this.selectedNode];
        }

        if (topicIds.length > 0) {
            const node = this.jm.get_node(topicIds[0]);
            if (!node || !node.parent) {
                this._showWarning(_t('Cannot create summary for root node'));
                return;
            }
        } else {
            // Enter summary selection mode: drag to select → auto create
            this._pendingFeatureMode = 'summary';
            const canvas = this.canvasRef.el;
            if (canvas) canvas.style.cursor = 'crosshair';
            this._updateStatus(_t('Drag to select topics for summary... (Esc to cancel)'));
            return;
        }

        const summaryOptions = {
            lineType: 'square',
            lineWidth: 5,
            lineColor: '#C3D69B',
            topicText: _t('Summary'),
            topicFillColor: '#77933C',
            topicTextColor: '#FFFFFF',
            topicFontSize: 10,
            topicShape: 'rounded',
            topicBorderColor: 'transparent',
            topicBorderWidth: 0,
            topicBold: false,
            topicItalic: true,
            branchType: 'curved',
            branchEndMarker: 'none',
            branchWidth: 1,
            branchColor: '#C3D69B',
        };

        this._createSummary(topicIds, summaryOptions);
    }

    _createSummary(topicIds, summaryOptions) {
        const node0 = this.jm.get_node(topicIds[0]);
        if (!node0 || !node0.parent) return;

        // Create summary node IN the render-engine tree (as sibling, with _isSummaryNode flag)
        // This allows Tab/Enter to add child/sibling topics, dblclick to inline edit
        // The layout engine skips it; SummaryRenderer positions it at the bracket endpoint
        const parentId = node0.parent.id;
        const summaryNodeId = this._generateNodeId();

        const nodeData = {
            _isSummaryNode: true,
            style: {
                background: summaryOptions.topicFillColor,
                color: summaryOptions.topicTextColor,
                'font-size': summaryOptions.topicFontSize + 'px',
            },
        };
        if (summaryOptions.topicItalic) nodeData.style['font-style'] = 'italic';

        const cmd = new AddNodeCommand(this.jm, parentId, summaryNodeId, summaryOptions.topicText, nodeData);
        this.commandStack.execute(cmd);

        // Wait for node to be in the tree, then render bracket + position the node
        setTimeout(() => {
            const summaryElement = this.jm.view.get_node_element(summaryNodeId);
            if (summaryElement) {
                summaryElement.classList.add('xmind-summary-node');
                // Apply summary styling
                summaryElement.style.background = summaryOptions.topicFillColor;
                summaryElement.style.color = summaryOptions.topicTextColor;
                summaryElement.style.fontFamily = 'Georgia, serif';
                summaryElement.style.borderRadius = '4px';
                summaryElement.style.boxShadow = '0 1px 4px rgba(0,0,0,0.15)';
            }

            const topicElements = this._collectBoundaryElements(topicIds);
            if (topicElements.length === 0) return;

            const renderedSummaryId = this.summaryRenderer.addSummary(topicElements, summaryElement, {
                lineType: summaryOptions.lineType,
                lineColor: summaryOptions.lineColor,
                lineWidth: summaryOptions.lineWidth,
                summaryTitle: summaryOptions.topicText,
                summaryFill: summaryOptions.topicFillColor,
                summaryColor: summaryOptions.topicTextColor,
                summaryFontSize: summaryOptions.topicFontSize,
                summaryItalic: summaryOptions.topicItalic,
            });

            this.summaries.push({
                id: renderedSummaryId,
                topicIds: topicIds,
                summaryNodeId: summaryNodeId,
                options: summaryOptions,
            });

            // Position the render-engine node at the bracket endpoint
            this._positionSummaryNode(summaryNodeId, topicIds);

            this._updateStatus(_t('Summary created'));
        }, 200);

        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
    }

    // ===== Callout =====
    onAddCallout() {
        if (!this.selectedNode) {
            this._showWarning(_t('Please select a topic to add callout'));
            return;
        }

        const options = {
            title: _t('Note'),
            content: '',
            backgroundColor: '#fffacd',
            borderColor: '#ffd700',
            shape: 'callout',
            offsetX: 80,
            offsetY: -50,
        };

        const parentElement = this.jm.view.get_node_element(this.selectedNode);
        if (parentElement) {
            this.calloutRenderer.addCallout(parentElement, options);
            this.callouts.push({ parentNodeId: this.selectedNode, options });
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Callout added'));
        }
    }

    // ===== Floating Topic =====
    onAddFloatingTopic() {
        this._promptDialog({
            title: _t("Add Floating Topic"),
            fields: [{ name: 'title', label: _t("Topic text"), value: _t('Floating Topic') }],
            confirmLabel: _t("Add"),
            onConfirm: ({ title }) => {
                const trimmed = (title || '').trim();
                if (!trimmed) {
                    return false;
                }
                // Place at center of visible canvas
                const canvas = this.canvasRef.el;
                const x = canvas ? canvas.scrollLeft + canvas.clientWidth / 2 : 200;
                const y = canvas ? canvas.scrollTop + canvas.clientHeight / 2 : 200;
                this._createFloatingTopicAt(trimmed, '', x, y);
            },
        });
    }

    // ===== Image =====
    onAddImage() {
        if (!this.selectedNode) {
            this._showWarning(_t('Please select a topic to add image'));
            return;
        }

        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = 'image/*';
        fileInput.addEventListener('change', () => {
            if (fileInput.files && fileInput.files[0]) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    this._addImageToNode(e.target.result, { position: 'above', width: 100, height: 100 });
                };
                reader.readAsDataURL(fileInput.files[0]);
            }
        });
        fileInput.click();
    }

    _addImageToNode(imageData, options) {
        const nodeElement = this.jm.view.get_node_element(this.selectedNode);
        if (nodeElement) {
            this.imageRenderer.renderImage(nodeElement, imageData, options);
            const node = this.jm.get_node(this.selectedNode);
            node.data = node.data || {};
            node.data.image = { data: imageData, options };
            this._updateImagePreview(node.data.image);
            // Re-layout once the image loads so neighbours/lines never collide.
            this._watchImageLoad(nodeElement);
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Image added to topic'));
        }
    }

    /** Re-layout when a node's image finishes loading (its real height is only
     *  known then). Debounced so many images loading at once trigger one relayout. */
    _watchImageLoad(element) {
        const img = element && element.querySelector('.xmind-image img');
        if (!img) return;
        if (img.complete && img.naturalHeight > 0) {
            this._relayoutForFeatureSizes();
        } else {
            img.addEventListener('load', () => this._relayoutForFeatureSizes(), { once: true });
        }
    }

    /** Re-measure every node and re-layout if any grew (image/marker/badge), so
     *  topic boxes and connection lines auto-space and never overlap. */
    _relayoutForFeatureSizes() {
        clearTimeout(this._featureRelayoutTimer);
        this._featureRelayoutTimer = setTimeout(() => {
            if (!this.jm || !this.jm.view || !this.jm.mind) return;
            const nodes = this.jm.mind.nodes;
            let changed = false;
            for (const id in nodes) {
                const node = nodes[id];
                const el = this.jm.view.get_node_element(id);
                if (el) {
                    const ow = el.offsetWidth, oh = el.offsetHeight;
                    if (ow !== node._w || oh !== node._h) { node._w = ow; node._h = oh; changed = true; }
                }
            }
            if (changed) {
                this.jm.view.refresh();
                this._updateFeaturePositions();
            }
        }, 60);
    }

    // ===== Internal Methods =====
    _editSelectedNode(initialChar) {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        this.jm.begin_edit(this.selectedNode);

        setTimeout(() => {
            const container = this.containerRef.el;
            if (!container) return;
            const editElement = container.querySelector('input.xmind-edit-input');
            if (editElement) {
                const oldTopic = node.topic;
                let cancelled = false;

                // If triggered by typing a character, replace content with that char
                if (initialChar) {
                    editElement.value = initialChar;
                    // Move cursor to end
                    editElement.setSelectionRange(initialChar.length, initialChar.length);
                }

                // Listen for Escape to cancel (render-engine resets value, we flag it)
                editElement.addEventListener('keydown', (e) => {
                    if (e.key === 'Escape') cancelled = true;
                });

                editElement.addEventListener('blur', () => {
                    if (cancelled) return; // Escape pressed — render-engine already restored original text
                    const newTopic = editElement.value;
                    if (newTopic !== oldTopic) {
                        const cmd = new UpdateNodeCommand(this.jm, this.selectedNode, newTopic, oldTopic);
                        this.commandStack.undoStack.push(cmd);
                        this.commandStack.redoStack = [];
                        this.commandStack.isDirty = true;
                        this.commandStack._notifyListeners();
                    }
                }, { once: true });
            }
        }, 100);
    }

    _toggleSelectedExpand() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;
        const cmd = new ToggleExpandCommand(this.jm, this.selectedNode, !node.expanded);
        this.commandStack.execute(cmd);
    }

    _showBranchStylePicker(nodeId) {
        const node = this.jm.get_node(nodeId);
        if (!node) return;
        const current = (node.data && node.data.branchStyle) || {};

        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;';

        const dialog = document.createElement('div');
        dialog.style.cssText = 'background:white;border-radius:12px;padding:20px;width:340px;box-shadow:0 16px 48px rgba(0,0,0,0.3);';
        dialog.innerHTML = `
            <h6 style="margin-bottom:14px;"><i class="fa fa-code-fork"></i> ${_t('Branch Style')}</h6>
            <div class="mb-2">
                <label class="small fw-bold">${_t('Line Type')}</label>
                <div class="d-flex gap-1 flex-wrap o_bs_types"></div>
            </div>
            <div class="row mb-2">
                <div class="col-6">
                    <label class="small fw-bold">${_t('Width')}</label>
                    <input type="range" class="form-range o_bs_width" min="1" max="5" value="${current.lineWidth || 1}"/>
                </div>
                <div class="col-6">
                    <label class="small fw-bold">${_t('Color')}</label>
                    <input type="color" class="form-control form-control-sm o_bs_color" value="${current.lineColor || '#558ED5'}"/>
                </div>
            </div>
            <div class="mb-3">
                <label class="small fw-bold">${_t('Pattern')}</label>
                <div class="d-flex gap-1 o_bs_patterns"></div>
            </div>
            <div class="d-flex gap-2">
                <button class="btn btn-primary btn-sm o_bs_apply">${_t('Apply')}</button>
                <button class="btn btn-outline-secondary btn-sm o_bs_reset">${_t('Reset')}</button>
                <button class="btn btn-secondary btn-sm o_bs_close">${_t('Close')}</button>
            </div>
        `;

        // Line type buttons with visual preview
        const types = [
            { id: 'curved', label: _t('Curve'), icon: '╭╯' },
            { id: 'straight', label: _t('Straight'), icon: '─' },
            { id: 'roundedElbow', label: _t('Rounded'), icon: '╰┐' },
            { id: 'angular', label: _t('Angular'), icon: '└┐' },
            { id: 'none', label: _t('None'), icon: '⋯' },
        ];
        const typesDiv = dialog.querySelector('.o_bs_types');
        let selectedType = current.lineType || 'curved';
        for (const t of types) {
            const btn = document.createElement('button');
            btn.className = `btn btn-sm ${t.id === selectedType ? 'btn-primary' : 'btn-outline-secondary'}`;
            btn.style.cssText = 'min-width:55px;font-size:11px;';
            btn.innerHTML = `<span style="font-size:14px;">${t.icon}</span><br/>${t.label}`;
            btn.addEventListener('click', () => {
                selectedType = t.id;
                typesDiv.querySelectorAll('.btn').forEach(b => { b.className = 'btn btn-sm btn-outline-secondary'; b.style.minWidth = '55px'; b.style.fontSize = '11px'; });
                btn.className = 'btn btn-sm btn-primary';
                btn.style.cssText = 'min-width:55px;font-size:11px;';
            });
            typesDiv.appendChild(btn);
        }

        // Pattern buttons
        const patterns = [
            { id: 'solid', label: '───' },
            { id: 'dashed', label: '- - -' },
            { id: 'dotted', label: '···' },
        ];
        const patternsDiv = dialog.querySelector('.o_bs_patterns');
        let selectedPattern = current.lineStyle || 'solid';
        for (const p of patterns) {
            const btn = document.createElement('button');
            btn.className = `btn btn-sm ${p.id === selectedPattern ? 'btn-primary' : 'btn-outline-secondary'}`;
            btn.style.fontSize = '12px';
            btn.textContent = p.label;
            btn.addEventListener('click', () => {
                selectedPattern = p.id;
                patternsDiv.querySelectorAll('.btn').forEach(b => b.className = 'btn btn-sm btn-outline-secondary');
                btn.className = 'btn btn-sm btn-primary';
            });
            patternsDiv.appendChild(btn);
        }

        // Apply
        dialog.querySelector('.o_bs_apply').addEventListener('click', () => {
            const branchStyle = {
                lineType: selectedType,
                lineWidth: parseInt(dialog.querySelector('.o_bs_width').value),
                lineColor: dialog.querySelector('.o_bs_color').value,
                lineStyle: selectedPattern,
            };
            this._applyBranchStyles(nodeId, branchStyle);
            overlay.remove();
        });

        // Reset
        dialog.querySelector('.o_bs_reset').addEventListener('click', () => {
            if (node.data) delete node.data.branchStyle;
            this.jm.view.draw_lines();
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            overlay.remove();
        });

        dialog.querySelector('.o_bs_close').addEventListener('click', () => overlay.remove());
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
    }

    _showMarkerDialog() {
        // Group markers by category
        const categories = {};
        for (let marker of this.markers) {
            if (!categories[marker.category]) {
                categories[marker.category] = { name: marker.category.charAt(0).toUpperCase() + marker.category.slice(1), markers: [] };
            }
            categories[marker.category].markers.push(marker);
        }

        // Create a simple marker selection popup
        const popup = document.createElement('div');
        popup.style.cssText = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; border-radius: 8px; padding: 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.3); z-index: 10000; max-height: 80vh; overflow-y: auto; min-width: 300px;';
        popup.innerHTML = '<h5>' + _t('Select Marker') + '</h5>';

        for (let cat of Object.values(categories)) {
            const catDiv = document.createElement('div');
            catDiv.className = 'o_marker_category mb-3';
            catDiv.innerHTML = '<h6>' + cat.name + '</h6><div class="o_marker_list d-flex flex-wrap gap-1"></div>';
            const list = catDiv.querySelector('.o_marker_list');

            for (let marker of cat.markers) {
                const btn = document.createElement('button');
                btn.className = 'o_marker_item btn btn-sm';
                btn.innerHTML = '<i class="' + marker.icon + '" style="color:' + marker.color + '"></i>';
                btn.title = marker.name;
                btn.addEventListener('click', () => {
                    this._addMarker(marker.id);
                    popup.remove();
                    overlay.remove();
                });
                list.appendChild(btn);
            }
            popup.appendChild(catDiv);
        }

        const closeBtn = document.createElement('button');
        closeBtn.className = 'btn btn-secondary btn-sm mt-2';
        closeBtn.textContent = _t('Close');
        closeBtn.addEventListener('click', () => { popup.remove(); overlay.remove(); });
        popup.appendChild(closeBtn);

        const overlay = document.createElement('div');
        overlay.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.3); z-index: 9999;';
        overlay.addEventListener('click', () => { popup.remove(); overlay.remove(); });

        document.body.appendChild(overlay);
        document.body.appendChild(popup);
    }

    _addMarker(markerId) {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;
        const marker = this.markers.find(m => m.id === markerId);
        if (!marker) return;

        node.data = node.data || {};
        node.data.markers = node.data.markers || [];
        if (!node.data.markers.includes(marker.code)) {
            node.data.markers.push(marker.code);
            // Update sidebar display
            this._updateMarkersDisplay(node.data.markers);
            // Update inline marker badges on the node
            const element = this.jm.view.get_node_element(this.selectedNode);
            if (element) {
                this.markerBadgeRenderer.renderMarkers(element, node.data.markers, this.markers);
            }
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Added marker: ') + marker.name);
        }
    }

    _removeMarker(code) {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.data || !node.data.markers) return;
        const index = node.data.markers.indexOf(code);
        if (index > -1) {
            node.data.markers.splice(index, 1);
            // Update sidebar display
            this._updateMarkersDisplay(node.data.markers);
            // Update inline marker badges on the node
            const element = this.jm.view.get_node_element(this.selectedNode);
            if (element) {
                this.markerBadgeRenderer.renderMarkers(element, node.data.markers, this.markers);
            }
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Removed marker'));
        }
    }

    _createRelationship(sourceId, targetId) {
        if (sourceId === targetId) {
            this._showWarning(_t('Cannot create relationship to self'));
            return;
        }
        // Show properties dialog for the new relationship
        this._showRelationshipPropertiesDialog(sourceId, targetId, null);
    }

    _showRelationshipPropertiesDialog(sourceId, targetId, existingRelId) {
        const existing = existingRelId ? this.relationships.find(r => r.id === existingRelId) : null;
        const defaults = existing ? existing.options : {
            shapeType: 'curved', lineStyle: 'dashed', lineWidth: 3, lineColor: '#77933C',
            startMarker: 'none', endMarker: 'arrow', markerSize: 'medium',
            label: '', labelFontSize: 10, labelColor: '#595959',
            labelBold: false, labelItalic: true, labelBackground: false,
        };

        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

        const dialog = document.createElement('div');
        dialog.style.cssText = 'background:white;border-radius:12px;padding:24px;max-width:420px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:0 16px 48px rgba(0,0,0,0.3);';
        dialog.innerHTML = `
            <h5 style="margin-bottom:16px;">${existing ? _t('Edit Relationship') : _t('Create Relationship')}</h5>
            <div class="mb-2"><label class="small fw-bold">${_t('Shape Type')}</label>
                <select class="form-select form-select-sm o_dlg_shape">${['curved','straight','angled','roundedElbow','arrowedCurve','zigzag','arc'].map(v => `<option value="${v}" ${defaults.shapeType===v?'selected':''}>${v}</option>`).join('')}</select></div>
            <div class="mb-2"><label class="small fw-bold">${_t('Line Style')}</label>
                <select class="form-select form-select-sm o_dlg_linestyle">${['solid','dashed','dotted','dash-dot'].map(v => `<option value="${v}" ${defaults.lineStyle===v?'selected':''}>${v}</option>`).join('')}</select></div>
            <div class="row mb-2">
                <div class="col-6"><label class="small fw-bold">${_t('Width')}</label>
                    <input type="number" class="form-control form-control-sm o_dlg_width" min="1" max="8" value="${defaults.lineWidth}"/></div>
                <div class="col-6"><label class="small fw-bold">${_t('Color')}</label>
                    <input type="color" class="form-control form-control-sm o_dlg_color" value="${defaults.lineColor}"/></div>
            </div>
            <div class="row mb-2">
                <div class="col-6"><label class="small fw-bold">${_t('Start Marker')}</label>
                    <select class="form-select form-select-sm o_dlg_startmarker">${['none','arrow','arrow-open','diamond','diamond-filled','circle','circle-filled','square'].map(v => `<option value="${v}" ${defaults.startMarker===v?'selected':''}>${v}</option>`).join('')}</select></div>
                <div class="col-6"><label class="small fw-bold">${_t('End Marker')}</label>
                    <select class="form-select form-select-sm o_dlg_endmarker">${['none','arrow','arrow-open','diamond','diamond-filled','circle','circle-filled','square'].map(v => `<option value="${v}" ${defaults.endMarker===v?'selected':''}>${v}</option>`).join('')}</select></div>
            </div>
            <div class="mb-2"><label class="small fw-bold">${_t('Marker Size')}</label>
                <select class="form-select form-select-sm o_dlg_markersize">${['small','medium','large'].map(v => `<option value="${v}" ${defaults.markerSize===v?'selected':''}>${v}</option>`).join('')}</select></div>
            <hr/>
            <div class="mb-2"><label class="small fw-bold">${_t('Label')}</label>
                <input type="text" class="form-control form-control-sm o_dlg_label" value="${defaults.label || ''}" placeholder="${_t('Optional label')}"/></div>
            <div class="row mb-2">
                <div class="col-4"><label class="small fw-bold">${_t('Font Size')}</label>
                    <input type="number" class="form-control form-control-sm o_dlg_labelfontsize" min="8" max="24" value="${defaults.labelFontSize || 12}"/></div>
                <div class="col-4"><label class="small fw-bold">${_t('Color')}</label>
                    <input type="color" class="form-control form-control-sm o_dlg_labelcolor" value="${defaults.labelColor || '#666666'}"/></div>
                <div class="col-4 d-flex align-items-end gap-1">
                    <button class="btn btn-sm ${defaults.labelBold ? 'btn-secondary' : 'btn-outline-secondary'} o_dlg_labelbold"><b>B</b></button>
                    <button class="btn btn-sm ${defaults.labelItalic ? 'btn-secondary' : 'btn-outline-secondary'} o_dlg_labelitalic"><i>I</i></button>
                </div>
            </div>
            <div class="form-check mb-3"><input type="checkbox" class="form-check-input o_dlg_labelbg" ${defaults.labelBackground ? 'checked' : ''}/>
                <label class="form-check-label small">${_t('Label Background')}</label></div>
            <div class="d-flex gap-2">
                <button class="btn btn-primary btn-sm o_dlg_ok">${existing ? _t('Update') : _t('Create')}</button>
                ${existing ? `<button class="btn btn-danger btn-sm o_dlg_delete">${_t('Delete')}</button>` : ''}
                <button class="btn btn-secondary btn-sm o_dlg_cancel">${_t('Cancel')}</button>
            </div>
        `;

        // Toggle bold/italic buttons
        dialog.querySelector('.o_dlg_labelbold').addEventListener('click', function() { this.classList.toggle('btn-secondary'); this.classList.toggle('btn-outline-secondary'); });
        dialog.querySelector('.o_dlg_labelitalic').addEventListener('click', function() { this.classList.toggle('btn-secondary'); this.classList.toggle('btn-outline-secondary'); });

        const readOptions = () => ({
            shapeType: dialog.querySelector('.o_dlg_shape').value,
            lineStyle: dialog.querySelector('.o_dlg_linestyle').value,
            lineWidth: parseInt(dialog.querySelector('.o_dlg_width').value),
            lineColor: dialog.querySelector('.o_dlg_color').value,
            startMarker: dialog.querySelector('.o_dlg_startmarker').value,
            endMarker: dialog.querySelector('.o_dlg_endmarker').value,
            markerSize: dialog.querySelector('.o_dlg_markersize').value,
            label: dialog.querySelector('.o_dlg_label').value,
            labelFontSize: parseInt(dialog.querySelector('.o_dlg_labelfontsize').value),
            labelColor: dialog.querySelector('.o_dlg_labelcolor').value,
            labelBold: dialog.querySelector('.o_dlg_labelbold').classList.contains('btn-secondary'),
            labelItalic: dialog.querySelector('.o_dlg_labelitalic').classList.contains('btn-secondary'),
            labelBackground: dialog.querySelector('.o_dlg_labelbg').checked,
        });

        dialog.querySelector('.o_dlg_ok').addEventListener('click', () => {
            const opts = readOptions();
            if (existing) {
                this.advancedRelationshipManager.updateRelationshipOptions(existingRelId, opts);
                existing.options = opts;
                this.commandStack.isDirty = true;
                this.commandStack._notifyListeners();
                this._updateStatus(_t('Relationship updated'));
            } else {
                this._doCreateRelationship(sourceId, targetId, opts);
            }
            overlay.remove();
        });

        if (existing) {
            dialog.querySelector('.o_dlg_delete').addEventListener('click', () => {
                this.advancedRelationshipManager.removeRelationship(existingRelId);
                const idx = this.relationships.findIndex(r => r.id === existingRelId);
                if (idx > -1) this.relationships.splice(idx, 1);
                this.commandStack.isDirty = true;
                this.commandStack._notifyListeners();
                this._updateStatus(_t('Relationship deleted'));
                overlay.remove();
            });
        }

        dialog.querySelector('.o_dlg_cancel').addEventListener('click', () => overlay.remove());
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
    }

    _doCreateRelationship(sourceId, targetId, options) {
        const sourceElement = this.jm.view.get_node_element(sourceId);
        const targetElement = this.jm.view.get_node_element(targetId);
        if (!sourceElement || !targetElement) return;

        const relId = this.advancedRelationshipManager.addRelationship(sourceElement, targetElement, options);
        if (relId) {
            this.relationships.push({ id: relId, sourceId, targetId, options });
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Relationship created'));
        }
    }

    _setTopicHyperlink(url, title) {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        node.data = node.data || {};
        node.data.hyperlink = url;
        node.data.hyperlinkTitle = title;

        const nodeElement = this.jm.view.get_node_element(this.selectedNode);
        if (nodeElement) {
            if (url) {
                this.hyperlinkIndicator.addIndicator(nodeElement, url, title);
            } else {
                this.hyperlinkIndicator.removeIndicator(nodeElement);
            }
        }

        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(url ? _t('Hyperlink added') : _t('Hyperlink removed'));
    }

    _setTopicNote(note) {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        node.data = node.data || {};
        node.data.note = note;

        const nodeElement = this.jm.view.get_node_element(this.selectedNode);
        if (nodeElement) this.noteIndicator.addIndicator(nodeElement, !!note);

        const noteEl = this._el('.o_topic_note');
        if (noteEl) noteEl.value = note;
        const countEl = this._el('.o_topic_note_count');
        if (countEl) countEl.textContent = note.length + ' ' + _t('characters');

        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Note updated'));
    }

    _addAttachment(file, displayName) {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            node.data = node.data || {};
            node.data.attachments = node.data.attachments || [];
            node.data.attachments.push({ name: displayName || file.name, type: file.type, size: file.size, data: e.target.result });

            const nodeElement = this.jm.view.get_node_element(this.selectedNode);
            if (nodeElement) this.attachmentIndicator.addIndicator(nodeElement, node.data.attachments.length);
            this._updateAttachmentsList(node.data.attachments);
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Attachment added: ') + file.name);
        };
        reader.readAsDataURL(file);
    }

    async _saveData(isAuto = false) {
        if (!this.workbookId) return;
        // Never overwrite the server copy with default data after a failed load.
        if (this._loadFailed) {
            console.warn('[MindmapEditor] Save blocked: initial load failed.');
            return false;
        }

        // Build the full payload: tree + every feature layer in ONE request so
        // the backend writes them in a single transaction. This removes the
        // previous cross-RPC race (a relationship could end up pointing at a
        // component_id whose topic save had not landed yet) and lets the
        // revision snapshot capture the complete state (incl. features).
        const data = this.jm.get_data('node_tree');

        this._syncRelationshipControlPoints();
        data.relationships = this.relationships.map(r => ({
            source_id: r.sourceId,
            target_id: r.targetId,
            options: r.options || {},
            controlPoints: r.controlPoints || [],
        }));

        data.boundaries = this.boundaries.map(b => ({
            topicIds: b.topicIds || [],
            options: b.options || {},
        }));

        data.summaries = this.summaries.map(s => ({
            topicIds: s.topicIds || [],
            summaryNodeId: s.summaryNodeId || '',
            options: s.options || {},
        }));

        data.callouts = this.callouts.map(c => ({
            parentNodeId: c.parentNodeId || '',
            options: c.options || {},
        }));

        // Floating topics — sync positions from render-engine node data.
        // 先對帳：刪除／剪下／復原新增都會把節點從畫布拿掉卻不動這個陣列，
        // 不清掉的話會把已刪除的浮動主題以空白標題寫回去。
        this._pruneFloatingTopics();
        data.floating_topics = this.floatingTopics.map(ft => {
            const node = this.jm.get_node(ft.id);
            const nd = (node && node.data) || {};
            return {
                component_id: ft.component_id || ft.id,
                title: node ? node.topic : (ft.title || ''),
                note: nd.note || ft.note || '',
                x: Math.round(nd._ftX != null ? nd._ftX : ft.x),
                y: Math.round(nd._ftY != null ? nd._ftY : ft.y),
                style: nd.style || ft.style || {},
            };
        });

        try {
            // 一定要帶上目前顯示的 sheet：後端沒有這個值時只能寫第一張，
            // 於是切換分頁前的這次存檔會用當下畫面覆蓋掉第一張的內容。
            const result = await rpc('/xmind/workbook/' + this.workbookId + '/save', {
                data,
                is_auto: isAuto,
                sheet_id: this._currentSheetId || false,
            });
            if (result && result.error) {
                this._showError(result.error);
                return false;
            }
            return true;
        } catch (e) {
            this._showError(_t('Save failed — your changes may not be stored. Please retry.'));
            console.error('[xmind] save failed', e);
            return false;
        }
    }

    async _saveSettings() {
        if (!this.workbookId) return;
        await rpc('/xmind/workbook/' + this.workbookId + '/settings', { settings: this.sheetSettings });
    }

    /** Capture a thumbnail of the current mind map and save to backend */
    _saveThumbnail() {
        if (!this.workbookId || !this.jm || !this.jm.view) return;
        const panel = this.jm.view.e_panel;
        if (!panel) return;

        const nodes = panel.querySelectorAll('.xmind-node');
        if (nodes.length === 0) return;

        // Compute bounding box of all visible nodes
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        nodes.forEach(n => {
            if (n.style.display === 'none') return;
            const l = parseInt(n.style.left) || 0;
            const t = parseInt(n.style.top) || 0;
            minX = Math.min(minX, l);
            minY = Math.min(minY, t);
            maxX = Math.max(maxX, l + n.offsetWidth);
            maxY = Math.max(maxY, t + n.offsetHeight);
        });
        if (minX === Infinity) return;

        const pad = 20;
        const fullW = maxX - minX + pad * 2;
        const fullH = maxY - minY + pad * 2;

        // Thumbnail target: max 400px wide, proportional height
        const thumbMaxW = 400;
        const scale = Math.min(1, thumbMaxW / fullW);
        const thumbW = Math.round(fullW * scale);
        const thumbH = Math.round(fullH * scale);

        const canvas = document.createElement('canvas');
        canvas.width = thumbW;
        canvas.height = thumbH;
        const ctx = canvas.getContext('2d');
        ctx.scale(scale, scale);
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, fullW, fullH);

        // Draw SVG lines first
        const svgEl = this.jm.view.e_lines;
        const drawNodes = () => {
            this._drawNodesOnCanvas(ctx, nodes, minX, minY, pad, () => {
                const dataUrl = canvas.toDataURL('image/png');
                // Send to backend (fire and forget)
                rpc('/xmind/workbook/' + this.workbookId + '/thumbnail', {
                    thumbnail: dataUrl
                }).catch(() => {}); // silent fail
            });
        };

        if (svgEl) {
            try {
                const svgData = new XMLSerializer().serializeToString(svgEl);
                const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
                const url = URL.createObjectURL(svgBlob);
                const img = new Image();
                img.onload = () => {
                    ctx.drawImage(img, -minX + pad, -minY + pad, panel.scrollWidth, panel.scrollHeight);
                    URL.revokeObjectURL(url);
                    drawNodes();
                };
                img.onerror = () => {
                    URL.revokeObjectURL(url);
                    drawNodes();
                };
                img.src = url;
            } catch (e) {
                drawNodes();
            }
        } else {
            drawNodes();
        }
    }

    _generateNodeId() {
        return 'node_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    _updateStatus(message) {
        const el = this._el('.o_mindmap_status_text');
        if (el) el.textContent = message;
        // Keep the status-bar counts fresh on every status change (cheap).
        this._updateStatusCounts();
    }

    /** Refresh the topic + selection counters shown in the status bar. */
    _updateStatusCounts() {
        const topicEl = this._el('.o_mindmap_topic_count');
        if (topicEl && this.jm && this.jm.mind && this.jm.mind.nodes) {
            // Exclude internal summary nodes from the visible topic tally.
            let n = 0;
            for (const id in this.jm.mind.nodes) {
                const nd = this.jm.mind.nodes[id];
                if (nd && nd.data && nd.data._isSummaryNode) continue;
                n++;
            }
            topicEl.textContent = n + ' 個主題';
        }
        const selEl = this._el('.o_mindmap_selection_count');
        if (selEl) {
            const selCount = (this.selectedNodes && this.selectedNodes.length)
                || (this.selectedNode ? 1 : 0);
            selEl.textContent = selCount > 1 ? ('  ·  已選 ' + selCount + ' 個') : '';
        }
    }

    /** Status-bar zoom slider → set absolute zoom level. */
    onZoomSlider(ev) {
        if (!this.jm) return;
        const pct = parseInt(ev.target.value, 10) || 100;
        this._zoomLevel = Math.min(Math.max(pct / 100, 0.3), 3);
        this._applyZoom();
    }

    _showWarning(message) {
        this.notification.add(message, { type: 'warning' });
    }

    _showError(message) {
        this.notification.add(message, { type: 'danger' });
    }

    // ===== Shape & Style Application =====
    _applyShapeToNode(element, shapeData) {
        if (!element || !shapeData) return;

        element.style.borderRadius = '';
        element.style.clipPath = '';
        element.style.border = '';
        element.style.backgroundColor = '';
        element.style.boxShadow = '';
        element.style.aspectRatio = '';
        element.style.outline = '';
        element.style.outlineOffset = '';
        // circle / stroke 會把節點改成 flex 置中；不一併重置的話，從那兩種形狀
        // 切換到別的形狀時置中會殘留（文字位置與其他同形狀節點對不上）。
        element.style.display = '';
        element.style.alignItems = '';
        element.style.justifyContent = '';
        element.classList.remove('shape-rectangle', 'shape-rounded', 'shape-ellipse', 'shape-circle',
            'shape-diamond', 'shape-parallelogram', 'shape-hexagon', 'shape-cloud',
            'shape-underline', 'shape-stroke',
            // noBorder / fishhead 也要在這裡列出來 —— 它們同樣有專屬的選取外框
            // 樣式（CSS 把 fishhead 與 diamond/hexagon 歸為同一組），漏列的話
            // 切換形狀後舊 class 會殘留。
            'shape-noBorder', 'shape-fishhead_left', 'shape-fishhead_right');

        switch (shapeData.type) {
            case 'rectangle':
                element.style.borderRadius = '0';
                element.classList.add('shape-rectangle');
                break;
            case 'rounded':
                element.style.borderRadius = '8px';
                element.classList.add('shape-rounded');
                break;
            case 'ellipse':
                element.style.borderRadius = '50%';
                element.classList.add('shape-ellipse');
                break;
            case 'circle':
                // circle: perfect circle that fits content (aspect-ratio 1:1)
                element.style.borderRadius = '50%';
                element.style.aspectRatio = '1';
                element.style.display = 'flex';
                element.style.alignItems = 'center';
                element.style.justifyContent = 'center';
                element.classList.add('shape-circle');
                break;
            case 'diamond':
                element.style.clipPath = 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)';
                element.classList.add('shape-diamond');
                break;
            case 'parallelogram':
                element.style.clipPath = 'polygon(10% 0%, 100% 0%, 90% 100%, 0% 100%)';
                element.classList.add('shape-parallelogram');
                break;
            case 'hexagon':
                element.style.clipPath = 'polygon(25% 0%, 75% 0%, 100% 50%, 75% 100%, 25% 100%, 0% 50%)';
                element.classList.add('shape-hexagon');
                break;
            case 'cloud':
                element.style.borderRadius = '50% 20% 50% 20% / 20% 50% 20% 50%';
                element.classList.add('shape-cloud');
                break;
            case 'underline':
                element.style.backgroundColor = 'transparent';
                element.style.border = 'none';
                element.style.borderBottom = `${shapeData.borderWidth || 2}px solid ${shapeData.borderColor || '#558ED5'}`;
                element.style.boxShadow = 'none';
                element.classList.add('shape-underline');
                return;
            case 'noBorder':
                element.style.backgroundColor = 'transparent';
                element.style.border = 'none';
                element.style.boxShadow = 'none';
                element.style.borderRadius = '0';
                element.classList.add('shape-noBorder');
                return;
            case 'stroke':
                // double-ring circle: double-ring circle (inner border + outer outline)
                element.style.borderRadius = '50%';
                element.style.aspectRatio = '1';
                element.style.display = 'flex';
                element.style.alignItems = 'center';
                element.style.justifyContent = 'center';
                element.classList.add('shape-stroke');
                break;
            case 'fishhead_left':
                element.classList.add('shape-fishhead_left');
                element.style.clipPath = 'polygon(15% 0%, 100% 0%, 100% 100%, 15% 100%, 0% 50%)';
                element.style.borderRadius = '0';
                break;
            case 'fishhead_right':
                element.classList.add('shape-fishhead_right');
                element.style.clipPath = 'polygon(0% 0%, 85% 0%, 100% 50%, 85% 100%, 0% 100%)';
                element.style.borderRadius = '0';
                break;
        }

        if (shapeData.fillColor) element.style.backgroundColor = shapeData.fillColor;
        const bw = shapeData.borderWidth || 2;
        const bc = shapeData.borderColor || '#558ED5';
        if (shapeData.borderColor || shapeData.borderWidth) {
            element.style.border = `${bw}px solid ${bc}`;
        }
        // Stroke shape: add outer ring via outline
        if (shapeData.type === 'stroke') {
            const outlineColor = shapeData.borderColor || '#558ED5';
            element.style.outline = `3px solid ${outlineColor}`;
            element.style.outlineOffset = '3px';
        }
    }

    _restoreNodeStyle(element, styleData) {
        if (!element || !styleData) return;
        if (styleData.fontFamily && styleData.fontFamily !== 'inherit') element.style.fontFamily = styleData.fontFamily;
        if (styleData.fontSize) element.style.fontSize = styleData.fontSize + 'px';
        if (styleData.color) element.style.color = styleData.color;
        if (styleData.bgColor && styleData.bgColor !== '#ffffff') element.style.backgroundColor = styleData.bgColor;
        if (styleData.bold !== undefined) element.style.fontWeight = styleData.bold ? 'bold' : 'normal';
        if (styleData.italic !== undefined) element.style.fontStyle = styleData.italic ? 'italic' : 'normal';
        let textDecoration = [];
        if (styleData.underline) textDecoration.push('underline');
        if (styleData.strikethrough) textDecoration.push('line-through');
        element.style.textDecoration = textDecoration.length > 0 ? textDecoration.join(' ') : 'none';
    }

    _applyStyleToNode(node, styleData) {
        const element = this.jm.view.get_node_element(node.id || node);
        if (!element) return;

        if (styleData.shape) {
            this._applyShapeToNode(element, styleData.shape);
            const n = typeof node === 'string' ? this.jm.get_node(node) : node;
            if (n) { if (!n.data) n.data = {}; n.data.shape = styleData.shape; }
        }

        const textStyle = styleData.text;
        if (textStyle.fontFamily && textStyle.fontFamily !== 'inherit') element.style.fontFamily = textStyle.fontFamily;
        if (textStyle.fontSize) element.style.fontSize = textStyle.fontSize + 'px';
        if (textStyle.color) element.style.color = textStyle.color;
        if (textStyle.bgColor && textStyle.bgColor !== '#ffffff' && !styleData.shape) element.style.backgroundColor = textStyle.bgColor;

        element.style.fontWeight = textStyle.bold ? 'bold' : 'normal';
        element.style.fontStyle = textStyle.italic ? 'italic' : 'normal';
        let textDecoration = [];
        if (textStyle.underline) textDecoration.push('underline');
        if (textStyle.strikethrough) textDecoration.push('line-through');
        element.style.textDecoration = textDecoration.length > 0 ? textDecoration.join(' ') : 'none';

        const n = typeof node === 'string' ? this.jm.get_node(node) : node;
        if (n) { if (!n.data) n.data = {}; n.data.style = textStyle; }
    }

    _applyBranchStyles(nodeId, branchStyle) {
        // Save branch style to node data for persistence and per-node line drawing
        const node = typeof nodeId === 'string' ? this.jm.get_node(nodeId) : nodeId;
        if (!node) return;
        if (!node.data) node.data = {};
        node.data.branchStyle = { ...branchStyle };

        // Redraw lines to pick up per-node overrides
        this.jm.view.draw_lines();
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
    }

    _applyGlobalBranchStyles(branchStyle) {
        this.branchStyleSettings = branchStyle;

        // Apply to all non-root nodes
        const nodes = this.jm.mind.nodes;
        for (let id in nodes) {
            const node = nodes[id];
            if (!node.isroot) {
                if (!node.data) node.data = {};
                node.data.branchStyle = { ...branchStyle };
            }
        }

        // Redraw lines to pick up overrides
        this.jm.view.draw_lines();
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
    }

    _applyLayoutSpacing(layoutSettings) {
        if (this.jm && this.jm.view) {
            // Update layout engine gaps directly
            this.jm.view.layout.hgap = layoutSettings.hSpace;
            this.jm.view.layout.vgap = layoutSettings.vSpace;
            this.jm.view.relayout();
            setTimeout(() => {
                this._renderAllFeatures();
            }, 100);
        }
    }

    _applyLayoutType(layoutType) {
        if (this.jm && this.jm.layout && this.jm.view) {
            this.jm.layout.setLayoutMode(layoutType);
            this.jm.view.refresh();
            setTimeout(() => {
                this._renderAllFeatures();
                // reset=true → relationship connectors re-optimise for new layout
                this._updateFeaturePositions(true);
            }, 100);
            this._updateStatus(_t('Layout changed to: ') + layoutType);
        }
    }

    _collectFormatSettings() {
        // Search in component root first, then globally (Bootstrap may move dropdown to body)
        const getVal = (sel, def) => {
            let el = this._el(sel);
            if (!el) el = document.querySelector(sel);
            return el ? el.value : def;
        };
        return {
            shape: {
                type: getVal('.o_format_shape_type', 'rounded'),
                fillColor: getVal('.o_format_fill_color', '#DCE6F2'),
                borderColor: getVal('.o_format_border_color', '#558ED5'),
                borderWidth: parseInt(getVal('.o_format_border_width', '2'))
            },
            text: {
                fontFamily: getVal('.o_format_font_family', "'Open Sans', sans-serif"),
                fontSize: getVal('.o_format_font_size', '13'),
                color: getVal('.o_format_text_color', '#17375E'),
                bgColor: getVal('.o_format_bg_color', '#DCE6F2'),
                bold: this.formatState.bold,
                italic: this.formatState.italic,
                underline: this.formatState.underline,
                strikethrough: this.formatState.strikethrough
            },
            layout: {
                type: getVal('.o_format_structure_type', 'map'),
                hSpace: parseInt(getVal('.o_format_h_space', '80')),
                vSpace: parseInt(getVal('.o_format_v_space', '25'))
            },
            branch: {
                lineType: getVal('.o_format_line_type', 'curved'),
                lineWidth: parseInt(getVal('.o_format_line_width', '2')),
                lineColor: getVal('.o_format_line_color', '#558ED5'),
                lineStyle: getVal('.o_format_line_style', 'solid')
            }
        };
    }

    // ===== Multi-Selection =====
    _selectNodesInRect(selRect) {
        const nodes = this.jm.mind.nodes;
        for (let id in nodes) {
            const element = this.jm.view.get_node_element(id);
            if (!element) continue;
            const nodeRect = element.getBoundingClientRect();
            if (this._rectsIntersect(selRect, nodeRect)) {
                this._addNodeToSelection(nodes[id]);
            }
        }
        this._updateSelectionCount();
    }

    _rectsIntersect(rect1, rect2) {
        return !(rect2.left > rect1.right || rect2.right < rect1.left || rect2.top > rect1.bottom || rect2.bottom < rect1.top);
    }

    _toggleNodeSelection(node) {
        const index = this.selectedNodes.findIndex(n => n.id === node.id);
        if (index > -1) {
            this.selectedNodes.splice(index, 1);
            this._highlightNode(node, false);
        } else {
            this._addNodeToSelection(node);
        }
        this._updateSelectionCount();
    }

    _selectSiblingRange(fromId, toId) {
        // Fix #2: Shift+Click — select all siblings between fromId and toId
        const fromNode = this.jm.get_node(fromId);
        const toNode = this.jm.get_node(toId);
        if (!fromNode || !toNode) return;
        // Must share same parent
        if (!fromNode.parent || !toNode.parent || fromNode.parent.id !== toNode.parent.id) {
            // Different parents — just toggle target
            this._toggleNodeSelection(toNode);
            return;
        }
        const siblings = fromNode.parent.children;
        const idxA = siblings.findIndex(c => c.id === fromId);
        const idxB = siblings.findIndex(c => c.id === toId);
        if (idxA < 0 || idxB < 0) return;
        const start = Math.min(idxA, idxB);
        const end = Math.max(idxA, idxB);
        this._clearMultiSelection();
        for (let i = start; i <= end; i++) {
            this._addNodeToSelection(siblings[i]);
        }
    }

    _addNodeToSelection(node) {
        if (!this.selectedNodes.find(n => n.id === node.id)) {
            this.selectedNodes.push(node);
            this._highlightNode(node, true);
        }
        this._updateSelectionCount();
    }

    _highlightNode(node, highlight) {
        const element = this.jm.view.get_node_element(node.id);
        if (!element) return;
        if (highlight) {
            element.classList.add('multi-selected');
            element.style.outline = '3px solid #007bff';
            element.style.outlineOffset = '2px';
        } else {
            element.classList.remove('multi-selected');
            element.style.outline = '';
            element.style.outlineOffset = '';
        }
    }

    _clearMultiSelection() {
        for (let node of this.selectedNodes) {
            this._highlightNode(node, false);
        }
        this.selectedNodes = [];
        this._updateSelectionCount();
    }

    _updateSelectionCount() {
        // 選取數現於狀態列以文字呈現（與主題/指令數同區），統一由 _updateStatusCounts 更新。
        this._updateStatusCounts();
    }

    _showSummaryContextMenu(summaryId, event) {
        // Remove existing
        document.querySelectorAll('.o_summary_context_menu').forEach(el => el.remove());

        const menu = document.createElement('div');
        menu.className = 'o_summary_context_menu dropdown-menu show';
        menu.style.cssText = `position: fixed; left: ${event.clientX}px; top: ${event.clientY}px; z-index: 10000;`;
        menu.innerHTML = `
            <a class="dropdown-item" href="#" data-action="delete"><i class="fa fa-trash"/> ${_t('Delete Summary')}</a>
        `;
        menu.addEventListener('click', (e) => {
            e.preventDefault();
            const action = e.target.closest('[data-action]');
            if (action && action.dataset.action === 'delete') {
                this._deleteSummary(summaryId);
            }
            menu.remove();
        });

        document.body.appendChild(menu);
        setTimeout(() => {
            document.addEventListener('click', () => menu.remove(), { once: true });
        }, 10);
    }

    _deleteSummary(summaryId) {
        const summaryIndex = this.summaries.findIndex(s => s.id === summaryId);
        if (summaryIndex === -1) return;

        const summaryData = this.summaries[summaryIndex];
        if (summaryData.summaryNodeId) {
            const cmd = new RemoveNodeCommand(this.jm, summaryData.summaryNodeId);
            this.commandStack.execute(cmd);
        }

        this.summaryRenderer.removeSummary(summaryId);
        this.summaries.splice(summaryIndex, 1);
        this._updateStatus(_t('Summary deleted'));
    }

    // ===== Re-render All Features =====
    _renderAllFeatures(resetRelationships = false) {
        const nodes = this.jm.mind.nodes;

        // Phase 1: Apply all visual features (shapes, styles, markers, labels, etc.)
        for (let id in nodes) {
            const node = nodes[id];
            const element = this.jm.view.get_node_element(id);
            if (element && node.data) {
                if (node.data.shape) this._applyShapeToNode(element, node.data.shape);
                if (node.data.style) this._restoreNodeStyle(element, node.data.style);
                if (node.data.markers && node.data.markers.length > 0) {
                    this.markerBadgeRenderer.renderMarkers(element, node.data.markers, this.markers);
                }
                if (node.data.labels && node.data.labels.length > 0) this.labelRenderer.renderLabels(element, node.data.labels);
                if (node.data.note) this.noteIndicator.addIndicator(element, true);
                if (node.data.hyperlink) this.hyperlinkIndicator.addIndicator(element, node.data.hyperlink, node.data.hyperlinkTitle);
                if (node.data.attachments && node.data.attachments.length > 0) this.attachmentIndicator.addIndicator(element, node.data.attachments.length);
                if (node.data.image) {
                    this.imageRenderer.renderImage(element, node.data.image.data, node.data.image.options);
                    // Image loads async → its height isn't counted by the Phase 2
                    // re-measure below; re-layout once it loads so spacing/lines never
                    // collide with the grown node.
                    this._watchImageLoad(element);
                }
                if (node.data.taskInfo) this._renderTaskIndicator(element, node.data.taskInfo);
                if (node.data.taskId) {
                    this._renderActivityClock(element, id, node.data.taskId, node.data.activity || {});
                    // Assignee avatar(s) after the clock (before the text).
                    this._renderAssignee(element, node.data.assignees || []);
                }
            }
        }

        // Phase 2: Re-measure ALL nodes after styling — shapes/styles/markers can
        // all change node dimensions.  Without this the layout uses stale sizes,
        // causing branches and connection lines to overlap on first render.
        let needsRelayout = false;
        for (let id in nodes) {
            const node = nodes[id];
            const element = this.jm.view.get_node_element(id);
            if (element) {
                const ow = element.offsetWidth;
                const oh = element.offsetHeight;
                if (ow !== node._w || oh !== node._h) {
                    node._w = ow;
                    node._h = oh;
                    needsRelayout = true;
                }
            }
        }

        // Phase 3: Relayout if any node changed size, then redraw lines
        if (needsRelayout) {
            this.jm.view.refresh();
        }

        // Position floating topics BEFORE boundaries/summaries so their
        // children are at correct positions for bounding-box calculations
        this._renderAllFloatingTopics();

        this._rebuildBoundaries();

        this._rebuildSummaries();

        // Redraw branch lines after summary positioning (hide parent→summary lines)
        if (this.jm && this.jm.view) {
            this.jm.view.draw_lines();
        }

        // Rebuild all relationships. On initial load (resetRelationships=true) we
        // re-optimise control points for the current layout, same as a layout switch.
        this._rebuildRelationships(resetRelationships);

        // Apply per-topic numbering
        this._applyAllPerTopicNumbering();

        // Deferred second pass: floating topic sub-trees may need a re-layout
        // after summaries are positioned (summary nodes change size/position).
        // Also ensures boundaries/summaries reflect final positions.
        if (this.floatingTopics.length > 0) {
            requestAnimationFrame(() => {
                this._renderAllFloatingTopics();
                this._rebuildBoundaries();
                this._rebuildSummaries();
                if (this.jm && this.jm.view) this.jm.view.draw_lines();
                this._rebuildRelationships(resetRelationships);
            });
        }
    }

    /**
     * Walk all nodes and apply per-topic numbering where node.data.numbering is set.
     */
    _applyAllPerTopicNumbering() {
        const nodes = this.jm.mind.nodes;
        for (const id in nodes) {
            const node = nodes[id];
            if (node.data && node.data.numbering && node.data.numbering !== 'none') {
                this._applyPerTopicNumbering(node);
            }
        }
    }

    // ===== Zoom Controls =====
    onZoomIn() {
        if (!this.jm) return;
        this._zoomLevel = Math.min((this._zoomLevel || 1) + 0.1, 3);
        this._applyZoom();
    }

    onZoomOut() {
        if (!this.jm) return;
        this._zoomLevel = Math.max((this._zoomLevel || 1) - 0.1, 0.3);
        this._applyZoom();
    }

    onZoomFit() {
        if (!this.jm || !this.jm.view) return;
        const container = this.containerRef.el;
        if (!container) return;

        const panel = this.jm.view.e_panel;
        if (!panel) return;

        // Get the bounding box of all nodes
        const nodes = panel.querySelectorAll('.xmind-node');
        if (nodes.length === 0) return;

        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        const panelRect = panel.getBoundingClientRect();

        nodes.forEach(node => {
            const rect = node.getBoundingClientRect();
            const x = rect.left - panelRect.left;
            const y = rect.top - panelRect.top;
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, x + rect.width);
            maxY = Math.max(maxY, y + rect.height);
        });

        const contentW = maxX - minX + 100;
        const contentH = maxY - minY + 100;
        const containerW = container.parentElement.offsetWidth;
        const containerH = container.parentElement.offsetHeight - 60;

        const scaleX = containerW / contentW;
        const scaleY = containerH / contentH;
        this._zoomLevel = Math.min(scaleX, scaleY, 2);
        this._zoomLevel = Math.max(this._zoomLevel, 0.3);

        this._applyZoom();
        this._updateStatus(_t('Fit to view: ') + Math.round(this._zoomLevel * 100) + '%');
    }

    onZoomReset() {
        this._zoomLevel = 1;
        this._applyZoom();
    }

    _applyZoom() {
        if (!this.jm || !this.jm.view) return;

        const level = this._zoomLevel || 1;
        // Use jsmind's built-in zoom (transform on world element)
        this.jm.view.setZoom(level);

        // Update every zoom-level readout (toolbar + status bar).
        const pct = Math.round(level * 100) + '%';
        this._elAll('.o_mindmap_zoom_level').forEach(el => { el.textContent = pct; });
        // Keep the status-bar slider in sync (wheel/keyboard/fit zoom changes).
        const slider = this._el('.o_mindmap_zoom_slider');
        if (slider) slider.value = Math.round(level * 100);
    }


    _createFloatingTopicAt(title, note, x, y) {
        if (!this.jm) return;
        const rootId = this.jm.get_root().id;
        const nodeId = this._generateNodeId();
        const nodeData = {
            _isFloatingTopic: true,
            _ftX: x,
            _ftY: y,
            note: note || '',
            style: {
                background: '#FFFFFF',
                color: '#303030',
                'font-size': '13px',
                'font-weight': 'bold',
                fontSize: '13',
                bold: true,
            },
            shape: { type: 'rounded', fillColor: '#FFFFFF', borderColor: '#558ED5', borderWidth: 2 },
        };

        // Add as real render-engine node (child of root, excluded from layout)
        const cmd = new AddNodeCommand(this.jm, rootId, nodeId, title || _t('Floating Topic'), nodeData);
        this.commandStack.execute(cmd);

        // Track in floatingTopics array for save/load
        this.floatingTopics.push({ id: nodeId, component_id: nodeId, x, y });

        // Position and style
        this._positionFloatingNode(nodeId, x, y);
        this._setupFloatingDrag(nodeId);

        this._updateStatus(_t('Floating topic added'));
    }

    /** Position a floating topic node at stored coordinates */
    _positionFloatingNode(nodeId, x, y) {
        const node = this.jm.get_node(nodeId);
        if (!node) return;
        // Update stored position in node data
        if (node.data) {
            node.data._ftX = x;
            node.data._ftY = y;
        }
        // Run sub-tree layout for this floating node
        if (this.jm.view._layoutFloatingSubtree) {
            this.jm.view._layoutFloatingSubtree(node);
        }
        // Redraw lines for sub-tree
        this.jm.view.draw_lines();
    }

    /** Setup drag-to-reposition for a floating topic node */
    _setupFloatingDrag(nodeId) {
        const el = this.jm.view.get_node_element(nodeId);
        if (!el) return;
        el.classList.add('xmind-floating-topic');
        el.style.cursor = 'move';

        let isDragging = false, startX, startY, origX, origY;
        const ftData = this.floatingTopics.find(f => f.id === nodeId);

        el.addEventListener('mousedown', (e) => {
            // Only drag on left button and when clicking the floating node itself (not children)
            if (e.button !== 0) return;
            const node = this.jm.get_node(nodeId);
            if (!node || !node.data || !node.data._isFloatingTopic) return;
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            origX = ftData ? ftData.x : (parseInt(el.style.left) || 0);
            origY = ftData ? ftData.y : (parseInt(el.style.top) || 0);
            e.stopPropagation();
            e.preventDefault();
        });

        const onMove = (e) => {
            if (!isDragging) return;
            const zoom = this._zoomLevel || 1;
            const newX = origX + (e.clientX - startX) / zoom;
            const newY = origY + (e.clientY - startY) / zoom;
            if (ftData) { ftData.x = newX; ftData.y = newY; }
            this._positionFloatingNode(nodeId, newX, newY);
        };

        const onUp = () => {
            // Always detach the per-drag listeners (even if no drag occurred)
            // so each mousedown doesn't permanently leak a move/up pair.
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            if (!isDragging) return;
            isDragging = false;
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
        };

        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }

    /** Convert a floating topic to a regular child of root (removes floating status) */
    _convertFloatingToRegular(nodeId) {
        const node = this.jm.get_node(nodeId);
        if (!node || !node.data) return;
        delete node.data._isFloatingTopic;
        delete node.data._ftX;
        delete node.data._ftY;
        const el = this.jm.view.get_node_element(nodeId);
        if (el) el.classList.remove('xmind-floating-topic');
        // Remove from tracking array
        const idx = this.floatingTopics.findIndex(f => f.id === nodeId);
        if (idx > -1) this.floatingTopics.splice(idx, 1);
        // Refresh layout so it joins the main tree
        this.jm.view.refresh();
        setTimeout(() => this._renderAllFeatures(), 100);
        this._updateStatus(_t('Converted to regular topic'));
    }

    /**
     * 把 `floatingTopics` 對回畫布的實際節點，丟掉已經不存在的項目。
     *
     * `floatingTopics` 是畫布之外的第二份狀態，但浮動主題本身是 root 的真實
     * 子節點，會被三條完全不知道這個陣列存在的路徑移除：`onDelete()`、
     * `onCutTopic()`，以及 `AddNodeCommand.undo()`（復原「新增浮動主題」）。
     *
     * 不對帳的話，存檔時 `this.jm.get_node(ft.id)` 取到 null，仍會照著殘留項
     * 寫一筆回去 —— 而那些項目是 `{id, component_id, x, y}`，連 title 都沒有，
     * 於是刪掉的浮動主題會以「空白標題」復活。與其在每條移除路徑補一次
     * splice（下一條新路徑照樣會漏），在使用這份狀態之前統一對帳。
     *
     * 「轉為一般主題」不在此列 —— 那條路徑自己會 splice，而且節點還在，
     * 這裡看不出差別（`_isFloatingTopic` 要等第一次 render 才會標上去，拿它
     * 當判準反而會誤刪剛建立、還沒畫過的浮動主題）。
     */
    _pruneFloatingTopics() {
        if (!this.jm || this.floatingTopics.length === 0) return;
        this.floatingTopics = this.floatingTopics.filter(
            (ft) => Boolean(this.jm.get_node(ft.id))
        );
    }

    _renderAllFloatingTopics() {
        this._pruneFloatingTopics();
        if (this.floatingTopics.length === 0) return;

        // Build set of node IDs that are wrapped by boundaries
        const boundaryNodeIds = new Set();
        for (const b of this.boundaries) {
            if (b.topicIds) b.topicIds.forEach(id => boundaryNodeIds.add(id));
        }

        // Phase 1: Initial positioning
        for (const ft of this.floatingTopics) {
            const node = this.jm.get_node(ft.id);
            if (!node) continue;
            if (!node.data) node.data = {};
            node.data._isFloatingTopic = true;
            node.data._ftX = ft.x;
            node.data._ftY = ft.y;

            let hasBoundaryChildren = false;
            if (node.children) {
                for (const c of node.children) {
                    if (boundaryNodeIds.has(c.id)) { hasBoundaryChildren = true; break; }
                }
            }
            node.data._ftExtraVSpace = hasBoundaryChildren ? 36 : 0;

            this._positionFloatingNode(ft.id, ft.x, ft.y);
        }

        // Phase 2: Collision detection & resolution between floating topics
        this._resolveFloatingCollisions();

        // Phase 3: Setup drag handlers
        for (const ft of this.floatingTopics) {
            this._setupFloatingDrag(ft.id);
        }
    }

    /** Compute the bounding box of a floating topic's entire visible subtree */
    _getFloatingSubtreeBounds(ftId) {
        const node = this.jm.get_node(ftId);
        if (!node) return null;

        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

        const measure = (n) => {
            const el = this.jm.view.get_node_element(n.id);
            if (!el || el.style.display === 'none') return;
            const l = parseInt(el.style.left) || 0;
            const t = parseInt(el.style.top) || 0;
            const w = el.offsetWidth || n._w || 0;
            const h = el.offsetHeight || n._h || 0;
            minX = Math.min(minX, l);
            minY = Math.min(minY, t);
            maxX = Math.max(maxX, l + w);
            maxY = Math.max(maxY, t + h);
            if (n.expanded && n.children) {
                for (const c of n.children) measure(c);
            }
        };
        measure(node);

        if (minX === Infinity) return null;
        // Add padding for boundaries
        const pad = 20;
        return { minX: minX - pad, minY: minY - pad, maxX: maxX + pad, maxY: maxY + pad };
    }

    /** Push overlapping floating topics apart */
    _resolveFloatingCollisions() {
        if (this.floatingTopics.length < 2) return;

        // Collect bounding boxes
        const boxes = [];
        for (const ft of this.floatingTopics) {
            const bounds = this._getFloatingSubtreeBounds(ft.id);
            if (bounds) {
                boxes.push({ ft, bounds, node: this.jm.get_node(ft.id) });
            }
        }

        // Iterative push-apart (max 10 iterations)
        const margin = 20;
        for (let iter = 0; iter < 10; iter++) {
            let anyMoved = false;
            for (let i = 0; i < boxes.length; i++) {
                for (let j = i + 1; j < boxes.length; j++) {
                    const a = boxes[i].bounds;
                    const b = boxes[j].bounds;

                    // Check overlap
                    const overlapX = a.maxX > b.minX && b.maxX > a.minX;
                    const overlapY = a.maxY > b.minY && b.maxY > a.minY;
                    if (!overlapX || !overlapY) continue;

                    // Calculate overlap amounts
                    const pushRight = a.maxX - b.minX + margin;
                    const pushDown = a.maxY - b.minY + margin;

                    // Push the smaller (or rightward/downward) one away
                    // Choose the direction with less overlap to minimize movement
                    const bFt = boxes[j].ft;
                    const bNode = boxes[j].node;

                    if (pushRight < pushDown) {
                        // Push B to the right
                        bFt.x += pushRight;
                    } else {
                        // Push B downward
                        bFt.y += pushDown;
                    }

                    // Re-position B
                    if (bNode && bNode.data) {
                        bNode.data._ftX = bFt.x;
                        bNode.data._ftY = bFt.y;
                    }
                    this._positionFloatingNode(bFt.id, bFt.x, bFt.y);

                    // Re-measure B's bounds
                    const newBounds = this._getFloatingSubtreeBounds(bFt.id);
                    if (newBounds) boxes[j].bounds = newBounds;

                    anyMoved = true;
                }
            }
            if (!anyMoved) break;
        }
    }

    // ===== Template System =====
    onLoadTemplate() {
        this._showTemplateDialog(this._getTemplates());
    }

    _getTemplates() {
        // 範本內容搬到 mindmap_templates_data.js（純資料，與編輯器狀態無關）。
        return getMindmapTemplates(this._getDefaultData());
    }

    _showTemplateDialog(templates) {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

        const dialog = document.createElement('div');
        dialog.style.cssText = 'background:white;border-radius:12px;padding:24px;max-width:700px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:0 16px 48px rgba(0,0,0,0.3);';

        dialog.innerHTML = `<h4 style="margin-bottom:16px;">${_t('Choose a Template')}</h4>`;

        const categories = { basic: _t('Basic'), business: _t('Business'), education: _t('Education'), personal: _t('Personal') };

        for (const [catKey, catName] of Object.entries(categories)) {
            const catTemplates = templates.filter(t => t.category === catKey);
            if (catTemplates.length === 0) continue;

            const section = document.createElement('div');
            section.style.marginBottom = '16px';
            section.innerHTML = `<h6 style="color:#6c757d;margin-bottom:8px;">${catName}</h6>`;

            const grid = document.createElement('div');
            grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;';

            for (const tmpl of catTemplates) {
                const card = document.createElement('div');
                card.style.cssText = 'border:1px solid #dee2e6;border-radius:8px;padding:12px;text-align:center;cursor:pointer;transition:all 0.2s;';
                card.innerHTML = `<i class="fa ${tmpl.icon}" style="font-size:24px;color:#007bff;display:block;margin-bottom:8px;"></i><span style="font-size:13px;">${tmpl.name}</span>`;
                card.addEventListener('mouseenter', () => { card.style.borderColor = '#007bff'; card.style.boxShadow = '0 2px 8px rgba(0,123,255,0.2)'; });
                card.addEventListener('mouseleave', () => { card.style.borderColor = '#dee2e6'; card.style.boxShadow = 'none'; });
                card.addEventListener('click', () => {
                    this._applyTemplate(tmpl);
                    overlay.remove();
                });
                grid.appendChild(card);
            }

            section.appendChild(grid);
            dialog.appendChild(section);
        }

        const closeBtn = document.createElement('button');
        closeBtn.className = 'btn btn-secondary mt-3';
        closeBtn.textContent = _t('Cancel');
        closeBtn.addEventListener('click', () => overlay.remove());
        dialog.appendChild(closeBtn);

        overlay.appendChild(dialog);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
        document.body.appendChild(overlay);
    }

    _applyTemplate(template) {
        if (!this.jm) return;

        this.dialog.add(ConfirmationDialog, {
            body: _t('This will replace the current mind map. Continue?'),
            confirm: () => {
                this.mindmapData = template.data;
                this.jm.show(template.data, () => {
                    this._renderAllFeatures();
                    this._updateStatus(_t('Template applied: ') + template.name);
                });
                this.commandStack.clear();
            },
        });
    }
}

registry.category("actions").add("dobtor_xmind.mindmap_editor", MindmapEditor);
