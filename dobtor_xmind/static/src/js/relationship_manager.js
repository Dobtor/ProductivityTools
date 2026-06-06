/** @odoo-module **/

/**
 * Advanced Relationship Manager
 * XMind 2 dual control point system:
 * - Cubic bezier: M source C cp0 cp1 target
 * - CP0 controls curvature near source, CP1 near target
 * - Dragging CP moves endpoint along topic border based on CP direction
 * - 4 handles when selected: source endpoint, CP0, CP1, target endpoint
 */
import { _t } from "@web/core/l10n/translation";

export class RelationshipManager {
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
            overflow: visible;
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
        const zoom = this.container.style.transform ? parseFloat(this.container.style.transform.match(/scale\(([^)]+)\)/)?.[1] || 1) : 1;
        const x = (e.clientX - containerRect.left) / zoom;
        const y = (e.clientY - containerRect.top) / zoom;

        this.activeControlPoint.x = x;
        this.activeControlPoint.y = y;

        const circle = this.activeControlPoint.element;
        circle.setAttribute('cx', x);
        circle.setAttribute('cy', y);

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

    /**
     * Calculate where a line from center toward target intersects the node's border.
     * Used to position endpoints on the topic's edge.
     */
    _getEdgePoint(element, targetX, targetY) {
        const cx = element.offsetLeft + element.offsetWidth / 2;
        const cy = element.offsetTop + element.offsetHeight / 2;
        const hw = element.offsetWidth / 2;
        const hh = element.offsetHeight / 2;
        const dx = targetX - cx;
        const dy = targetY - cy;

        if (dx === 0 && dy === 0) return { x: cx, y: cy };

        const absDx = Math.abs(dx);
        const absDy = Math.abs(dy);

        const scaleX = hw / (absDx || 1);
        const scaleY = hh / (absDy || 1);
        const scale = Math.min(scaleX, scaleY);

        return {
            x: cx + dx * scale,
            y: cy + dy * scale,
        };
    }

    /**
     * Generate default control points for a new relationship.
     * CP0 near source, CP1 near target, offset perpendicular to the line.
     */
    _defaultControlPoints(sx, sy, tx, ty) {
        const midX = (sx + tx) / 2;
        const midY = (sy + ty) / 2;
        const dx = tx - sx;
        const dy = ty - sy;
        const dist = Math.sqrt(dx * dx + dy * dy);

        // Perpendicular offset (30% of distance)
        const offset = dist * 0.3;
        // Normal vector (perpendicular to line direction)
        const nx = -dy / (dist || 1);
        const ny = dx / (dist || 1);

        // CP0 at 1/3 along the line, offset perpendicular
        // CP1 at 2/3 along the line, offset perpendicular
        return [
            { x: sx + dx * 0.33 + nx * offset, y: sy + dy * 0.33 + ny * offset },
            { x: sx + dx * 0.67 + nx * offset, y: sy + dy * 0.67 + ny * offset },
        ];
    }

    addRelationship(sourceElement, targetElement, options = {}) {
        if (!sourceElement || !targetElement) return null;

        // Calculate center points first
        const scx = sourceElement.offsetLeft + sourceElement.offsetWidth / 2;
        const scy = sourceElement.offsetTop + sourceElement.offsetHeight / 2;
        const tcx = targetElement.offsetLeft + targetElement.offsetWidth / 2;
        const tcy = targetElement.offsetTop + targetElement.offsetHeight / 2;

        // Get edge intersection points (toward other node's center)
        const srcEdge = this._getEdgePoint(sourceElement, tcx, tcy);
        const tgtEdge = this._getEdgePoint(targetElement, scx, scy);
        const sx = srcEdge.x;
        const sy = srcEdge.y;
        const tx = tgtEdge.x;
        const ty = tgtEdge.y;

        const relId = 'rel_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);

        // Use saved control points if provided (must have 2), otherwise generate defaults
        const savedCp = options.controlPoints;
        const hasValidCp = savedCp && savedCp.length >= 2 &&
            (savedCp[0].x || savedCp[0].y) && (savedCp[1].x || savedCp[1].y);
        const controlPoints = hasValidCp
            ? [{ x: savedCp[0].x, y: savedCp[0].y }, { x: savedCp[1].x, y: savedCp[1].y }]
            : this._defaultControlPoints(sx, sy, tx, ty);

        const relData = {
            id: relId,
            sourceElement: sourceElement,
            targetElement: targetElement,
            sx: sx,
            sy: sy,
            tx: tx,
            ty: ty,
            controlPoints: controlPoints,
            options: Object.assign({
                shapeType: 'curved',
                lineStyle: 'dashed',
                lineWidth: 3,
                lineColor: '#77933C',
                startMarker: 'none',
                endMarker: 'arrow',
                markerSize: 'medium',
                label: '',
                labelFontSize: 10,
                labelColor: '#595959',
                labelBold: false,
                labelItalic: true,
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

        // Calculate path
        const d = this._calculatePath(relData);

        // Invisible wide hit area (20px wide transparent stroke)
        const hitArea = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        hitArea.setAttribute('d', d);
        hitArea.setAttribute('stroke', 'transparent');
        hitArea.setAttribute('stroke-width', '20');
        hitArea.setAttribute('fill', 'none');
        hitArea.setAttribute('class', 'relationship-path');
        hitArea.style.cursor = 'pointer';
        group.appendChild(hitArea);

        // Visible path
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('class', 'relationship-path relationship-path-visible');
        path.setAttribute('d', d);
        path.style.cursor = 'pointer';
        path.style.pointerEvents = 'none';

        this._applyPathStyles(path, relData);

        group.appendChild(path);
        relData.pathElement = path;
        relData.hitAreaElement = hitArea;

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

        // Apply markers. Each relationship gets its OWN colour-keyed marker
        // clone so that recolouring one line never bleeds into the shared
        // marker definitions used by every other line.
        if (opts.startMarker !== 'none') {
            const startId = this._getColoredMarkerId(opts.startMarker, opts.markerSize, opts.lineColor, true);
            path.setAttribute('marker-start', `url(#${startId})`);
        } else {
            path.removeAttribute('marker-start');
        }

        if (opts.endMarker !== 'none') {
            const endId = this._getColoredMarkerId(opts.endMarker, opts.markerSize, opts.lineColor, false);
            path.setAttribute('marker-end', `url(#${endId})`);
        } else {
            path.removeAttribute('marker-end');
        }
    }

    /**
     * Return the id of a marker tinted with ``color`` (creating it on first
     * use). Markers are keyed by type+size+color (+reverse) so each colour has
     * its own def and lines never share/overwrite marker colours.
     */
    _getColoredMarkerId(baseType, size, color, reverse) {
        const colorKey = String(color || '').replace(/[^a-zA-Z0-9]/g, '') || 'def';
        const id = `${baseType}-${size}-${colorKey}${reverse ? '-rev' : ''}`;
        if (!this.svg.querySelector(`#${CSS.escape(id)}`)) {
            const orig = this.svg.querySelector(`#${baseType}-${size}`);
            const defs = this.svg.querySelector('defs');
            if (orig && defs) {
                const clone = orig.cloneNode(true);
                clone.setAttribute('id', id);
                if (reverse) clone.setAttribute('orient', 'auto-start-reverse');
                clone.querySelectorAll('.marker-fill').forEach(m => m.setAttribute('fill', color));
                clone.querySelectorAll('.marker-stroke').forEach(m => m.setAttribute('stroke', color));
                defs.appendChild(clone);
            }
        }
        return id;
    }

    /**
     * Calculate SVG path. Always uses cubic bezier (C) with 2 control points.
     * For endpoints, recalculate edge points based on CP direction.
     */
    _calculatePath(relData) {
        const { controlPoints, options } = relData;
        const cp0 = controlPoints[0];
        const cp1 = controlPoints[1] || cp0;

        // Recalculate endpoint edge positions based on control point direction
        // Source endpoint: edge point toward CP0
        // Target endpoint: edge point toward CP1
        if (relData.sourceElement && relData.targetElement) {
            const srcEdge = this._getEdgePoint(relData.sourceElement, cp0.x, cp0.y);
            const tgtEdge = this._getEdgePoint(relData.targetElement, cp1.x, cp1.y);
            relData.sx = srcEdge.x;
            relData.sy = srcEdge.y;
            relData.tx = tgtEdge.x;
            relData.ty = tgtEdge.y;
        }

        const { sx, sy, tx, ty } = relData;

        switch (options.shapeType) {
            case 'straight':
                return `M ${sx} ${sy} L ${tx} ${ty}`;

            case 'angled': {
                const midX = (sx + tx) / 2;
                return `M ${sx} ${sy} L ${midX} ${sy} L ${midX} ${ty} L ${tx} ${ty}`;
            }

            case 'roundedElbow': {
                const midX2 = (sx + tx) / 2;
                const r = Math.min(Math.abs(ty - sy) / 2, Math.abs(midX2 - sx) / 2, 12);
                const dy = ty > sy ? 1 : -1;
                return `M ${sx} ${sy} L ${midX2 - r} ${sy} Q ${midX2} ${sy} ${midX2} ${sy + r * dy} L ${midX2} ${ty - r * dy} Q ${midX2} ${ty} ${midX2 + r} ${ty} L ${tx} ${ty}`;
            }

            case 'curved':
            default:
                // Cubic bezier with 2 control points
                return `M ${sx} ${sy} C ${cp0.x} ${cp0.y}, ${cp1.x} ${cp1.y}, ${tx} ${ty}`;
        }
    }

    /**
     * Calculate midpoint on cubic bezier at t=0.5.
     * B(0.5) = 0.125*P0 + 0.375*CP0 + 0.375*CP1 + 0.125*P2
     */
    _getCurveMidpoint(relData) {
        const sx = relData.sx, sy = relData.sy, tx = relData.tx, ty = relData.ty;
        const cp0 = relData.controlPoints[0];
        const cp1 = relData.controlPoints[1] || cp0;

        return {
            x: 0.125 * sx + 0.375 * cp0.x + 0.375 * cp1.x + 0.125 * tx,
            y: 0.125 * sy + 0.375 * cp0.y + 0.375 * cp1.y + 0.125 * ty,
        };
    }

    _createLabel(relData) {
        const opts = relData.options;
        const mid = this._getCurveMidpoint(relData);

        const labelGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        labelGroup.style.cursor = 'pointer';

        const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        bgRect.setAttribute('fill', '#ffffff');
        bgRect.setAttribute('stroke', opts.labelBorderColor || opts.lineColor || '#77933C');
        bgRect.setAttribute('stroke-width', opts.labelBorderWidth || '1');
        bgRect.setAttribute('rx', '4');
        bgRect.setAttribute('ry', '4');
        bgRect.setAttribute('class', 'label-background');
        labelGroup.appendChild(bgRect);

        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', mid.x);
        text.setAttribute('y', mid.y);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('dominant-baseline', 'middle');
        text.setAttribute('fill', opts.labelColor || '#595959');
        text.setAttribute('font-size', opts.labelFontSize || 10);
        text.setAttribute('font-family', "'Microsoft YaHei', Georgia, serif");
        if (opts.labelBold) text.setAttribute('font-weight', 'bold');
        if (opts.labelItalic) text.setAttribute('font-style', 'italic');
        text.textContent = opts.label;
        labelGroup.appendChild(text);

        // Size background to fit text
        setTimeout(() => {
            try {
                const bbox = text.getBBox();
                const padX = 8, padY = 4;
                bgRect.setAttribute('x', bbox.x - padX);
                bgRect.setAttribute('y', bbox.y - padY);
                bgRect.setAttribute('width', bbox.width + padX * 2);
                bgRect.setAttribute('height', bbox.height + padY * 2);
            } catch (e) {}
        }, 10);

        // Double-click to edit label text
        labelGroup.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            e.preventDefault();
            this._beginLabelEdit(relData, text, bgRect, opts);
        });

        return labelGroup;
    }

    _beginLabelEdit(relData, textEl, bgRect, opts) {
        const bbox = textEl.getBBox();
        const fo = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
        fo.setAttribute('x', bbox.x - 8);
        fo.setAttribute('y', bbox.y - 4);
        fo.setAttribute('width', Math.max(bbox.width + 40, 80));
        fo.setAttribute('height', bbox.height + 12);

        const input = document.createElement('input');
        input.type = 'text';
        input.value = opts.label || '';
        input.style.cssText = `
            width: 100%; height: 100%; border: 2px solid #558ED5; border-radius: 4px;
            padding: 1px 4px; font-size: ${opts.labelFontSize || 10}px;
            font-family: 'Microsoft YaHei', Georgia, serif; text-align: center;
            outline: none; background: #fff; color: ${opts.labelColor || '#595959'};
            ${opts.labelItalic ? 'font-style: italic;' : ''}
            ${opts.labelBold ? 'font-weight: bold;' : ''}
        `;

        fo.appendChild(input);
        textEl.style.display = 'none';
        bgRect.style.display = 'none';
        relData.group.appendChild(fo);

        input.focus();
        input.select();

        const finish = (save) => {
            if (save) {
                const newText = input.value.trim();
                opts.label = newText;
                textEl.textContent = newText;
            }
            textEl.style.display = '';
            bgRect.style.display = '';
            fo.remove();
            setTimeout(() => {
                try {
                    const nb = textEl.getBBox();
                    bgRect.setAttribute('x', nb.x - 8);
                    bgRect.setAttribute('y', nb.y - 4);
                    bgRect.setAttribute('width', nb.width + 16);
                    bgRect.setAttribute('height', nb.height + 8);
                } catch (e) {}
            }, 10);
        };

        input.addEventListener('blur', () => finish(true));
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
            if (e.key === 'Escape') { finish(false); }
        });
    }

    selectRelationship(relId) {
        if (this.selectedRelationship) {
            this._hideControlPoints(this.selectedRelationship);
        }

        const relData = this.relationships.find(r => r.id === relId);
        if (!relData) return;

        this.selectedRelationship = relData;
        this._showControlPoints(relData);
    }

    /**
     * Show 4 handles: source endpoint (blue), CP0 (green), CP1 (green), target endpoint (red).
     * Control lines: source→CP0 and CP1→target (dashed guide lines).
     */
    _showControlPoints(relData) {
        const controlsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        controlsGroup.setAttribute('class', 'control-points');
        controlsGroup.style.pointerEvents = 'auto';

        const cp0 = relData.controlPoints[0];
        const cp1 = relData.controlPoints[1] || cp0;

        // Control guide lines: source→CP0 and CP1→target
        const line0 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line0.setAttribute('x1', relData.sx);
        line0.setAttribute('y1', relData.sy);
        line0.setAttribute('x2', cp0.x);
        line0.setAttribute('y2', cp0.y);
        line0.setAttribute('stroke', '#aaa');
        line0.setAttribute('stroke-width', '1');
        line0.setAttribute('stroke-dasharray', '4,3');
        line0.style.pointerEvents = 'none';
        line0.setAttribute('class', 'cp-guide-line cp-guide-0');
        controlsGroup.appendChild(line0);

        const line1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line1.setAttribute('x1', cp1.x);
        line1.setAttribute('y1', cp1.y);
        line1.setAttribute('x2', relData.tx);
        line1.setAttribute('y2', relData.ty);
        line1.setAttribute('stroke', '#aaa');
        line1.setAttribute('stroke-width', '1');
        line1.setAttribute('stroke-dasharray', '4,3');
        line1.style.pointerEvents = 'none';
        line1.setAttribute('class', 'cp-guide-line cp-guide-1');
        controlsGroup.appendChild(line1);

        // Source endpoint handle (blue circle)
        const srcHandle = this._createCircleHandle(controlsGroup, relData.sx, relData.sy, '#007bff');
        this._makeEndpointDraggable(srcHandle, relData, 'source', controlsGroup);

        // CP0 handle (green circle — near source)
        const cp0Handle = this._createCircleHandle(controlsGroup, cp0.x, cp0.y, '#28a745');
        this._makeCPDraggable(cp0Handle, relData, 0, controlsGroup);

        // CP1 handle (green circle — near target)
        const cp1Handle = this._createCircleHandle(controlsGroup, cp1.x, cp1.y, '#28a745');
        this._makeCPDraggable(cp1Handle, relData, 1, controlsGroup);

        // Target endpoint handle (red circle)
        const tgtHandle = this._createCircleHandle(controlsGroup, relData.tx, relData.ty, '#dc3545');
        this._makeEndpointDraggable(tgtHandle, relData, 'target', controlsGroup);

        relData.group.appendChild(controlsGroup);
        relData.controlsGroup = controlsGroup;
        relData.controlPointElements = [cp0Handle.hit, cp1Handle.hit];
    }

    /**
     * Create a circular handle with background circle, colored fill, and invisible hit area.
     */
    _createCircleHandle(parent, x, y, color) {
        // White background circle
        const bg = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        bg.setAttribute('cx', x);
        bg.setAttribute('cy', y);
        bg.setAttribute('r', '6');
        bg.setAttribute('fill', 'white');
        bg.setAttribute('stroke', color);
        bg.setAttribute('stroke-width', '2');
        bg.style.pointerEvents = 'none';
        bg.setAttribute('class', 'cp-handle-bg');

        // Colored inner fill
        const inner = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        inner.setAttribute('cx', x);
        inner.setAttribute('cy', y);
        inner.setAttribute('r', '3');
        inner.setAttribute('fill', color);
        inner.style.pointerEvents = 'none';
        inner.setAttribute('class', 'cp-handle-inner');

        // Invisible hit area (larger — easy to grab)
        const hit = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        hit.setAttribute('cx', x);
        hit.setAttribute('cy', y);
        hit.setAttribute('r', '12');
        hit.setAttribute('fill', 'transparent');
        hit.setAttribute('stroke', 'none');
        hit.style.cursor = 'grab';
        hit.style.pointerEvents = 'all';
        hit.setAttribute('class', 'draggable-control');

        parent.appendChild(bg);
        parent.appendChild(inner);
        parent.appendChild(hit);

        return { bg, inner, hit };
    }

    /**
     * Make a control point (CP0 or CP1) handle draggable.
     * Dragging a CP updates the curve AND moves the nearest endpoint along the topic border.
     */
    _makeCPDraggable(handle, relData, cpIndex, controlsGroup) {
        const self = this;
        const cp = relData.controlPoints[cpIndex];

        handle.hit.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();

            const onMove = (ev) => {
                const containerRect = self.container.getBoundingClientRect();
                const zoom = self.container.style.transform
                    ? parseFloat(self.container.style.transform.match(/scale\(([^)]+)\)/)?.[1] || 1) : 1;
                const x = (ev.clientX - containerRect.left) / zoom;
                const y = (ev.clientY - containerRect.top) / zoom;

                cp.x = x;
                cp.y = y;

                // Update handle visual position
                handle.bg.setAttribute('cx', x);
                handle.bg.setAttribute('cy', y);
                handle.inner.setAttribute('cx', x);
                handle.inner.setAttribute('cy', y);
                handle.hit.setAttribute('cx', x);
                handle.hit.setAttribute('cy', y);

                // Recalculate path (will also move endpoints via _calculatePath)
                self._updateRelationshipPath(relData);

                // Update guide lines and endpoint handle positions
                self._updateControlHandles(relData, controlsGroup);
            };

            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    /**
     * Make an endpoint (source or target) handle draggable.
     * Drag to re-target to a different node (drop on node = reconnect).
     */
    _makeEndpointDraggable(handle, relData, endType, controlsGroup) {
        const self = this;
        const origSx = relData.sx, origSy = relData.sy;
        const origTx = relData.tx, origTy = relData.ty;

        handle.hit.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();

            const onMove = (ev) => {
                const containerRect = self.container.getBoundingClientRect();
                const zoom = self.container.style.transform
                    ? parseFloat(self.container.style.transform.match(/scale\(([^)]+)\)/)?.[1] || 1) : 1;
                const x = (ev.clientX - containerRect.left) / zoom;
                const y = (ev.clientY - containerRect.top) / zoom;

                // Move handle
                handle.bg.setAttribute('cx', x);
                handle.bg.setAttribute('cy', y);
                handle.inner.setAttribute('cx', x);
                handle.inner.setAttribute('cy', y);
                handle.hit.setAttribute('cx', x);
                handle.hit.setAttribute('cy', y);

                if (endType === 'source') { relData.sx = x; relData.sy = y; }
                else { relData.tx = x; relData.ty = y; }

                // Update path without recalculating edge points (we're dragging freely)
                const d = this._calculatePathRaw(relData);
                relData.pathElement.setAttribute('d', d);
                if (relData.hitAreaElement) relData.hitAreaElement.setAttribute('d', d);
                self._updateControlHandles(relData, controlsGroup);

                // Highlight nearest node for drop
                const el = document.elementFromPoint(ev.clientX, ev.clientY);
                const nodeEl = el ? el.closest('.xmind-node') : null;
                self.container.querySelectorAll('.rel-drop-target').forEach(n => n.classList.remove('rel-drop-target'));
                if (nodeEl) nodeEl.classList.add('rel-drop-target');
            };

            const onUp = (ev) => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                self.container.querySelectorAll('.rel-drop-target').forEach(n => n.classList.remove('rel-drop-target'));

                const el = document.elementFromPoint(ev.clientX, ev.clientY);
                const nodeEl = el ? el.closest('.xmind-node') : null;

                if (nodeEl) {
                    if (endType === 'source') {
                        relData.sourceElement = nodeEl;
                    } else {
                        relData.targetElement = nodeEl;
                    }
                    // Generate new default control points for the new connection
                    const scx = relData.sourceElement.offsetLeft + relData.sourceElement.offsetWidth / 2;
                    const scy = relData.sourceElement.offsetTop + relData.sourceElement.offsetHeight / 2;
                    const tcx = relData.targetElement.offsetLeft + relData.targetElement.offsetWidth / 2;
                    const tcy = relData.targetElement.offsetTop + relData.targetElement.offsetHeight / 2;
                    const srcEdge = self._getEdgePoint(relData.sourceElement, tcx, tcy);
                    const tgtEdge = self._getEdgePoint(relData.targetElement, scx, scy);
                    relData.sx = srcEdge.x;
                    relData.sy = srcEdge.y;
                    relData.tx = tgtEdge.x;
                    relData.ty = tgtEdge.y;
                    relData.controlPoints = self._defaultControlPoints(relData.sx, relData.sy, relData.tx, relData.ty);
                } else {
                    // Snap back
                    if (endType === 'source') { relData.sx = origSx; relData.sy = origSy; }
                    else { relData.tx = origTx; relData.ty = origTy; }
                }

                self._updateRelationshipPath(relData);
                self._hideControlPoints(relData);
                self._showControlPoints(relData);
            };

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    /**
     * Calculate path without recalculating edge points (used during endpoint drag).
     */
    _calculatePathRaw(relData) {
        const { sx, sy, tx, ty, controlPoints, options } = relData;
        const cp0 = controlPoints[0];
        const cp1 = controlPoints[1] || cp0;

        switch (options.shapeType) {
            case 'straight':
                return `M ${sx} ${sy} L ${tx} ${ty}`;
            case 'angled': {
                const midX = (sx + tx) / 2;
                return `M ${sx} ${sy} L ${midX} ${sy} L ${midX} ${ty} L ${tx} ${ty}`;
            }
            case 'curved':
            default:
                return `M ${sx} ${sy} C ${cp0.x} ${cp0.y}, ${cp1.x} ${cp1.y}, ${tx} ${ty}`;
        }
    }

    /**
     * Update guide lines and endpoint handle positions after CP or endpoint move.
     */
    _updateControlHandles(relData, controlsGroup) {
        if (!controlsGroup) return;

        const cp0 = relData.controlPoints[0];
        const cp1 = relData.controlPoints[1] || cp0;

        // Update guide lines
        const guide0 = controlsGroup.querySelector('.cp-guide-0');
        if (guide0) {
            guide0.setAttribute('x1', relData.sx);
            guide0.setAttribute('y1', relData.sy);
            guide0.setAttribute('x2', cp0.x);
            guide0.setAttribute('y2', cp0.y);
        }
        const guide1 = controlsGroup.querySelector('.cp-guide-1');
        if (guide1) {
            guide1.setAttribute('x1', cp1.x);
            guide1.setAttribute('y1', cp1.y);
            guide1.setAttribute('x2', relData.tx);
            guide1.setAttribute('y2', relData.ty);
        }

        // Update endpoint handle positions (source and target may have moved due to edge recalc)
        const handles = controlsGroup.querySelectorAll('.cp-handle-bg');
        const inners = controlsGroup.querySelectorAll('.cp-handle-inner');
        const hits = controlsGroup.querySelectorAll('.draggable-control');
        if (handles.length >= 4) {
            // Order: src(0), cp0(1), cp1(2), tgt(3)
            [handles[0], inners[0], hits[0]].forEach(el => {
                el.setAttribute('cx', relData.sx);
                el.setAttribute('cy', relData.sy);
            });
            [handles[3], inners[3], hits[3]].forEach(el => {
                el.setAttribute('cx', relData.tx);
                el.setAttribute('cy', relData.ty);
            });
        }
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

        if (relData.hitAreaElement) {
            relData.hitAreaElement.setAttribute('d', d);
        }

        // Update guide lines + endpoint handles if controls are visible
        if (relData.controlsGroup) {
            this._updateControlHandles(relData, relData.controlsGroup);
        }

        // Update label position
        if (relData.labelElement) {
            const mid = this._getCurveMidpoint(relData);
            const text = relData.labelElement.querySelector('text');
            if (text) {
                text.setAttribute('x', mid.x);
                text.setAttribute('y', mid.y);
            }
            const bgRect = relData.labelElement.querySelector('.label-background');
            if (bgRect && text) {
                try {
                    const bbox = text.getBBox();
                    bgRect.setAttribute('x', bbox.x - 8);
                    bgRect.setAttribute('y', bbox.y - 4);
                    bgRect.setAttribute('width', bbox.width + 16);
                    bgRect.setAttribute('height', bbox.height + 8);
                } catch (e) {}
            }
        }
    }

    updateRelationshipOptions(relId, newOptions) {
        const relData = this.relationships.find(r => r.id === relId);
        if (!relData) return;

        Object.assign(relData.options, newOptions);
        this._applyPathStyles(relData.pathElement, relData);

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
        this.relationships.forEach(relData => {
            if (!relData.sourceElement || !relData.targetElement) return;

            // Remember old endpoints
            const oldSx = relData.sx, oldSy = relData.sy;
            const oldTx = relData.tx, oldTy = relData.ty;

            // Get new center-to-center edge points (for initial estimate)
            const scx = relData.sourceElement.offsetLeft + relData.sourceElement.offsetWidth / 2;
            const scy = relData.sourceElement.offsetTop + relData.sourceElement.offsetHeight / 2;
            const tcx = relData.targetElement.offsetLeft + relData.targetElement.offsetWidth / 2;
            const tcy = relData.targetElement.offsetTop + relData.targetElement.offsetHeight / 2;

            // Shift control points by the movement delta of their nearest endpoint
            const srcEdge = this._getEdgePoint(relData.sourceElement, tcx, tcy);
            const tgtEdge = this._getEdgePoint(relData.targetElement, scx, scy);

            const dsx = srcEdge.x - oldSx;
            const dsy = srcEdge.y - oldSy;
            const dtx = tgtEdge.x - oldTx;
            const dty = tgtEdge.y - oldTy;

            // CP0 moves with source, CP1 moves with target
            if (relData.controlPoints[0]) {
                relData.controlPoints[0].x += dsx;
                relData.controlPoints[0].y += dsy;
            }
            if (relData.controlPoints[1]) {
                relData.controlPoints[1].x += dtx;
                relData.controlPoints[1].y += dty;
            }

            relData.sx = srcEdge.x;
            relData.sy = srcEdge.y;
            relData.tx = tgtEdge.x;
            relData.ty = tgtEdge.y;

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
            sourceId: rel.sourceElement.getAttribute('data-nodeid'),
            targetId: rel.targetElement.getAttribute('data-nodeid'),
            controlPoints: rel.controlPoints.map(cp => ({ x: cp.x, y: cp.y })),
            options: { ...rel.options }
        }));
    }
}
