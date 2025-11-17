/**
 * Drag and Drop Manager for XMind 2 Style Topic Reorganization
 * Supports: Detach, Reparent, Visual Feedback
 */
odoo.define('dobtor_xmind.DragDropManager', function (require) {
    "use strict";

    const core = require('web.core');
    const _t = core._t;

    class DragDropManager {
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

            this._boundMouseDown = this._onMouseDown.bind(this);
            this._boundMouseMove = this._onMouseMove.bind(this);
            this._boundMouseUp = this._onMouseUp.bind(this);
        }

        init() {
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
        }

        _detachEvents() {
            const container = this.jm.view.e_panel;
            if (container) {
                container.removeEventListener('mousedown', this._boundMouseDown);
            }
            document.removeEventListener('mousemove', this._boundMouseMove);
            document.removeEventListener('mouseup', this._boundMouseUp);
        }

        _onMouseDown(e) {
            // Check if clicking on a jmnode
            const nodeElement = e.target.closest('jmnode');
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

            // Create ghost element
            this._createGhost();

            // Add dragging class to original
            this.draggedElement.classList.add('dragging');
            this.draggedElement.style.opacity = '0.5';

            // Update cursor
            document.body.style.cursor = 'grabbing';

            this.editor._updateStatus(_t('Dragging: ') + this.draggedNode.topic);
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

            // Find potential drop target
            this._findDropTarget(e);
        }

        _findDropTarget(e) {
            const containerRect = this.jm.view.e_panel.getBoundingClientRect();
            const mouseX = e.clientX - containerRect.left;
            const mouseY = e.clientY - containerRect.top;

            let closestNode = null;
            let closestDistance = this.dropProximity;

            // Check all nodes for proximity
            const nodes = this.jm.mind.nodes;
            for (let id in nodes) {
                const node = nodes[id];

                // Skip self and descendants
                if (this._isDescendant(this.draggedNode, node)) continue;

                const element = this.jm.view.get_node_element(id);
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
                this._showDropIndicator(closestNode);
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

        _showDropIndicator(targetInfo) {
            const element = targetInfo.element;
            const rect = element.getBoundingClientRect();

            // Position drop indicator around target
            const box = this.dropIndicator.querySelector('.drop-target-box');
            box.style.width = (rect.width + 20) + 'px';
            box.style.height = (rect.height + 20) + 'px';

            this.dropIndicator.style.left = (rect.left - 10) + 'px';
            this.dropIndicator.style.top = (rect.top - 10) + 'px';
            this.dropIndicator.style.display = 'block';

            // Position arrow
            const arrow = this.dropIndicator.querySelector('.drop-arrow');
            arrow.style.left = (rect.width / 2) + 'px';
            arrow.style.top = '-20px';

            // Update label
            const label = this.dropIndicator.querySelector('.drop-label');
            label.textContent = _t('Attach to: ') + targetInfo.node.topic;

            // Highlight target element
            element.classList.add('drop-target');
        }

        _hideDropIndicator() {
            this.dropIndicator.style.display = 'none';

            // Remove highlight from all nodes
            const highlighted = document.querySelectorAll('.drop-target');
            highlighted.forEach(el => el.classList.remove('drop-target'));
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

            // Perform the move operation
            if (this.potentialTarget && this.draggedNode) {
                this._performMove(this.draggedNode, this.potentialTarget);
            } else if (this.draggedNode) {
                // Dropped in empty space - could convert to floating topic
                this._handleEmptySpaceDrop(e);
            }

            this.potentialTarget = null;
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

            // Update direction for proper layout
            if (newParent.isroot) {
                node.direction = (newParent.children.length % 2 === 0) ? -1 : 1;
            } else {
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

    return DragDropManager;
});
