/**
 * XMind 2 Style Mind Map Editor for Odoo
 * Implements XMind 2's editing features with Command Pattern
 */
odoo.define('dobtor_xmind.MindmapEditor', function (require) {
    "use strict";

    const AbstractAction = require('web.AbstractAction');
    const core = require('web.core');
    const rpc = require('web.rpc');
    const Dialog = require('web.Dialog');
    const CommandModule = require('dobtor_xmind.CommandStack');
    const XMindFeatures = require('dobtor_xmind.XMindFeatures');
    const DragDropManager = require('dobtor_xmind.DragDropManager');
    const RelationshipManager = require('dobtor_xmind.RelationshipManager');
    const QWeb = core.qweb;
    const _t = core._t;

    const MindmapEditor = AbstractAction.extend({
        template: 'dobtor_xmind.MindmapEditor',
        hasControlPanel: false,
        loadControlPanel: false,

        events: {
            'click .o_mindmap_btn_undo': '_onUndo',
            'click .o_mindmap_btn_redo': '_onRedo',
            'click .o_mindmap_btn_add_child': '_onAddChild',
            'click .o_mindmap_btn_add_sibling': '_onAddSibling',
            'click .o_mindmap_btn_delete': '_onDelete',
            'click .o_mindmap_btn_expand_all': '_onExpandAll',
            'click .o_mindmap_btn_collapse_all': '_onCollapseAll',
            'click .o_mindmap_btn_note': '_onOpenNote',
            'click .o_mindmap_btn_marker': '_onOpenMarker',
            'click .o_mindmap_btn_relationship': '_onAddRelationship',
            'click .o_mindmap_btn_boundary': '_onAddBoundary',
            'click .o_mindmap_btn_summary': '_onAddSummary',
            'click .o_mindmap_btn_callout': '_onAddCallout',
            'click .o_mindmap_btn_floating': '_onAddFloatingTopic',
            'click .o_mindmap_btn_image': '_onAddImage',
            'click .o_mindmap_insert_image': '_onInsertImage',
            'click .o_mindmap_insert_hyperlink': '_onInsertHyperlink',
            'click .o_mindmap_insert_note': '_onInsertNote',
            'click .o_mindmap_insert_attachment': '_onInsertAttachment',
            'click .o_mindmap_btn_save': '_onSave',
            'click .o_mindmap_btn_export': '_onExport',
            'click .o_mindmap_sidebar_close': '_closeSidebar',
            'click .o_topic_hyperlink_open': '_onOpenHyperlink',
            'click .o_topic_change_image': '_onChangeImage',
            'click .o_topic_remove_image': '_onRemoveImage',
            'change .o_mindmap_layout_select': '_onLayoutChange',
            'change .o_mindmap_theme_select': '_onThemeChange',
            'change .o_topic_title': '_onTopicPropertyChange',
            'change .o_topic_bg_color': '_onTopicStyleChange',
            'change .o_topic_text_color': '_onTopicStyleChange',
            'change .o_topic_font_size': '_onTopicStyleChange',
            'change .o_topic_font_weight': '_onTopicStyleChange',
            'change .o_topic_note': '_onTopicNoteChange',
            'input .o_topic_note': '_onTopicNoteInput',
            'change .o_topic_labels': '_onTopicPropertyChange',
            'change .o_topic_hyperlink': '_onTopicHyperlinkChange',
            'change .o_topic_hyperlink_title': '_onTopicHyperlinkChange',
            // Format menu events
            'click .o_format_bold': '_onFormatBold',
            'click .o_format_italic': '_onFormatItalic',
            'click .o_format_underline': '_onFormatUnderline',
            'click .o_format_strikethrough': '_onFormatStrikethrough',
            'click .o_format_apply': '_onFormatApply',
            'click .o_format_apply_all': '_onFormatApplyAll',
            'click .o_format_reset': '_onFormatReset',
            'input .o_format_h_space': '_onFormatHSpaceChange',
            'input .o_format_v_space': '_onFormatVSpaceChange',
            'change .o_format_structure_type': '_onFormatStructureChange',
            // Multi-selection events
            'click .o_mindmap_btn_multiselect': '_onToggleMultiSelect',
            'click .o_mindmap_btn_clear_selection': '_onClearSelection',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.workbookId = action.params && action.params.workbook_id;
            this.jm = null;
            this.commandStack = new CommandModule.CommandStack(200);
            this.selectedNode = null;
            this.autoSaveTimer = null;
            this.markers = [];
            this.relationshipMode = false;
            this.relationshipSource = null;

            // XMind 2 Feature Renderers
            this.relationshipRenderer = null;
            this.boundaryRenderer = null;
            this.summaryRenderer = null;
            this.calloutRenderer = null;
            this.markerBadgeRenderer = new XMindFeatures.MarkerBadgeRenderer();
            this.labelRenderer = new XMindFeatures.LabelRenderer();
            this.noteIndicator = new XMindFeatures.NoteIndicator();
            this.imageRenderer = new XMindFeatures.ImageRenderer();
            this.hyperlinkIndicator = new XMindFeatures.HyperlinkIndicator();
            this.attachmentIndicator = new XMindFeatures.AttachmentIndicator();

            // Feature data
            this.boundaries = [];
            this.summaries = [];
            this.relationships = [];
            this.callouts = [];
            this.floatingTopics = [];
            this.boundarySelectionMode = false;
            this.summarySelectionMode = false;
            this.summaryBranchStyles = {}; // Store branch styles for summary topics
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
            this.selectedNodes = []; // Array of selected node objects
            this.rectangleSelector = null;
        },

        willStart: function () {
            const self = this;
            return this._super.apply(this, arguments).then(function () {
                return Promise.all([
                    self._loadWorkbookData(),
                    self._loadMarkers(),
                ]);
            });
        },

        start: function () {
            const self = this;
            return this._super.apply(this, arguments).then(function () {
                const jmInitSuccess = self._initJsMind();
                if (!jmInitSuccess) {
                    self._updateStatus(_t('Initialization failed'));
                    return;
                }
                self._initXMindFeatures();
                self._setupCommandStackListener();
                self._setupKeyboardShortcuts();
                self._setupAutoSave();
                self._initFormatMenu();
                self._initRectangleSelector();
                self._updateStatus(_t('Ready'));
            });
        },

        _initFormatMenu: function () {
            // Prevent dropdown from closing when clicking inside
            this.$('.o_format_menu').on('click', function (e) {
                e.stopPropagation();
            });

            // Initialize range sliders display
            this.$('.o_format_h_space_val').text(this.$('.o_format_h_space').val() + 'px');
            this.$('.o_format_v_space_val').text(this.$('.o_format_v_space').val() + 'px');
        },

        _initRectangleSelector: function () {
            const self = this;
            const canvas = this.$('.o_mindmap_canvas')[0];

            // Create selection rectangle element
            this.selectionRect = document.createElement('div');
            this.selectionRect.className = 'selection-rectangle';
            this.selectionRect.style.cssText = `
                position: absolute;
                border: 2px dashed #007bff;
                background: rgba(0, 123, 255, 0.1);
                pointer-events: none;
                display: none;
                z-index: 1000;
            `;
            canvas.appendChild(this.selectionRect);

            let isSelecting = false;
            let startX, startY;

            // Mouse events for rectangle selection
            canvas.addEventListener('mousedown', function (e) {
                // Only start rectangle selection if clicking on empty space and not on a node
                if (e.target === canvas || e.target.closest('.o_mindmap_canvas') === canvas && !e.target.closest('jmnode')) {
                    if (e.shiftKey || self.multiSelectMode) {
                        isSelecting = true;
                        const rect = canvas.getBoundingClientRect();
                        startX = e.clientX - rect.left;
                        startY = e.clientY - rect.top;

                        self.selectionRect.style.left = startX + 'px';
                        self.selectionRect.style.top = startY + 'px';
                        self.selectionRect.style.width = '0px';
                        self.selectionRect.style.height = '0px';
                        self.selectionRect.style.display = 'block';

                        e.preventDefault();
                    }
                }
            });

            document.addEventListener('mousemove', function (e) {
                if (!isSelecting) return;

                const rect = canvas.getBoundingClientRect();
                const currentX = e.clientX - rect.left;
                const currentY = e.clientY - rect.top;

                const width = Math.abs(currentX - startX);
                const height = Math.abs(currentY - startY);
                const left = Math.min(currentX, startX);
                const top = Math.min(currentY, startY);

                self.selectionRect.style.left = left + 'px';
                self.selectionRect.style.top = top + 'px';
                self.selectionRect.style.width = width + 'px';
                self.selectionRect.style.height = height + 'px';
            });

            document.addEventListener('mouseup', function (e) {
                if (!isSelecting) return;
                isSelecting = false;
                self.selectionRect.style.display = 'none';

                // Find nodes within selection rectangle
                const selRect = self.selectionRect.getBoundingClientRect();
                self._selectNodesInRect(selRect);
            });

            // Click on node for selection (with Shift for multi-select)
            canvas.addEventListener('click', function (e) {
                const nodeElement = e.target.closest('jmnode');
                if (nodeElement) {
                    const nodeId = nodeElement.getAttribute('nodeid');
                    const node = self.jm.get_node(nodeId);

                    if (e.shiftKey || self.multiSelectMode) {
                        // Toggle selection
                        self._toggleNodeSelection(node);
                    } else {
                        // Single selection (clear others)
                        self._clearMultiSelection();
                        self._addNodeToSelection(node);
                    }
                }
            });
        },

        _initXMindFeatures: function () {
            // Defensive check
            if (!this.jm) {
                console.error('[MindmapEditor] Cannot initialize XMind features: jsMind not initialized');
                return;
            }

            const canvas = this.$('.o_mindmap_canvas')[0];
            if (!canvas) {
                console.error('[MindmapEditor] Canvas element not found');
                return;
            }

            this.relationshipRenderer = new XMindFeatures.RelationshipRenderer(canvas);
            this.advancedRelationshipManager = new RelationshipManager(canvas);
            this.boundaryRenderer = new XMindFeatures.BoundaryRenderer(canvas);
            this.summaryRenderer = new XMindFeatures.SummaryRenderer(canvas);
            this.calloutRenderer = new XMindFeatures.CalloutRenderer(canvas);

            // Set up summary renderer callbacks
            const self = this;
            this.summaryRenderer.setContextMenuCallback((summaryId, event) => {
                self._showSummaryContextMenu(summaryId, event);
            });

            this.summaryRenderer.setClickCallback((summaryId, event) => {
                // Optional: handle click event (e.g., show properties panel)
                self._updateStatus(_t('Summary selected: ') + summaryId);
            });

            // Initialize drag and drop
            this.dragDropManager = new DragDropManager(this.jm, this);
            this.dragDropManager.init();
        },

        destroy: function () {
            if (this.autoSaveTimer) {
                clearInterval(this.autoSaveTimer);
            }
            if (this.dragDropManager) {
                this.dragDropManager.destroy();
            }
            if (this.jm) {
                // Clean up jsMind
            }
            this._super.apply(this, arguments);
        },

        _loadWorkbookData: function () {
            const self = this;
            if (!this.workbookId) {
                this.mindmapData = this._getDefaultData();
                this.sheetSettings = { layout: 'map', theme: 'primary' };
                return Promise.resolve();
            }

            return rpc.query({
                route: '/xmind/workbook/' + this.workbookId + '/data',
                params: {},
            }).then(function (result) {
                if (result.error) {
                    self._showError(result.error);
                    self.mindmapData = self._getDefaultData();
                } else {
                    self.mindmapData = result.mindmap_data;
                    self.sheetSettings = result.sheet_settings || { layout: 'map', theme: 'primary' };
                }
            });
        },

        _loadMarkers: function () {
            const self = this;
            return rpc.query({
                route: '/xmind/markers',
                params: {},
            }).then(function (markers) {
                self.markers = markers;
            });
        },

        _getDefaultData: function () {
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
        },

        _initJsMind: function () {
            const self = this;
            const container = this.$('#jsmind_container')[0];

            // Defensive check: ensure container exists
            if (!container) {
                console.error('[MindmapEditor] Container #jsmind_container not found. Template may not be rendered.');
                this.displayNotification({
                    title: _t('Initialization Error'),
                    message: _t('Mind map container not found. Please refresh the page.'),
                    type: 'danger',
                });
                return false;
            }

            // Additional check: ensure container is a valid DOM node
            console.log('[MindmapEditor] Container type:', Object.prototype.toString.call(container));
            console.log('[MindmapEditor] Container is Node:', container instanceof Node);
            console.log('[MindmapEditor] Container tagName:', container.tagName);

            if (!(container instanceof Node)) {
                console.error('[MindmapEditor] Container is not a valid DOM Node');
                return false;
            }

            // Check for OdooXMind library (our namespaced version)
            // IMPORTANT: Only use OdooXMind to avoid conflicts with other jsMind versions
            console.log('[MindmapEditor] Checking libraries:', {
                OdooXMind: typeof window.OdooXMind,
                jsMind: typeof window.jsMind,
                OdooXMindVersion: window.OdooXMind ? 'custom-odoo' : 'not loaded'
            });

            if (!window.OdooXMind) {
                console.error('[MindmapEditor] OdooXMind library not loaded. Check that dobtor_xmind assets are loaded.');

                // If jsMind exists but OdooXMind doesn't, there's a conflict
                if (window.jsMind) {
                    console.error('[MindmapEditor] WARNING: Another jsMind library is loaded, but OdooXMind is not. This causes conflicts.');
                    console.error('[MindmapEditor] SOLUTION: Clear Odoo asset cache and restart server.');
                }

                this.displayNotification({
                    title: _t('Library Error'),
                    message: _t('Mind map library (OdooXMind) not loaded. Please clear cache and refresh.'),
                    type: 'danger',
                });
                return false;
            }

            // Verify it's our custom version (not the official jsMind which causes conflicts)
            // Our custom version should NOT have any 'align' property issues
            const MindMapClass = window.OdooXMind;
            console.log('[MindmapEditor] Using MindMapClass:', MindMapClass.name || 'jsMind');

            // Quick sanity check - our version should have these characteristics
            if (MindMapClass.toString().includes('textAlign') || MindMapClass.toString().includes('.align')) {
                console.error('[MindmapEditor] WARNING: This appears to be the official jsMind library, not OdooXMind custom version!');
                console.error('[MindmapEditor] The official library has canvas textAlign issues. Please clear all caches.');
            }

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
                    hspace: 30,
                    vspace: 20,
                    pspace: 13,
                },
                shortcut: {
                    enable: false, // We handle shortcuts ourselves
                },
            };

            // Apply layout based on settings
            this._applyLayoutSettings(options);

            try {
                this.jm = new MindMapClass(options);
                this.jm.show(this.mindmapData);
            } catch (error) {
                console.error('[MindmapEditor] Failed to initialize jsMind:', error);
                this.displayNotification({
                    title: _t('Initialization Error'),
                    message: _t('Failed to initialize mind map: ') + error.message,
                    type: 'danger',
                });
                return false;
            }

            // Event handlers
            this.jm.add_event_listener(function (type, data) {
                self._onJsMindEvent(type, data);
            });

            // Setup drag and drop
            this._setupDragDrop();

            // Update theme/layout selectors
            this.$('.o_mindmap_theme_select').val(this.sheetSettings.theme || 'primary');
            this.$('.o_mindmap_layout_select').val(this.sheetSettings.layout || 'map');

            return true;
        },

        _applyLayoutSettings: function (options) {
            const layout = this.sheetSettings.layout || 'map';

            switch (layout) {
                case 'tree_right':
                    options.layout.hspace = 50;
                    options.layout.vspace = 10;
                    break;
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
                default: // map
                    options.layout.hspace = 30;
                    options.layout.vspace = 20;
            }
        },

        _setupCommandStackListener: function () {
            const self = this;
            this.commandStack.addListener(function (state) {
                self._updateUndoRedoButtons(state);
                self._updateCommandCount(state.commandCount);
                if (state.isDirty) {
                    self._updateStatus(_t('Modified'));
                }
            });
        },

        _updateUndoRedoButtons: function (state) {
            this.$('.o_mindmap_btn_undo').prop('disabled', !state.canUndo);
            this.$('.o_mindmap_btn_redo').prop('disabled', !state.canRedo);

            if (state.canUndo) {
                this.$('.o_mindmap_btn_undo').attr('title', _t('Undo: ') + state.undoLabel);
            }
            if (state.canRedo) {
                this.$('.o_mindmap_btn_redo').attr('title', _t('Redo: ') + state.redoLabel);
            }
        },

        _updateCommandCount: function (count) {
            this.$('.o_mindmap_command_count').text(count + ' ' + _t('commands'));
        },

        _setupKeyboardShortcuts: function () {
            const self = this;
            $(document).on('keydown.mindmap_editor', function (e) {
                if (self._isInputFocused()) {
                    return;
                }

                // Ctrl+Z: Undo
                if (e.ctrlKey && e.key === 'z' && !e.shiftKey) {
                    e.preventDefault();
                    self._onUndo();
                }
                // Ctrl+Y or Ctrl+Shift+Z: Redo
                else if ((e.ctrlKey && e.key === 'y') || (e.ctrlKey && e.shiftKey && e.key === 'Z')) {
                    e.preventDefault();
                    self._onRedo();
                }
                // Tab: Add child
                else if (e.key === 'Tab' && !e.shiftKey) {
                    e.preventDefault();
                    self._onAddChild();
                }
                // Enter: Add sibling
                else if (e.key === 'Enter' && !e.ctrlKey) {
                    e.preventDefault();
                    self._onAddSibling();
                }
                // Delete: Remove node
                else if (e.key === 'Delete') {
                    e.preventDefault();
                    self._onDelete();
                }
                // Ctrl+S: Save
                else if (e.ctrlKey && e.key === 's') {
                    e.preventDefault();
                    self._onSave();
                }
                // F2: Edit node
                else if (e.key === 'F2') {
                    e.preventDefault();
                    self._editSelectedNode();
                }
                // Arrow keys: Navigate
                else if (e.key.startsWith('Arrow')) {
                    self._handleArrowNavigation(e);
                }
                // Space: Toggle expand
                else if (e.key === ' ') {
                    e.preventDefault();
                    self._toggleSelectedExpand();
                }
            });
        },

        _isInputFocused: function () {
            const activeElement = document.activeElement;
            return activeElement && (
                activeElement.tagName === 'INPUT' ||
                activeElement.tagName === 'TEXTAREA' ||
                activeElement.contentEditable === 'true'
            );
        },

        _handleArrowNavigation: function (e) {
            if (!this.selectedNode) return;

            const node = this.jm.get_node(this.selectedNode);
            if (!node) return;

            let targetNode = null;

            switch (e.key) {
                case 'ArrowUp':
                    // Go to previous sibling
                    if (node.parent) {
                        const siblings = node.parent.children;
                        const index = siblings.indexOf(node);
                        if (index > 0) {
                            targetNode = siblings[index - 1];
                        }
                    }
                    break;
                case 'ArrowDown':
                    // Go to next sibling
                    if (node.parent) {
                        const siblings = node.parent.children;
                        const index = siblings.indexOf(node);
                        if (index < siblings.length - 1) {
                            targetNode = siblings[index + 1];
                        }
                    }
                    break;
                case 'ArrowLeft':
                    // Go to parent
                    if (node.parent) {
                        targetNode = node.parent;
                    }
                    break;
                case 'ArrowRight':
                    // Go to first child
                    if (node.children && node.children.length > 0) {
                        targetNode = node.children[0];
                    }
                    break;
            }

            if (targetNode) {
                e.preventDefault();
                this.jm.select_node(targetNode.id);
            }
        },

        _setupAutoSave: function () {
            const self = this;
            this.autoSaveTimer = setInterval(function () {
                if (self.commandStack.isDirty && self.workbookId) {
                    self._autoSave();
                }
            }, 60000); // Auto-save every minute
        },

        _autoSave: function () {
            const self = this;
            this._updateStatus(_t('Auto-saving...'));
            this.$('.o_mindmap_autosave_indicator').text(_t('Saving...'));

            this._saveData().then(function () {
                self.$('.o_mindmap_autosave_indicator').text(_t('Auto-saved'));
                setTimeout(function () {
                    self.$('.o_mindmap_autosave_indicator').text('');
                }, 3000);
            });
        },

        _setupDragDrop: function () {
            // jsMind has built-in drag support
            // We intercept for command pattern
            const self = this;
            // Note: jsMind's internal drag-drop will be wrapped with commands
        },

        _onJsMindEvent: function (type, data) {
            const self = this;

            if (type === 1) { // select
                this.selectedNode = data.node;
                this._updateSidebar(data.node);
                this._openSidebar();

                // Handle relationship mode
                if (this.relationshipMode && this.relationshipSource) {
                    this._createRelationship(this.relationshipSource, data.node);
                    this.relationshipMode = false;
                    this.relationshipSource = null;
                    this._updateStatus(_t('Ready'));
                }
            } else if (type === 2) { // update
                // Node was edited directly in jsMind
                // This is already handled by our commands
                // Update feature positions after node changes
                this._updateFeaturePositions();
            } else if (type === 3) { // show
                // Mind map was redrawn
                setTimeout(() => self._updateFeaturePositions(), 100);
            } else if (type === 4) { // resize
                // Container was resized
                setTimeout(() => self._updateFeaturePositions(), 100);
            }
        },

        _updateFeaturePositions: function () {
            // Update all feature positions (summaries, relationships, boundaries)
            if (this.summaryRenderer) {
                this.summaryRenderer.updatePositions();
            }

            if (this.relationshipRenderer) {
                // Update relationship positions if method exists
                if (typeof this.relationshipRenderer.updatePositions === 'function') {
                    this.relationshipRenderer.updatePositions();
                }
            }

            if (this.boundaryRenderer) {
                // Update boundary positions if method exists
                if (typeof this.boundaryRenderer.updatePositions === 'function') {
                    this.boundaryRenderer.updatePositions();
                }
            }
        },

        _updateSidebar: function (nodeId) {
            if (!nodeId) {
                this._closeSidebar();
                return;
            }

            const node = this.jm.get_node(nodeId);
            if (!node) return;

            const data = node.data || {};
            const style = data.style || {};

            this.$('.o_topic_title').val(node.topic);
            this.$('.o_topic_bg_color').val(style.background || '#ffffff');
            this.$('.o_topic_text_color').val(style.color || '#333333');
            this.$('.o_topic_font_size').val(parseInt(style['font-size']) || 14);
            this.$('.o_topic_font_weight').val(style['font-weight'] || 'normal');
            this.$('.o_topic_note').val(data.note || '');
            this.$('.o_topic_labels').val((data.labels || []).join(', '));

            // Update note character count
            const noteLength = (data.note || '').length;
            this.$('.o_topic_note_count').text(noteLength + ' ' + _t('characters'));

            // Update hyperlink
            this.$('.o_topic_hyperlink').val(data.hyperlink || '');
            this.$('.o_topic_hyperlink_title').val(data.hyperlinkTitle || '');

            // Update image preview
            this._updateImagePreview(data.image);

            // Update attachments list
            this._updateAttachmentsList(data.attachments || []);

            // Update markers display
            this._updateMarkersDisplay(data.markers || []);
        },

        _updateImagePreview: function (imageData) {
            const $preview = this.$('.o_topic_image_preview');
            $preview.empty();

            if (imageData && imageData.data) {
                const thumbnail = this.imageRenderer.createThumbnail(imageData.data, 120);
                $preview.append(thumbnail);

                const $info = $('<div class="mt-1 text-muted small">');
                $info.text(_t('Position: ') + (imageData.options.position || 'above'));
                $preview.append($info);

                this.$('.o_topic_remove_image').show();
            } else {
                $preview.html('<span class="text-muted">' + _t('No image attached') + '</span>');
                this.$('.o_topic_remove_image').hide();
            }
        },

        _updateAttachmentsList: function (attachments) {
            const $list = this.$('.o_topic_attachments');
            $list.empty();

            if (!attachments || attachments.length === 0) {
                $list.html('<small class="text-muted">' + _t('No attachments') + '</small>');
                return;
            }

            for (let att of attachments) {
                const $item = $('<div class="d-flex align-items-center mb-1">');
                $item.append('<i class="fa fa-file mr-2 text-muted"/>');
                $item.append('<span class="flex-grow-1">' + att.name + '</span>');
                $item.append('<button class="btn btn-sm btn-link text-danger p-0"><i class="fa fa-trash"/></button>');
                $list.append($item);
            }
        },

        _updateMarkersDisplay: function (markerCodes) {
            const self = this;
            const $container = this.$('.o_topic_markers');
            $container.empty();

            for (let code of markerCodes) {
                const marker = this.markers.find(m => m.code === code);
                if (marker) {
                    const $badge = $('<span class="badge badge-light mr-1">');
                    $badge.html('<i class="' + marker.icon + '" style="color:' + marker.color + '"></i> ' + marker.name);
                    $badge.append(
                        $('<button class="btn btn-link btn-sm p-0 ml-1">').html('<i class="fa fa-times"></i>')
                            .click(function () {
                                self._removeMarker(code);
                            })
                    );
                    $container.append($badge);
                }
            }
        },

        _openSidebar: function () {
            this.$('.o_mindmap_sidebar').addClass('open');
        },

        _closeSidebar: function () {
            this.$('.o_mindmap_sidebar').removeClass('open');
        },

        // Command-based operations
        _onUndo: function () {
            if (this.commandStack.canUndo()) {
                const cmd = this.commandStack.undo();
                this._updateStatus(_t('Undone: ') + cmd.getLabel());
            }
        },

        _onRedo: function () {
            if (this.commandStack.canRedo()) {
                const cmd = this.commandStack.redo();
                this._updateStatus(_t('Redone: ') + cmd.getLabel());
            }
        },

        _onAddChild: function () {
            const parentNode = this.selectedNode ? this.jm.get_node(this.selectedNode) : this.jm.get_root();
            const parentId = parentNode.id;
            const nodeId = this._generateNodeId();
            const topic = _t('New Topic');

            // Inherit parent's shape and style settings
            const inheritedData = {
                style: {
                    background: '#f0f0f0',
                    color: '#333333',
                }
            };

            // Inherit shape from parent
            if (parentNode.data && parentNode.data.shape) {
                inheritedData.shape = JSON.parse(JSON.stringify(parentNode.data.shape));
            }

            // Inherit text style from parent
            if (parentNode.data && parentNode.data.style) {
                inheritedData.style = JSON.parse(JSON.stringify(parentNode.data.style));
            }

            // Check if parent is a summary topic with custom branch styles
            let summaryBranchStyle = null;
            if (this.summaryBranchStyles && this.summaryBranchStyles[parentId]) {
                summaryBranchStyle = this.summaryBranchStyles[parentId];
                inheritedData.branchStyle = summaryBranchStyle;
            }

            const cmd = new CommandModule.AddNodeCommand(this.jm, parentId, nodeId, topic, inheritedData);
            this.commandStack.execute(cmd);

            // Apply inherited styles to the new node element
            const newNode = this.jm.get_node(nodeId);
            const newElement = this.jm.view.get_node_element(nodeId);
            if (newNode && newElement) {
                if (inheritedData.shape) {
                    this._applyShapeToNode(newElement, inheritedData.shape);
                }
                if (inheritedData.style) {
                    this._restoreNodeStyle(newElement, inheritedData.style);
                }

                // Apply custom branch style if parent is a summary topic
                if (summaryBranchStyle) {
                    this._applySummaryBranchStyle(parentId, nodeId, summaryBranchStyle);
                }
            }

            // Select and edit the new node
            this.jm.select_node(nodeId);
            this._editSelectedNode();

            this._updateStatus(_t('Added child node (inherited parent style)'));
        },

        _onAddSibling: function () {
            if (!this.selectedNode) return;

            const node = this.jm.get_node(this.selectedNode);
            if (!node || !node.parent) return;

            const parentNode = node.parent;
            const parentId = parentNode.id;
            const nodeId = this._generateNodeId();
            const topic = _t('New Topic');

            // Inherit parent's shape and style settings (same as sibling)
            const inheritedData = {
                style: {
                    background: '#f0f0f0',
                    color: '#333333',
                }
            };

            // Inherit shape from parent
            if (parentNode.data && parentNode.data.shape) {
                inheritedData.shape = JSON.parse(JSON.stringify(parentNode.data.shape));
            }

            // Inherit text style from parent
            if (parentNode.data && parentNode.data.style) {
                inheritedData.style = JSON.parse(JSON.stringify(parentNode.data.style));
            }

            const cmd = new CommandModule.AddNodeCommand(this.jm, parentId, nodeId, topic, inheritedData);
            this.commandStack.execute(cmd);

            // Apply inherited styles to the new node element
            const newNode = this.jm.get_node(nodeId);
            const newElement = this.jm.view.get_node_element(nodeId);
            if (newNode && newElement) {
                if (inheritedData.shape) {
                    this._applyShapeToNode(newElement, inheritedData.shape);
                }
                if (inheritedData.style) {
                    this._restoreNodeStyle(newElement, inheritedData.style);
                }
            }

            this.jm.select_node(nodeId);
            this._editSelectedNode();

            this._updateStatus(_t('Added sibling node'));
        },

        _onDelete: function () {
            if (!this.selectedNode) return;

            const node = this.jm.get_node(this.selectedNode);
            if (!node || !node.parent) {
                this._showWarning(_t('Cannot delete root node'));
                return;
            }

            const self = this;
            Dialog.confirm(this, _t('Delete this topic and all its children?'), {
                confirm_callback: function () {
                    const cmd = new CommandModule.RemoveNodeCommand(self.jm, self.selectedNode);
                    self.commandStack.execute(cmd);
                    self.selectedNode = null;
                    self._closeSidebar();
                    self._updateStatus(_t('Deleted node'));
                },
            });
        },

        _editSelectedNode: function () {
            if (!this.selectedNode) return;

            const self = this;
            const node = this.jm.get_node(this.selectedNode);
            if (!node) return;

            this.jm.begin_edit(this.selectedNode);

            // Listen for edit completion
            setTimeout(function () {
                const editElement = self.$('#jsmind_container').find('input.jmnode-input');
                if (editElement.length) {
                    const oldTopic = node.topic;
                    editElement.on('blur', function () {
                        const newTopic = editElement.val();
                        if (newTopic !== oldTopic) {
                            // Create update command
                            const cmd = new CommandModule.UpdateNodeCommand(self.jm, self.selectedNode, newTopic, oldTopic);
                            // Note: jsMind already updated the node, so we just track the command
                            self.commandStack.undoStack.push(cmd);
                            self.commandStack.redoStack = [];
                            self.commandStack.isDirty = true;
                            self.commandStack._notifyListeners();
                        }
                    });
                }
            }, 100);
        },

        _toggleSelectedExpand: function () {
            if (!this.selectedNode) return;

            const node = this.jm.get_node(this.selectedNode);
            if (!node) return;

            const willExpand = !node.expanded;
            const cmd = new CommandModule.ToggleExpandCommand(this.jm, this.selectedNode, willExpand);
            this.commandStack.execute(cmd);
        },

        _onExpandAll: function () {
            this.jm.expand_all();
            this._updateStatus(_t('Expanded all nodes'));
        },

        _onCollapseAll: function () {
            this.jm.collapse_all();
            this._updateStatus(_t('Collapsed all nodes'));
        },

        _onTopicPropertyChange: function () {
            if (!this.selectedNode) return;

            const node = this.jm.get_node(this.selectedNode);
            if (!node) return;

            const newTopic = this.$('.o_topic_title').val();
            const note = this.$('.o_topic_note').val();
            const labels = this.$('.o_topic_labels').val().split(',').map(l => l.trim()).filter(l => l);

            // Update topic if changed
            if (newTopic !== node.topic) {
                const cmd = new CommandModule.UpdateNodeCommand(this.jm, this.selectedNode, newTopic, node.topic);
                this.commandStack.execute(cmd);
            }

            // Update node data
            node.data = node.data || {};
            node.data.note = note;
            node.data.labels = labels;

            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
        },

        _onTopicStyleChange: function () {
            if (!this.selectedNode) return;

            const node = this.jm.get_node(this.selectedNode);
            if (!node) return;

            const oldStyle = (node.data && node.data.style) ? JSON.parse(JSON.stringify(node.data.style)) : {};
            const newStyle = {
                background: this.$('.o_topic_bg_color').val(),
                color: this.$('.o_topic_text_color').val(),
                'font-size': this.$('.o_topic_font_size').val() + 'px',
                'font-weight': this.$('.o_topic_font_weight').val(),
            };

            const cmd = new CommandModule.UpdateNodeStyleCommand(this.jm, this.selectedNode, newStyle, oldStyle);
            this.commandStack.execute(cmd);

            this._updateStatus(_t('Updated style'));
        },

        _onOpenNote: function () {
            if (!this.selectedNode) {
                this._showWarning(_t('Please select a topic first'));
                return;
            }

            this._openSidebar();
            this.$('.o_topic_note').focus();
        },

        _onOpenMarker: function () {
            if (!this.selectedNode) {
                this._showWarning(_t('Please select a topic first'));
                return;
            }

            this._showMarkerDialog();
        },

        _showMarkerDialog: function () {
            const self = this;

            // Group markers by category
            const categories = {};
            for (let marker of this.markers) {
                if (!categories[marker.category]) {
                    categories[marker.category] = {
                        name: marker.category.charAt(0).toUpperCase() + marker.category.slice(1),
                        markers: []
                    };
                }
                categories[marker.category].markers.push(marker);
            }

            const $content = $(QWeb.render('dobtor_xmind.MarkerSelector', {
                categories: Object.values(categories)
            }));

            const dialog = new Dialog(this, {
                title: _t('Select Marker'),
                $content: $content,
                buttons: [
                    { text: _t('Close'), close: true }
                ],
            });

            $content.on('click', '.o_marker_item', function () {
                const markerId = $(this).data('marker-id');
                self._addMarker(markerId);
                dialog.close();
            });

            dialog.open();
        },

        _addMarker: function (markerId) {
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
        },

        _removeMarker: function (code) {
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
        },

        _onAddRelationship: function () {
            if (!this.selectedNode) {
                this._showWarning(_t('Please select a source topic first'));
                return;
            }

            this.relationshipMode = true;
            this.relationshipSource = this.selectedNode;
            this._updateStatus(_t('Click on target topic to create relationship...'));
        },

        _showRelationshipPropertiesDialog: function (sourceId, targetId) {
            const self = this;

            const $content = $(QWeb.render('dobtor_xmind.RelationshipProperties'));

            // Toggle buttons for bold/italic
            $content.find('.o_rel_label_bold').on('click', function () {
                $(this).toggleClass('active');
            });
            $content.find('.o_rel_label_italic').on('click', function () {
                $(this).toggleClass('active');
            });

            const dialog = new Dialog(this, {
                title: _t('Relationship Properties'),
                size: 'medium',
                $content: $content,
                buttons: [
                    {
                        text: _t('Create'),
                        classes: 'btn-primary',
                        click: function () {
                            const options = {
                                shapeType: $content.find('.o_rel_shape_type').val(),
                                lineStyle: $content.find('.o_rel_line_style').val(),
                                lineWidth: parseInt($content.find('.o_rel_line_width').val()),
                                lineColor: $content.find('.o_rel_line_color').val(),
                                startMarker: $content.find('.o_rel_start_marker').val(),
                                endMarker: $content.find('.o_rel_end_marker').val(),
                                markerSize: $content.find('.o_rel_marker_size').val(),
                                label: $content.find('.o_rel_label_text').val(),
                                labelFontSize: parseInt($content.find('.o_rel_label_font_size').val()),
                                labelColor: $content.find('.o_rel_label_color').val(),
                                labelBold: $content.find('.o_rel_label_bold').hasClass('active'),
                                labelItalic: $content.find('.o_rel_label_italic').hasClass('active'),
                                labelBackground: $content.find('.o_rel_label_background').is(':checked')
                            };

                            self._createAdvancedRelationship(sourceId, targetId, options);
                            dialog.close();
                        }
                    },
                    {
                        text: _t('Cancel'),
                        close: true
                    }
                ]
            });

            dialog.open();
        },

        _createAdvancedRelationship: function (sourceId, targetId, options) {
            const sourceElement = this.jm.view.get_node_element(sourceId);
            const targetElement = this.jm.view.get_node_element(targetId);

            if (!sourceElement || !targetElement) {
                this._showWarning(_t('Could not find topic elements'));
                return;
            }

            const relId = this.advancedRelationshipManager.addRelationship(sourceElement, targetElement, options);

            if (relId) {
                // Store for saving
                this.relationships.push({
                    id: relId,
                    sourceId: sourceId,
                    targetId: targetId,
                    options: options
                });

                this._updateStatus(_t('Relationship created: ') + (options.label || _t('(no label)')));
            }
        },

        _createRelationship: function (sourceId, targetId) {
            if (sourceId === targetId) {
                this._showWarning(_t('Cannot create relationship to self'));
                return;
            }

            // Show properties dialog for advanced options
            this._showRelationshipPropertiesDialog(sourceId, targetId);
        },

        _onEditRelationship: function (relId) {
            const relData = this.relationships.find(r => r.id === relId);
            if (!relData) return;

            const self = this;
            const $content = $(QWeb.render('dobtor_xmind.RelationshipProperties'));

            // Pre-populate with current values
            $content.find('.o_rel_shape_type').val(relData.options.shapeType);
            $content.find('.o_rel_line_style').val(relData.options.lineStyle);
            $content.find('.o_rel_line_width').val(relData.options.lineWidth);
            $content.find('.o_rel_line_color').val(relData.options.lineColor);
            $content.find('.o_rel_start_marker').val(relData.options.startMarker);
            $content.find('.o_rel_end_marker').val(relData.options.endMarker);
            $content.find('.o_rel_marker_size').val(relData.options.markerSize);
            $content.find('.o_rel_label_text').val(relData.options.label);
            $content.find('.o_rel_label_font_size').val(relData.options.labelFontSize);
            $content.find('.o_rel_label_color').val(relData.options.labelColor);
            if (relData.options.labelBold) {
                $content.find('.o_rel_label_bold').addClass('active');
            }
            if (relData.options.labelItalic) {
                $content.find('.o_rel_label_italic').addClass('active');
            }
            $content.find('.o_rel_label_background').prop('checked', relData.options.labelBackground);

            // Toggle buttons
            $content.find('.o_rel_label_bold').on('click', function () {
                $(this).toggleClass('active');
            });
            $content.find('.o_rel_label_italic').on('click', function () {
                $(this).toggleClass('active');
            });

            const dialog = new Dialog(this, {
                title: _t('Edit Relationship'),
                size: 'medium',
                $content: $content,
                buttons: [
                    {
                        text: _t('Update'),
                        classes: 'btn-primary',
                        click: function () {
                            const newOptions = {
                                shapeType: $content.find('.o_rel_shape_type').val(),
                                lineStyle: $content.find('.o_rel_line_style').val(),
                                lineWidth: parseInt($content.find('.o_rel_line_width').val()),
                                lineColor: $content.find('.o_rel_line_color').val(),
                                startMarker: $content.find('.o_rel_start_marker').val(),
                                endMarker: $content.find('.o_rel_end_marker').val(),
                                markerSize: $content.find('.o_rel_marker_size').val(),
                                label: $content.find('.o_rel_label_text').val(),
                                labelFontSize: parseInt($content.find('.o_rel_label_font_size').val()),
                                labelColor: $content.find('.o_rel_label_color').val(),
                                labelBold: $content.find('.o_rel_label_bold').hasClass('active'),
                                labelItalic: $content.find('.o_rel_label_italic').hasClass('active'),
                                labelBackground: $content.find('.o_rel_label_background').is(':checked')
                            };

                            // Update in manager
                            self.advancedRelationshipManager.updateRelationshipOptions(relId, newOptions);

                            // Update stored data
                            relData.options = newOptions;

                            self._updateStatus(_t('Relationship updated'));
                            dialog.close();
                        }
                    },
                    {
                        text: _t('Delete'),
                        classes: 'btn-danger',
                        click: function () {
                            self.advancedRelationshipManager.removeRelationship(relId);
                            const index = self.relationships.findIndex(r => r.id === relId);
                            if (index > -1) {
                                self.relationships.splice(index, 1);
                            }
                            self._updateStatus(_t('Relationship deleted'));
                            dialog.close();
                        }
                    },
                    {
                        text: _t('Cancel'),
                        close: true
                    }
                ]
            });

            dialog.open();
        },

        _refreshRelationshipPositions: function () {
            if (this.advancedRelationshipManager) {
                this.advancedRelationshipManager.refreshPositions();
            }
        },

        _oldCreateRelationship: function (sourceId, targetId) {
            if (sourceId === targetId) {
                this._showWarning(_t('Cannot create relationship to self'));
                return;
            }

            // Store relationship for saving
            // This will be saved when the mindmap is saved
            this._updateStatus(_t('Relationship created'));
        },

        _onLayoutChange: function (ev) {
            const layout = $(ev.currentTarget).val();
            this.sheetSettings.layout = layout;
            this._saveSettings();
            this._updateStatus(_t('Layout changed to: ') + layout);

            // Reload with new layout
            // Note: jsMind doesn't support runtime layout change easily
            // We would need to reload the mindmap
        },

        _onThemeChange: function (ev) {
            const theme = $(ev.currentTarget).val();
            this.sheetSettings.theme = theme;
            this.jm.set_theme(theme);
            this._saveSettings();
            this._updateStatus(_t('Theme changed to: ') + theme);
        },

        _saveSettings: function () {
            if (!this.workbookId) return;

            rpc.query({
                route: '/xmind/workbook/' + this.workbookId + '/settings',
                params: { settings: this.sheetSettings },
            });
        },

        _onSave: function () {
            const self = this;
            this._updateStatus(_t('Saving...'));

            this._saveData().then(function () {
                self.commandStack.markSaved();
                self._updateStatus(_t('Saved successfully'));
            }).catch(function (error) {
                self._showError(_t('Save failed: ') + error);
            });
        },

        _saveData: function () {
            if (!this.workbookId) {
                return Promise.resolve();
            }

            const data = this.jm.get_data('node_tree');
            return rpc.query({
                route: '/xmind/workbook/' + this.workbookId + '/save',
                params: { data: data },
            });
        },

        _onExport: function () {
            if (!this.workbookId) return;

            window.location.href = '/web/content?model=xmind.workbook&id=' + this.workbookId +
                '&field=xmind_file&filename_field=xmind_filename&download=true';
        },

        _generateNodeId: function () {
            return 'node_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        },

        _applySummaryBranchStyle: function (parentId, childId, branchStyle) {
            // Apply custom branch line style for summary topic children
            if (!branchStyle) return;

            const parentElement = this.jm.view.get_node_element(parentId);
            const childElement = this.jm.view.get_node_element(childId);

            if (!parentElement || !childElement) return;

            const containerRect = this.jm.view.e_panel.getBoundingClientRect();
            const parentRect = parentElement.getBoundingClientRect();
            const childRect = childElement.getBoundingClientRect();

            // Calculate connection points
            const px = parentRect.right - containerRect.left;
            const py = parentRect.top - containerRect.top + parentRect.height / 2;
            const cx = childRect.left - containerRect.left;
            const cy = childRect.top - containerRect.top + childRect.height / 2;

            // Create custom branch line overlay
            let branchSvg = this.jm.view.e_panel.querySelector('.summary-branch-overlay');
            if (!branchSvg) {
                branchSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                branchSvg.classList.add('summary-branch-overlay');
                branchSvg.style.position = 'absolute';
                branchSvg.style.top = '0';
                branchSvg.style.left = '0';
                branchSvg.style.width = '100%';
                branchSvg.style.height = '100%';
                branchSvg.style.pointerEvents = 'none';
                branchSvg.style.zIndex = '4';
                this.jm.view.e_panel.appendChild(branchSvg);

                // Add marker definitions
                const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
                const markerTypes = ['arrow', 'circle', 'diamond'];
                markerTypes.forEach(type => {
                    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
                    marker.setAttribute('id', `summary-branch-${type}`);
                    marker.setAttribute('markerWidth', '10');
                    marker.setAttribute('markerHeight', '10');
                    marker.setAttribute('refX', '10');
                    marker.setAttribute('refY', '5');
                    marker.setAttribute('orient', 'auto');

                    let shape;
                    if (type === 'arrow') {
                        shape = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                        shape.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
                    } else if (type === 'circle') {
                        shape = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                        shape.setAttribute('cx', '5');
                        shape.setAttribute('cy', '5');
                        shape.setAttribute('r', '4');
                    } else if (type === 'diamond') {
                        shape = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                        shape.setAttribute('d', 'M 5 0 L 10 5 L 5 10 L 0 5 z');
                    }
                    shape.setAttribute('fill', branchStyle.lineColor || '#2196F3');
                    marker.appendChild(shape);
                    defs.appendChild(marker);
                });
                branchSvg.appendChild(defs);
            }

            // Create branch line path
            const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            let d = '';

            switch (branchStyle.lineType) {
                case 'curved':
                    const cpx = px + (cx - px) / 2;
                    d = `M ${px} ${py} C ${cpx} ${py}, ${cpx} ${cy}, ${cx} ${cy}`;
                    break;
                case 'straight':
                    d = `M ${px} ${py} L ${cx} ${cy}`;
                    break;
                case 'angular':
                    const midX = px + (cx - px) / 2;
                    d = `M ${px} ${py} L ${midX} ${py} L ${midX} ${cy} L ${cx} ${cy}`;
                    break;
                default:
                    const cpx2 = px + (cx - px) / 2;
                    d = `M ${px} ${py} C ${cpx2} ${py}, ${cpx2} ${cy}, ${cx} ${cy}`;
            }

            line.setAttribute('d', d);
            line.setAttribute('stroke', branchStyle.lineColor || '#2196F3');
            line.setAttribute('stroke-width', branchStyle.lineWidth || 2);
            line.setAttribute('fill', 'none');
            line.setAttribute('data-parent', parentId);
            line.setAttribute('data-child', childId);

            // Apply end marker if specified
            if (branchStyle.endMarker && branchStyle.endMarker !== 'none') {
                line.setAttribute('marker-end', `url(#summary-branch-${branchStyle.endMarker})`);
            }

            branchSvg.appendChild(line);
        },

        _updateStatus: function (message) {
            this.$('.o_mindmap_status_text').text(message);
        },

        _showWarning: function (message) {
            Dialog.alert(this, message, { title: _t('Warning') });
        },

        _showError: function (message) {
            Dialog.alert(this, message, { title: _t('Error') });
        },

        // ===== XMind 2 Advanced Features =====

        _onAddBoundary: function () {
            if (!this.selectedNode) {
                this._showWarning(_t('Please select at least one topic to create a boundary'));
                return;
            }

            const self = this;
            this.boundarySelectionMode = true;
            this.selectedTopicsForFeature = [this.selectedNode];
            this._updateStatus(_t('Shift+Click to select more topics, then click Create in dialog...'));

            // Advanced boundary properties dialog
            const $content = $(QWeb.render('dobtor_xmind.BoundaryProperties'));

            // Toggle buttons for bold/italic
            $content.find('.o_bnd_title_bold').on('click', function () {
                $(this).toggleClass('active');
            });
            $content.find('.o_bnd_title_italic').on('click', function () {
                $(this).toggleClass('active');
            });

            // Opacity slider update
            $content.find('.o_bnd_fill_opacity').on('input', function () {
                $content.find('.o_bnd_fill_opacity_val').text($(this).val() + '%');
            });

            const dialog = new Dialog(this, {
                title: _t('Create Boundary'),
                size: 'medium',
                $content: $content,
                buttons: [
                    {
                        text: _t('Create'),
                        classes: 'btn-primary',
                        click: function () {
                            const fillColor = $content.find('.o_bnd_fill_color').val();
                            const opacity = parseInt($content.find('.o_bnd_fill_opacity').val()) / 100;
                            const fillColorWithOpacity = self._hexToRgba(fillColor, opacity);

                            const options = {
                                shape: $content.find('.o_bnd_shape_type').val(),
                                fillColor: fillColorWithOpacity,
                                borderColor: $content.find('.o_bnd_border_color').val(),
                                borderWidth: parseInt($content.find('.o_bnd_border_width').val()),
                                borderStyle: $content.find('.o_bnd_border_style').val(),
                                title: $content.find('.o_bnd_title_text').val(),
                                titlePosition: $content.find('.o_bnd_title_position').val(),
                                titleFontSize: parseInt($content.find('.o_bnd_title_font_size').val()),
                                titleColor: $content.find('.o_bnd_title_color').val(),
                                titleBold: $content.find('.o_bnd_title_bold').hasClass('active'),
                                titleItalic: $content.find('.o_bnd_title_italic').hasClass('active'),
                                titleBackground: $content.find('.o_bnd_title_background').is(':checked')
                            };
                            self._createBoundary(options);
                            dialog.close();
                        }
                    },
                    { text: _t('Cancel'), close: true }
                ],
            });
            dialog.open();
        },

        _hexToRgba: function (hex, opacity) {
            const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
            if (result) {
                const r = parseInt(result[1], 16);
                const g = parseInt(result[2], 16);
                const b = parseInt(result[3], 16);
                return `rgba(${r}, ${g}, ${b}, ${opacity})`;
            }
            return hex;
        },

        _createBoundary: function (options) {
            const topicElements = [];
            for (let nodeId of this.selectedTopicsForFeature) {
                const element = this.jm.view.get_node_element(nodeId);
                if (element) {
                    topicElements.push(element);
                }
            }

            if (topicElements.length > 0) {
                this.boundaryRenderer.addBoundary(topicElements, options);
                this.boundaries.push({
                    topicIds: this.selectedTopicsForFeature.slice(),
                    options: options
                });
                this.commandStack.isDirty = true;
                this.commandStack._notifyListeners();
                this._updateStatus(_t('Boundary created: ') + (options.title || _t('(no title)')));
            }

            this.boundarySelectionMode = false;
            this.selectedTopicsForFeature = [];
        },

        _onAddSummary: function () {
            if (!this.selectedNode) {
                this._showWarning(_t('Please select sibling topics to summarize'));
                return;
            }

            const node = this.jm.get_node(this.selectedNode);
            if (!node || !node.parent) {
                this._showWarning(_t('Cannot create summary for root node'));
                return;
            }

            const self = this;
            const siblings = node.parent.children;
            const siblingOptions = siblings.map((s, i) => `<option value="${s.id}" ${s.id === this.selectedNode ? 'selected' : ''}>${s.topic}</option>`).join('');

            // Create dialog with topic selection and summary properties
            const $topicSelection = $(`
                <div class="o_summary_topic_selection mb-3">
                    <h6 class="text-muted mb-2">
                        <i class="fa fa-list"/> Select Topics
                    </h6>
                    <div class="form-group">
                        <label class="small">${_t('Topics to summarize')}</label>
                        <select multiple class="form-control form-control-sm o_sum_select_topics" size="4">
                            ${siblingOptions}
                        </select>
                        <small class="text-muted">${_t('Hold Ctrl/Cmd to select multiple')}</small>
                    </div>
                </div>
                <hr/>
            `);

            const $propertiesContent = $(QWeb.render('dobtor_xmind.SummaryProperties'));
            const $content = $topicSelection.add($propertiesContent);

            // Initialize toggle buttons for bold/italic
            $propertiesContent.find('.o_sum_topic_bold, .o_sum_topic_italic').on('click', function() {
                $(this).toggleClass('active btn-secondary btn-outline-secondary');
            });

            const dialog = new Dialog(this, {
                title: _t('Create Summary'),
                size: 'medium',
                $content: $content,
                buttons: [
                    {
                        text: _t('Create'),
                        classes: 'btn-primary',
                        click: function () {
                            const selectedIds = Array.from($content.find('.o_sum_select_topics')[0].selectedOptions).map(o => o.value);
                            if (selectedIds.length === 0) {
                                self._showWarning(_t('Please select at least one topic'));
                                return;
                            }

                            // Gather all summary options
                            const summaryOptions = {
                                // Summary line settings
                                lineType: $content.find('.o_sum_line_type').val(),
                                lineWidth: parseInt($content.find('.o_sum_line_width').val()),
                                lineColor: $content.find('.o_sum_line_color').val(),

                                // Summary topic shape settings
                                topicShape: $content.find('.o_sum_topic_shape').val(),
                                topicFillColor: $content.find('.o_sum_topic_fill').val(),
                                topicBorderColor: $content.find('.o_sum_topic_border').val(),
                                topicBorderWidth: parseInt($content.find('.o_sum_topic_border_width').val()),

                                // Summary topic text settings
                                topicText: $content.find('.o_sum_topic_text').val() || _t('Summary'),
                                topicFontSize: parseInt($content.find('.o_sum_topic_font_size').val()),
                                topicTextColor: $content.find('.o_sum_topic_text_color').val(),
                                topicBold: $content.find('.o_sum_topic_bold').hasClass('active'),
                                topicItalic: $content.find('.o_sum_topic_italic').hasClass('active'),

                                // Branch settings
                                branchType: $content.find('.o_sum_branch_type').val(),
                                branchEndMarker: $content.find('.o_sum_branch_end').val(),
                                branchWidth: parseInt($content.find('.o_sum_branch_width').val()),
                                branchColor: $content.find('.o_sum_branch_color').val()
                            };

                            self._createSummary(selectedIds, summaryOptions);
                            dialog.close();
                        }
                    },
                    { text: _t('Cancel'), close: true }
                ],
            });
            dialog.open();
        },

        _createSummary: function (topicIds, summaryOptions) {
            // Create a new node as summary topic with full styling
            const parentId = this.jm.get_node(topicIds[0]).parent.id;
            const summaryNodeId = this._generateNodeId();

            // Build node style from options
            const nodeStyle = {
                background: summaryOptions.topicFillColor,
                color: summaryOptions.topicTextColor,
                'font-size': summaryOptions.topicFontSize + 'px',
                'border': `${summaryOptions.topicBorderWidth}px solid ${summaryOptions.topicBorderColor}`
            };

            if (summaryOptions.topicBold) {
                nodeStyle['font-weight'] = 'bold';
            }
            if (summaryOptions.topicItalic) {
                nodeStyle['font-style'] = 'italic';
            }

            const cmd = new CommandModule.AddNodeCommand(this.jm, parentId, summaryNodeId, summaryOptions.topicText, {
                style: nodeStyle
            });
            this.commandStack.execute(cmd);

            // Apply shape to the summary topic node
            setTimeout(() => {
                const summaryElement = this.jm.view.get_node_element(summaryNodeId);
                const summaryNode = this.jm.get_node(summaryNodeId);

                if (summaryElement && summaryOptions.topicShape !== 'rounded') {
                    // Create proper shape data object
                    const shapeData = {
                        type: summaryOptions.topicShape,
                        fillColor: summaryOptions.topicFillColor,
                        borderColor: summaryOptions.topicBorderColor,
                        borderWidth: summaryOptions.topicBorderWidth
                    };
                    this._applyShapeToNode(summaryElement, shapeData);

                    // Store shape data in node for inheritance
                    if (summaryNode) {
                        if (!summaryNode.data) summaryNode.data = {};
                        summaryNode.data.shape = shapeData;
                    }
                }

                // Store branch style settings for this summary node
                if (!this.summaryBranchStyles) {
                    this.summaryBranchStyles = {};
                }
                this.summaryBranchStyles[summaryNodeId] = {
                    lineType: summaryOptions.branchType,
                    endMarker: summaryOptions.branchEndMarker,
                    lineWidth: summaryOptions.branchWidth,
                    lineColor: summaryOptions.branchColor
                };

                // Mark node as summary topic for special handling
                if (summaryElement) {
                    summaryElement.classList.add('summary-topic');
                    summaryElement.setAttribute('data-summary-id', summaryNodeId);
                }
            }, 100);

            // Render summary bracket with all styling options
            const topicElements = topicIds.map(id => this.jm.view.get_node_element(id)).filter(e => e);
            const summaryElement = this.jm.view.get_node_element(summaryNodeId);

            const renderedSummaryId = this.summaryRenderer.addSummary(topicElements, summaryElement, {
                lineType: summaryOptions.lineType,
                lineColor: summaryOptions.lineColor,
                lineWidth: summaryOptions.lineWidth
            });

            this.summaries.push({
                id: renderedSummaryId,
                topicIds: topicIds,
                summaryNodeId: summaryNodeId,
                options: summaryOptions
            });

            this._updateStatus(_t('Summary created'));
        },

        _showSummaryContextMenu: function (summaryId, event) {
            // Remove existing context menu
            this._removeSummaryContextMenu();

            const self = this;
            const $menu = $(`
                <div class="o_summary_context_menu dropdown-menu show" style="position: fixed; left: ${event.clientX}px; top: ${event.clientY}px; z-index: 10000;">
                    <a class="dropdown-item" href="#" data-action="edit">
                        <i class="fa fa-edit"/> ${_t('Edit Summary')}
                    </a>
                    <a class="dropdown-item text-danger" href="#" data-action="delete">
                        <i class="fa fa-trash"/> ${_t('Delete Summary')}
                    </a>
                </div>
            `);

            $menu.on('click', 'a', function(e) {
                e.preventDefault();
                const action = $(this).data('action');
                if (action === 'edit') {
                    self._onEditSummary(summaryId);
                } else if (action === 'delete') {
                    self._onDeleteSummary(summaryId);
                }
                self._removeSummaryContextMenu();
            });

            $('body').append($menu);

            // Close menu on click outside
            setTimeout(() => {
                $(document).one('click', () => self._removeSummaryContextMenu());
            }, 10);
        },

        _removeSummaryContextMenu: function () {
            $('.o_summary_context_menu').remove();
        },

        _onEditSummary: function (summaryId) {
            const summaryData = this.summaries.find(s => s.id === summaryId);
            if (!summaryData) {
                this._showWarning(_t('Summary not found'));
                return;
            }

            const self = this;
            const currentOptions = summaryData.options;

            // Create edit dialog with current values
            const $propertiesContent = $(QWeb.render('dobtor_xmind.SummaryProperties'));

            // Set current values
            $propertiesContent.find('.o_sum_line_type').val(currentOptions.lineType || 'bracket');
            $propertiesContent.find('.o_sum_line_width').val(currentOptions.lineWidth || 2);
            $propertiesContent.find('.o_sum_line_color').val(currentOptions.lineColor || '#6c757d');
            $propertiesContent.find('.o_sum_topic_shape').val(currentOptions.topicShape || 'rounded');
            $propertiesContent.find('.o_sum_topic_fill').val(currentOptions.topicFillColor || '#E3F2FD');
            $propertiesContent.find('.o_sum_topic_border').val(currentOptions.topicBorderColor || '#2196F3');
            $propertiesContent.find('.o_sum_topic_border_width').val(currentOptions.topicBorderWidth || 2);
            $propertiesContent.find('.o_sum_topic_text').val(currentOptions.topicText || 'Summary');
            $propertiesContent.find('.o_sum_topic_font_size').val(currentOptions.topicFontSize || 14);
            $propertiesContent.find('.o_sum_topic_text_color').val(currentOptions.topicTextColor || '#1565C0');
            $propertiesContent.find('.o_sum_branch_type').val(currentOptions.branchType || 'curved');
            $propertiesContent.find('.o_sum_branch_end').val(currentOptions.branchEndMarker || 'none');
            $propertiesContent.find('.o_sum_branch_width').val(currentOptions.branchWidth || 2);
            $propertiesContent.find('.o_sum_branch_color').val(currentOptions.branchColor || '#2196F3');

            if (currentOptions.topicBold) {
                $propertiesContent.find('.o_sum_topic_bold').addClass('active btn-secondary').removeClass('btn-outline-secondary');
            }
            if (currentOptions.topicItalic) {
                $propertiesContent.find('.o_sum_topic_italic').addClass('active btn-secondary').removeClass('btn-outline-secondary');
            }

            // Initialize toggle buttons
            $propertiesContent.find('.o_sum_topic_bold, .o_sum_topic_italic').on('click', function() {
                $(this).toggleClass('active btn-secondary btn-outline-secondary');
            });

            const dialog = new Dialog(this, {
                title: _t('Edit Summary Properties'),
                size: 'medium',
                $content: $propertiesContent,
                buttons: [
                    {
                        text: _t('Apply'),
                        classes: 'btn-primary',
                        click: function () {
                            const newOptions = {
                                lineType: $propertiesContent.find('.o_sum_line_type').val(),
                                lineWidth: parseInt($propertiesContent.find('.o_sum_line_width').val()),
                                lineColor: $propertiesContent.find('.o_sum_line_color').val(),
                                topicShape: $propertiesContent.find('.o_sum_topic_shape').val(),
                                topicFillColor: $propertiesContent.find('.o_sum_topic_fill').val(),
                                topicBorderColor: $propertiesContent.find('.o_sum_topic_border').val(),
                                topicBorderWidth: parseInt($propertiesContent.find('.o_sum_topic_border_width').val()),
                                topicText: $propertiesContent.find('.o_sum_topic_text').val(),
                                topicFontSize: parseInt($propertiesContent.find('.o_sum_topic_font_size').val()),
                                topicTextColor: $propertiesContent.find('.o_sum_topic_text_color').val(),
                                topicBold: $propertiesContent.find('.o_sum_topic_bold').hasClass('active'),
                                topicItalic: $propertiesContent.find('.o_sum_topic_italic').hasClass('active'),
                                branchType: $propertiesContent.find('.o_sum_branch_type').val(),
                                branchEndMarker: $propertiesContent.find('.o_sum_branch_end').val(),
                                branchWidth: parseInt($propertiesContent.find('.o_sum_branch_width').val()),
                                branchColor: $propertiesContent.find('.o_sum_branch_color').val()
                            };

                            self._applySummaryChanges(summaryId, newOptions);
                            dialog.close();
                        }
                    },
                    { text: _t('Cancel'), close: true }
                ],
            });
            dialog.open();
        },

        _applySummaryChanges: function (summaryId, newOptions) {
            const summaryData = this.summaries.find(s => s.id === summaryId);
            if (!summaryData) return;

            // Update stored options
            Object.assign(summaryData.options, newOptions);

            // Update the summary line in renderer
            this.summaryRenderer.updateSummaryOptions(summaryId, newOptions);

            // Update the summary topic node
            const summaryNode = this.jm.get_node(summaryData.summaryNodeId);
            const summaryElement = this.jm.view.get_node_element(summaryData.summaryNodeId);

            if (summaryNode && summaryElement) {
                // Update node topic text
                if (newOptions.topicText !== summaryNode.topic) {
                    this.jm.update_node(summaryData.summaryNodeId, newOptions.topicText);
                }

                // Update node style
                const newStyle = {
                    background: newOptions.topicFillColor,
                    color: newOptions.topicTextColor,
                    'font-size': newOptions.topicFontSize + 'px',
                    'border': `${newOptions.topicBorderWidth}px solid ${newOptions.topicBorderColor}`
                };

                if (newOptions.topicBold) {
                    newStyle['font-weight'] = 'bold';
                } else {
                    newStyle['font-weight'] = 'normal';
                }

                if (newOptions.topicItalic) {
                    newStyle['font-style'] = 'italic';
                } else {
                    newStyle['font-style'] = 'normal';
                }

                // Apply styles directly to element
                Object.keys(newStyle).forEach(key => {
                    summaryElement.style[key.replace(/-([a-z])/g, (g) => g[1].toUpperCase())] = newStyle[key];
                });

                // Update shape
                if (newOptions.topicShape !== 'rounded') {
                    const shapeData = {
                        type: newOptions.topicShape,
                        fillColor: newOptions.topicFillColor,
                        borderColor: newOptions.topicBorderColor,
                        borderWidth: newOptions.topicBorderWidth
                    };
                    this._applyShapeToNode(summaryElement, shapeData);
                    if (summaryNode.data) summaryNode.data.shape = shapeData;
                }

                // Update branch styles
                this.summaryBranchStyles[summaryData.summaryNodeId] = {
                    lineType: newOptions.branchType,
                    endMarker: newOptions.branchEndMarker,
                    lineWidth: newOptions.branchWidth,
                    lineColor: newOptions.branchColor
                };
            }

            this._updateStatus(_t('Summary updated'));
        },

        _onDeleteSummary: function (summaryId) {
            const self = this;

            Dialog.confirm(this, _t('Are you sure you want to delete this summary? The summary topic node will also be removed.'), {
                confirm_callback: function () {
                    self._deleteSummary(summaryId);
                }
            });
        },

        _deleteSummary: function (summaryId) {
            const summaryIndex = this.summaries.findIndex(s => s.id === summaryId);
            if (summaryIndex === -1) return;

            const summaryData = this.summaries[summaryIndex];

            // Remove summary node from mind map
            if (summaryData.summaryNodeId) {
                const cmd = new CommandModule.RemoveNodeCommand(this.jm, summaryData.summaryNodeId);
                this.commandStack.execute(cmd);

                // Remove branch style data
                delete this.summaryBranchStyles[summaryData.summaryNodeId];
            }

            // Remove from renderer
            this.summaryRenderer.removeSummary(summaryId);

            // Remove from our list
            this.summaries.splice(summaryIndex, 1);

            this._updateStatus(_t('Summary deleted'));
        },

        _onAddCallout: function () {
            if (!this.selectedNode) {
                this._showWarning(_t('Please select a topic to add callout'));
                return;
            }

            const self = this;
            const $content = $(`
                <div class="form-group">
                    <label>${_t('Title')}</label>
                    <input type="text" class="form-control" id="callout_title" value="${_t('Note')}"/>
                </div>
                <div class="form-group">
                    <label>${_t('Content')}</label>
                    <textarea class="form-control" id="callout_content" rows="4"></textarea>
                </div>
                <div class="form-group">
                    <label>${_t('Background Color')}</label>
                    <input type="color" class="form-control" id="callout_bg" value="#fffacd"/>
                </div>
            `);

            const dialog = new Dialog(this, {
                title: _t('Add Callout'),
                $content: $content,
                buttons: [
                    {
                        text: _t('Add'),
                        classes: 'btn-primary',
                        click: function () {
                            const options = {
                                title: $content.find('#callout_title').val(),
                                content: $content.find('#callout_content').val(),
                                backgroundColor: $content.find('#callout_bg').val(),
                                borderColor: '#ffd700',
                                shape: 'callout',
                                offsetX: 80,
                                offsetY: -50,
                            };
                            self._createCallout(options);
                            dialog.close();
                        }
                    },
                    { text: _t('Cancel'), close: true }
                ],
            });
            dialog.open();
        },

        _createCallout: function (options) {
            const parentElement = this.jm.view.get_node_element(this.selectedNode);
            if (parentElement) {
                this.calloutRenderer.addCallout(parentElement, options);
                this.callouts.push({
                    parentNodeId: this.selectedNode,
                    options: options
                });
                this.commandStack.isDirty = true;
                this.commandStack._notifyListeners();
                this._updateStatus(_t('Callout added'));
            }
        },

        _onAddFloatingTopic: function () {
            const self = this;
            const $content = $(`
                <div class="form-group">
                    <label>${_t('Topic Text')}</label>
                    <input type="text" class="form-control" id="floating_title" value="${_t('Floating Topic')}"/>
                </div>
                <div class="form-group">
                    <label>${_t('Note')}</label>
                    <textarea class="form-control" id="floating_note" rows="3"></textarea>
                </div>
            `);

            const dialog = new Dialog(this, {
                title: _t('Add Floating Topic'),
                $content: $content,
                buttons: [
                    {
                        text: _t('Add'),
                        classes: 'btn-primary',
                        click: function () {
                            const title = $content.find('#floating_title').val();
                            const note = $content.find('#floating_note').val();
                            self._createFloatingTopic(title, note);
                            dialog.close();
                        }
                    },
                    { text: _t('Cancel'), close: true }
                ],
            });
            dialog.open();
        },

        _createFloatingTopic: function (title, note) {
            const canvas = this.$('.o_mindmap_canvas')[0];
            const floatingDiv = document.createElement('div');
            floatingDiv.className = 'xmind-floating-topic';
            floatingDiv.style.position = 'absolute';
            floatingDiv.style.left = '100px';
            floatingDiv.style.top = '100px';
            floatingDiv.style.background = '#e0e0e0';
            floatingDiv.style.padding = '10px 16px';
            floatingDiv.style.borderRadius = '8px';
            floatingDiv.style.boxShadow = '0 2px 8px rgba(0,0,0,0.15)';
            floatingDiv.style.cursor = 'move';
            floatingDiv.style.zIndex = '20';
            floatingDiv.textContent = title;

            if (note) {
                floatingDiv.title = note;
            }

            // Make draggable
            let isDragging = false;
            let offsetX, offsetY;

            floatingDiv.addEventListener('mousedown', function (e) {
                isDragging = true;
                offsetX = e.clientX - floatingDiv.offsetLeft;
                offsetY = e.clientY - floatingDiv.offsetTop;
            });

            document.addEventListener('mousemove', function (e) {
                if (isDragging) {
                    floatingDiv.style.left = (e.clientX - offsetX) + 'px';
                    floatingDiv.style.top = (e.clientY - offsetY) + 'px';
                }
            });

            document.addEventListener('mouseup', function () {
                isDragging = false;
            });

            canvas.appendChild(floatingDiv);

            this.floatingTopics.push({
                element: floatingDiv,
                title: title,
                note: note
            });

            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Floating topic added'));
        },

        _onAddImage: function () {
            if (!this.selectedNode) {
                this._showWarning(_t('Please select a topic to add image'));
                return;
            }

            const self = this;
            const $content = $(`
                <div class="form-group">
                    <label>${_t('Select Image')}</label>
                    <input type="file" class="form-control-file" id="image_file" accept="image/*"/>
                </div>
                <div class="form-group">
                    <label>${_t('Position')}</label>
                    <select class="form-control" id="image_position">
                        <option value="above">Above Topic</option>
                        <option value="below">Below Topic</option>
                        <option value="left">Left of Topic</option>
                        <option value="right">Right of Topic</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>${_t('Max Width (px)')}</label>
                    <input type="number" class="form-control" id="image_width" value="100" min="50" max="300"/>
                </div>
            `);

            const dialog = new Dialog(this, {
                title: _t('Add Image/Sticker'),
                $content: $content,
                buttons: [
                    {
                        text: _t('Add'),
                        classes: 'btn-primary',
                        click: function () {
                            const fileInput = $content.find('#image_file')[0];
                            if (fileInput.files && fileInput.files[0]) {
                                const reader = new FileReader();
                                reader.onload = function (e) {
                                    const imageData = e.target.result;
                                    const options = {
                                        position: $content.find('#image_position').val(),
                                        width: parseInt($content.find('#image_width').val()),
                                        height: parseInt($content.find('#image_width').val()),
                                    };
                                    self._addImageToNode(imageData, options);
                                };
                                reader.readAsDataURL(fileInput.files[0]);
                            }
                            dialog.close();
                        }
                    },
                    { text: _t('Cancel'), close: true }
                ],
            });
            dialog.open();
        },

        _addImageToNode: function (imageData, options) {
            const nodeElement = this.jm.view.get_node_element(this.selectedNode);
            if (nodeElement) {
                this.imageRenderer.renderImage(nodeElement, imageData, options);

                // Store in node data
                const node = this.jm.get_node(this.selectedNode);
                node.data = node.data || {};
                node.data.image = {
                    data: imageData,
                    options: options
                };

                // Update sidebar preview
                this._updateImagePreview(node.data.image);

                this.commandStack.isDirty = true;
                this.commandStack._notifyListeners();
                this._updateStatus(_t('Image added to topic'));
            }
        },

        // ===== Insert Menu Handlers =====

        _onInsertImage: function (ev) {
            ev.preventDefault();
            this._onAddImage();
        },

        _onInsertHyperlink: function (ev) {
            ev.preventDefault();
            if (!this.selectedNode) {
                this._showWarning(_t('Please select a topic first'));
                return;
            }

            const self = this;
            const node = this.jm.get_node(this.selectedNode);
            const currentUrl = (node.data && node.data.hyperlink) || '';
            const currentTitle = (node.data && node.data.hyperlinkTitle) || '';

            const $content = $(`
                <div class="form-group">
                    <label>${_t('URL')}</label>
                    <input type="url" class="form-control" id="hyperlink_url" value="${currentUrl}" placeholder="https://..."/>
                </div>
                <div class="form-group">
                    <label>${_t('Title (optional)')}</label>
                    <input type="text" class="form-control" id="hyperlink_title" value="${currentTitle}" placeholder="Link description"/>
                </div>
                <div class="form-group">
                    <label>${_t('Quick Links')}</label>
                    <div class="btn-group-vertical w-100">
                        <button class="btn btn-outline-secondary btn-sm text-left" data-url="https://www.google.com">
                            <i class="fa fa-google"/> Google
                        </button>
                        <button class="btn btn-outline-secondary btn-sm text-left" data-url="https://www.github.com">
                            <i class="fa fa-github"/> GitHub
                        </button>
                        <button class="btn btn-outline-secondary btn-sm text-left" data-url="https://www.odoo.com">
                            <i class="fa fa-globe"/> Odoo
                        </button>
                    </div>
                </div>
            `);

            $content.find('[data-url]').click(function () {
                $content.find('#hyperlink_url').val($(this).data('url'));
            });

            const dialog = new Dialog(this, {
                title: _t('Insert Hyperlink'),
                $content: $content,
                buttons: [
                    {
                        text: _t('Insert'),
                        classes: 'btn-primary',
                        click: function () {
                            const url = $content.find('#hyperlink_url').val().trim();
                            const title = $content.find('#hyperlink_title').val().trim();
                            if (url) {
                                self._setTopicHyperlink(url, title);
                            }
                            dialog.close();
                        }
                    },
                    {
                        text: _t('Remove'),
                        classes: 'btn-outline-danger',
                        click: function () {
                            self._setTopicHyperlink('', '');
                            dialog.close();
                        }
                    },
                    { text: _t('Cancel'), close: true }
                ],
            });
            dialog.open();
        },

        _setTopicHyperlink: function (url, title) {
            if (!this.selectedNode) return;

            const node = this.jm.get_node(this.selectedNode);
            if (!node) return;

            node.data = node.data || {};
            node.data.hyperlink = url;
            node.data.hyperlinkTitle = title;

            // Update visual indicator on node
            const nodeElement = this.jm.view.get_node_element(this.selectedNode);
            if (nodeElement) {
                if (url) {
                    this.hyperlinkIndicator.addIndicator(nodeElement, url, title);
                } else {
                    this.hyperlinkIndicator.removeIndicator(nodeElement);
                }
            }

            // Update sidebar
            this.$('.o_topic_hyperlink').val(url);
            this.$('.o_topic_hyperlink_title').val(title);

            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(url ? _t('Hyperlink added') : _t('Hyperlink removed'));
        },

        _onInsertNote: function (ev) {
            ev.preventDefault();
            if (!this.selectedNode) {
                this._showWarning(_t('Please select a topic first'));
                return;
            }

            const self = this;
            const node = this.jm.get_node(this.selectedNode);
            const currentNote = (node.data && node.data.note) || '';

            const $content = $(`
                <div class="form-group">
                    <label>${_t('Note Content')}</label>
                    <textarea class="form-control" id="note_content" rows="10" style="font-family: monospace;">${currentNote}</textarea>
                    <small class="text-muted">
                        <span id="note_char_count">${currentNote.length}</span> ${_t('characters')}
                    </small>
                </div>
                <div class="form-group">
                    <label>${_t('Quick Insert')}</label>
                    <div class="btn-group">
                        <button class="btn btn-outline-secondary btn-sm" data-insert="• ">
                            <i class="fa fa-list"/> Bullet
                        </button>
                        <button class="btn btn-outline-secondary btn-sm" data-insert="1. ">
                            <i class="fa fa-list-ol"/> Number
                        </button>
                        <button class="btn btn-outline-secondary btn-sm" data-insert="[ ] ">
                            <i class="fa fa-square-o"/> Checkbox
                        </button>
                        <button class="btn btn-outline-secondary btn-sm" data-insert="---\n">
                            <i class="fa fa-minus"/> Divider
                        </button>
                    </div>
                </div>
            `);

            const textarea = $content.find('#note_content');
            textarea.on('input', function () {
                $content.find('#note_char_count').text(this.value.length);
            });

            $content.find('[data-insert]').click(function () {
                const text = $(this).data('insert');
                const pos = textarea[0].selectionStart;
                const val = textarea.val();
                textarea.val(val.substring(0, pos) + text + val.substring(pos));
                textarea.focus();
                textarea[0].selectionStart = textarea[0].selectionEnd = pos + text.length;
            });

            const dialog = new Dialog(this, {
                title: _t('Edit Note'),
                size: 'large',
                $content: $content,
                buttons: [
                    {
                        text: _t('Save'),
                        classes: 'btn-primary',
                        click: function () {
                            const note = $content.find('#note_content').val();
                            self._setTopicNote(note);
                            dialog.close();
                        }
                    },
                    {
                        text: _t('Clear'),
                        classes: 'btn-outline-danger',
                        click: function () {
                            $content.find('#note_content').val('');
                            $content.find('#note_char_count').text('0');
                        }
                    },
                    { text: _t('Cancel'), close: true }
                ],
            });
            dialog.open();
        },

        _setTopicNote: function (note) {
            if (!this.selectedNode) return;

            const node = this.jm.get_node(this.selectedNode);
            if (!node) return;

            node.data = node.data || {};
            node.data.note = note;

            // Update visual indicator
            const nodeElement = this.jm.view.get_node_element(this.selectedNode);
            if (nodeElement) {
                this.noteIndicator.addIndicator(nodeElement, !!note);
            }

            // Update sidebar
            this.$('.o_topic_note').val(note);
            this.$('.o_topic_note_count').text(note.length + ' ' + _t('characters'));

            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Note updated'));
        },

        _onInsertAttachment: function (ev) {
            ev.preventDefault();
            if (!this.selectedNode) {
                this._showWarning(_t('Please select a topic first'));
                return;
            }

            const self = this;
            const $content = $(`
                <div class="form-group">
                    <label>${_t('Select File')}</label>
                    <input type="file" class="form-control-file" id="attachment_file"/>
                </div>
                <div class="form-group">
                    <label>${_t('Display Name (optional)')}</label>
                    <input type="text" class="form-control" id="attachment_name" placeholder="File name"/>
                </div>
            `);

            const dialog = new Dialog(this, {
                title: _t('Add Attachment'),
                $content: $content,
                buttons: [
                    {
                        text: _t('Attach'),
                        classes: 'btn-primary',
                        click: function () {
                            const fileInput = $content.find('#attachment_file')[0];
                            const name = $content.find('#attachment_name').val();
                            if (fileInput.files && fileInput.files[0]) {
                                self._addAttachment(fileInput.files[0], name);
                            }
                            dialog.close();
                        }
                    },
                    { text: _t('Cancel'), close: true }
                ],
            });
            dialog.open();
        },

        _addAttachment: function (file, displayName) {
            if (!this.selectedNode) return;

            const self = this;
            const node = this.jm.get_node(this.selectedNode);
            if (!node) return;

            const reader = new FileReader();
            reader.onload = function (e) {
                node.data = node.data || {};
                node.data.attachments = node.data.attachments || [];
                node.data.attachments.push({
                    name: displayName || file.name,
                    type: file.type,
                    size: file.size,
                    data: e.target.result
                });

                // Update visual indicator
                const nodeElement = self.jm.view.get_node_element(self.selectedNode);
                if (nodeElement) {
                    self.attachmentIndicator.addIndicator(nodeElement, node.data.attachments.length);
                }

                // Update sidebar
                self._updateAttachmentsList(node.data.attachments);

                self.commandStack.isDirty = true;
                self.commandStack._notifyListeners();
                self._updateStatus(_t('Attachment added: ') + file.name);
            };
            reader.readAsDataURL(file);
        },

        _onTopicNoteChange: function () {
            const note = this.$('.o_topic_note').val();
            this._setTopicNote(note);
        },

        _onTopicNoteInput: function () {
            const note = this.$('.o_topic_note').val();
            this.$('.o_topic_note_count').text(note.length + ' ' + _t('characters'));
        },

        _onTopicHyperlinkChange: function () {
            const url = this.$('.o_topic_hyperlink').val().trim();
            const title = this.$('.o_topic_hyperlink_title').val().trim();
            this._setTopicHyperlink(url, title);
        },

        _onOpenHyperlink: function () {
            const url = this.$('.o_topic_hyperlink').val().trim();
            if (url) {
                window.open(url, '_blank');
            }
        },

        _onChangeImage: function () {
            this._onAddImage();
        },

        _onRemoveImage: function () {
            if (!this.selectedNode) return;

            const node = this.jm.get_node(this.selectedNode);
            if (!node) return;

            node.data = node.data || {};
            delete node.data.image;

            // Remove from visual
            const nodeElement = this.jm.view.get_node_element(this.selectedNode);
            if (nodeElement) {
                const img = nodeElement.querySelector('.xmind-image');
                if (img) img.remove();
            }

            // Update sidebar
            this._updateImagePreview(null);

            this.commandStack.isDirty = true;
            this.commandStack._notifyListeners();
            this._updateStatus(_t('Image removed'));
        },

        _showFloatingTopicOption: function (node, x, y) {
            const self = this;
            const canvas = this.$('.o_mindmap_canvas')[0];

            // Create option dialog
            const optionDiv = document.createElement('div');
            optionDiv.className = 'floating-topic-option';
            optionDiv.style.left = x + 'px';
            optionDiv.style.top = y + 'px';

            optionDiv.innerHTML = `
                <h6>${_t('What would you like to do?')}</h6>
                <div>
                    <button class="btn btn-sm btn-success" data-action="root">
                        <i class="fa fa-sitemap"/> ${_t('Attach to Root')}
                    </button>
                    <button class="btn btn-sm btn-warning" data-action="floating">
                        <i class="fa fa-plus-circle"/> ${_t('Make Floating')}
                    </button>
                    <button class="btn btn-sm btn-secondary" data-action="cancel">
                        <i class="fa fa-times"/> ${_t('Cancel')}
                    </button>
                </div>
            `;

            canvas.appendChild(optionDiv);

            // Handle actions
            optionDiv.addEventListener('click', function (e) {
                const action = e.target.closest('[data-action]');
                if (!action) return;

                const actionType = action.getAttribute('data-action');

                if (actionType === 'root') {
                    // Attach to root
                    self.dragDropManager._performMove(node, self.jm.mind.root);
                } else if (actionType === 'floating') {
                    // Convert to floating topic (detach and create floating version)
                    self._convertToFloatingTopic(node, x, y);
                }

                // Remove option dialog
                if (optionDiv.parentNode) {
                    optionDiv.parentNode.removeChild(optionDiv);
                }
            });

            // Auto-close after 5 seconds
            setTimeout(function () {
                if (optionDiv.parentNode) {
                    optionDiv.parentNode.removeChild(optionDiv);
                }
            }, 5000);
        },

        _convertToFloatingTopic: function (node, x, y) {
            // Create a floating topic from the detached node
            const floatingDiv = document.createElement('div');
            floatingDiv.className = 'xmind-floating-topic';
            floatingDiv.style.cssText = `
                position: absolute;
                left: ${x}px;
                top: ${y}px;
                background: #fff3cd;
                padding: 10px 16px;
                border: 2px solid #ffc107;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.15);
                cursor: move;
                z-index: 20;
                min-width: 100px;
            `;
            floatingDiv.textContent = node.topic;

            if (node.data && node.data.note) {
                floatingDiv.title = node.data.note;
            }

            // Make draggable
            let isDragging = false;
            let offsetX, offsetY;

            floatingDiv.addEventListener('mousedown', function (e) {
                isDragging = true;
                offsetX = e.clientX - floatingDiv.offsetLeft;
                offsetY = e.clientY - floatingDiv.offsetTop;
                e.stopPropagation();
            });

            const moveHandler = function (e) {
                if (isDragging) {
                    floatingDiv.style.left = (e.clientX - offsetX) + 'px';
                    floatingDiv.style.top = (e.clientY - offsetY) + 'px';
                }
            };

            const upHandler = function () {
                isDragging = false;
            };

            document.addEventListener('mousemove', moveHandler);
            document.addEventListener('mouseup', upHandler);

            const canvas = this.$('.o_mindmap_canvas')[0];
            canvas.appendChild(floatingDiv);

            // Store floating topic data
            this.floatingTopics.push({
                element: floatingDiv,
                originalNode: node,
                title: node.topic,
                data: JSON.parse(JSON.stringify(node.data || {}))
            });

            // Remove the original node from the tree
            const cmd = new CommandModule.RemoveNodeCommand(this.jm, node.id);
            this.commandStack.execute(cmd);

            this._updateStatus(_t('Converted to floating topic: ') + node.topic);
        },

        // Format menu handlers
        _onFormatBold: function (e) {
            e.preventDefault();
            e.stopPropagation();
            this.formatState.bold = !this.formatState.bold;
            $(e.currentTarget).toggleClass('active', this.formatState.bold);
        },

        _onFormatItalic: function (e) {
            e.preventDefault();
            e.stopPropagation();
            this.formatState.italic = !this.formatState.italic;
            $(e.currentTarget).toggleClass('active', this.formatState.italic);
        },

        _onFormatUnderline: function (e) {
            e.preventDefault();
            e.stopPropagation();
            this.formatState.underline = !this.formatState.underline;
            $(e.currentTarget).toggleClass('active', this.formatState.underline);
        },

        _onFormatStrikethrough: function (e) {
            e.preventDefault();
            e.stopPropagation();
            this.formatState.strikethrough = !this.formatState.strikethrough;
            $(e.currentTarget).toggleClass('active', this.formatState.strikethrough);
        },

        _onFormatHSpaceChange: function (e) {
            const value = $(e.currentTarget).val();
            this.$('.o_format_h_space_val').text(value + 'px');
        },

        _onFormatVSpaceChange: function (e) {
            const value = $(e.currentTarget).val();
            this.$('.o_format_v_space_val').text(value + 'px');
        },

        _onFormatStructureChange: function (e) {
            const structureType = $(e.currentTarget).val();
            this._applyLayoutType(structureType);
        },

        _applyLayoutType: function (layoutType) {
            // Map layout types to jsMind compatible layouts
            const layoutMap = {
                'map': 'side',
                'tree_right': 'right',
                'tree_left': 'left',
                'logic_right': 'right',
                'logic_left': 'left',
                'org_chart_down': 'side',
                'org_chart_up': 'side',
                'fishbone_left': 'left',
                'fishbone_right': 'right'
            };

            const jsmindLayout = layoutMap[layoutType] || 'side';

            if (this.jm) {
                // Store current mind data
                const mindData = this.jm.get_data('node_tree');

                // Re-initialize with new layout
                this.jm.options.layout = { type: jsmindLayout };
                this.jm.view.relayout();

                // Re-render XMind features
                setTimeout(() => {
                    this._renderAllXMindFeatures();
                }, 100);

                this._updateStatus(_t('Layout changed to: ') + layoutType);
            }
        },

        _onFormatApply: function (e) {
            e.preventDefault();
            e.stopPropagation();

            const styleData = this._collectFormatSettings();

            // Check if multiple nodes are selected
            if (this.selectedNodes.length > 0) {
                // Apply to all selected nodes
                for (let node of this.selectedNodes) {
                    this._applyStyleToNode(node, styleData);

                    // Apply branch styles if node has children
                    if (node.children && node.children.length > 0) {
                        this._applyBranchStyles(node, styleData.branch);
                    }
                }
                this._updateStatus(_t('Style applied to ') + this.selectedNodes.length + _t(' topics'));
            } else if (this.selectedNode) {
                // Apply to single selected node
                this._applyStyleToNode(this.selectedNode, styleData);

                // Apply branch styles if node has children
                if (this.selectedNode.children && this.selectedNode.children.length > 0) {
                    this._applyBranchStyles(this.selectedNode, styleData.branch);
                }

                this._updateStatus(_t('Style applied to: ') + this.selectedNode.topic);
            } else {
                this._showNotification(_t('Please select at least one topic first'), 'warning');
                return;
            }
        },

        _onFormatApplyAll: function (e) {
            e.preventDefault();
            e.stopPropagation();

            const styleData = this._collectFormatSettings();
            const nodes = this.jm.mind.nodes;

            for (let id in nodes) {
                const node = nodes[id];
                this._applyStyleToNode(node, styleData);
            }

            // Apply global branch styles
            this._applyGlobalBranchStyles(styleData.branch);

            // Apply layout spacing
            this._applyLayoutSpacing(styleData.layout);

            this._updateStatus(_t('Style applied to all topics'));
        },

        _onFormatReset: function (e) {
            e.preventDefault();
            e.stopPropagation();

            // Reset format state
            this.formatState = {
                bold: false,
                italic: false,
                underline: false,
                strikethrough: false
            };

            // Reset UI toggles
            this.$('.o_format_bold, .o_format_italic, .o_format_underline, .o_format_strikethrough').removeClass('active');

            // Reset shape settings
            this.$('.o_format_shape_type').val('rounded');
            this.$('.o_format_fill_color').val('#ffffff');
            this.$('.o_format_border_color').val('#558ED5');
            this.$('.o_format_border_width').val('2');

            // Reset form values to defaults
            this.$('.o_format_font_family').val('inherit');
            this.$('.o_format_font_size').val('14');
            this.$('.o_format_text_color').val('#333333');
            this.$('.o_format_bg_color').val('#ffffff');
            this.$('.o_format_structure_type').val('map');
            this.$('.o_format_h_space').val(80);
            this.$('.o_format_h_space_val').text('80px');
            this.$('.o_format_v_space').val(25);
            this.$('.o_format_v_space_val').text('25px');
            this.$('.o_format_line_type').val('curved');
            this.$('.o_format_line_width').val('2');
            this.$('.o_format_line_color').val('#558ED5');
            this.$('.o_format_line_style').val('solid');

            this._updateStatus(_t('Format settings reset to default'));
        },

        _collectFormatSettings: function () {
            return {
                shape: {
                    type: this.$('.o_format_shape_type').val(),
                    fillColor: this.$('.o_format_fill_color').val(),
                    borderColor: this.$('.o_format_border_color').val(),
                    borderWidth: parseInt(this.$('.o_format_border_width').val())
                },
                text: {
                    fontFamily: this.$('.o_format_font_family').val(),
                    fontSize: this.$('.o_format_font_size').val(),
                    color: this.$('.o_format_text_color').val(),
                    bgColor: this.$('.o_format_bg_color').val(),
                    bold: this.formatState.bold,
                    italic: this.formatState.italic,
                    underline: this.formatState.underline,
                    strikethrough: this.formatState.strikethrough
                },
                layout: {
                    type: this.$('.o_format_structure_type').val(),
                    hSpace: parseInt(this.$('.o_format_h_space').val()),
                    vSpace: parseInt(this.$('.o_format_v_space').val())
                },
                branch: {
                    lineType: this.$('.o_format_line_type').val(),
                    lineWidth: parseInt(this.$('.o_format_line_width').val()),
                    lineColor: this.$('.o_format_line_color').val(),
                    lineStyle: this.$('.o_format_line_style').val()
                }
            };
        },

        _applyStyleToNode: function (node, styleData) {
            const element = this.jm.view.get_node_element(node.id);
            if (!element) return;

            // Apply shape styles
            if (styleData.shape) {
                this._applyShapeToNode(element, styleData.shape);
                if (!node.data) node.data = {};
                node.data.shape = styleData.shape;
            }

            const textStyle = styleData.text;

            // Apply font family
            if (textStyle.fontFamily && textStyle.fontFamily !== 'inherit') {
                element.style.fontFamily = textStyle.fontFamily;
            }

            // Apply font size
            if (textStyle.fontSize) {
                element.style.fontSize = textStyle.fontSize + 'px';
            }

            // Apply text color
            if (textStyle.color) {
                element.style.color = textStyle.color;
            }

            // Apply background color (only if not using shape fill)
            if (textStyle.bgColor && textStyle.bgColor !== '#ffffff' && !styleData.shape) {
                element.style.backgroundColor = textStyle.bgColor;
            }

            // Apply text decorations
            let fontWeight = textStyle.bold ? 'bold' : 'normal';
            let fontStyle = textStyle.italic ? 'italic' : 'normal';
            let textDecoration = [];

            if (textStyle.underline) textDecoration.push('underline');
            if (textStyle.strikethrough) textDecoration.push('line-through');

            element.style.fontWeight = fontWeight;
            element.style.fontStyle = fontStyle;
            element.style.textDecoration = textDecoration.length > 0 ? textDecoration.join(' ') : 'none';

            // Store style data in node
            if (!node.data) node.data = {};
            node.data.style = textStyle;
        },

        _applyShapeToNode: function (element, shapeData) {
            if (!element || !shapeData) return;

            // Reset previous shape styles
            element.style.borderRadius = '';
            element.style.clipPath = '';
            element.style.border = '';
            element.style.backgroundColor = '';
            element.classList.remove('shape-rectangle', 'shape-rounded', 'shape-ellipse', 'shape-diamond', 'shape-parallelogram', 'shape-hexagon', 'shape-cloud', 'shape-underline');

            // Apply shape type
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
                    element.style.borderRadius = '0';
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
                    return; // Skip other border/fill for underline
            }

            // Apply fill color
            if (shapeData.fillColor) {
                element.style.backgroundColor = shapeData.fillColor;
            }

            // Apply border
            if (shapeData.borderColor && shapeData.borderWidth) {
                element.style.border = `${shapeData.borderWidth}px solid ${shapeData.borderColor}`;
            }
        },

        _applyBranchStyles: function (node, branchStyle) {
            // Apply branch line styles to SVG paths
            const svgContainer = this.jm.view.e_lines;
            if (!svgContainer) return;

            const paths = svgContainer.querySelectorAll('path');
            paths.forEach(path => {
                // Check if this path is connected to the node
                const pathData = path.getAttribute('d');
                const nodeElement = this.jm.view.get_node_element(node.id);
                if (nodeElement) {
                    const rect = nodeElement.getBoundingClientRect();
                    const containerRect = svgContainer.getBoundingClientRect();

                    // Apply styles to paths near this node
                    path.style.stroke = branchStyle.lineColor;
                    path.style.strokeWidth = branchStyle.lineWidth + 'px';

                    // Apply line style
                    switch (branchStyle.lineStyle) {
                        case 'dashed':
                            path.style.strokeDasharray = '8, 4';
                            break;
                        case 'dotted':
                            path.style.strokeDasharray = '2, 2';
                            break;
                        default:
                            path.style.strokeDasharray = 'none';
                    }
                }
            });
        },

        _applyGlobalBranchStyles: function (branchStyle) {
            this.branchStyleSettings = branchStyle;

            const svgContainer = this.jm.view.e_lines;
            if (!svgContainer) return;

            const paths = svgContainer.querySelectorAll('path');
            paths.forEach(path => {
                path.style.stroke = branchStyle.lineColor;
                path.style.strokeWidth = branchStyle.lineWidth + 'px';

                switch (branchStyle.lineStyle) {
                    case 'dashed':
                        path.style.strokeDasharray = '8, 4';
                        break;
                    case 'dotted':
                        path.style.strokeDasharray = '2, 2';
                        break;
                    default:
                        path.style.strokeDasharray = 'none';
                }
            });

            // Store in jsMind options for persistence
            if (this.jm.options.view) {
                this.jm.options.view.line_color = branchStyle.lineColor;
                this.jm.options.view.line_width = branchStyle.lineWidth;
            }
        },

        _applyLayoutSpacing: function (layoutSettings) {
            if (this.jm && this.jm.options.layout) {
                this.jm.options.layout.hspace = layoutSettings.hSpace;
                this.jm.options.layout.vspace = layoutSettings.vSpace;

                // Relayout with new spacing
                this.jm.view.relayout();

                // Re-render XMind features
                setTimeout(() => {
                    this._renderAllXMindFeatures();
                    this._applyGlobalBranchStyles(this.branchStyleSettings);
                }, 100);
            }
        },

        _restoreNodeStyle: function (element, styleData) {
            if (!element || !styleData) return;

            // Restore font family
            if (styleData.fontFamily && styleData.fontFamily !== 'inherit') {
                element.style.fontFamily = styleData.fontFamily;
            }

            // Restore font size
            if (styleData.fontSize) {
                element.style.fontSize = styleData.fontSize + 'px';
            }

            // Restore text color
            if (styleData.color) {
                element.style.color = styleData.color;
            }

            // Restore background color
            if (styleData.bgColor && styleData.bgColor !== '#ffffff') {
                element.style.backgroundColor = styleData.bgColor;
            }

            // Restore text decorations
            if (styleData.bold !== undefined) {
                element.style.fontWeight = styleData.bold ? 'bold' : 'normal';
            }

            if (styleData.italic !== undefined) {
                element.style.fontStyle = styleData.italic ? 'italic' : 'normal';
            }

            let textDecoration = [];
            if (styleData.underline) textDecoration.push('underline');
            if (styleData.strikethrough) textDecoration.push('line-through');
            element.style.textDecoration = textDecoration.length > 0 ? textDecoration.join(' ') : 'none';
        },

        // Multi-selection methods
        _selectNodesInRect: function (selRect) {
            const nodes = this.jm.mind.nodes;
            const canvasRect = this.$('.o_mindmap_canvas')[0].getBoundingClientRect();

            for (let id in nodes) {
                const node = nodes[id];
                const element = this.jm.view.get_node_element(id);
                if (!element) continue;

                const nodeRect = element.getBoundingClientRect();

                // Check if node is within selection rectangle
                if (this._rectsIntersect(selRect, nodeRect)) {
                    this._addNodeToSelection(node);
                }
            }

            this._updateSelectionCount();
        },

        _rectsIntersect: function (rect1, rect2) {
            return !(rect2.left > rect1.right ||
                rect2.right < rect1.left ||
                rect2.top > rect1.bottom ||
                rect2.bottom < rect1.top);
        },

        _toggleNodeSelection: function (node) {
            const index = this.selectedNodes.findIndex(n => n.id === node.id);
            if (index > -1) {
                this.selectedNodes.splice(index, 1);
                this._highlightNode(node, false);
            } else {
                this._addNodeToSelection(node);
            }
            this._updateSelectionCount();
        },

        _addNodeToSelection: function (node) {
            if (!this.selectedNodes.find(n => n.id === node.id)) {
                this.selectedNodes.push(node);
                this._highlightNode(node, true);
            }
            this._updateSelectionCount();
        },

        _highlightNode: function (node, highlight) {
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
        },

        _clearMultiSelection: function () {
            for (let node of this.selectedNodes) {
                this._highlightNode(node, false);
            }
            this.selectedNodes = [];
            this._updateSelectionCount();
        },

        _updateSelectionCount: function () {
            const count = this.selectedNodes.length;
            const badge = this.$('.o_mindmap_selection_count');
            const countSpan = badge.find('.count');

            if (count > 0) {
                badge.show();
                countSpan.text(count);
            } else {
                badge.hide();
            }
        },

        _onToggleMultiSelect: function () {
            this.multiSelectMode = !this.multiSelectMode;
            this.$('.o_mindmap_btn_multiselect').toggleClass('active btn-primary', this.multiSelectMode);

            if (this.multiSelectMode) {
                this._updateStatus(_t('Multi-select mode enabled. Click or drag to select multiple topics.'));
            } else {
                this._updateStatus(_t('Multi-select mode disabled'));
            }
        },

        _onClearSelection: function () {
            this._clearMultiSelection();
            this._updateStatus(_t('Selection cleared'));
        },

        _renderAllXMindFeatures: function () {
            // Re-render all XMind 2 features after layout changes
            const self = this;

            // Render markers on all nodes
            const nodes = this.jm.mind.nodes;
            for (let id in nodes) {
                const node = nodes[id];
                const element = this.jm.view.get_node_element(id);
                if (element && node.data) {
                    // Restore saved shape styles
                    if (node.data.shape) {
                        this._applyShapeToNode(element, node.data.shape);
                    }
                    // Restore saved text styles
                    if (node.data.style) {
                        this._restoreNodeStyle(element, node.data.style);
                    }
                    // Render markers
                    if (node.data.markers && node.data.markers.length > 0) {
                        this.markerBadgeRenderer.renderMarkers(element, node.data.markers, this.markers);
                    }
                    // Render labels
                    if (node.data.labels && node.data.labels.length > 0) {
                        this.labelRenderer.renderLabels(element, node.data.labels);
                    }
                    // Render note indicator
                    if (node.data.note) {
                        this.noteIndicator.addIndicator(element, true);
                    }
                    // Render hyperlink indicator
                    if (node.data.hyperlink) {
                        this.hyperlinkIndicator.addIndicator(element, node.data.hyperlink, node.data.hyperlinkTitle);
                    }
                    // Render attachment indicator
                    if (node.data.attachments && node.data.attachments.length > 0) {
                        this.attachmentIndicator.addIndicator(element, node.data.attachments.length);
                    }
                    // Render image
                    if (node.data.image) {
                        this.imageRenderer.renderImage(element, node.data.image.data, node.data.image.options);
                    }
                }
            }

            // Re-render boundaries
            this.boundaryRenderer.clear();
            for (let boundary of this.boundaries) {
                const elements = boundary.topicIds.map(id => this.jm.view.get_node_element(id)).filter(e => e);
                if (elements.length > 0) {
                    this.boundaryRenderer.addBoundary(elements, boundary.options);
                }
            }

            // Re-render summaries
            this.summaryRenderer.clear();
            for (let summary of this.summaries) {
                const topicElements = summary.topicIds.map(id => this.jm.view.get_node_element(id)).filter(e => e);
                const summaryElement = this.jm.view.get_node_element(summary.summaryNodeId);
                if (topicElements.length > 0 && summaryElement) {
                    this.summaryRenderer.addSummary(topicElements, summaryElement);
                }
            }

            // Re-render relationships
            this.relationshipRenderer.clear();
            for (let rel of this.relationships) {
                const sourceElement = this.jm.view.get_node_element(rel.sourceId);
                const targetElement = this.jm.view.get_node_element(rel.targetId);
                if (sourceElement && targetElement) {
                    this.relationshipRenderer.addRelationship(sourceElement, targetElement, rel.options);
                }
            }
        },
    });

    core.action_registry.add('dobtor_xmind.mindmap_editor', MindmapEditor);

    return MindmapEditor;
});
