/** @odoo-module **/

/**
 * Drag and Drop Manager for XMind 2 Style Topic Reorganization
 * Supports: Detach, Reparent, Visual Feedback
 */
import { _t } from "@web/core/l10n/translation";

export class DragDropManager {
    constructor(jm, editor) {
        this.jm = jm;
        this.editor = editor;
        this.isDragging = false;
        this.draggedNode = null;
        this.draggedElement = null;
        this.ghostElement = null;
        this.dropIndicator = null;
        this.potentialTarget = null;
        this.startX = 0;
        this.startY = 0;
        this.offsetX = 0;
        this.offsetY = 0;
        this.dragThreshold = 10;
        this.dropProximity = 80; // pixels to detect drop target

        // XMind-style drag and drop
        this.freePositioningMode = false; // Default to XMind behavior (attach to parent)
        this.shiftPressed = false; // Track Shift key
        this.draggedChildren = []; // Store child nodes being dragged with parent
        this.childrenOffsets = []; // Store relative offsets of children
        this.attachmentDistance = 50; // Distance to trigger attachment (pixels)

        this._boundMouseDown = this._onMouseDown.bind(this);
        this._boundMouseMove = this._onMouseMove.bind(this);
        this._boundMouseUp = this._onMouseUp.bind(this);
        this._boundKeyDown = this._onKeyDown.bind(this);
        this._boundKeyUp = this._onKeyUp.bind(this);
    }

    init() {
        // Defensive check
        if (!this.jm || !this.jm.view) {
            console.error('[DragDropManager] Cannot initialize: jsMind instance or view not available');
            return;
        }
        this._createDropIndicator();
        this._attachEvents();
    }

    destroy() {
        this._detachEvents();
        if (this.dropIndicator && this.dropIndicator.parentNode) {
            this.dropIndicator.parentNode.removeChild(this.dropIndicator);
        }
    }

    _createDropIndicator() {
        this.dropIndicator = document.createElement('div');
        this.dropIndicator.className = 'xmind-drop-indicator';
        this.dropIndicator.style.cssText = `
            position: absolute;
            display: none;
            pointer-events: none;
            z-index: 1000;
        `;

        // Target highlight box
        const targetBox = document.createElement('div');
        targetBox.className = 'drop-target-box';
        targetBox.style.cssText = `
            border: 3px dashed #28a745;
            border-radius: 8px;
            background: rgba(40, 167, 69, 0.1);
            padding: 10px;
            animation: pulse 1s infinite;
        `;
        this.dropIndicator.appendChild(targetBox);

        // Arrow indicator
        const arrow = document.createElement('div');
        arrow.className = 'drop-arrow';
        arrow.style.cssText = `
            position: absolute;
            width: 0;
            height: 0;
            border-left: 10px solid transparent;
            border-right: 10px solid transparent;
            border-top: 15px solid #28a745;
        `;
        this.dropIndicator.appendChild(arrow);

        // Text label
        const label = document.createElement('div');
        label.className = 'drop-label';
        label.style.cssText = `
            position: absolute;
            bottom: -25px;
            left: 50%;
            transform: translateX(-50%);
            background: #28a745;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            white-space: nowrap;
        `;
        label.textContent = _t('Drop here to attach');
        this.dropIndicator.appendChild(label);

        document.body.appendChild(this.dropIndicator);
    }

    _attachEvents() {
        const container = this.jm.view.e_panel;
        container.addEventListener('mousedown', this._boundMouseDown);
        document.addEventListener('mousemove', this._boundMouseMove);
        document.addEventListener('mouseup', this._boundMouseUp);
        document.addEventListener('keydown', this._boundKeyDown);
        document.addEventListener('keyup', this._boundKeyUp);
    }

    _detachEvents() {
        const container = this.jm.view.e_panel;
        if (container) {
            container.removeEventListener('mousedown', this._boundMouseDown);
        }
        document.removeEventListener('mousemove', this._boundMouseMove);
        document.removeEventListener('mouseup', this._boundMouseUp);
        document.removeEventListener('keydown', this._boundKeyDown);
        document.removeEventListener('keyup', this._boundKeyUp);
    }

    _onKeyDown(e) {
        if (e.key === 'Shift') {
            this.shiftPressed = true;
            if (this.isDragging) {
                // Update visual feedback when Shift is pressed during drag
                this._hideDropIndicator();
                this.editor._updateStatus(_t('Shift: Create floating topic'));
            }
        }
    }

    _onKeyUp(e) {
        if (e.key === 'Shift') {
            this.shiftPressed = false;
            if (this.isDragging) {
                this.editor._updateStatus(_t('Dragging: ') + this.draggedNode.topic);
            }
        }
    }

    _onMouseDown(e) {
        // Check if clicking on a jmnode (now using class selector)
        const nodeElement = e.target.closest('.jmnode');
        if (!nodeElement) return;

        const nodeId = nodeElement.getAttribute('nodeid');
        const node = this.jm.get_node(nodeId);

        // Don't allow dragging root node
        if (!node || node.isroot) return;

        this.startX = e.clientX;
        this.startY = e.clientY;
        this.draggedNode = node;
        this.draggedElement = nodeElement;

        // Calculate offset from node center
        const rect = nodeElement.getBoundingClientRect();
        this.offsetX = e.clientX - rect.left - rect.width / 2;
        this.offsetY = e.clientY - rect.top - rect.height / 2;

        e.preventDefault();
    }

    _onMouseMove(e) {
        if (!this.draggedNode) return;

        const dx = e.clientX - this.startX;
        const dy = e.clientY - this.startY;

        // Start dragging after threshold
        if (!this.isDragging && (Math.abs(dx) > this.dragThreshold || Math.abs(dy) > this.dragThreshold)) {
            this._startDrag(e);
        }

        if (this.isDragging) {
            this._updateDrag(e);
        }
    }

    _onMouseUp(e) {
        if (this.isDragging) {
            this._endDrag(e);
        }

        this.draggedNode = null;
        this.draggedElement = null;
        this.isDragging = false;
    }

    _startDrag(e) {
        this.isDragging = true;

        // In free positioning mode, collect all children
        if (this.freePositioningMode) {
            this._collectChildrenForDrag();
        }

        // Create ghost element
        this._createGhost();

        // Add dragging class to original
        this.draggedElement.classList.add('dragging');
        this.draggedElement.style.opacity = '0.5';

        // Update cursor
        document.body.style.cursor = 'grabbing';

        this.editor._updateStatus(_t('Dragging: ') + this.draggedNode.topic);
    }

    _collectChildrenForDrag() {
        this.draggedChildren = [];
        this.childrenOffsets = [];

        const parentRect = this.draggedElement.getBoundingClientRect();
        const containerRect = this.jm.view.e_panel.getBoundingClientRect();

        const collectDescendants = (node) => {
            if (!node.children || node.children.length === 0) return;

            for (let child of node.children) {
                const childElement = document.querySelector(`.jmnode[nodeid="${child.id}"]`);
                if (childElement) {
                    const childRect = childElement.getBoundingClientRect();

                    // Calculate relative offset to parent
                    const offsetX = (childRect.left - containerRect.left) - (parentRect.left - containerRect.left);
                    const offsetY = (childRect.top - containerRect.top) - (parentRect.top - containerRect.top);

                    this.draggedChildren.push({ node: child, element: childElement });
                    this.childrenOffsets.push({ x: offsetX, y: offsetY });

                    // Recursively collect descendants
                    collectDescendants(child);
                }
            }
        };

        collectDescendants(this.draggedNode);
    }

    _createGhost() {
        this.ghostElement = this.draggedElement.cloneNode(true);
        this.ghostElement.classList.add('drag-ghost');
        this.ghostElement.style.cssText = `
            position: fixed;
            pointer-events: none;
            z-index: 10000;
            opacity: 0.8;
            transform: scale(1.05);
            box-shadow: 0 8px 25px rgba(0,0,0,0.3);
            transition: transform 0.1s ease;
        `;
        document.body.appendChild(this.ghostElement);
    }

    _updateDrag(e) {
        // Move ghost element
        if (this.ghostElement) {
            this.ghostElement.style.left = (e.clientX - this.offsetX - this.ghostElement.offsetWidth / 2) + 'px';
            this.ghostElement.style.top = (e.clientY - this.offsetY - this.ghostElement.offsetHeight / 2) + 'px';
        }

        // Find potential attachment target (unless Shift is pressed)
        if (!this.shiftPressed) {
            this._findAttachmentTarget(e);
        } else {
            this._hideDropIndicator();
        }
    }

    _moveNodeToPosition(element, x, y) {
        element.style.left = x + 'px';
        element.style.top = y + 'px';
    }

    _checkOverlaps() {
        if (!this.draggedElement) return;

        const draggedRect = this.draggedElement.getBoundingClientRect();
        let hasOverlap = false;

        // Check all other nodes
        const allNodes = document.querySelectorAll('.jmnode');
        allNodes.forEach(node => {
            if (node === this.draggedElement) return;
            if (this.draggedChildren.some(c => c.element === node)) return;

            const nodeRect = node.getBoundingClientRect();

            // Check if rectangles overlap
            if (!(draggedRect.right < nodeRect.left ||
                  draggedRect.left > nodeRect.right ||
                  draggedRect.bottom < nodeRect.top ||
                  draggedRect.top > nodeRect.bottom)) {
                hasOverlap = true;
                node.classList.add('overlap-warning');
            } else {
                node.classList.remove('overlap-warning');
            }
        });

        // Add visual feedback to dragged node
        if (hasOverlap) {
            this.draggedElement.classList.add('overlap-warning');
        } else {
            this.draggedElement.classList.remove('overlap-warning');
        }
    }

    _findAttachmentTarget(e) {
        const containerRect = this.jm.view.e_panel.getBoundingClientRect();
        const mouseX = e.clientX - containerRect.left;
        const mouseY = e.clientY - containerRect.top;

        let closestNode = null;
        let closestDistance = this.attachmentDistance; // Smaller distance for attachment

        // Check all nodes for proximity
        const nodes = this.jm.mind.nodes;
        for (let id in nodes) {
            const node = nodes[id];

            // Skip self and descendants
            if (this._isDescendant(this.draggedNode, node)) continue;

            const element = document.querySelector(`.jmnode[nodeid="${id}"]`);
            if (!element) continue;

            const rect = element.getBoundingClientRect();
            const nodeX = rect.left - containerRect.left + rect.width / 2;
            const nodeY = rect.top - containerRect.top + rect.height / 2;

            const distance = Math.sqrt(Math.pow(mouseX - nodeX, 2) + Math.pow(mouseY - nodeY, 2));

            if (distance < closestDistance) {
                closestDistance = distance;
                closestNode = { node: node, element: element, distance: distance };
            }
        }

        // Update visual feedback
        if (closestNode) {
            this._showAttachmentIndicator(closestNode);
            this.potentialTarget = closestNode.node;
        } else {
            this._hideDropIndicator();
            this.potentialTarget = null;
        }
    }

    _isDescendant(parent, child) {
        if (parent.id === child.id) return true;

        for (let c of parent.children) {
            if (this._isDescendant(c, child)) return true;
        }

        return false;
    }

    _showAttachmentIndicator(targetInfo) {
        const element = targetInfo.element;
        const rect = element.getBoundingClientRect();

        // Position attachment indicator around target (green/blue for attachment)
        const box = this.dropIndicator.querySelector('.drop-target-box');
        box.style.width = (rect.width + 20) + 'px';
        box.style.height = (rect.height + 20) + 'px';
        box.style.borderColor = '#17a2b8'; // Blue color for attachment
        box.style.background = 'rgba(23, 162, 184, 0.1)';

        this.dropIndicator.style.left = (rect.left - 10) + 'px';
        this.dropIndicator.style.top = (rect.top - 10) + 'px';
        this.dropIndicator.style.display = 'block';

        // Position arrow
        const arrow = this.dropIndicator.querySelector('.drop-arrow');
        arrow.style.left = (rect.width / 2) + 'px';
        arrow.style.top = '-20px';
        arrow.style.borderTopColor = '#17a2b8'; // Blue arrow

        // Update label
        const label = this.dropIndicator.querySelector('.drop-label');
        label.textContent = _t('Attach to: ') + targetInfo.node.topic;
        label.style.background = '#17a2b8'; // Blue label

        // Highlight target element with blue glow
        element.classList.add('attachment-target');
    }

    _hideDropIndicator() {
        this.dropIndicator.style.display = 'none';

        // Remove highlight from all nodes
        const highlighted = document.querySelectorAll('.attachment-target');
        highlighted.forEach(el => el.classList.remove('attachment-target'));
    }

    _endDrag(e) {
        // Clean up ghost
        if (this.ghostElement && this.ghostElement.parentNode) {
            this.ghostElement.parentNode.removeChild(this.ghostElement);
            this.ghostElement = null;
        }

        // Reset original element
        if (this.draggedElement) {
            this.draggedElement.classList.remove('dragging');
            this.draggedElement.style.opacity = '';
        }

        // Reset cursor
        document.body.style.cursor = '';

        // Hide drop indicator
        this._hideDropIndicator();

        // XMind behavior: if Shift is pressed, create floating topic
        // Otherwise, try to attach to nearby node
        if (this.shiftPressed) {
            this._createFloatingTopic(e);
        } else if (this.potentialTarget && this.draggedNode) {
            // Attach to target node
            this._performAttachment(this.draggedNode, this.potentialTarget);
        } else {
            // No target nearby, create floating topic with auto-avoid
            this._createFloatingTopicWithAvoid(e);
        }

        this.potentialTarget = null;
        this.draggedChildren = [];
        this.childrenOffsets = [];
    }

    _performAttachment(sourceNode, targetNode) {
        // Attach source node as child of target node
        this._performMove(sourceNode, targetNode);
        this.editor._updateStatus(_t('Attached to: ') + targetNode.topic);
    }

    _createFloatingTopic(e) {
        const containerRect = this.jm.view.e_panel.getBoundingClientRect();
        const finalX = e.clientX - containerRect.left - this.offsetX;
        const finalY = e.clientY - containerRect.top - this.offsetY;

        this._convertToFloating(finalX, finalY);
        this.editor._updateStatus(_t('Created floating topic'));
    }

    _createFloatingTopicWithAvoid(e) {
        const containerRect = this.jm.view.e_panel.getBoundingClientRect();
        let finalX = e.clientX - containerRect.left - this.offsetX;
        let finalY = e.clientY - containerRect.top - this.offsetY;

        // Auto-avoid overlaps
        const adjustedPos = this._findNonOverlappingPosition(finalX, finalY);
        finalX = adjustedPos.x;
        finalY = adjustedPos.y;

        this._convertToFloating(finalX, finalY);
        this.editor._updateStatus(_t('Created floating topic (auto-positioned)'));
    }

    _convertToFloating(x, y) {
        // Mark node as floating and detach from parent
        this.draggedNode.isFloating = true;
        this.draggedNode.absolutePosition = { x: x, y: y };

        // Remove from parent's children
        if (this.draggedNode.parent && !this.draggedNode.isroot) {
            const parentChildren = this.draggedNode.parent.children;
            const index = parentChildren.indexOf(this.draggedNode);
            if (index > -1) {
                parentChildren.splice(index, 1);
            }
            this.draggedNode.parent = null;
        }

        // Save positions for all children with relative offsets
        for (let i = 0; i < this.draggedChildren.length; i++) {
            const childData = this.draggedChildren[i];
            const offset = this.childrenOffsets[i];
            childData.node.absolutePosition = { x: x + offset.x, y: y + offset.y };
        }

        // Redraw
        this.jm.view.refresh();
    }

    _findNonOverlappingPosition(startX, startY) {
        const nodeWidth = this.draggedElement.offsetWidth;
        const nodeHeight = this.draggedElement.offsetHeight;
        const margin = 20; // Minimum space between nodes

        let bestX = startX;
        let bestY = startY;
        let minOverlap = Infinity;

        // Try the original position first
        const overlap = this._calculateOverlapArea(startX, startY, nodeWidth, nodeHeight);
        if (overlap === 0) {
            return { x: startX, y: startY };
        }

        // Try positions in a spiral pattern around the drop point
        const maxAttempts = 8;
        const radius = 50;

        for (let i = 0; i < maxAttempts; i++) {
            const angle = (i / maxAttempts) * 2 * Math.PI;
            const testX = startX + Math.cos(angle) * radius;
            const testY = startY + Math.sin(angle) * radius;

            const testOverlap = this._calculateOverlapArea(testX, testY, nodeWidth, nodeHeight);

            if (testOverlap === 0) {
                return { x: testX, y: testY };
            }

            if (testOverlap < minOverlap) {
                minOverlap = testOverlap;
                bestX = testX;
                bestY = testY;
            }
        }

        return { x: bestX, y: bestY };
    }

    _calculateOverlapArea(x, y, width, height) {
        let totalOverlap = 0;

        const allNodes = document.querySelectorAll('.jmnode');
        allNodes.forEach(node => {
            if (node === this.draggedElement) return;
            if (this.draggedChildren.some(c => c.element === node)) return;

            const rect = node.getBoundingClientRect();
            const containerRect = this.jm.view.e_panel.getBoundingClientRect();

            const nodeX = rect.left - containerRect.left;
            const nodeY = rect.top - containerRect.top;
            const nodeW = rect.width;
            const nodeH = rect.height;

            // Calculate overlap
            const overlapX = Math.max(0, Math.min(x + width, nodeX + nodeW) - Math.max(x, nodeX));
            const overlapY = Math.max(0, Math.min(y + height, nodeY + nodeH) - Math.max(y, nodeY));

            totalOverlap += overlapX * overlapY;
        });

        return totalOverlap;
    }

    _performMove(sourceNode, targetNode) {
        // Save original parent info for undo
        const oldParent = sourceNode.parent;
        const oldParentId = oldParent.id;
        const oldIndex = oldParent.children.indexOf(sourceNode);

        // Save all node data (including children)
        const nodeData = this._saveNodeData(sourceNode);

        // Perform the move in the model
        this._moveNode(sourceNode, targetNode);

        // Refresh the view
        this.jm.view.refresh();

        // Re-render XMind features on moved nodes
        this._reapplyFeatures(sourceNode);

        // Create command for undo/redo
        const command = {
            label: 'Move Node',
            execute: () => {
                this._moveNode(sourceNode, targetNode);
                this.jm.view.refresh();
            },
            undo: () => {
                this._moveNode(sourceNode, oldParent);
                this.jm.view.refresh();
            },
            redo: function () { this.execute(); },
            getLabel: function () { return this.label; },
            canUndo: true
        };

        // Add to command stack
        this.editor.commandStack.undoStack.push(command);
        this.editor.commandStack.redoStack = [];
        this.editor.commandStack.isDirty = true;
        this.editor.commandStack._notifyListeners();

        this.editor._updateStatus(_t('Moved "') + sourceNode.topic + _t('" to "') + targetNode.topic + '"');
    }

    _moveNode(node, newParent) {
        // Remove from old parent
        const oldParent = node.parent;
        const oldIndex = oldParent.children.indexOf(node);
        if (oldIndex > -1) {
            oldParent.children.splice(oldIndex, 1);
        }

        // Update node's parent reference
        node.parent = newParent;

        // Update direction based on layout mode
        const layoutMode = this.jm.layout.mode || 'map';

        if (newParent.isroot) {
            if (layoutMode === 'map') {
                // Mind Map: alternate left/right
                node.direction = (newParent.children.length % 2 === 0) ? -1 : 1;
            } else if (layoutMode === 'tree_right' || layoutMode === 'logic_right') {
                // Tree/Logic Right: all to the right
                node.direction = 1;
            } else if (layoutMode === 'tree_left') {
                // Tree Left: all to the left
                node.direction = -1;
            } else if (layoutMode === 'org_chart_down') {
                // Org Chart: all downward
                node.direction = 2;
            }
        } else {
            // Non-root: inherit parent's direction
            node.direction = newParent.direction;
        }

        // Add to new parent
        newParent.children.push(node);

        // Recursively update children's direction
        this._updateChildrenDirection(node);
    }

    _updateChildrenDirection(node) {
        for (let child of node.children) {
            child.direction = node.direction;
            this._updateChildrenDirection(child);
        }
    }

    _saveNodeData(node) {
        return {
            id: node.id,
            topic: node.topic,
            data: JSON.parse(JSON.stringify(node.data || {})),
            expanded: node.expanded,
            children: node.children.map(c => this._saveNodeData(c))
        };
    }

    _reapplyFeatures(node) {
        // Re-render visual features after move
        const element = this.jm.view.get_node_element(node.id);
        if (element && node.data) {
            if (node.data.markers && node.data.markers.length > 0) {
                this.editor.markerBadgeRenderer.renderMarkers(element, node.data.markers, this.editor.markers);
            }
            if (node.data.labels && node.data.labels.length > 0) {
                this.editor.labelRenderer.renderLabels(element, node.data.labels);
            }
            if (node.data.note) {
                this.editor.noteIndicator.addIndicator(element, true);
            }
            if (node.data.hyperlink) {
                this.editor.hyperlinkIndicator.addIndicator(element, node.data.hyperlink, node.data.hyperlinkTitle);
            }
            if (node.data.attachments && node.data.attachments.length > 0) {
                this.editor.attachmentIndicator.addIndicator(element, node.data.attachments.length);
            }
            if (node.data.image) {
                this.editor.imageRenderer.renderImage(element, node.data.image.data, node.data.image.options);
            }
        }

        // Recursively for children
        for (let child of node.children) {
            this._reapplyFeatures(child);
        }
    }

    _handleEmptySpaceDrop(e) {
        // Option: Convert to floating topic or attach to root
        const containerRect = this.jm.view.e_panel.getBoundingClientRect();
        const x = e.clientX - containerRect.left;
        const y = e.clientY - containerRect.top;

        // Check if far from root - could become floating
        const root = this.jm.mind.root;
        const rootElement = this.jm.view.get_node_element(root.id);
        const rootRect = rootElement.getBoundingClientRect();
        const rootX = rootRect.left - containerRect.left + rootRect.width / 2;
        const rootY = rootRect.top - containerRect.top + rootRect.height / 2;

        const distFromRoot = Math.sqrt(Math.pow(x - rootX, 2) + Math.pow(y - rootY, 2));

        if (distFromRoot > 300) {
            // Far from root - offer to convert to floating topic
            this.editor._showFloatingTopicOption(this.draggedNode, x, y);
        } else {
            // Near root - attach to root
            this._performMove(this.draggedNode, root);
        }
    }
}

