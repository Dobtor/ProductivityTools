/** @odoo-module **/

/**
 * 心智圖畫布的右鍵選單（節點／標記／空白處／關連線）。
 *
 * 從 mindmap_editor.js 抽出來的 547 行。它其實是「編輯器命令的選單」——
 * 原本 71 個 `this.*` 有 62 個是在呼叫編輯器身上的東西，留在 god-component
 * 裡看起來像自家邏輯，其實是對整個編輯器 API 的分派表。抽出來之後這個相依
 * 變成建構子參數，grep 得到、也擋得住「順手多讀一個內部狀態」。
 *
 * 作法比照同檔案夾的 DragDropManager / RelationshipManager：不是 OWL 元件，
 * 因為這些選單是命令式地建 DOM 再掛到 document 上（一次只會有一個），改寫成
 * 元件需要連同 overlay 服務一起重做，而這 547 行目前沒有任何自動化測試
 * 護欄 —— 那屬於另一次有 UI 測試打底的改版。
 */
import { _t } from "@web/core/l10n/translation";

export class MindmapContextMenu {
    /** @param {import("@dobtor_xmind/js/mindmap_editor").MindmapEditor} editor */
    constructor(editor) {
        this.editor = editor;
    }

    setup() {
        const canvas = this.editor.canvasRef.el;
        if (!canvas) return;

        canvas.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            e.stopPropagation();

            // Fix #5: Right-click cancels relationship mode
            if (this.editor.relationshipMode) {
                this.editor._exitRelationshipMode();
                return;
            }

            // Remove existing context menus
            document.querySelectorAll('.o_xmind_context_menu').forEach(el => el.remove());

            // Check if right-clicking on a relationship line
            const relPath = e.target.closest('.relationship-path');
            const relGroup = relPath ? relPath.closest('g[data-rel-id]') : null;

            if (relGroup) {
                this._showRelationshipContextMenu(e, relGroup.getAttribute('data-rel-id'));
                return;
            }

            // Fix #8: Right-click on marker badge → show replace/remove menu
            const markerBadge = e.target.closest('.xmind-marker-badge');
            if (markerBadge) {
                const nodeElement = markerBadge.closest('.xmind-node');
                if (nodeElement) {
                    const nodeId = nodeElement.getAttribute('data-nodeid');
                    const markerCode = markerBadge.dataset.markerCode;
                    this._showMarkerContextMenu(e, nodeId, markerCode);
                    return;
                }
            }

            const nodeElement = e.target.closest('.xmind-node');
            if (nodeElement) {
                this._showNodeContextMenu(e, nodeElement);
            } else {
                this._showCanvasContextMenu(e);
            }
        });
    }

    _showNodeContextMenu(e, nodeElement) {
        const nodeId = nodeElement.getAttribute('data-nodeid');
        const node = this.editor.jm.get_node(nodeId);
        if (!node) return;

        const isRoot = node.isroot;

        const menu = document.createElement('div');
        menu.className = 'o_xmind_context_menu dropdown-menu show';
        menu.style.cssText = `position: fixed; left: ${e.clientX}px; top: ${e.clientY}px; z-index: 10000;`;

        const hasChildren = node.children && node.children.length > 0;

        const items = [
            // Edit group
            { icon: 'fa-pencil', label: _t('Edit (F2)'), action: 'edit', disabled: false },
            { divider: true },
            // Topic creation group (Insert submenu)
            { icon: 'fa-plus', label: _t('Topic (Enter)'), action: 'addSibling', disabled: isRoot },
            { icon: 'fa-level-down', label: _t('Subtopic (Tab)'), action: 'addChild', disabled: false },
            { icon: 'fa-level-up', label: _t('Topic Before (Shift+Enter)'), action: 'addBefore', disabled: isRoot },
            { icon: 'fa-outdent', label: _t('Parent Topic (Ctrl+Enter)'), action: 'addParent', disabled: isRoot },
            { icon: 'fa-comment', label: _t('Callout'), action: 'callout', disabled: false },
            { divider: true },
            // Structure elements
            { icon: 'fa-link', label: _t('Relationship'), action: 'relationship', disabled: false },
            { icon: 'fa-square-o', label: _t('Boundary'), action: 'boundary', disabled: false },
            { icon: 'fa-indent', label: _t('Summary'), action: 'summary', disabled: isRoot },
            { divider: true },
            // Insert content
            { icon: 'fa-flag', label: _t('Marker'), action: 'marker', disabled: false },
            { icon: 'fa-sticky-note', label: _t('Notes'), action: 'note', disabled: false },
            { icon: 'fa-tag', label: _t('Label'), action: 'label', disabled: false },
            { icon: 'fa-link', label: _t('Hyperlink'), action: 'hyperlink', disabled: false },
            { icon: 'fa-image', label: _t('Image'), action: 'image', disabled: false },
            { divider: true },
            // Clipboard (Cut/Copy/Paste/Duplicate)
            { icon: 'fa-scissors', label: _t('Cut (Ctrl+X)'), action: 'cutTopic', disabled: isRoot },
            { icon: 'fa-copy', label: _t('Copy (Ctrl+C)'), action: 'copyTopic', disabled: false },
            { icon: 'fa-paste', label: _t('Paste (Ctrl+V)'), action: 'pasteTopic', disabled: !this.editor._clipboardTopic },
            { icon: 'fa-files-o', label: _t('Duplicate (Ctrl+D)'), action: 'duplicateTopic', disabled: isRoot },
            { divider: true },
            // Style
            { icon: 'fa-clone', label: _t('Copy Style'), action: 'copyStyle', disabled: false },
            { icon: 'fa-paint-brush', label: _t('Paste Style'), action: 'pasteStyle', disabled: !this.editor._copiedStyle },
            { icon: 'fa-eraser', label: _t('Reset Style'), action: 'resetStyle', disabled: false },
            { divider: true },
            // Visibility (Extend/Collapse/ExtendAll/CollapseAll)
            { icon: node.expanded ? 'fa-compress' : 'fa-expand', label: node.expanded ? _t('Collapse') : _t('Expand'), action: 'toggle', disabled: !hasChildren },
            { icon: 'fa-expand', label: _t('Expand All'), action: 'expandAllFromNode', disabled: !hasChildren },
            { icon: 'fa-compress', label: _t('Collapse All'), action: 'collapseAllFromNode', disabled: !hasChildren },
            { divider: true },
            // Navigation
            { icon: 'fa-arrow-circle-down', label: _t('Drill Down'), action: 'drillDown', disabled: !hasChildren },
            { icon: 'fa-arrow-circle-up', label: _t('Drill Up'), action: 'drillUp', disabled: !this.editor._drillStack || this.editor._drillStack.length === 0 },
            { divider: true },
            // Position (Move/Sort)
            { icon: 'fa-arrow-up', label: _t('Move Up (Alt+↑)'), action: 'moveUp', disabled: isRoot },
            { icon: 'fa-arrow-down', label: _t('Move Down (Alt+↓)'), action: 'moveDown', disabled: isRoot },
            { icon: 'fa-sort-alpha-asc', label: _t('Sort A→Z'), action: 'sortAsc', disabled: !hasChildren || node.children.length < 2 },
            { icon: 'fa-sort-alpha-desc', label: _t('Sort Z→A'), action: 'sortDesc', disabled: !hasChildren || node.children.length < 2 },
            { icon: 'fa-sort-numeric-asc', label: _t('Sort by Priority'), action: 'sortPriority', disabled: !hasChildren || node.children.length < 2 },
            { divider: true },
            // Selection
            { icon: 'fa-users', label: _t('Select Siblings'), action: 'selectSiblings', disabled: isRoot },
            { icon: 'fa-level-down', label: _t('Select Children'), action: 'selectChildren', disabled: !hasChildren },
            { divider: true },
            // Branch Style
            { icon: 'fa-code-fork', label: _t('Branch Style...'), action: 'branchStyle', disabled: isRoot },
            // Properties
            { icon: 'fa-cog', label: _t('Properties'), action: 'properties', disabled: false },
            { divider: true },
            // Floating topic specific
            { icon: 'fa-arrows', label: _t('Convert to Regular Topic'), action: 'convertFloating', disabled: !(node.data && node.data._isFloatingTopic) },
            // Delete
            { icon: 'fa-trash text-danger', label: _t('Delete (Del)'), action: 'delete', disabled: isRoot, cls: 'text-danger' },
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

    // Fix #8: Marker right-click replacement menu
    _showMarkerContextMenu(e, nodeId, markerCode) {
        const node = this.editor.jm.get_node(nodeId);
        if (!node) return;

        const menu = document.createElement('div');
        menu.className = 'o_xmind_context_menu dropdown-menu show';
        menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:10000;max-height:300px;overflow-y:auto;`;

        // Find current marker's category to show same-category alternatives
        const currentMarker = this.editor.markers.find(m => m.code === markerCode);
        const category = currentMarker ? currentMarker.category : '';
        const sameCategory = this.editor.markers.filter(m => m.category === category);

        for (const marker of sameCategory) {
            const item = document.createElement('a');
            item.className = 'dropdown-item' + (marker.code === markerCode ? ' active' : '');
            item.href = '#';
            item.innerHTML = `<i class="${marker.icon}" style="color:${marker.color}"></i> ${marker.name}`;
            item.addEventListener('click', (ev) => {
                ev.preventDefault();
                // Replace marker
                if (!node.data) node.data = {};
                if (!node.data.markers) node.data.markers = [];
                const idx = node.data.markers.indexOf(markerCode);
                if (idx > -1) node.data.markers[idx] = marker.code;
                // Re-render
                const element = this.editor.jm.view.get_node_element(nodeId);
                if (element) this.editor.markerBadgeRenderer.renderMarkers(element, node.data.markers, this.editor.markers);
                this.editor.commandStack.isDirty = true;
                this.editor.commandStack._notifyListeners();
                menu.remove();
            });
            menu.appendChild(item);
        }

        // Remove marker option
        const divider = document.createElement('div');
        divider.className = 'dropdown-divider';
        menu.appendChild(divider);
        const removeItem = document.createElement('a');
        removeItem.className = 'dropdown-item text-danger';
        removeItem.href = '#';
        removeItem.innerHTML = `<i class="fa fa-trash"></i> ${_t('Remove Marker')}`;
        removeItem.addEventListener('click', (ev) => {
            ev.preventDefault();
            if (node.data && node.data.markers) {
                node.data.markers = node.data.markers.filter(c => c !== markerCode);
                const element = this.editor.jm.view.get_node_element(nodeId);
                if (element) this.editor.markerBadgeRenderer.renderMarkers(element, node.data.markers, this.editor.markers);
                this.editor.commandStack.isDirty = true;
                this.editor.commandStack._notifyListeners();
            }
            menu.remove();
        });
        menu.appendChild(removeItem);

        document.body.appendChild(menu);
        setTimeout(() => {
            const closeHandler = () => { menu.remove(); document.removeEventListener('click', closeHandler); };
            document.addEventListener('click', closeHandler);
        }, 100);
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
        const relData = this.editor.relationships.find(r => r.id === relId);
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
                    this.editor._showRelationshipPropertiesDialog(relData.sourceId, relData.targetId, relId);
                } else if (item.action === 'controlPoints') {
                    this.editor.advancedRelationshipManager.selectRelationship(relId);
                    this.editor._updateStatus(_t('Drag green points to adjust curve, blue/red to move endpoints'));
                } else if (item.action === 'delete') {
                    this.editor.advancedRelationshipManager.removeRelationship(relId);
                    const idx = this.editor.relationships.findIndex(r => r.id === relId);
                    if (idx > -1) this.editor.relationships.splice(idx, 1);
                    this.editor.commandStack.isDirty = true;
                    this.editor.commandStack._notifyListeners();
                    this.editor._updateStatus(_t('Relationship deleted'));
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
                if (nodeId) this.editor.jm.select_node(nodeId);
                this.editor.selectedNode = nodeId;
                this.editor.onAddChild();
                break;
            case 'addSibling':
                if (nodeId) this.editor.jm.select_node(nodeId);
                this.editor.selectedNode = nodeId;
                this.editor.onAddSibling();
                break;
            case 'addBefore':
                this.editor.selectedNode = nodeId;
                this.editor.onAddTopicBefore();
                break;
            case 'addParent':
                this.editor.selectedNode = nodeId;
                this.editor.onAddParentTopic();
                break;
            case 'edit':
                this.editor.selectedNode = nodeId;
                this.editor._editSelectedNode();
                break;
            case 'moveUp':
                this.editor.selectedNode = nodeId;
                this.editor.onMoveUp();
                break;
            case 'moveDown':
                this.editor.selectedNode = nodeId;
                this.editor.onMoveDown();
                break;
            case 'cutTopic':
                this.editor.selectedNode = nodeId;
                this.editor.onCutTopic();
                break;
            case 'copyTopic':
                this.editor.selectedNode = nodeId;
                this.editor.onCopyTopic();
                break;
            case 'pasteTopic':
                this.editor.selectedNode = nodeId;
                this.editor.onPasteTopic();
                break;
            case 'duplicateTopic':
                this.editor.selectedNode = nodeId;
                this.editor.onDuplicateTopic();
                break;
            case 'drillDown':
                this.editor.selectedNode = nodeId;
                this.editor.onDrillDown();
                break;
            case 'drillUp':
                this.editor.onDrillUp();
                break;
            case 'sortAsc':
                this.editor.selectedNode = nodeId;
                this.editor.onSortAscending();
                break;
            case 'sortDesc':
                this.editor.selectedNode = nodeId;
                this.editor.onSortDescending();
                break;
            case 'sortPriority':
                this.editor.selectedNode = nodeId;
                this.editor.onSortByPriority();
                break;
            case 'selectSiblings':
                this.editor.selectedNode = nodeId;
                this.editor.onSelectSiblings();
                break;
            case 'selectChildren':
                this.editor.selectedNode = nodeId;
                this.editor.onSelectChildren();
                break;
            case 'copyStyle':
                this._copyNodeStyle(nodeId);
                break;
            case 'pasteStyle':
                this._pasteNodeStyle(nodeId);
                break;
            case 'resetStyle':
                this.editor.selectedNode = nodeId;
                this.editor.onResetStyle();
                break;
            case 'relationship':
                this.editor.selectedNode = nodeId;
                this.editor.onAddRelationship();
                break;
            case 'boundary':
                this.editor.selectedNode = nodeId;
                this.editor.onAddBoundary();
                break;
            case 'summary':
                this.editor.selectedNode = nodeId;
                this.editor.onAddSummary();
                break;
            case 'callout':
                this.editor.selectedNode = nodeId;
                this.editor.onAddCallout();
                break;
            case 'marker':
                this.editor.selectedNode = nodeId;
                this.editor.onOpenMarker();
                break;
            case 'hyperlink':
                this.editor.selectedNode = nodeId;
                this.editor.onInsertHyperlink({ preventDefault: () => {} });
                break;
            case 'note':
                this.editor.selectedNode = nodeId;
                this.editor.onOpenNote();
                break;
            case 'image':
                this.editor.selectedNode = nodeId;
                this.editor.onAddImage();
                break;
            case 'toggle':
                this.editor.selectedNode = nodeId;
                this.editor._toggleSelectedExpand();
                break;
            case 'expandAllFromNode':
                this.editor.selectedNode = nodeId;
                this.editor.onExpandAllFromNode();
                break;
            case 'collapseAllFromNode':
                this.editor.selectedNode = nodeId;
                this.editor.onCollapseAllFromNode();
                break;
            case 'branchStyle':
                this.editor.selectedNode = nodeId;
                this.editor._showBranchStylePicker(nodeId);
                break;
            case 'properties':
                this.editor.selectedNode = nodeId;
                this.editor._openSidebar();
                this.editor._updateSidebar(nodeId);
                break;
            case 'label':
                this.editor.selectedNode = nodeId;
                this.editor._openSidebar();
                setTimeout(() => {
                    const el = this.editor._el('.o_topic_labels');
                    if (el) el.focus();
                }, 200);
                break;
            case 'convertFloating':
                this.editor._convertFloatingToRegular(nodeId);
                break;
            case 'delete':
                this.editor.selectedNode = nodeId;
                this.editor.onDelete();
                break;
            case 'floatingAt':
                if (originalEvent) {
                    const world = this.editor.jm.view.world;
                    if (world) {
                        const wr = world.getBoundingClientRect();
                        const zoom = this.editor._zoomLevel || 1;
                        const fx = (originalEvent.clientX - wr.left) / zoom;
                        const fy = (originalEvent.clientY - wr.top) / zoom;
                        this.editor._createFloatingTopicAt(_t('Floating Topic'), '', fx, fy);
                    }
                } else {
                    this.editor.onAddFloatingTopic();
                }
                break;
            case 'expandAll': this.editor.onExpandAll(); break;
            case 'collapseAll': this.editor.onCollapseAll(); break;
            case 'zoomIn': this.editor.onZoomIn(); break;
            case 'zoomOut': this.editor.onZoomOut(); break;
            case 'zoomFit': this.editor.onZoomFit(); break;
            case 'zoomReset': this.editor.onZoomReset(); break;
            case 'save': this.editor.onSave(); break;
            case 'zoomFitSelection': this.editor.onZoomFitSelection(); break;
            case 'overview': this.editor.onToggleOverview(); break;
            case 'outline': this.editor.onToggleOutline(); break;
            case 'themes': this.editor.onManageThemes(); break;
            case 'template': this.editor.onLoadTemplate(); break;
            case 'revisions': this.editor.onToggleRevisions(); break;
        }
    }

    _copyNodeStyle(nodeId) {
        const node = this.editor.jm.get_node(nodeId);
        if (!node) return;
        this.editor._copiedStyle = JSON.parse(JSON.stringify(node.data && node.data.style || {}));
        if (node.data && node.data.shape) {
            this.editor._copiedStyle._shape = JSON.parse(JSON.stringify(node.data.shape));
        }
        this.editor._updateStatus(_t('Style copied'));
    }

    _pasteNodeStyle(nodeId) {
        if (!this.editor._copiedStyle) return;
        const node = this.editor.jm.get_node(nodeId);
        if (!node) return;

        const element = this.editor.jm.view.get_node_element(nodeId);
        if (!element) return;

        node.data = node.data || {};
        const style = { ...this.editor._copiedStyle };
        const shape = style._shape;
        delete style._shape;

        node.data.style = style;
        this.editor._restoreNodeStyle(element, style);

        if (shape) {
            node.data.shape = shape;
            this.editor._applyShapeToNode(element, shape);
        }

        this.editor.commandStack.isDirty = true;
        this.editor.commandStack._notifyListeners();
        this.editor._updateStatus(_t('Style pasted'));
    }
}
