/**
 * Advanced Relationship Manager
 * Supports: Shape types, markers, text labels, draggable control points
 */
odoo.define('dobtor_xmind.RelationshipManager', function (require) {
    "use strict";

    const core = require('web.core');
    const _t = core._t;

    class RelationshipManager {
        constructor(container) {
            this.container = container;
            this.svg = null;
            this.relationships = [];
            this.selectedRelationship = null;
            this.controlPointsVisible = false;
            this.isDraggingControlPoint = false;
            this.activeControlPoint = null;

            this._createSVG();
            this._attachEvents();
        }

        _createSVG() {
            this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            this.svg.style.cssText = `
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
                z-index: 15;
            `;
            this.container.appendChild(this.svg);

            // Create marker definitions
            this._createMarkerDefinitions();
        }

        _createMarkerDefinitions() {
            const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');

            // Arrow markers (different sizes)
            ['small', 'medium', 'large'].forEach(size => {
                const sizeMap = { small: 8, medium: 10, large: 14 };
                const s = sizeMap[size];

                // Filled arrow
                const arrow = this._createMarker(`arrow-${size}`, s, s * 0.7, s, s * 0.35);
                const arrowPoly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                arrowPoly.setAttribute('points', `0 0, ${s} ${s * 0.35}, 0 ${s * 0.7}`);
                arrowPoly.setAttribute('class', 'marker-fill');
                arrow.appendChild(arrowPoly);
                defs.appendChild(arrow);

                // Open arrow
                const arrowOpen = this._createMarker(`arrow-open-${size}`, s, s * 0.7, s, s * 0.35);
                const arrowOpenPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                arrowOpenPath.setAttribute('d', `M 0 0 L ${s} ${s * 0.35} L 0 ${s * 0.7}`);
                arrowOpenPath.setAttribute('fill', 'none');
                arrowOpenPath.setAttribute('stroke-width', '1.5');
                arrowOpenPath.setAttribute('class', 'marker-stroke');
                arrowOpen.appendChild(arrowOpenPath);
                defs.appendChild(arrowOpen);

                // Diamond
                const diamond = this._createMarker(`diamond-${size}`, s, s, s / 2, s / 2);
                const diamondPoly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                diamondPoly.setAttribute('points', `${s / 2} 0, ${s} ${s / 2}, ${s / 2} ${s}, 0 ${s / 2}`);
                diamondPoly.setAttribute('fill', 'none');
                diamondPoly.setAttribute('stroke-width', '1.5');
                diamondPoly.setAttribute('class', 'marker-stroke');
                diamond.appendChild(diamondPoly);
                defs.appendChild(diamond);

                // Diamond filled
                const diamondFilled = this._createMarker(`diamond-filled-${size}`, s, s, s / 2, s / 2);
                const diamondFilledPoly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                diamondFilledPoly.setAttribute('points', `${s / 2} 0, ${s} ${s / 2}, ${s / 2} ${s}, 0 ${s / 2}`);
                diamondFilledPoly.setAttribute('class', 'marker-fill');
                diamondFilled.appendChild(diamondFilledPoly);
                defs.appendChild(diamondFilled);

                // Circle
                const circle = this._createMarker(`circle-${size}`, s, s, s / 2, s / 2);
                const circleElem = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                circleElem.setAttribute('cx', s / 2);
                circleElem.setAttribute('cy', s / 2);
                circleElem.setAttribute('r', s / 2 - 1);
                circleElem.setAttribute('fill', 'none');
                circleElem.setAttribute('stroke-width', '1.5');
                circleElem.setAttribute('class', 'marker-stroke');
                circle.appendChild(circleElem);
                defs.appendChild(circle);

                // Circle filled
                const circleFilled = this._createMarker(`circle-filled-${size}`, s, s, s / 2, s / 2);
                const circleFilledElem = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                circleFilledElem.setAttribute('cx', s / 2);
                circleFilledElem.setAttribute('cy', s / 2);
                circleFilledElem.setAttribute('r', s / 2 - 1);
                circleFilledElem.setAttribute('class', 'marker-fill');
                circleFilled.appendChild(circleFilledElem);
                defs.appendChild(circleFilled);

                // Square
                const square = this._createMarker(`square-${size}`, s, s, s / 2, s / 2);
                const squareRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                squareRect.setAttribute('x', 1);
                squareRect.setAttribute('y', 1);
                squareRect.setAttribute('width', s - 2);
                squareRect.setAttribute('height', s - 2);
                squareRect.setAttribute('fill', 'none');
                squareRect.setAttribute('stroke-width', '1.5');
                squareRect.setAttribute('class', 'marker-stroke');
                square.appendChild(squareRect);
                defs.appendChild(square);
            });

            this.svg.appendChild(defs);
        }

        _createMarker(id, width, height, refX, refY) {
            const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
            marker.setAttribute('id', id);
            marker.setAttribute('markerWidth', width);
            marker.setAttribute('markerHeight', height);
            marker.setAttribute('refX', refX);
            marker.setAttribute('refY', refY);
            marker.setAttribute('orient', 'auto');
            marker.setAttribute('markerUnits', 'strokeWidth');
            return marker;
        }

        _attachEvents() {
            this.container.addEventListener('click', (e) => {
                if (e.target.closest('.relationship-path')) {
                    const relId = e.target.closest('g').getAttribute('data-rel-id');
                    this.selectRelationship(relId);
                }
            });

            document.addEventListener('mousemove', this._onMouseMove.bind(this));
            document.addEventListener('mouseup', this._onMouseUp.bind(this));
        }

        _onMouseMove(e) {
            if (!this.isDraggingControlPoint || !this.activeControlPoint) return;

            const containerRect = this.container.getBoundingClientRect();
            const x = e.clientX - containerRect.left;
            const y = e.clientY - containerRect.top;

            this.activeControlPoint.x = x;
            this.activeControlPoint.y = y;

            // Update control point visual
            const circle = this.activeControlPoint.element;
            circle.setAttribute('cx', x);
            circle.setAttribute('cy', y);

            // Update relationship path
            this._updateRelationshipPath(this.activeControlPoint.relationship);
        }

        _onMouseUp(e) {
            this.isDraggingControlPoint = false;
            this.activeControlPoint = null;
        }

        clear() {
            while (this.svg.childNodes.length > 1) {
                this.svg.removeChild(this.svg.lastChild);
            }
            this.relationships = [];
            this.selectedRelationship = null;
        }

        addRelationship(sourceElement, targetElement, options = {}) {
            if (!sourceElement || !targetElement) return null;

            const containerRect = this.container.getBoundingClientRect();
            const sourceRect = sourceElement.getBoundingClientRect();
            const targetRect = targetElement.getBoundingClientRect();

            const sx = sourceRect.left - containerRect.left + sourceRect.width / 2;
            const sy = sourceRect.top - containerRect.top + sourceRect.height / 2;
            const tx = targetRect.left - containerRect.left + targetRect.width / 2;
            const ty = targetRect.top - containerRect.top + targetRect.height / 2;

            const relId = 'rel_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);

            // Default control points for curve (middle of line)
            const midX = (sx + tx) / 2;
            const midY = (sy + ty) / 2;
            const distance = Math.sqrt(Math.pow(tx - sx, 2) + Math.pow(ty - sy, 2));

            const relData = {
                id: relId,
                sourceElement: sourceElement,
                targetElement: targetElement,
                sx: sx,
                sy: sy,
                tx: tx,
                ty: ty,
                controlPoints: [
                    { x: midX, y: midY - distance * 0.3 } // Default curve offset
                ],
                options: Object.assign({
                    shapeType: 'curved',
                    lineStyle: 'dashed',
                    lineWidth: 2,
                    lineColor: '#999999',
                    startMarker: 'none',
                    endMarker: 'arrow',
                    markerSize: 'medium',
                    label: '',
                    labelFontSize: 12,
                    labelColor: '#666666',
                    labelBold: false,
                    labelItalic: false,
                    labelBackground: false
                }, options),
                group: null,
                pathElement: null,
                labelElement: null,
                controlPointElements: []
            };

            this.relationships.push(relData);
            this._renderRelationship(relData);

            return relId;
        }

        _renderRelationship(relData) {
            const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            group.setAttribute('data-rel-id', relData.id);
            group.style.pointerEvents = 'auto';

            // Create path
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('class', 'relationship-path');
            path.style.cursor = 'pointer';

            // Apply styles
            this._applyPathStyles(path, relData);

            // Calculate path
            const d = this._calculatePath(relData);
            path.setAttribute('d', d);

            group.appendChild(path);
            relData.pathElement = path;

            // Add label if provided
            if (relData.options.label) {
                const labelGroup = this._createLabel(relData);
                group.appendChild(labelGroup);
                relData.labelElement = labelGroup;
            }

            this.svg.appendChild(group);
            relData.group = group;
        }

        _applyPathStyles(path, relData) {
            const opts = relData.options;

            path.setAttribute('stroke', opts.lineColor);
            path.setAttribute('stroke-width', opts.lineWidth);
            path.setAttribute('fill', 'none');

            // Apply line style
            switch (opts.lineStyle) {
                case 'solid':
                    path.removeAttribute('stroke-dasharray');
                    break;
                case 'dashed':
                    path.setAttribute('stroke-dasharray', '8, 4');
                    break;
                case 'dotted':
                    path.setAttribute('stroke-dasharray', '2, 2');
                    break;
                case 'dash-dot':
                    path.setAttribute('stroke-dasharray', '8, 4, 2, 4');
                    break;
            }

            // Apply markers
            if (opts.startMarker !== 'none') {
                path.setAttribute('marker-start', `url(#${opts.startMarker}-${opts.markerSize})`);
            } else {
                path.removeAttribute('marker-start');
            }

            if (opts.endMarker !== 'none') {
                path.setAttribute('marker-end', `url(#${opts.endMarker}-${opts.markerSize})`);
            } else {
                path.removeAttribute('marker-end');
            }

            // Set marker colors
            const markers = this.svg.querySelectorAll('.marker-fill, .marker-stroke');
            markers.forEach(m => {
                if (m.classList.contains('marker-fill')) {
                    m.setAttribute('fill', opts.lineColor);
                }
                if (m.classList.contains('marker-stroke')) {
                    m.setAttribute('stroke', opts.lineColor);
                }
            });
        }

        _calculatePath(relData) {
            const { sx, sy, tx, ty, controlPoints, options } = relData;

            switch (options.shapeType) {
                case 'straight':
                    return `M ${sx} ${sy} L ${tx} ${ty}`;

                case 'angled': {
                    const midX = (sx + tx) / 2;
                    return `M ${sx} ${sy} L ${midX} ${sy} L ${midX} ${ty} L ${tx} ${ty}`;
                }

                case 'zigzag': {
                    const dx = tx - sx;
                    const dy = ty - sy;
                    const steps = 4;
                    let d = `M ${sx} ${sy}`;
                    for (let i = 1; i <= steps; i++) {
                        const x = sx + (dx * i / steps);
                        const y = sy + (dy * i / steps);
                        const offset = (i % 2 === 1) ? 20 : -20;
                        d += ` L ${x + offset} ${y}`;
                    }
                    d += ` L ${tx} ${ty}`;
                    return d;
                }

                case 'arc': {
                    const dx = tx - sx;
                    const dy = ty - sy;
                    const r = Math.sqrt(dx * dx + dy * dy) * 0.6;
                    return `M ${sx} ${sy} A ${r} ${r} 0 0 1 ${tx} ${ty}`;
                }

                case 'curved':
                default: {
                    if (controlPoints.length === 1) {
                        const cp = controlPoints[0];
                        return `M ${sx} ${sy} Q ${cp.x} ${cp.y} ${tx} ${ty}`;
                    } else if (controlPoints.length === 2) {
                        const cp1 = controlPoints[0];
                        const cp2 = controlPoints[1];
                        return `M ${sx} ${sy} C ${cp1.x} ${cp1.y} ${cp2.x} ${cp2.y} ${tx} ${ty}`;
                    }
                    return `M ${sx} ${sy} L ${tx} ${ty}`;
                }
            }
        }

        _createLabel(relData) {
            const opts = relData.options;
            const cp = relData.controlPoints[0] || {
                x: (relData.sx + relData.tx) / 2,
                y: (relData.sy + relData.ty) / 2
            };

            const labelGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');

            // Background rect if needed
            if (opts.labelBackground) {
                const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                bgRect.setAttribute('fill', '#ffffff');
                bgRect.setAttribute('stroke', opts.lineColor);
                bgRect.setAttribute('stroke-width', '1');
                bgRect.setAttribute('rx', '3');
                bgRect.setAttribute('class', 'label-background');
                labelGroup.appendChild(bgRect);
            }

            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', cp.x);
            text.setAttribute('y', cp.y - 10);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('dominant-baseline', 'middle');
            text.setAttribute('fill', opts.labelColor);
            text.setAttribute('font-size', opts.labelFontSize);

            if (opts.labelBold) {
                text.setAttribute('font-weight', 'bold');
            }
            if (opts.labelItalic) {
                text.setAttribute('font-style', 'italic');
            }

            text.textContent = opts.label;
            labelGroup.appendChild(text);

            // Update background size after text is rendered
            if (opts.labelBackground) {
                setTimeout(() => {
                    const bbox = text.getBBox();
                    const bgRect = labelGroup.querySelector('.label-background');
                    if (bgRect) {
                        bgRect.setAttribute('x', bbox.x - 4);
                        bgRect.setAttribute('y', bbox.y - 2);
                        bgRect.setAttribute('width', bbox.width + 8);
                        bgRect.setAttribute('height', bbox.height + 4);
                    }
                }, 10);
            }

            return labelGroup;
        }

        selectRelationship(relId) {
            // Deselect previous
            if (this.selectedRelationship) {
                this._hideControlPoints(this.selectedRelationship);
            }

            const relData = this.relationships.find(r => r.id === relId);
            if (!relData) return;

            this.selectedRelationship = relData;
            this._showControlPoints(relData);
        }

        _showControlPoints(relData) {
            const controlsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            controlsGroup.setAttribute('class', 'control-points');
            controlsGroup.style.pointerEvents = 'auto';

            // Source point (not draggable)
            this._createControlPoint(controlsGroup, relData.sx, relData.sy, '#007bff', false);

            // Curve control points (draggable)
            relData.controlPoints.forEach((cp, index) => {
                const circle = this._createControlPoint(controlsGroup, cp.x, cp.y, '#28a745', true);
                circle.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.isDraggingControlPoint = true;
                    this.activeControlPoint = {
                        relationship: relData,
                        pointIndex: index,
                        x: cp.x,
                        y: cp.y,
                        element: circle
                    };
                    relData.controlPoints[index] = this.activeControlPoint;
                });
                relData.controlPointElements.push(circle);
            });

            // Target point (not draggable)
            this._createControlPoint(controlsGroup, relData.tx, relData.ty, '#dc3545', false);

            // Draw control lines
            const controlLine1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            controlLine1.setAttribute('x1', relData.sx);
            controlLine1.setAttribute('y1', relData.sy);
            controlLine1.setAttribute('x2', relData.controlPoints[0].x);
            controlLine1.setAttribute('y2', relData.controlPoints[0].y);
            controlLine1.setAttribute('stroke', '#28a745');
            controlLine1.setAttribute('stroke-width', '1');
            controlLine1.setAttribute('stroke-dasharray', '4,2');
            controlLine1.setAttribute('class', 'control-line');
            controlsGroup.insertBefore(controlLine1, controlsGroup.firstChild);

            const controlLine2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            controlLine2.setAttribute('x1', relData.controlPoints[0].x);
            controlLine2.setAttribute('y1', relData.controlPoints[0].y);
            controlLine2.setAttribute('x2', relData.tx);
            controlLine2.setAttribute('y2', relData.ty);
            controlLine2.setAttribute('stroke', '#28a745');
            controlLine2.setAttribute('stroke-width', '1');
            controlLine2.setAttribute('stroke-dasharray', '4,2');
            controlLine2.setAttribute('class', 'control-line');
            controlsGroup.insertBefore(controlLine2, controlsGroup.firstChild);

            relData.group.appendChild(controlsGroup);
            relData.controlsGroup = controlsGroup;
        }

        _createControlPoint(parent, x, y, color, draggable) {
            const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            circle.setAttribute('cx', x);
            circle.setAttribute('cy', y);
            circle.setAttribute('r', draggable ? 8 : 6);
            circle.setAttribute('fill', color);
            circle.setAttribute('stroke', '#ffffff');
            circle.setAttribute('stroke-width', '2');
            circle.style.cursor = draggable ? 'grab' : 'default';

            if (draggable) {
                circle.classList.add('draggable-control');
            }

            parent.appendChild(circle);
            return circle;
        }

        _hideControlPoints(relData) {
            if (relData.controlsGroup) {
                relData.controlsGroup.remove();
                relData.controlsGroup = null;
            }
            relData.controlPointElements = [];
        }

        _updateRelationshipPath(relData) {
            if (!relData.pathElement) return;

            const d = this._calculatePath(relData);
            relData.pathElement.setAttribute('d', d);

            // Update control lines
            if (relData.controlsGroup) {
                const lines = relData.controlsGroup.querySelectorAll('.control-line');
                if (lines.length >= 2) {
                    lines[0].setAttribute('x2', relData.controlPoints[0].x);
                    lines[0].setAttribute('y2', relData.controlPoints[0].y);
                    lines[1].setAttribute('x1', relData.controlPoints[0].x);
                    lines[1].setAttribute('y1', relData.controlPoints[0].y);
                }
            }

            // Update label position
            if (relData.labelElement) {
                const cp = relData.controlPoints[0];
                const text = relData.labelElement.querySelector('text');
                if (text) {
                    text.setAttribute('x', cp.x);
                    text.setAttribute('y', cp.y - 10);
                }

                const bgRect = relData.labelElement.querySelector('.label-background');
                if (bgRect && text) {
                    const bbox = text.getBBox();
                    bgRect.setAttribute('x', bbox.x - 4);
                    bgRect.setAttribute('y', bbox.y - 2);
                }
            }
        }

        updateRelationshipOptions(relId, newOptions) {
            const relData = this.relationships.find(r => r.id === relId);
            if (!relData) return;

            Object.assign(relData.options, newOptions);

            // Re-apply styles
            this._applyPathStyles(relData.pathElement, relData);

            // Update label if changed
            if (relData.labelElement) {
                relData.labelElement.remove();
            }
            if (relData.options.label) {
                const labelGroup = this._createLabel(relData);
                relData.group.appendChild(labelGroup);
                relData.labelElement = labelGroup;
            }
        }

        refreshPositions() {
            const containerRect = this.container.getBoundingClientRect();

            this.relationships.forEach(relData => {
                if (!relData.sourceElement || !relData.targetElement) return;

                const sourceRect = relData.sourceElement.getBoundingClientRect();
                const targetRect = relData.targetElement.getBoundingClientRect();

                // Calculate delta
                const newSx = sourceRect.left - containerRect.left + sourceRect.width / 2;
                const newSy = sourceRect.top - containerRect.top + sourceRect.height / 2;
                const newTx = targetRect.left - containerRect.left + targetRect.width / 2;
                const newTy = targetRect.top - containerRect.top + targetRect.height / 2;

                const dsx = newSx - relData.sx;
                const dsy = newSy - relData.sy;
                const dtx = newTx - relData.tx;
                const dty = newTy - relData.ty;

                // Update control points proportionally
                relData.controlPoints.forEach(cp => {
                    cp.x += (dsx + dtx) / 2;
                    cp.y += (dsy + dty) / 2;
                });

                relData.sx = newSx;
                relData.sy = newSy;
                relData.tx = newTx;
                relData.ty = newTy;

                this._updateRelationshipPath(relData);
            });
        }

        removeRelationship(relId) {
            const index = this.relationships.findIndex(r => r.id === relId);
            if (index === -1) return;

            const relData = this.relationships[index];
            if (relData.group) {
                relData.group.remove();
            }

            this.relationships.splice(index, 1);

            if (this.selectedRelationship && this.selectedRelationship.id === relId) {
                this.selectedRelationship = null;
            }
        }

        getRelationshipData() {
            return this.relationships.map(rel => ({
                id: rel.id,
                sourceId: rel.sourceElement.getAttribute('nodeid'),
                targetId: rel.targetElement.getAttribute('nodeid'),
                controlPoints: rel.controlPoints.map(cp => ({ x: cp.x, y: cp.y })),
                options: { ...rel.options }
            }));
        }
    }

    return RelationshipManager;
});
