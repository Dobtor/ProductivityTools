/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
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

/**
 * XMind 2 Style Mind Map Editor for Odoo 18
 * OWL Component with Command Pattern
 */
export class MindmapEditor extends Component {
    static template = "dobtor_xmind.MindmapEditor";
    static props = { action: { type: Object, optional: true }, "*": true };

    setup() {
        this.rpc = useService("rpc");
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        this.canvasRef = useRef("canvas");
        this.containerRef = useRef("jsmindContainer");
        this.sidebarRef = useRef("sidebar");

        this.workbookId = this.props.action && this.props.action.params && this.props.action.params.workbook_id;
        this.jm = null;
        this.commandStack = new CommandStack(200);
        this.selectedNode = null;
        this.autoSaveTimer = null;
        this.markers = [];
        this.relationshipMode = false;
        this.relationshipSource = null;

        // XMind 2 Feature Renderers
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
        this.summaryBranchStyles = {};
        this.selectedTopicsForFeature = [];

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
            lineWidth: 2,
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
        this._boundKeydownHandler = this._setupKeyboardShortcuts.bind(this);

        onMounted(async () => {
            await this._loadData();
            const jmInitSuccess = this._initJsMind();
            if (!jmInitSuccess) {
                this._updateStatus(_t('Initialization failed'));
                return;
            }
            this._initXMindFeatures();
            this._setupCommandStackListener();
            this._setupContextMenu();
            document.addEventListener('keydown', this._boundKeydownHandler);
            this._setupAutoSave();
            this._initFormatMenu();
            this._initRectangleSelector();
            this._zoomLevel = 1;
            this._copiedStyle = null;
            this._updateStatus(_t('Ready'));
        });

        onWillUnmount(() => {
            if (this.autoSaveTimer) {
                clearInterval(this.autoSaveTimer);
            }
            if (this.dragDropManager) {
                this.dragDropManager.destroy();
            }
            document.removeEventListener('keydown', this._boundKeydownHandler);
        });
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
        if (!this.workbookId) {
            this.mindmapData = this._getDefaultData();
            this.sheetSettings = { layout: 'map', theme: 'primary' };
            return;
        }

        try {
            const result = await this.rpc('/xmind/workbook/' + this.workbookId + '/data', {});
            if (result.error) {
                this._showError(result.error);
                this.mindmapData = this._getDefaultData();
            } else {
                this.mindmapData = result.mindmap_data;
                this.sheetSettings = result.sheet_settings || { layout: 'map', theme: 'primary' };
            }
        } catch (e) {
            this.mindmapData = this._getDefaultData();
        }
    }

    async _loadMarkers() {
        try {
            this.markers = await this.rpc('/xmind/markers', {});
        } catch (e) {
            this.markers = [];
        }
    }

    _getDefaultData() {
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
                    style: {
                        background: '#428bca',
                        color: '#ffffff',
                        'font-weight': 'bold',
                        'font-size': '18px',
                    }
                }
            }
        };
    }

    // ===== jsMind Initialization =====
    _initJsMind() {
        const container = this.containerRef.el;

        if (!container) {
            console.error('[MindmapEditor] Container #jsmind_container not found.');
            this.notification.add(_t('Mind map container not found. Please refresh the page.'), { type: 'danger' });
            return false;
        }

        if (!window.OdooXMind) {
            console.error('[MindmapEditor] OdooXMind library not loaded.');
            this.notification.add(_t('Mind map library (OdooXMind) not loaded. Please clear cache and refresh.'), { type: 'danger' });
            return false;
        }

        const MindMapClass = window.OdooXMind;

        const options = {
            container: container,
            theme: this.sheetSettings.theme || 'primary',
            editable: true,
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
                vspace: this.sheetSettings.spacing_minor || 20,
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

            this.jm.show(this.mindmapData);
        } catch (error) {
            console.error('[MindmapEditor] Failed to initialize jsMind:', error);
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

        switch (layout) {
            case 'tree_right':
            case 'tree_left':
                options.layout.hspace = 50;
                options.layout.vspace = 10;
                break;
            case 'logic_right':
                options.layout.hspace = 60;
                options.layout.vspace = 15;
                break;
            case 'org_chart_down':
                options.layout.hspace = 20;
                options.layout.vspace = 40;
                break;
            default:
                options.layout.hspace = 30;
                options.layout.vspace = 20;
        }
    }

    // ===== Command Stack =====
    _setupCommandStackListener() {
        this.commandStack.addListener((state) => {
            this._updateUndoRedoButtons(state);
            this._updateCommandCount(state.commandCount);
            if (state.isDirty) {
                this._updateStatus(_t('Modified'));
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

    _updateCommandCount(count) {
        const el = this._el('.o_mindmap_command_count');
        if (el) el.textContent = count + ' ' + _t('commands');
    }

    // ===== Keyboard Shortcuts =====
    _setupKeyboardShortcuts(e) {
        if (this._isInputFocused()) return;

        if (e.ctrlKey && e.key === 'z' && !e.shiftKey) {
            e.preventDefault();
            this.onUndo();
        } else if ((e.ctrlKey && e.key === 'y') || (e.ctrlKey && e.shiftKey && e.key === 'Z')) {
            e.preventDefault();
            this.onRedo();
        } else if (e.key === 'Tab' && !e.shiftKey) {
            e.preventDefault();
            this.onAddChild();
        } else if (e.key === 'Enter' && !e.ctrlKey) {
            e.preventDefault();
            this.onAddSibling();
        } else if (e.key === 'Delete') {
            e.preventDefault();
            this.onDelete();
        } else if (e.ctrlKey && e.key === 's') {
            e.preventDefault();
            this.onSave();
        } else if (e.key === 'F2') {
            e.preventDefault();
            this._editSelectedNode();
        } else if (e.key.startsWith('Arrow')) {
            this._handleArrowNavigation(e);
        } else if (e.key === ' ') {
            e.preventDefault();
            this._toggleSelectedExpand();
        } else if (e.shiftKey && e.key === 'Enter') {
            e.preventDefault();
            this.onAddTopicBefore();
        } else if (e.ctrlKey && e.key === 'Enter') {
            e.preventDefault();
            this.onAddParentTopic();
        } else if (e.altKey && e.key === 'ArrowUp') {
            e.preventDefault();
            this.onMoveUp();
        } else if (e.altKey && e.key === 'ArrowDown') {
            e.preventDefault();
            this.onMoveDown();
        } else if (e.ctrlKey && e.key === 'c' && this.selectedNode) {
            e.preventDefault();
            this.onCopyTopic();
        } else if (e.ctrlKey && e.key === 'v' && this._clipboardTopic) {
            e.preventDefault();
            this.onPasteTopic();
        } else if (e.ctrlKey && (e.key === '=' || e.key === '+')) {
            e.preventDefault();
            this.onZoomIn();
        } else if (e.ctrlKey && e.key === '-') {
            e.preventDefault();
            this.onZoomOut();
        } else if (e.ctrlKey && e.key === '0') {
            e.preventDefault();
            this.onZoomReset();
        }
    }

    _isInputFocused() {
        const activeElement = document.activeElement;
        return activeElement && (
            activeElement.tagName === 'INPUT' ||
            activeElement.tagName === 'TEXTAREA' ||
            activeElement.contentEditable === 'true'
        );
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

        await this._saveData();

        if (indicator) {
            indicator.textContent = _t('Auto-saved');
            setTimeout(() => { indicator.textContent = ''; }, 3000);
        }
    }

    // ===== jsMind Events =====
    _onJsMindEvent(type, data) {
        if (type === 1) { // select
            this.selectedNode = data.node;
            this._updateSidebar(data.node);
            this._openSidebar();

            if (this.relationshipMode && this.relationshipSource) {
                this._createRelationship(this.relationshipSource, data.node);
                this.relationshipMode = false;
                this.relationshipSource = null;
                this._updateStatus(_t('Ready'));
            }
        } else if (type === 2) { // update
            this._updateFeaturePositions();
        } else if (type === 3) { // show
            setTimeout(() => this._updateFeaturePositions(), 100);
        } else if (type === 4) { // resize
            setTimeout(() => this._updateFeaturePositions(), 100);
        }
    }

    _updateFeaturePositions() {
        if (this.summaryRenderer) {
            this.summaryRenderer.updatePositions();
        }
        if (this.advancedRelationshipManager && typeof this.advancedRelationshipManager.refreshPositions === 'function') {
            this.advancedRelationshipManager.refreshPositions();
        }
        if (this.boundaryRenderer && typeof this.boundaryRenderer.updatePositions === 'function') {
            this.boundaryRenderer.updatePositions();
        }
    }

    // ===== XMind Features Init =====
    _initXMindFeatures() {
        if (!this.jm) return;

        const canvas = this.canvasRef.el;
        if (!canvas) return;

        this.advancedRelationshipManager = new RelationshipManager(canvas);
        this.boundaryRenderer = new BoundaryRenderer(canvas);
        this.summaryRenderer = new SummaryRenderer(canvas);
        this.calloutRenderer = new CalloutRenderer(canvas);

        this.summaryRenderer.setContextMenuCallback((summaryId, event) => {
            this._showSummaryContextMenu(summaryId, event);
        });

        this.summaryRenderer.setClickCallback((summaryId, event) => {
            this._updateStatus(_t('Summary selected: ') + summaryId);
        });

        this.dragDropManager = new DragDropManager(this.jm, this);
        this.dragDropManager.init();

        // Hook relationship click → show control points; double-click → edit dialog
        this._setupRelationshipInteraction();
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

        // Track when control point drag ends → mark dirty + sync data
        const origMouseUp = this.advancedRelationshipManager._onMouseUp.bind(this.advancedRelationshipManager);
        this.advancedRelationshipManager._onMouseUp = (e) => {
            const wasDragging = this.advancedRelationshipManager.isDraggingControlPoint;
            origMouseUp(e);
            if (wasDragging) {
                // Sync control point data back to our stored relationships
                this._syncRelationshipControlPoints();
                this.commandStack.isDirty = true;
                this.commandStack._notifyListeners();
                this._updateStatus(_t('Curve adjusted'));
            }
        };
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
            if (e.target === canvas || (e.target.closest('.o_mindmap_canvas') === canvas && !e.target.closest('jmnode'))) {
                if (e.shiftKey || this.multiSelectMode) {
                    isSelecting = true;
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
            }
        });

        document.addEventListener('mousemove', (e) => {
            if (!isSelecting) return;
            const rect = canvas.getBoundingClientRect();
            const currentX = e.clientX - rect.left;
            const currentY = e.clientY - rect.top;
            this.selectionRect.style.left = Math.min(currentX, startX) + 'px';
            this.selectionRect.style.top = Math.min(currentY, startY) + 'px';
            this.selectionRect.style.width = Math.abs(currentX - startX) + 'px';
            this.selectionRect.style.height = Math.abs(currentY - startY) + 'px';
        });

        document.addEventListener('mouseup', (e) => {
            if (!isSelecting) return;
            isSelecting = false;
            this.selectionRect.style.display = 'none';
            const selRect = this.selectionRect.getBoundingClientRect();
            this._selectNodesInRect(selRect);
        });

        canvas.addEventListener('click', (e) => {
            const nodeElement = e.target.closest('jmnode');
            if (nodeElement) {
                const nodeId = nodeElement.getAttribute('nodeid');
                const node = this.jm.get_node(nodeId);
                if (e.shiftKey || this.multiSelectMode) {
                    this._toggleNodeSelection(node);
                } else {
                    this._clearMultiSelection();
                    this._addNodeToSelection(node);
                }
            }
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
        setVal('.o_topic_title', node.topic);
        setVal('.o_topic_bg_color', style.background || '#ffffff');
        setVal('.o_topic_text_color', style.color || '#333333');
        setVal('.o_topic_font_size', parseInt(style['font-size']) || 14);
        setVal('.o_topic_font_weight', style['font-weight'] || 'normal');
        setVal('.o_topic_note', data.note || '');
        setVal('.o_topic_labels', (data.labels || []).join(', '));
        setVal('.o_topic_hyperlink', data.hyperlink || '');
        setVal('.o_topic_hyperlink_title', data.hyperlinkTitle || '');

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

    onAddChild() {
        const parentNode = this.selectedNode ? this.jm.get_node(this.selectedNode) : this.jm.get_root();
        const parentId = parentNode.id;
        const nodeId = this._generateNodeId();
        const topic = _t('New Topic');

        const inheritedData = { style: { background: '#f0f0f0', color: '#333333' } };

        if (parentNode.data && parentNode.data.shape) {
            inheritedData.shape = JSON.parse(JSON.stringify(parentNode.data.shape));
        }
        if (parentNode.data && parentNode.data.style) {
            inheritedData.style = JSON.parse(JSON.stringify(parentNode.data.style));
        }

        let summaryBranchStyle = null;
        if (this.summaryBranchStyles && this.summaryBranchStyles[parentId]) {
            summaryBranchStyle = this.summaryBranchStyles[parentId];
            inheritedData.branchStyle = summaryBranchStyle;
        }

        const cmd = new AddNodeCommand(this.jm, parentId, nodeId, topic, inheritedData);
        this.commandStack.execute(cmd);

        const newNode = this.jm.get_node(nodeId);
        const newElement = this.jm.view.get_node_element(nodeId);
        if (newNode && newElement) {
            if (inheritedData.shape) this._applyShapeToNode(newElement, inheritedData.shape);
            if (inheritedData.style) this._restoreNodeStyle(newElement, inheritedData.style);
            if (summaryBranchStyle) this._applySummaryBranchStyle(parentId, nodeId, summaryBranchStyle);
        }

        this.jm.select_node(nodeId);
        this._editSelectedNode();
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

        const inheritedData = { style: { background: '#f0f0f0', color: '#333333' } };
        if (parentNode.data && parentNode.data.shape) {
            inheritedData.shape = JSON.parse(JSON.stringify(parentNode.data.shape));
        }
        if (parentNode.data && parentNode.data.style) {
            inheritedData.style = JSON.parse(JSON.stringify(parentNode.data.style));
        }

        const cmd = new AddNodeCommand(this.jm, parentId, nodeId, topic, inheritedData);
        this.commandStack.execute(cmd);

        const newElement = this.jm.view.get_node_element(nodeId);
        if (newElement) {
            if (inheritedData.shape) this._applyShapeToNode(newElement, inheritedData.shape);
            if (inheritedData.style) this._restoreNodeStyle(newElement, inheritedData.style);
        }

        this.jm.select_node(nodeId);
        this._editSelectedNode();
        this._updateStatus(_t('Added sibling node'));
    }

    onDelete() {
        if (!this.selectedNode) return;

        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) {
            this._showWarning(_t('Cannot delete root node'));
            return;
        }

        this.dialog.add(ConfirmationDialog, {
            body: _t('Delete this topic and all its children?'),
            confirm: () => {
                const cmd = new RemoveNodeCommand(this.jm, this.selectedNode);
                this.commandStack.execute(cmd);
                this.selectedNode = null;
                this._closeSidebar();
                this._updateStatus(_t('Deleted node'));
            },
        });
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

        // Add as child of parent, then move before current node
        const cmd = new AddNodeCommand(this.jm, parentId, nodeId, topic, {
            style: { background: '#f0f0f0', color: '#333333' }
        });
        this.commandStack.execute(cmd);

        // Move it before the selected node
        try {
            this.jm.move_node(nodeId, this.selectedNode, parentId);
        } catch (e) { /* jsMind may not support beforeId in all layouts */ }

        this.jm.select_node(nodeId);
        this._editSelectedNode();
        this._updateStatus(_t('Added topic before'));
    }

    onAddParentTopic() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) return;

        const grandParentId = node.parent.id;
        const newParentId = this._generateNodeId();
        const topic = _t('New Topic');

        // 1. Create new node as sibling of current
        const cmd = new AddNodeCommand(this.jm, grandParentId, newParentId, topic, {
            style: { background: '#e9ecef', color: '#333333' }
        });
        this.commandStack.execute(cmd);

        // 2. Move current node under new parent
        try {
            this.jm.move_node(this.selectedNode, null, newParentId);
        } catch (e) { /* fallback: just created a sibling */ }

        this.jm.select_node(newParentId);
        this._editSelectedNode();
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
        setTimeout(() => this._renderAllXMindFeatures(), 100);
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Topic pasted'));
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

        this.jm.show(subData);
        setTimeout(() => this._renderAllXMindFeatures(), 200);
        this._updateStatus(_t('Drill down: ') + node.topic);
    }

    onDrillUp() {
        if (!this._drillStack || this._drillStack.length === 0) {
            this._showWarning(_t('Already at top level'));
            return;
        }
        const prevData = this._drillStack.pop();
        this.jm.show(prevData);
        setTimeout(() => this._renderAllXMindFeatures(), 200);
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

        // Clone the jsMind panel content
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
        setTimeout(() => this._renderAllXMindFeatures(), 100);

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
            const revisions = await this.rpc('/xmind/workbook/' + this.workbookId + '/revisions', {});
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
                            await this.rpc('/xmind/workbook/' + this.workbookId + '/revisions/' + rev.id + '/restore', {});
                            // Reload mindmap
                            await this._loadWorkbookData();
                            this.jm.show(this.mindmapData);
                            setTimeout(() => this._renderAllXMindFeatures(), 200);
                            this._updateStatus(_t('Revision restored: ') + rev.name);
                        },
                    });
                });

                item.querySelector('[data-action="preview"]').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const result = await this.rpc('/xmind/workbook/' + this.workbookId + '/revisions/' + rev.id + '/preview', {});
                    if (result && result.data) {
                        // Temporarily show the revision data
                        this.jm.show(result.data);
                        setTimeout(() => this._renderAllXMindFeatures(), 200);
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
        if (!this.selectedNode) {
            this._showWarning(_t('Please select a source topic first'));
            return;
        }
        this.relationshipMode = true;
        this.relationshipSource = this.selectedNode;
        this._updateStatus(_t('Click on target topic to create relationship...'));
    }

    onSave() {
        this._updateStatus(_t('Saving...'));
        this._saveData().then(() => {
            this.commandStack.markSaved();
            this._updateStatus(_t('Saved successfully'));
        }).catch((error) => {
            this._showError(_t('Save failed: ') + error);
        });
    }

    onExport() {
        if (!this.workbookId) return;
        window.location.href = '/web/content?model=xmind.workbook&id=' + this.workbookId +
            '&field=xmind_file&filename_field=xmind_filename&download=true';
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

        const titleEl = this._el('.o_topic_title');
        const noteEl = this._el('.o_topic_note');
        const labelsEl = this._el('.o_topic_labels');

        const newTopic = titleEl ? titleEl.value : '';
        const note = noteEl ? noteEl.value : '';
        const labels = labelsEl ? labelsEl.value.split(',').map(l => l.trim()).filter(l => l) : [];

        if (newTopic !== node.topic) {
            const cmd = new UpdateNodeCommand(this.jm, this.selectedNode, newTopic, node.topic);
            this.commandStack.execute(cmd);
        }

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
        // Use prompt-based simple dialog for Odoo 18
        const node = this.jm.get_node(this.selectedNode);
        const currentUrl = (node.data && node.data.hyperlink) || '';
        const url = prompt(_t('Enter URL:'), currentUrl);
        if (url !== null) {
            const title = prompt(_t('Enter title (optional):'), (node.data && node.data.hyperlinkTitle) || '');
            this._setTopicHyperlink(url.trim(), (title || '').trim());
        }
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

    onInsertAttachment(ev) {
        ev.preventDefault();
        if (!this.selectedNode) {
            this._showWarning(_t('Please select a topic first'));
            return;
        }
        // Create file input and trigger
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.addEventListener('change', () => {
            if (fileInput.files && fileInput.files[0]) {
                this._addAttachment(fileInput.files[0], fileInput.files[0].name);
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
            for (let node of this.selectedNodes) {
                this._applyStyleToNode(node, styleData);
                if (node.children && node.children.length > 0) {
                    this._applyBranchStyles(node, styleData.branch);
                }
            }
            this._updateStatus(_t('Style applied to ') + this.selectedNodes.length + _t(' topics'));
        } else if (this.selectedNode) {
            this._applyStyleToNode(this.selectedNode, styleData);
            this._updateStatus(_t('Style applied'));
        } else {
            this.notification.add(_t('Please select at least one topic first'), { type: 'warning' });
        }
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

    onClearSelection() {
        this._clearMultiSelection();
        this._updateStatus(_t('Selection cleared'));
    }

    // ===== Boundary =====
    onAddBoundary() {
        if (!this.selectedNode) {
            this._showWarning(_t('Please select at least one topic to create a boundary'));
            return;
        }
        this.selectedTopicsForFeature = [this.selectedNode];

        // Simple boundary with default options
        const options = {
            shape: 'rounded',
            fillColor: 'rgba(255, 255, 0, 0.2)',
            borderColor: '#ffc107',
            borderWidth: 2,
            borderStyle: 'solid',
            title: '',
        };
        this._createBoundary(options);
    }

    _createBoundary(options) {
        const topicElements = [];
        for (let nodeId of this.selectedTopicsForFeature) {
            const element = this.jm.view.get_node_element(nodeId);
            if (element) topicElements.push(element);
        }

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
        if (!this.selectedNode) {
            this._showWarning(_t('Please select sibling topics to summarize'));
            return;
        }

        const node = this.jm.get_node(this.selectedNode);
        if (!node || !node.parent) {
            this._showWarning(_t('Cannot create summary for root node'));
            return;
        }

        const summaryOptions = {
            lineType: 'bracket',
            lineWidth: 2,
            lineColor: '#6c757d',
            topicText: _t('Summary'),
            topicFillColor: '#E3F2FD',
            topicTextColor: '#1565C0',
            topicFontSize: 14,
            topicShape: 'rounded',
            topicBorderColor: '#2196F3',
            topicBorderWidth: 2,
            topicBold: false,
            topicItalic: false,
            branchType: 'curved',
            branchEndMarker: 'none',
            branchWidth: 2,
            branchColor: '#2196F3',
        };

        this._createSummary([this.selectedNode], summaryOptions);
    }

    _createSummary(topicIds, summaryOptions) {
        const parentId = this.jm.get_node(topicIds[0]).parent.id;
        const summaryNodeId = this._generateNodeId();

        const nodeStyle = {
            background: summaryOptions.topicFillColor,
            color: summaryOptions.topicTextColor,
            'font-size': summaryOptions.topicFontSize + 'px',
            'border': `${summaryOptions.topicBorderWidth}px solid ${summaryOptions.topicBorderColor}`
        };
        if (summaryOptions.topicBold) nodeStyle['font-weight'] = 'bold';
        if (summaryOptions.topicItalic) nodeStyle['font-style'] = 'italic';

        const cmd = new AddNodeCommand(this.jm, parentId, summaryNodeId, summaryOptions.topicText, { style: nodeStyle });
        this.commandStack.execute(cmd);

        setTimeout(() => {
            const summaryElement = this.jm.view.get_node_element(summaryNodeId);
            if (summaryElement) summaryElement.classList.add('summary-topic');

            this.summaryBranchStyles[summaryNodeId] = {
                lineType: summaryOptions.branchType,
                endMarker: summaryOptions.branchEndMarker,
                lineWidth: summaryOptions.branchWidth,
                lineColor: summaryOptions.branchColor
            };
        }, 100);

        const topicElements = topicIds.map(id => this.jm.view.get_node_element(id)).filter(e => e);
        const summaryElement = this.jm.view.get_node_element(summaryNodeId);

        const renderedSummaryId = this.summaryRenderer.addSummary(topicElements, summaryElement, {
            lineType: summaryOptions.lineType,
            lineColor: summaryOptions.lineColor,
            lineWidth: summaryOptions.lineWidth,
        });

        this.summaries.push({
            id: renderedSummaryId,
            topicIds: topicIds,
            summaryNodeId: summaryNodeId,
            options: summaryOptions,
        });

        this._updateStatus(_t('Summary created'));
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
        const title = prompt(_t('Topic Text:'), _t('Floating Topic'));
        if (title) {
            this._createFloatingTopicElement(title, '');
        }
    }

    _createFloatingTopicElement(title, note) {
        const canvas = this.canvasRef.el;
        const floatingDiv = document.createElement('div');
        floatingDiv.className = 'xmind-floating-topic';
        floatingDiv.style.cssText = 'position: absolute; left: 100px; top: 100px; background: #e0e0e0; padding: 10px 16px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); cursor: move; z-index: 20;';
        floatingDiv.textContent = title;
        if (note) floatingDiv.title = note;

        let isDragging = false, offsetX, offsetY;
        floatingDiv.addEventListener('mousedown', (e) => {
            isDragging = true;
            offsetX = e.clientX - floatingDiv.offsetLeft;
            offsetY = e.clientY - floatingDiv.offsetTop;
        });
        document.addEventListener('mousemove', (e) => {
            if (isDragging) {
                floatingDiv.style.left = (e.clientX - offsetX) + 'px';
                floatingDiv.style.top = (e.clientY - offsetY) + 'px';
            }
        });
        document.addEventListener('mouseup', () => { isDragging = false; });

        canvas.appendChild(floatingDiv);
        this.floatingTopics.push({ element: floatingDiv, title, note });
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Floating topic added'));
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
            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Image added to topic'));
        }
    }

    // ===== Internal Methods =====
    _editSelectedNode() {
        if (!this.selectedNode) return;
        const node = this.jm.get_node(this.selectedNode);
        if (!node) return;

        this.jm.begin_edit(this.selectedNode);

        setTimeout(() => {
            const container = this.containerRef.el;
            if (!container) return;
            const editElement = container.querySelector('input.jmnode-input');
            if (editElement) {
                const oldTopic = node.topic;
                editElement.addEventListener('blur', () => {
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
            this._updateMarkersDisplay(node.data.markers);
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
            this._updateMarkersDisplay(node.data.markers);
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
            shapeType: 'curved', lineStyle: 'dashed', lineWidth: 2, lineColor: '#999999',
            startMarker: 'none', endMarker: 'arrow', markerSize: 'medium',
            label: '', labelFontSize: 12, labelColor: '#666666',
            labelBold: false, labelItalic: false, labelBackground: false,
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

    async _saveData() {
        if (!this.workbookId) return;
        const data = this.jm.get_data('node_tree');
        await this.rpc('/xmind/workbook/' + this.workbookId + '/save', { data });
    }

    async _saveSettings() {
        if (!this.workbookId) return;
        await this.rpc('/xmind/workbook/' + this.workbookId + '/settings', { settings: this.sheetSettings });
    }

    _generateNodeId() {
        return 'node_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    _updateStatus(message) {
        const el = this._el('.o_mindmap_status_text');
        if (el) el.textContent = message;
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
        element.classList.remove('shape-rectangle', 'shape-rounded', 'shape-ellipse', 'shape-diamond', 'shape-parallelogram', 'shape-hexagon', 'shape-cloud', 'shape-underline');

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
                element.style.borderBottom = `${shapeData.borderWidth}px solid ${shapeData.borderColor}`;
                element.style.boxShadow = 'none';
                element.classList.add('shape-underline');
                return;
            case 'noBorder':
                element.style.backgroundColor = 'transparent';
                element.style.border = 'none';
                element.style.boxShadow = 'none';
                element.style.borderRadius = '0';
                return;
            case 'fishhead_left':
                element.style.clipPath = 'polygon(15% 0%, 100% 0%, 100% 100%, 15% 100%, 0% 50%)';
                element.style.borderRadius = '0';
                break;
            case 'fishhead_right':
                element.style.clipPath = 'polygon(0% 0%, 85% 0%, 100% 50%, 85% 100%, 0% 100%)';
                element.style.borderRadius = '0';
                break;
        }

        if (shapeData.fillColor) element.style.backgroundColor = shapeData.fillColor;
        if (shapeData.borderColor && shapeData.borderWidth) {
            element.style.border = `${shapeData.borderWidth}px solid ${shapeData.borderColor}`;
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

    _applyBranchStyles(node, branchStyle) {
        const svgContainer = this.jm.view.e_lines;
        if (!svgContainer) return;
        const paths = svgContainer.querySelectorAll('path');
        paths.forEach(path => {
            path.style.stroke = branchStyle.lineColor;
            path.style.strokeWidth = branchStyle.lineWidth + 'px';
            switch (branchStyle.lineStyle) {
                case 'dashed': path.style.strokeDasharray = '8, 4'; break;
                case 'dotted': path.style.strokeDasharray = '2, 2'; break;
                default: path.style.strokeDasharray = 'none';
            }
        });
    }

    _applyGlobalBranchStyles(branchStyle) {
        this.branchStyleSettings = branchStyle;
        const svgContainer = this.jm.view.e_lines;
        if (!svgContainer) return;
        const paths = svgContainer.querySelectorAll('path');
        paths.forEach(path => {
            path.style.stroke = branchStyle.lineColor;
            path.style.strokeWidth = branchStyle.lineWidth + 'px';
            switch (branchStyle.lineStyle) {
                case 'dashed': path.style.strokeDasharray = '8, 4'; break;
                case 'dotted': path.style.strokeDasharray = '2, 2'; break;
                default: path.style.strokeDasharray = 'none';
            }
        });
        if (this.jm.options.view) {
            this.jm.options.view.line_color = branchStyle.lineColor;
            this.jm.options.view.line_width = branchStyle.lineWidth;
        }
    }

    _applyLayoutSpacing(layoutSettings) {
        if (this.jm && this.jm.options.layout) {
            this.jm.options.layout.hspace = layoutSettings.hSpace;
            this.jm.options.layout.vspace = layoutSettings.vSpace;
            this.jm.view.relayout();
            setTimeout(() => {
                this._renderAllXMindFeatures();
                this._applyGlobalBranchStyles(this.branchStyleSettings);
            }, 100);
        }
    }

    _applyLayoutType(layoutType) {
        const layoutMap = {
            'map': 'side', 'tree_right': 'right', 'tree_left': 'left',
            'logic_right': 'right', 'logic_left': 'left',
            'org_chart_down': 'side', 'org_chart_up': 'side',
            'fishbone_left': 'left', 'fishbone_right': 'right'
        };
        if (this.jm) {
            this.jm.options.layout = { type: layoutMap[layoutType] || 'side' };
            this.jm.view.relayout();
            setTimeout(() => this._renderAllXMindFeatures(), 100);
            this._updateStatus(_t('Layout changed to: ') + layoutType);
        }
    }

    _collectFormatSettings() {
        const getVal = (sel, def) => { const el = this._el(sel); return el ? el.value : def; };
        return {
            shape: {
                type: getVal('.o_format_shape_type', 'rounded'),
                fillColor: getVal('.o_format_fill_color', '#ffffff'),
                borderColor: getVal('.o_format_border_color', '#558ED5'),
                borderWidth: parseInt(getVal('.o_format_border_width', '2'))
            },
            text: {
                fontFamily: getVal('.o_format_font_family', 'inherit'),
                fontSize: getVal('.o_format_font_size', '14'),
                color: getVal('.o_format_text_color', '#333333'),
                bgColor: getVal('.o_format_bg_color', '#ffffff'),
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

    _applySummaryBranchStyle(parentId, childId, branchStyle) {
        if (!branchStyle) return;
        // Simplified version - applies custom branch line between summary topic and child
        const parentElement = this.jm.view.get_node_element(parentId);
        const childElement = this.jm.view.get_node_element(childId);
        if (!parentElement || !childElement) return;
        // Branch style will be applied via CSS/SVG in the renderer
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
        const badge = this._el('.o_mindmap_selection_count');
        if (!badge) return;
        const count = this.selectedNodes.length;
        badge.style.display = count > 0 ? '' : 'none';
        const countSpan = badge.querySelector('.count');
        if (countSpan) countSpan.textContent = count;
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
            delete this.summaryBranchStyles[summaryData.summaryNodeId];
        }

        this.summaryRenderer.removeSummary(summaryId);
        this.summaries.splice(summaryIndex, 1);
        this._updateStatus(_t('Summary deleted'));
    }

    // ===== Re-render All Features =====
    _renderAllXMindFeatures() {
        const nodes = this.jm.mind.nodes;
        for (let id in nodes) {
            const node = nodes[id];
            const element = this.jm.view.get_node_element(id);
            if (element && node.data) {
                if (node.data.shape) this._applyShapeToNode(element, node.data.shape);
                if (node.data.style) this._restoreNodeStyle(element, node.data.style);
                if (node.data.markers && node.data.markers.length > 0) this.markerBadgeRenderer.renderMarkers(element, node.data.markers, this.markers);
                if (node.data.labels && node.data.labels.length > 0) this.labelRenderer.renderLabels(element, node.data.labels);
                if (node.data.note) this.noteIndicator.addIndicator(element, true);
                if (node.data.hyperlink) this.hyperlinkIndicator.addIndicator(element, node.data.hyperlink, node.data.hyperlinkTitle);
                if (node.data.attachments && node.data.attachments.length > 0) this.attachmentIndicator.addIndicator(element, node.data.attachments.length);
                if (node.data.image) this.imageRenderer.renderImage(element, node.data.image.data, node.data.image.options);
            }
        }

        this.boundaryRenderer.clear();
        for (let boundary of this.boundaries) {
            const elements = boundary.topicIds.map(id => this.jm.view.get_node_element(id)).filter(e => e);
            if (elements.length > 0) this.boundaryRenderer.addBoundary(elements, boundary.options);
        }

        this.summaryRenderer.clear();
        for (let summary of this.summaries) {
            const topicElements = summary.topicIds.map(id => this.jm.view.get_node_element(id)).filter(e => e);
            const summaryElement = this.jm.view.get_node_element(summary.summaryNodeId);
            if (topicElements.length > 0 && summaryElement) this.summaryRenderer.addSummary(topicElements, summaryElement);
        }

        // Use advancedRelationshipManager (with control points) instead of basic renderer
        this.advancedRelationshipManager.clear();
        for (let rel of this.relationships) {
            const sourceElement = this.jm.view.get_node_element(rel.sourceId);
            const targetElement = this.jm.view.get_node_element(rel.targetId);
            if (sourceElement && targetElement) {
                this.advancedRelationshipManager.addRelationship(sourceElement, targetElement, rel.options);
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
        const nodes = panel.querySelectorAll('.jmnode');
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
        const panel = this.jm.view.e_panel;
        if (!panel) return;

        const level = this._zoomLevel || 1;
        panel.style.transform = `scale(${level})`;
        panel.style.transformOrigin = 'center center';

        const zoomEl = this._el('.o_mindmap_zoom_level');
        if (zoomEl) zoomEl.textContent = Math.round(level * 100) + '%';
    }

    // ===== Global Context Menu =====
    _setupContextMenu() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        canvas.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            e.stopPropagation();

            // Remove existing context menus
            document.querySelectorAll('.o_xmind_context_menu').forEach(el => el.remove());

            // Check if right-clicking on a relationship line
            const relPath = e.target.closest('.relationship-path');
            const relGroup = relPath ? relPath.closest('g[data-rel-id]') : null;

            if (relGroup) {
                this._showRelationshipContextMenu(e, relGroup.getAttribute('data-rel-id'));
                return;
            }

            const nodeElement = e.target.closest('.jmnode');
            if (nodeElement) {
                this._showNodeContextMenu(e, nodeElement);
            } else {
                this._showCanvasContextMenu(e);
            }
        });
    }

    _showNodeContextMenu(e, nodeElement) {
        const nodeId = nodeElement.getAttribute('nodeid');
        const node = this.jm.get_node(nodeId);
        if (!node) return;

        const isRoot = node.isroot;

        const menu = document.createElement('div');
        menu.className = 'o_xmind_context_menu dropdown-menu show';
        menu.style.cssText = `position: fixed; left: ${e.clientX}px; top: ${e.clientY}px; z-index: 10000;`;

        const items = [
            { icon: 'fa-plus', label: _t('Add Child (Tab)'), action: 'addChild', disabled: false },
            { icon: 'fa-plus', label: _t('Add Sibling (Enter)'), action: 'addSibling', disabled: isRoot },
            { icon: 'fa-level-up', label: _t('Add Before (Shift+Enter)'), action: 'addBefore', disabled: isRoot },
            { icon: 'fa-level-down', label: _t('Add Parent (Ctrl+Enter)'), action: 'addParent', disabled: isRoot },
            { icon: 'fa-pencil', label: _t('Edit (F2)'), action: 'edit', disabled: false },
            { divider: true },
            { icon: 'fa-arrow-up', label: _t('Move Up (Alt+↑)'), action: 'moveUp', disabled: isRoot },
            { icon: 'fa-arrow-down', label: _t('Move Down (Alt+↓)'), action: 'moveDown', disabled: isRoot },
            { divider: true },
            { icon: 'fa-copy', label: _t('Copy Topic (Ctrl+C)'), action: 'copyTopic', disabled: false },
            { icon: 'fa-paste', label: _t('Paste Topic (Ctrl+V)'), action: 'pasteTopic', disabled: !this._clipboardTopic },
            { icon: 'fa-clone', label: _t('Copy Style'), action: 'copyStyle', disabled: false },
            { icon: 'fa-paint-brush', label: _t('Paste Style'), action: 'pasteStyle', disabled: !this._copiedStyle },
            { divider: true },
            { icon: 'fa-search-plus', label: _t('Drill Down'), action: 'drillDown', disabled: !node.children || node.children.length === 0 },
            { icon: 'fa-search-minus', label: _t('Drill Up'), action: 'drillUp', disabled: !this._drillStack || this._drillStack.length === 0 },
            { divider: true },
            { icon: 'fa-link', label: _t('Add Relationship'), action: 'relationship', disabled: false },
            { icon: 'fa-square-o', label: _t('Add Boundary'), action: 'boundary', disabled: false },
            { icon: 'fa-indent', label: _t('Add Summary'), action: 'summary', disabled: isRoot },
            { icon: 'fa-comment', label: _t('Add Callout'), action: 'callout', disabled: false },
            { divider: true },
            { icon: 'fa-flag', label: _t('Add Marker'), action: 'marker', disabled: false },
            { icon: 'fa-link', label: _t('Insert Hyperlink'), action: 'hyperlink', disabled: false },
            { icon: 'fa-sticky-note', label: _t('Edit Note'), action: 'note', disabled: false },
            { icon: 'fa-image', label: _t('Insert Image'), action: 'image', disabled: false },
            { divider: true },
            { icon: 'fa-expand', label: node.expanded ? _t('Collapse') : _t('Expand'), action: 'toggle', disabled: !node.children || node.children.length === 0 },
            { divider: true },
            { icon: 'fa-sort-alpha-asc', label: _t('Sort A→Z'), action: 'sortAsc', disabled: !node.children || node.children.length < 2 },
            { icon: 'fa-sort-alpha-desc', label: _t('Sort Z→A'), action: 'sortDesc', disabled: !node.children || node.children.length < 2 },
            { icon: 'fa-sort-numeric-asc', label: _t('Sort by Priority'), action: 'sortPriority', disabled: !node.children || node.children.length < 2 },
            { divider: true },
            { icon: 'fa-users', label: _t('Select Siblings'), action: 'selectSiblings', disabled: isRoot },
            { icon: 'fa-level-down', label: _t('Select Children'), action: 'selectChildren', disabled: !node.children || node.children.length === 0 },
            { divider: true },
            { icon: 'fa-trash text-danger', label: _t('Delete'), action: 'delete', disabled: isRoot, cls: 'text-danger' },
        ];

        for (const item of items) {
            if (item.divider) {
                menu.insertAdjacentHTML('beforeend', '<div class="dropdown-divider"></div>');
                continue;
            }
            const a = document.createElement('a');
            a.className = `dropdown-item ${item.disabled ? 'disabled' : ''} ${item.cls || ''}`;
            a.href = '#';
            a.innerHTML = `<i class="fa ${item.icon} me-2" style="width:16px;text-align:center;"></i>${item.label}`;
            if (!item.disabled) {
                a.addEventListener('click', (ev) => {
                    ev.preventDefault();
                    menu.remove();
                    this._handleContextAction(item.action, nodeId);
                });
            }
            menu.appendChild(a);
        }

        document.body.appendChild(menu);
        this._clampMenuPosition(menu);

        setTimeout(() => {
            document.addEventListener('click', () => menu.remove(), { once: true });
        }, 10);
    }

    _showCanvasContextMenu(e) {
        const menu = document.createElement('div');
        menu.className = 'o_xmind_context_menu dropdown-menu show';
        menu.style.cssText = `position: fixed; left: ${e.clientX}px; top: ${e.clientY}px; z-index: 10000;`;

        const items = [
            { icon: 'fa-plus-circle', label: _t('Add Floating Topic'), action: 'floatingAt' },
            { divider: true },
            { icon: 'fa-expand', label: _t('Expand All'), action: 'expandAll' },
            { icon: 'fa-compress', label: _t('Collapse All'), action: 'collapseAll' },
            { divider: true },
            { icon: 'fa-search-plus', label: _t('Zoom In'), action: 'zoomIn' },
            { icon: 'fa-search-minus', label: _t('Zoom Out'), action: 'zoomOut' },
            { icon: 'fa-arrows-alt', label: _t('Fit to View'), action: 'zoomFit' },
            { icon: 'fa-compress', label: _t('Actual Size'), action: 'zoomReset' },
            { icon: 'fa-crosshairs', label: _t('Fit Selection'), action: 'zoomFitSelection' },
            { divider: true },
            { icon: 'fa-save', label: _t('Save (Ctrl+S)'), action: 'save' },
            { divider: true },
            { icon: 'fa-eye', label: _t('Overview Panel'), action: 'overview' },
            { icon: 'fa-list', label: _t('Outline Panel'), action: 'outline' },
            { icon: 'fa-paint-brush', label: _t('Theme Manager'), action: 'themes' },
            { icon: 'fa-file-text-o', label: _t('Load Template'), action: 'template' },
            { icon: 'fa-history', label: _t('Revisions'), action: 'revisions' },
        ];

        for (const item of items) {
            if (item.divider) {
                menu.insertAdjacentHTML('beforeend', '<div class="dropdown-divider"></div>');
                continue;
            }
            const a = document.createElement('a');
            a.className = 'dropdown-item';
            a.href = '#';
            a.innerHTML = `<i class="fa ${item.icon} me-2" style="width:16px;text-align:center;"></i>${item.label}`;
            a.addEventListener('click', (ev) => {
                ev.preventDefault();
                menu.remove();
                this._handleContextAction(item.action, null, e);
            });
            menu.appendChild(a);
        }

        document.body.appendChild(menu);
        this._clampMenuPosition(menu);

        setTimeout(() => {
            document.addEventListener('click', () => menu.remove(), { once: true });
        }, 10);
    }

    _showRelationshipContextMenu(e, relId) {
        const relData = this.relationships.find(r => r.id === relId);
        if (!relData) return;

        const menu = document.createElement('div');
        menu.className = 'o_xmind_context_menu dropdown-menu show';
        menu.style.cssText = `position: fixed; left: ${e.clientX}px; top: ${e.clientY}px; z-index: 10000;`;

        const items = [
            { icon: 'fa-pencil', label: _t('Edit Properties'), action: 'edit' },
            { icon: 'fa-hand-pointer-o', label: _t('Show Control Points'), action: 'controlPoints' },
            { divider: true },
            { icon: 'fa-trash text-danger', label: _t('Delete Relationship'), action: 'delete', cls: 'text-danger' },
        ];

        for (const item of items) {
            if (item.divider) {
                menu.insertAdjacentHTML('beforeend', '<div class="dropdown-divider"></div>');
                continue;
            }
            const a = document.createElement('a');
            a.className = `dropdown-item ${item.cls || ''}`;
            a.href = '#';
            a.innerHTML = `<i class="fa ${item.icon} me-2" style="width:16px;text-align:center;"></i>${item.label}`;
            a.addEventListener('click', (ev) => {
                ev.preventDefault();
                menu.remove();
                if (item.action === 'edit') {
                    this._showRelationshipPropertiesDialog(relData.sourceId, relData.targetId, relId);
                } else if (item.action === 'controlPoints') {
                    this.advancedRelationshipManager.selectRelationship(relId);
                    this._updateStatus(_t('Drag green points to adjust curve'));
                } else if (item.action === 'delete') {
                    this.advancedRelationshipManager.removeRelationship(relId);
                    const idx = this.relationships.findIndex(r => r.id === relId);
                    if (idx > -1) this.relationships.splice(idx, 1);
                    this.commandStack.isDirty = true;
                    this.commandStack._notifyListeners();
                    this._updateStatus(_t('Relationship deleted'));
                }
            });
            menu.appendChild(a);
        }

        document.body.appendChild(menu);
        this._clampMenuPosition(menu);
        setTimeout(() => {
            document.addEventListener('click', () => menu.remove(), { once: true });
        }, 10);
    }

    _clampMenuPosition(menu) {
        const rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth) {
            menu.style.left = (window.innerWidth - rect.width - 5) + 'px';
        }
        if (rect.bottom > window.innerHeight) {
            menu.style.top = (window.innerHeight - rect.height - 5) + 'px';
        }
    }

    _handleContextAction(action, nodeId, originalEvent) {
        switch (action) {
            case 'addChild':
                if (nodeId) this.jm.select_node(nodeId);
                this.selectedNode = nodeId;
                this.onAddChild();
                break;
            case 'addSibling':
                if (nodeId) this.jm.select_node(nodeId);
                this.selectedNode = nodeId;
                this.onAddSibling();
                break;
            case 'addBefore':
                this.selectedNode = nodeId;
                this.onAddTopicBefore();
                break;
            case 'addParent':
                this.selectedNode = nodeId;
                this.onAddParentTopic();
                break;
            case 'edit':
                this.selectedNode = nodeId;
                this._editSelectedNode();
                break;
            case 'moveUp':
                this.selectedNode = nodeId;
                this.onMoveUp();
                break;
            case 'moveDown':
                this.selectedNode = nodeId;
                this.onMoveDown();
                break;
            case 'copyTopic':
                this.selectedNode = nodeId;
                this.onCopyTopic();
                break;
            case 'pasteTopic':
                this.selectedNode = nodeId;
                this.onPasteTopic();
                break;
            case 'drillDown':
                this.selectedNode = nodeId;
                this.onDrillDown();
                break;
            case 'drillUp':
                this.onDrillUp();
                break;
            case 'sortAsc':
                this.selectedNode = nodeId;
                this.onSortAscending();
                break;
            case 'sortDesc':
                this.selectedNode = nodeId;
                this.onSortDescending();
                break;
            case 'sortPriority':
                this.selectedNode = nodeId;
                this.onSortByPriority();
                break;
            case 'selectSiblings':
                this.selectedNode = nodeId;
                this.onSelectSiblings();
                break;
            case 'selectChildren':
                this.selectedNode = nodeId;
                this.onSelectChildren();
                break;
            case 'copyStyle':
                this._copyNodeStyle(nodeId);
                break;
            case 'pasteStyle':
                this._pasteNodeStyle(nodeId);
                break;
            case 'relationship':
                this.selectedNode = nodeId;
                this.onAddRelationship();
                break;
            case 'boundary':
                this.selectedNode = nodeId;
                this.onAddBoundary();
                break;
            case 'summary':
                this.selectedNode = nodeId;
                this.onAddSummary();
                break;
            case 'callout':
                this.selectedNode = nodeId;
                this.onAddCallout();
                break;
            case 'marker':
                this.selectedNode = nodeId;
                this.onOpenMarker();
                break;
            case 'hyperlink':
                this.selectedNode = nodeId;
                this.onInsertHyperlink({ preventDefault: () => {} });
                break;
            case 'note':
                this.selectedNode = nodeId;
                this.onOpenNote();
                break;
            case 'image':
                this.selectedNode = nodeId;
                this.onAddImage();
                break;
            case 'toggle':
                this.selectedNode = nodeId;
                this._toggleSelectedExpand();
                break;
            case 'delete':
                this.selectedNode = nodeId;
                this.onDelete();
                break;
            case 'floatingAt':
                if (originalEvent) {
                    const canvas = this.canvasRef.el;
                    const rect = canvas.getBoundingClientRect();
                    const x = originalEvent.clientX - rect.left;
                    const y = originalEvent.clientY - rect.top;
                    this._createFloatingTopicAt(_t('Floating Topic'), '', x, y);
                } else {
                    this.onAddFloatingTopic();
                }
                break;
            case 'expandAll': this.onExpandAll(); break;
            case 'collapseAll': this.onCollapseAll(); break;
            case 'zoomIn': this.onZoomIn(); break;
            case 'zoomOut': this.onZoomOut(); break;
            case 'zoomFit': this.onZoomFit(); break;
            case 'zoomReset': this.onZoomReset(); break;
            case 'save': this.onSave(); break;
            case 'zoomFitSelection': this.onZoomFitSelection(); break;
            case 'overview': this.onToggleOverview(); break;
            case 'outline': this.onToggleOutline(); break;
            case 'themes': this.onManageThemes(); break;
            case 'template': this.onLoadTemplate(); break;
            case 'revisions': this.onToggleRevisions(); break;
    }

    _copyNodeStyle(nodeId) {
        const node = this.jm.get_node(nodeId);
        if (!node) return;
        this._copiedStyle = JSON.parse(JSON.stringify(node.data && node.data.style || {}));
        if (node.data && node.data.shape) {
            this._copiedStyle._shape = JSON.parse(JSON.stringify(node.data.shape));
        }
        this._updateStatus(_t('Style copied'));
    }

    _pasteNodeStyle(nodeId) {
        if (!this._copiedStyle) return;
        const node = this.jm.get_node(nodeId);
        if (!node) return;

        const element = this.jm.view.get_node_element(nodeId);
        if (!element) return;

        node.data = node.data || {};
        const style = { ...this._copiedStyle };
        const shape = style._shape;
        delete style._shape;

        node.data.style = style;
        this._restoreNodeStyle(element, style);

        if (shape) {
            node.data.shape = shape;
            this._applyShapeToNode(element, shape);
        }

        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Style pasted'));
    }

    _createFloatingTopicAt(title, note, x, y) {
        const canvas = this.canvasRef.el;
        const floatingDiv = document.createElement('div');
        floatingDiv.className = 'xmind-floating-topic';
        floatingDiv.style.cssText = `position: absolute; left: ${x}px; top: ${y}px; background: #e0e0e0; padding: 10px 16px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); cursor: move; z-index: 20;`;
        floatingDiv.textContent = title;
        if (note) floatingDiv.title = note;

        let isDragging = false, offsetX, offsetY;
        floatingDiv.addEventListener('mousedown', (e) => {
            isDragging = true;
            offsetX = e.clientX - floatingDiv.offsetLeft;
            offsetY = e.clientY - floatingDiv.offsetTop;
        });
        document.addEventListener('mousemove', (e) => {
            if (isDragging) {
                floatingDiv.style.left = (e.clientX - offsetX) + 'px';
                floatingDiv.style.top = (e.clientY - offsetY) + 'px';
            }
        });
        document.addEventListener('mouseup', () => { isDragging = false; });

        canvas.appendChild(floatingDiv);
        this.floatingTopics.push({ element: floatingDiv, title, note });
        this.commandStack.isDirty = true;
        this.commandStack._notifyListeners();
        this._updateStatus(_t('Floating topic added'));
    }

    // ===== Template System =====
    async onLoadTemplate() {
        const templates = await this._getTemplates();
        this._showTemplateDialog(templates);
    }

    _getTemplates() {
        return [
            {
                id: 'blank',
                name: _t('Blank Mind Map'),
                category: 'basic',
                icon: 'fa-file-o',
                data: this._getDefaultData(),
            },
            {
                id: 'business_plan',
                name: _t('Business Plan'),
                category: 'business',
                icon: 'fa-briefcase',
                data: this._buildTemplate('Business Plan', [
                    { topic: _t('Market Analysis'), children: [_t('Target Market'), _t('Competitors'), _t('Market Size')] },
                    { topic: _t('Products & Services'), children: [_t('Core Product'), _t('Value Proposition'), _t('Pricing')] },
                    { topic: _t('Marketing Strategy'), children: [_t('Channels'), _t('Campaigns'), _t('Budget')] },
                    { topic: _t('Financial Plan'), children: [_t('Revenue Model'), _t('Cost Structure'), _t('Projections')] },
                    { topic: _t('Team'), children: [_t('Key Roles'), _t('Hiring Plan'), _t('Advisors')] },
                ]),
            },
            {
                id: 'swot',
                name: _t('SWOT Analysis'),
                category: 'business',
                icon: 'fa-th-large',
                data: this._buildTemplate('SWOT Analysis', [
                    { topic: _t('Strengths'), children: [_t('Strength 1'), _t('Strength 2'), _t('Strength 3')], style: { background: '#28a745', color: '#fff' } },
                    { topic: _t('Weaknesses'), children: [_t('Weakness 1'), _t('Weakness 2'), _t('Weakness 3')], style: { background: '#dc3545', color: '#fff' } },
                    { topic: _t('Opportunities'), children: [_t('Opportunity 1'), _t('Opportunity 2'), _t('Opportunity 3')], style: { background: '#007bff', color: '#fff' } },
                    { topic: _t('Threats'), children: [_t('Threat 1'), _t('Threat 2'), _t('Threat 3')], style: { background: '#ffc107', color: '#333' } },
                ]),
            },
            {
                id: 'meeting',
                name: _t('Meeting Notes'),
                category: 'business',
                icon: 'fa-users',
                data: this._buildTemplate('Meeting Notes', [
                    { topic: _t('Attendees'), children: [_t('Person 1'), _t('Person 2')] },
                    { topic: _t('Agenda'), children: [_t('Item 1'), _t('Item 2'), _t('Item 3')] },
                    { topic: _t('Discussion'), children: [_t('Point 1'), _t('Point 2')] },
                    { topic: _t('Action Items'), children: [_t('Task 1'), _t('Task 2')] },
                    { topic: _t('Next Meeting'), children: [_t('Date'), _t('Topics')] },
                ]),
            },
            {
                id: 'project',
                name: _t('Project Dashboard'),
                category: 'business',
                icon: 'fa-tasks',
                data: this._buildTemplate('Project Dashboard', [
                    { topic: _t('Goals'), children: [_t('Goal 1'), _t('Goal 2')] },
                    { topic: _t('Milestones'), children: [_t('Phase 1'), _t('Phase 2'), _t('Phase 3')] },
                    { topic: _t('Resources'), children: [_t('Team'), _t('Budget'), _t('Tools')] },
                    { topic: _t('Risks'), children: [_t('Risk 1'), _t('Risk 2')] },
                    { topic: _t('Timeline'), children: [_t('Start'), _t('Checkpoints'), _t('Deadline')] },
                ]),
            },
            {
                id: 'cause_effect',
                name: _t('Cause & Effect (Fishbone)'),
                category: 'business',
                icon: 'fa-sitemap',
                data: this._buildTemplate('Problem Statement', [
                    { topic: _t('People'), children: [_t('Training'), _t('Communication')] },
                    { topic: _t('Process'), children: [_t('Workflow'), _t('Standards')] },
                    { topic: _t('Technology'), children: [_t('Systems'), _t('Tools')] },
                    { topic: _t('Environment'), children: [_t('Culture'), _t('Resources')] },
                ]),
            },
            {
                id: 'book_report',
                name: _t('Book Report'),
                category: 'education',
                icon: 'fa-book',
                data: this._buildTemplate('Book Title', [
                    { topic: _t('Author'), children: [_t('Background'), _t('Other Works')] },
                    { topic: _t('Characters'), children: [_t('Protagonist'), _t('Antagonist'), _t('Supporting')] },
                    { topic: _t('Plot'), children: [_t('Beginning'), _t('Climax'), _t('Resolution')] },
                    { topic: _t('Themes'), children: [_t('Theme 1'), _t('Theme 2')] },
                    { topic: _t('My Opinion'), children: [_t('Liked'), _t('Disliked'), _t('Rating')] },
                ]),
            },
            {
                id: 'study_plan',
                name: _t('Study Plan'),
                category: 'education',
                icon: 'fa-graduation-cap',
                data: this._buildTemplate('Study Plan', [
                    { topic: _t('Subjects'), children: [_t('Subject 1'), _t('Subject 2'), _t('Subject 3')] },
                    { topic: _t('Schedule'), children: [_t('Morning'), _t('Afternoon'), _t('Evening')] },
                    { topic: _t('Resources'), children: [_t('Textbooks'), _t('Online'), _t('Notes')] },
                    { topic: _t('Goals'), children: [_t('Short-term'), _t('Long-term')] },
                ]),
            },
            {
                id: 'travel_plan',
                name: _t('Travel Plan'),
                category: 'personal',
                icon: 'fa-plane',
                data: this._buildTemplate('Travel Plan', [
                    { topic: _t('Destination'), children: [_t('Places to Visit'), _t('Activities')] },
                    { topic: _t('Logistics'), children: [_t('Flights'), _t('Hotels'), _t('Transport')] },
                    { topic: _t('Budget'), children: [_t('Transportation'), _t('Accommodation'), _t('Food'), _t('Activities')] },
                    { topic: _t('Packing'), children: [_t('Essentials'), _t('Clothing'), _t('Documents')] },
                ]),
            },
            {
                id: 'weekly_plan',
                name: _t('Weekly Plan'),
                category: 'personal',
                icon: 'fa-calendar',
                data: this._buildTemplate('This Week', [
                    { topic: _t('Monday'), children: [_t('Task 1'), _t('Task 2')] },
                    { topic: _t('Tuesday'), children: [_t('Task 1'), _t('Task 2')] },
                    { topic: _t('Wednesday'), children: [_t('Task 1'), _t('Task 2')] },
                    { topic: _t('Thursday'), children: [_t('Task 1'), _t('Task 2')] },
                    { topic: _t('Friday'), children: [_t('Task 1'), _t('Task 2')] },
                ]),
            },
            {
                id: 'resume',
                name: _t('Resume / CV'),
                category: 'personal',
                icon: 'fa-id-card',
                data: this._buildTemplate('My Name', [
                    { topic: _t('Contact Info'), children: [_t('Email'), _t('Phone'), _t('Location')] },
                    { topic: _t('Experience'), children: [_t('Company 1'), _t('Company 2')] },
                    { topic: _t('Education'), children: [_t('Degree 1'), _t('Degree 2')] },
                    { topic: _t('Skills'), children: [_t('Technical'), _t('Soft Skills'), _t('Languages')] },
                    { topic: _t('Projects'), children: [_t('Project 1'), _t('Project 2')] },
                ]),
            },
            // ===== Additional Business Templates =====
            {
                id: 'annual_report', name: _t('Annual Report'), category: 'business', icon: 'fa-bar-chart',
                data: this._buildTemplate('Annual Report 2024', [
                    { topic: _t('Executive Summary'), children: [_t('Highlights'), _t('KPIs')] },
                    { topic: _t('Financial Results'), children: [_t('Revenue'), _t('Expenses'), _t('Profit')] },
                    { topic: _t('Operations'), children: [_t('Production'), _t('Quality'), _t('Efficiency')] },
                    { topic: _t('Market Overview'), children: [_t('Market Share'), _t('Growth'), _t('Trends')] },
                    { topic: _t('Outlook'), children: [_t('Goals'), _t('Investments'), _t('Risks')] },
                ]),
            },
            {
                id: 'balance_sheet', name: _t('Balance Sheet'), category: 'business', icon: 'fa-balance-scale',
                data: this._buildTemplate('Balance Sheet', [
                    { topic: _t('Assets'), children: [_t('Current Assets'), _t('Fixed Assets'), _t('Intangible')] },
                    { topic: _t('Liabilities'), children: [_t('Current'), _t('Long-term'), _t('Provisions')] },
                    { topic: _t('Equity'), children: [_t('Share Capital'), _t('Retained Earnings')] },
                ]),
            },
            {
                id: 'business_timeline', name: _t('Business Timeline'), category: 'business', icon: 'fa-clock-o',
                data: this._buildTemplate('Company Timeline', [
                    { topic: _t('Q1'), children: [_t('Jan'), _t('Feb'), _t('Mar')] },
                    { topic: _t('Q2'), children: [_t('Apr'), _t('May'), _t('Jun')] },
                    { topic: _t('Q3'), children: [_t('Jul'), _t('Aug'), _t('Sep')] },
                    { topic: _t('Q4'), children: [_t('Oct'), _t('Nov'), _t('Dec')] },
                ]),
            },
            {
                id: 'company_hierarchy', name: _t('Company Hierarchy'), category: 'business', icon: 'fa-sitemap',
                data: this._buildTemplate('CEO', [
                    { topic: _t('CTO'), children: [_t('Engineering'), _t('Product'), _t('QA')] },
                    { topic: _t('CFO'), children: [_t('Accounting'), _t('Finance'), _t('Legal')] },
                    { topic: _t('COO'), children: [_t('Operations'), _t('HR'), _t('Admin')] },
                    { topic: _t('CMO'), children: [_t('Marketing'), _t('Sales'), _t('PR')] },
                ]),
            },
            {
                id: 'manufacturing_flow', name: _t('Manufacturing Flow'), category: 'business', icon: 'fa-industry',
                data: this._buildTemplate('Manufacturing Process', [
                    { topic: _t('Raw Materials'), children: [_t('Sourcing'), _t('Inventory'), _t('Quality Check')] },
                    { topic: _t('Production'), children: [_t('Assembly'), _t('Testing'), _t('Packaging')] },
                    { topic: _t('Distribution'), children: [_t('Warehouse'), _t('Shipping'), _t('Delivery')] },
                ]),
            },
            {
                id: 'sales_mgmt', name: _t('Sales Management'), category: 'business', icon: 'fa-line-chart',
                data: this._buildTemplate('Sales Strategy', [
                    { topic: _t('Pipeline'), children: [_t('Leads'), _t('Opportunities'), _t('Deals')] },
                    { topic: _t('Channels'), children: [_t('Direct'), _t('Partners'), _t('Online')] },
                    { topic: _t('Targets'), children: [_t('Monthly'), _t('Quarterly'), _t('Annual')] },
                    { topic: _t('Team'), children: [_t('Reps'), _t('Managers'), _t('Training')] },
                ]),
            },
            {
                id: 'problem_solving', name: _t('Problem Solving'), category: 'business', icon: 'fa-puzzle-piece',
                data: this._buildTemplate('Problem Statement', [
                    { topic: _t('Root Causes'), children: [_t('Cause 1'), _t('Cause 2'), _t('Cause 3')] },
                    { topic: _t('Impact'), children: [_t('Cost'), _t('Time'), _t('Quality')] },
                    { topic: _t('Solutions'), children: [_t('Option A'), _t('Option B'), _t('Option C')] },
                    { topic: _t('Action Plan'), children: [_t('Step 1'), _t('Step 2'), _t('Step 3')] },
                ]),
            },
            // ===== Additional Education Templates =====
            {
                id: 'class_schedule', name: _t('Class Schedule'), category: 'education', icon: 'fa-calendar-check-o',
                data: this._buildTemplate('Class Schedule', [
                    { topic: _t('Monday'), children: [_t('Math'), _t('Science'), _t('English')] },
                    { topic: _t('Tuesday'), children: [_t('History'), _t('Art'), _t('PE')] },
                    { topic: _t('Wednesday'), children: [_t('Math'), _t('Music'), _t('Science')] },
                    { topic: _t('Thursday'), children: [_t('English'), _t('History'), _t('Lab')] },
                    { topic: _t('Friday'), children: [_t('Math'), _t('Review'), _t('Club')] },
                ]),
            },
            {
                id: 'compare_contrast', name: _t('Compare & Contrast'), category: 'education', icon: 'fa-columns',
                data: this._buildTemplate('Comparison', [
                    { topic: _t('Subject A'), children: [_t('Feature 1'), _t('Feature 2'), _t('Feature 3')], style: { background: '#007bff', color: '#fff' } },
                    { topic: _t('Similarities'), children: [_t('Common 1'), _t('Common 2')] },
                    { topic: _t('Subject B'), children: [_t('Feature 1'), _t('Feature 2'), _t('Feature 3')], style: { background: '#28a745', color: '#fff' } },
                ]),
            },
            {
                id: 'paper_outline', name: _t('Paper Outline'), category: 'education', icon: 'fa-file-text',
                data: this._buildTemplate('Paper Title', [
                    { topic: _t('Introduction'), children: [_t('Hook'), _t('Background'), _t('Thesis')] },
                    { topic: _t('Body'), children: [_t('Argument 1'), _t('Argument 2'), _t('Argument 3')] },
                    { topic: _t('Counter-arguments'), children: [_t('Objection 1'), _t('Rebuttal')] },
                    { topic: _t('Conclusion'), children: [_t('Summary'), _t('Implications'), _t('Call to Action')] },
                    { topic: _t('References'), children: [_t('Source 1'), _t('Source 2')] },
                ]),
            },
            {
                id: 'exam_review', name: _t('Exam Review'), category: 'education', icon: 'fa-check-square',
                data: this._buildTemplate('Final Exam Review', [
                    { topic: _t('Chapter 1'), children: [_t('Key Concepts'), _t('Formulas'), _t('Practice')] },
                    { topic: _t('Chapter 2'), children: [_t('Key Concepts'), _t('Formulas'), _t('Practice')] },
                    { topic: _t('Chapter 3'), children: [_t('Key Concepts'), _t('Formulas'), _t('Practice')] },
                    { topic: _t('Study Tips'), children: [_t('Flash Cards'), _t('Group Study'), _t('Past Papers')] },
                ]),
            },
            {
                id: 'syllabus', name: _t('Syllabus'), category: 'education', icon: 'fa-graduation-cap',
                data: this._buildTemplate('Course Name', [
                    { topic: _t('Instructor'), children: [_t('Name'), _t('Office Hours'), _t('Contact')] },
                    { topic: _t('Schedule'), children: [_t('Week 1-4'), _t('Week 5-8'), _t('Week 9-12')] },
                    { topic: _t('Grading'), children: [_t('Homework 30%'), _t('Midterm 30%'), _t('Final 40%')] },
                    { topic: _t('Resources'), children: [_t('Textbook'), _t('Online'), _t('Library')] },
                ]),
            },
            // ===== Additional Personal Templates =====
            {
                id: 'diet_plan', name: _t('Diet Plan'), category: 'personal', icon: 'fa-cutlery',
                data: this._buildTemplate('Diet Plan', [
                    { topic: _t('Breakfast'), children: [_t('Option 1'), _t('Option 2')] },
                    { topic: _t('Lunch'), children: [_t('Option 1'), _t('Option 2')] },
                    { topic: _t('Dinner'), children: [_t('Option 1'), _t('Option 2')] },
                    { topic: _t('Snacks'), children: [_t('Healthy'), _t('Treats')] },
                    { topic: _t('Goals'), children: [_t('Calories'), _t('Nutrition'), _t('Exercise')] },
                ]),
            },
            {
                id: 'party_prep', name: _t('Party Preparation'), category: 'personal', icon: 'fa-glass',
                data: this._buildTemplate('Party Plan', [
                    { topic: _t('Guest List'), children: [_t('Friends'), _t('Family'), _t('Colleagues')] },
                    { topic: _t('Venue'), children: [_t('Location'), _t('Decoration'), _t('Setup')] },
                    { topic: _t('Food & Drinks'), children: [_t('Menu'), _t('Beverages'), _t('Desserts')] },
                    { topic: _t('Entertainment'), children: [_t('Music'), _t('Games'), _t('Activities')] },
                    { topic: _t('Budget'), children: [_t('Venue'), _t('Food'), _t('Other')] },
                ]),
            },
            {
                id: 'shopping_list', name: _t('Shopping List'), category: 'personal', icon: 'fa-shopping-cart',
                data: this._buildTemplate('Shopping List', [
                    { topic: _t('Groceries'), children: [_t('Fruits'), _t('Vegetables'), _t('Dairy'), _t('Meat')] },
                    { topic: _t('Household'), children: [_t('Cleaning'), _t('Kitchen'), _t('Bathroom')] },
                    { topic: _t('Electronics'), children: [_t('Accessories'), _t('Cables')] },
                    { topic: _t('Clothing'), children: [_t('Tops'), _t('Bottoms'), _t('Shoes')] },
                ]),
            },
        ];
    }

    _buildTemplate(rootTopic, branches) {
        const children = branches.map((branch, i) => {
            const childNodes = (branch.children || []).map((childTopic, j) => ({
                id: `node_t_${i}_${j}`,
                topic: childTopic,
                expanded: true,
                children: [],
                data: { style: { background: '#f8f9fa', color: '#333333' } },
            }));
            return {
                id: `node_b_${i}`,
                topic: branch.topic,
                expanded: true,
                children: childNodes,
                data: { style: branch.style || { background: '#e9ecef', color: '#333333' } },
            };
        });

        return {
            meta: { name: rootTopic, author: '', version: '1.0' },
            format: 'node_tree',
            data: {
                id: 'root',
                topic: rootTopic,
                expanded: true,
                children: children,
                data: { style: { background: '#428bca', color: '#ffffff', 'font-weight': 'bold', 'font-size': '18px' } },
            },
        };
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
                this.jm.show(template.data);
                this.commandStack.clear();

                // Re-render features
                setTimeout(() => {
                    this._renderAllXMindFeatures();
                    this._updateStatus(_t('Template applied: ') + template.name);
                }, 200);
            },
        });
    }
}

registry.category("actions").add("dobtor_xmind.mindmap_editor", MindmapEditor);
