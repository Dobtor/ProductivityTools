/** @odoo-module **/

/**
 * Advanced Features - Visual Rendering
 * Implements: Boundaries, Summaries, Relationships, Markers, Callouts
 */
import { _t } from "@web/core/l10n/translation";

/**
 * Relationship Renderer - Draws curved connection lines between topics
 */
export class RelationshipRenderer {
    constructor(container) {
        this.container = container;
        this.svg = null;
        this.relationships = [];
        this._createSVG();
    }

    _createSVG() {
        this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        this.svg.style.position = 'absolute';
        this.svg.style.top = '0';
        this.svg.style.left = '0';
        this.svg.style.width = '100%';
        this.svg.style.height = '100%';
        this.svg.style.pointerEvents = 'none';
        this.svg.style.zIndex = '5';
        this.container.appendChild(this.svg);

        // Define arrow marker
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
        marker.setAttribute('id', 'arrowhead');
        marker.setAttribute('markerWidth', '10');
        marker.setAttribute('markerHeight', '7');
        marker.setAttribute('refX', '10');
        marker.setAttribute('refY', '3.5');
        marker.setAttribute('orient', 'auto');

        const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
        polygon.setAttribute('points', '0 0, 10 3.5, 0 7');
        polygon.setAttribute('fill', '#999');
        marker.appendChild(polygon);
        defs.appendChild(marker);
        this.svg.appendChild(defs);
    }

    clear() {
        while (this.svg.childNodes.length > 1) {
            this.svg.removeChild(this.svg.lastChild);
        }
        this.relationships = [];
    }

    addRelationship(sourceElement, targetElement, options = {}) {
        if (!sourceElement || !targetElement) return;

        // Use local coords for world-space SVG
        const sx = sourceElement.offsetLeft + sourceElement.offsetWidth / 2;
        const sy = sourceElement.offsetTop + sourceElement.offsetHeight / 2;
        const tx = targetElement.offsetLeft + targetElement.offsetWidth / 2;
        const ty = targetElement.offsetTop + targetElement.offsetHeight / 2;

        // Create path group
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');

        // Draw curved path
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const midX = (sx + tx) / 2;
        const midY = (sy + ty) / 2;
        const ctrlOffset = Math.min(Math.abs(tx - sx), Math.abs(ty - sy)) / 3;

        let d;
        if (options.lineType === 'straight') {
            d = `M ${sx} ${sy} L ${tx} ${ty}`;
        } else if (options.lineType === 'angled') {
            d = `M ${sx} ${sy} L ${midX} ${sy} L ${midX} ${ty} L ${tx} ${ty}`;
        } else { // curved (default)
            d = `M ${sx} ${sy} Q ${midX} ${sy - ctrlOffset * 2} ${tx} ${ty}`;
        }

        path.setAttribute('d', d);
        path.setAttribute('stroke', options.lineColor || '#0068cf');
        path.setAttribute('stroke-width', options.lineWidth || 3);
        path.setAttribute('stroke-dasharray', '2,3');
        path.setAttribute('fill', 'none');
        path.setAttribute('marker-end', 'url(#arrowhead)');
        group.appendChild(path);

        // Add label if provided
        if (options.title) {
            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', midX);
            text.setAttribute('y', midY - 10);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('fill', '#707070');
            text.setAttribute('font-size', '12');
            text.textContent = options.title;
            group.appendChild(text);
        }

        this.svg.appendChild(group);
        this.relationships.push(group);
    }

    refresh() {
        // Recalculate all relationship positions
    }
}

/**
 * Boundary Renderer - Draws enclosing shapes around groups of topics
 */
export class BoundaryRenderer {
    constructor(container) {
        this.container = container;
        this.svg = null;
        this.boundaries = [];
        this._createSVG();
    }

    _createSVG() {
        this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        this.svg.style.position = 'absolute';
        this.svg.style.top = '0';
        this.svg.style.left = '0';
        this.svg.style.width = '100%';
        this.svg.style.height = '100%';
        this.svg.style.pointerEvents = 'none';
        this.svg.style.overflow = 'visible';
        this.svg.style.zIndex = '1';
        this.container.appendChild(this.svg);
    }

    clear() {
        this.svg.innerHTML = '';
        this.boundaries = [];
    }

    // Compute bounding box from the given topic elements (editor passes descendants already)
    _computeBounds(topicElements) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

        for (const el of topicElements) {
            if (!el || el.style.display === 'none') continue;
            const x = el.offsetLeft;
            const y = el.offsetTop;
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, x + el.offsetWidth);
            maxY = Math.max(maxY, y + el.offsetHeight);
        }

        if (minX === Infinity) return { minX: 0, minY: 0, maxX: 100, maxY: 100 };
        return { minX, minY, maxX, maxY };
    }

    addBoundary(topicElements, options = {}) {
        if (!topicElements || topicElements.length === 0) return;

        const bounds = this._computeBounds(topicElements);
        let minX = bounds.minX, minY = bounds.minY;
        let maxX = bounds.maxX, maxY = bounds.maxY;

        // Per-side padding (set by editor to prevent overlap) or uniform fallback
        const fallback = 15 + (options._extraPadding || 0);
        minX -= (options._padLeft != null ? options._padLeft : fallback);
        minY -= (options._padTop != null ? options._padTop : fallback);
        maxX += (options._padRight != null ? options._padRight : fallback);
        maxY += (options._padBottom != null ? options._padBottom : fallback);

        const width = maxX - minX;
        const height = maxY - minY;

        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'boundary-group');

        // Draw boundary shape
        let shape;
        switch (options.shape) {
            case 'wave':
            case 'scallops':
                shape = this._createWavyRect(minX, minY, width, height, options.shape);
                break;
            case 'cloud':
                shape = this._createCloudShape(minX, minY, width, height);
                break;
            case 'bracket':
                shape = this._createBracketShape(minX, minY, width, height);
                break;
            case 'underline':
                shape = this._createUnderlineShape(minX, minY, width, height);
                break;
            case 'rectangle':
                shape = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                shape.setAttribute('x', minX);
                shape.setAttribute('y', minY);
                shape.setAttribute('width', width);
                shape.setAttribute('height', height);
                break;
            case 'rounded':
            default:
                shape = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                shape.setAttribute('x', minX);
                shape.setAttribute('y', minY);
                shape.setAttribute('width', width);
                shape.setAttribute('height', height);
                shape.setAttribute('rx', '10');
                shape.setAttribute('ry', '10');
                break;
        }

        shape.setAttribute('fill', options.fillColor || 'rgba(255, 255, 0, 0.2)');
        shape.setAttribute('stroke', options.borderColor || '#ffc107');
        shape.setAttribute('stroke-width', options.borderWidth || 2);

        if (options.borderStyle === 'dashed') {
            shape.setAttribute('stroke-dasharray', '10,5');
        } else if (options.borderStyle === 'dotted') {
            shape.setAttribute('stroke-dasharray', '2,2');
        }

        group.appendChild(shape);

        // Add title with advanced styling
        if (options.title) {
            const titleGroup = this._createBoundaryTitle(minX, minY, width, height, options);
            group.appendChild(titleGroup);
        }

        this.svg.appendChild(group);
        this.boundaries.push(group);
    }

    _createBoundaryTitle(minX, minY, width, height, options) {
        const titleGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');

        const fontSize = options.titleFontSize || 11;
        const insetX = 8;
        const bgColor = options.borderColor || '#77933C';

        // Placeholder text to measure
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', 0);
        text.setAttribute('y', 0);
        text.setAttribute('text-anchor', 'start');
        text.setAttribute('dominant-baseline', 'central');
        text.setAttribute('fill', '#ffffff');
        text.setAttribute('font-size', fontSize);
        text.setAttribute('font-family', "'Open Sans', sans-serif");
        text.setAttribute('font-weight', 'bold');
        text.textContent = options.title;
        titleGroup.appendChild(text);

        // Build pill background after text is measurable
        setTimeout(() => {
            try {
                const bbox = text.getBBox();
                if (bbox.width <= 0) return;
                const padH = 8, padV = 3, radius = 4;
                const pillW = bbox.width + padH * 2;
                const pillH = bbox.height + padV * 2;
                const pillX = minX + insetX;
                // Pill centered on the border line (style)
                const pillY = minY - pillH / 2;

                const pill = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                pill.setAttribute('x', pillX);
                pill.setAttribute('y', pillY);
                pill.setAttribute('width', pillW);
                pill.setAttribute('height', pillH);
                pill.setAttribute('rx', radius);
                pill.setAttribute('ry', radius);
                pill.setAttribute('fill', bgColor);

                // Position text inside pill
                text.setAttribute('x', pillX + padH);
                text.setAttribute('y', pillY + pillH / 2);

                titleGroup.insertBefore(pill, text);
            } catch (e) { /* not in DOM */ }
        }, 10);

        return titleGroup;
    }

    _createCloudShape(x, y, width, height) {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const r = Math.min(width, height) * 0.15;

        // Create cloud-like path with multiple arcs
        let d = `M ${x + r} ${y + height * 0.3}`;
        d += ` A ${r} ${r} 0 0 1 ${x + r * 2} ${y}`;
        d += ` A ${r * 1.5} ${r * 1.5} 0 0 1 ${x + width * 0.3} ${y}`;
        d += ` A ${r} ${r} 0 0 1 ${x + width * 0.5} ${y - r * 0.5}`;
        d += ` A ${r * 1.5} ${r * 1.5} 0 0 1 ${x + width * 0.7} ${y}`;
        d += ` A ${r} ${r} 0 0 1 ${x + width - r * 2} ${y}`;
        d += ` A ${r} ${r} 0 0 1 ${x + width - r} ${y + height * 0.3}`;
        d += ` A ${r} ${r} 0 0 1 ${x + width} ${y + height * 0.5}`;
        d += ` A ${r} ${r} 0 0 1 ${x + width - r} ${y + height * 0.7}`;
        d += ` A ${r} ${r} 0 0 1 ${x + width - r * 2} ${y + height}`;
        d += ` A ${r * 1.5} ${r * 1.5} 0 0 1 ${x + width * 0.5} ${y + height + r * 0.5}`;
        d += ` A ${r} ${r} 0 0 1 ${x + r * 2} ${y + height}`;
        d += ` A ${r} ${r} 0 0 1 ${x + r} ${y + height * 0.7}`;
        d += ` A ${r} ${r} 0 0 1 ${x} ${y + height * 0.5}`;
        d += ` Z`;

        path.setAttribute('d', d);
        return path;
    }

    _createBracketShape(x, y, width, height) {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const bracketWidth = 15;

        // Left and right brackets only
        let d = `M ${x + bracketWidth} ${y}`;
        d += ` Q ${x} ${y} ${x} ${y + bracketWidth}`;
        d += ` L ${x} ${y + height - bracketWidth}`;
        d += ` Q ${x} ${y + height} ${x + bracketWidth} ${y + height}`;

        d += ` M ${x + width - bracketWidth} ${y}`;
        d += ` Q ${x + width} ${y} ${x + width} ${y + bracketWidth}`;
        d += ` L ${x + width} ${y + height - bracketWidth}`;
        d += ` Q ${x + width} ${y + height} ${x + width - bracketWidth} ${y + height}`;

        path.setAttribute('d', d);
        path.setAttribute('fill', 'none');
        return path;
    }

    _createUnderlineShape(x, y, width, height) {
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', x);
        line.setAttribute('y1', y + height);
        line.setAttribute('x2', x + width);
        line.setAttribute('y2', y + height);
        return line;
    }

    _createWavyRect(x, y, width, height, type) {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const waveSize = type === 'scallops' ? 10 : 8;
        let d = `M ${x} ${y}`;

        // Top edge
        for (let i = 0; i < width; i += waveSize * 2) {
            if (type === 'scallops') {
                d += ` a ${waveSize} ${waveSize} 0 0 1 ${waveSize * 2} 0`;
            } else {
                d += ` q ${waveSize} -${waveSize / 2} ${waveSize * 2} 0`;
            }
        }

        // Right edge
        for (let i = 0; i < height; i += waveSize * 2) {
            if (type === 'scallops') {
                d += ` a ${waveSize} ${waveSize} 0 0 1 0 ${waveSize * 2}`;
            } else {
                d += ` q ${waveSize / 2} ${waveSize} 0 ${waveSize * 2}`;
            }
        }

        // Bottom edge (reversed)
        for (let i = width; i > 0; i -= waveSize * 2) {
            if (type === 'scallops') {
                d += ` a ${waveSize} ${waveSize} 0 0 1 -${waveSize * 2} 0`;
            } else {
                d += ` q -${waveSize} ${waveSize / 2} -${waveSize * 2} 0`;
            }
        }

        // Left edge (reversed)
        for (let i = height; i > 0; i -= waveSize * 2) {
            if (type === 'scallops') {
                d += ` a ${waveSize} ${waveSize} 0 0 1 0 -${waveSize * 2}`;
            } else {
                d += ` q -${waveSize / 2} -${waveSize} 0 -${waveSize * 2}`;
            }
        }

        d += ' Z';
        path.setAttribute('d', d);
        return path;
    }
}

/**
 * Summary Renderer - Draws bracket summaries for sibling topics
 */
export class SummaryRenderer {
    constructor(container) {
        this.container = container;
        this.svg = null;
        this.summaries = [];
        this.selectedSummary = null;
        this.onSummaryClick = null; // Callback for click events
        this.onSummaryContextMenu = null; // Callback for right-click events
        this._createSVG();
    }

    _createSVG() {
        this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        this.svg.style.position = 'absolute';
        this.svg.style.top = '0';
        this.svg.style.left = '0';
        this.svg.style.width = '100%';
        this.svg.style.height = '100%';
        this.svg.style.pointerEvents = 'none';
        this.svg.style.overflow = 'visible';
        this.svg.style.zIndex = '3';
        this.container.appendChild(this.svg);
    }

    clear() {
        this.svg.innerHTML = '';
        // Remove summary node DOM elements
        for (const s of this.summaries) {
            if (s.summaryNodeEl && s.summaryNodeEl.parentNode) {
                s.summaryNodeEl.parentNode.removeChild(s.summaryNodeEl);
            }
        }
        this.summaries = [];
        this.selectedSummary = null;
    }

    setClickCallback(callback) {
        this.onSummaryClick = callback;
    }

    setContextMenuCallback(callback) {
        this.onSummaryContextMenu = callback;
    }

    selectSummary(summaryId) {
        // Deselect previous
        if (this.selectedSummary) {
            const prevSummary = this.summaries.find(s => s.id === this.selectedSummary);
            if (prevSummary && prevSummary.path) {
                prevSummary.path.classList.remove('selected');
            }
        }

        this.selectedSummary = summaryId;

        // Select new
        const summary = this.summaries.find(s => s.id === summaryId);
        if (summary && summary.path) {
            summary.path.classList.add('selected');
        }
    }

    deselectAll() {
        this.summaries.forEach(s => {
            if (s.path) s.path.classList.remove('selected');
        });
        this.selectedSummary = null;
    }

    removeSummary(summaryId) {
        const index = this.summaries.findIndex(s => s.id === summaryId);
        if (index !== -1) {
            const summary = this.summaries[index];
            if (summary.group) summary.group.remove();
            if (summary.summaryNodeEl && summary.summaryNodeEl.parentNode) {
                summary.summaryNodeEl.parentNode.removeChild(summary.summaryNodeEl);
            }
            this.summaries.splice(index, 1);
        }
    }

    // Shared bracket path generator — supports left/right direction
    // dir: 1 = bracket on right (opens toward topics on left, tip points to summary on right)
    //     -1 = bracket on left (opens toward topics on right, tip points to summary on left)
    //
    // For dir=1 (right side): bracket looks like  ]  (vertical bar on right, arms reach left toward topics, tip → summary)
    //   Topics ──┐
    //            │ ]─── Summary
    //   Topics ──┘
    _generateBracketPath(lineType, geo) {
        if (geo.vertical) {
            return this._generateVerticalBracketPath(lineType, geo);
        }
        return this._generateHorizontalBracketPath(lineType, geo);
    }

    _generateHorizontalBracketPath(lineType, geo) {
        const { bracketX, minY, maxY, midY, dir } = geo;
        const d = dir || 1;
        const inward = -d * 10;
        const outward = d * 10;
        const inw5 = -d * 5;
        const out5 = d * 5;

        switch (lineType) {
            case 'bracket':
                return `M ${bracketX + inward} ${minY} L ${bracketX} ${minY} L ${bracketX} ${midY - 5} L ${bracketX + outward} ${midY} L ${bracketX} ${midY + 5} L ${bracketX} ${maxY} L ${bracketX + inward} ${maxY}`;
            case 'brace':
                return `M ${bracketX + inward} ${minY} Q ${bracketX} ${minY}, ${bracketX} ${minY + 10} L ${bracketX} ${midY - 15} Q ${bracketX} ${midY - 5}, ${bracketX + outward} ${midY} Q ${bracketX} ${midY + 5}, ${bracketX} ${midY + 15} L ${bracketX} ${maxY - 10} Q ${bracketX} ${maxY}, ${bracketX + inward} ${maxY}`;
            case 'straight':
                return `M ${bracketX} ${minY} L ${bracketX} ${maxY} M ${bracketX} ${midY} L ${bracketX + outward} ${midY}`;
            case 'curved':
                return `M ${bracketX + inward} ${minY} C ${bracketX + out5} ${minY}, ${bracketX + out5} ${midY - 20}, ${bracketX + outward} ${midY} C ${bracketX + out5} ${midY + 20}, ${bracketX + out5} ${maxY}, ${bracketX + inward} ${maxY}`;
            case 'square':
                return `M ${bracketX} ${minY} L ${bracketX + outward} ${minY} L ${bracketX + outward} ${maxY} L ${bracketX} ${maxY} M ${bracketX + outward} ${midY} L ${bracketX + outward * 2} ${midY}`;
            case 'angle':
                return `M ${bracketX + inw5} ${minY} L ${bracketX + outward} ${midY} L ${bracketX + inw5} ${maxY}`;
            case 'round': {
                const radius = (maxY - minY) / 2;
                const sweep = d > 0 ? 1 : 0;
                return `M ${bracketX + inw5} ${minY} A ${radius * 0.6} ${radius} 0 0 ${sweep} ${bracketX + inw5} ${maxY} M ${bracketX + inw5 + d * radius * 0.3} ${midY} L ${bracketX + outward} ${midY}`;
            }
            default:
                return `M ${bracketX + inward} ${minY} L ${bracketX} ${minY} L ${bracketX} ${midY - 5} L ${bracketX + outward} ${midY} L ${bracketX} ${midY + 5} L ${bracketX} ${maxY} L ${bracketX + inward} ${maxY}`;
        }
    }

    /**
     * Generate bracket path for vertical layouts (org_chart_up/down).
     * Bracket is horizontal, spanning minX~maxX, with tip pointing up or down.
     */
    _generateVerticalBracketPath(lineType, geo) {
        const { bracketY, minX, maxX, midX, vdir } = geo;
        const d = vdir || 1; // 1=down, -1=up
        const inward = -d * 10;
        const outward = d * 10;

        switch (lineType) {
            case 'bracket':
                return `M ${minX} ${bracketY + inward} L ${minX} ${bracketY} L ${midX - 5} ${bracketY} L ${midX} ${bracketY + outward} L ${midX + 5} ${bracketY} L ${maxX} ${bracketY} L ${maxX} ${bracketY + inward}`;
            case 'brace':
                return `M ${minX} ${bracketY + inward} Q ${minX} ${bracketY}, ${minX + 10} ${bracketY} L ${midX - 15} ${bracketY} Q ${midX - 5} ${bracketY}, ${midX} ${bracketY + outward} Q ${midX + 5} ${bracketY}, ${midX + 15} ${bracketY} L ${maxX - 10} ${bracketY} Q ${maxX} ${bracketY}, ${maxX} ${bracketY + inward}`;
            case 'straight':
                return `M ${minX} ${bracketY} L ${maxX} ${bracketY} M ${midX} ${bracketY} L ${midX} ${bracketY + outward}`;
            case 'square':
                return `M ${minX} ${bracketY} L ${minX} ${bracketY + outward} L ${maxX} ${bracketY + outward} L ${maxX} ${bracketY} M ${midX} ${bracketY + outward} L ${midX} ${bracketY + outward * 2}`;
            case 'angle':
                return `M ${minX} ${bracketY - d * 5} L ${midX} ${bracketY + outward} L ${maxX} ${bracketY - d * 5}`;
            default:
                return `M ${minX} ${bracketY + inward} L ${minX} ${bracketY} L ${midX - 5} ${bracketY} L ${midX} ${bracketY + outward} L ${midX + 5} ${bracketY} L ${maxX} ${bracketY} L ${maxX} ${bracketY + inward}`;
        }
    }

    /**
     * Compute bracket geometry, supporting both horizontal and vertical layouts.
     * @param {Element[]} topicElements
     * @param {string} layoutMode - current layout mode (e.g. 'org_chart_up')
     */
    _computeBracketGeometry(topicElements, layoutMode) {
        let minY = Infinity, maxY = -Infinity;
        let leftX = Infinity, rightX = -Infinity;

        for (const element of topicElements) {
            const x = element.offsetLeft;
            const y = element.offsetTop;
            minY = Math.min(minY, y);
            maxY = Math.max(maxY, y + element.offsetHeight);
            leftX = Math.min(leftX, x);
            rightX = Math.max(rightX, x + element.offsetWidth);
        }

        const isVertical = layoutMode === 'org_chart_up' || layoutMode === 'org_chart_down';

        if (isVertical) {
            // Vertical layout: bracket is horizontal, spanning leftX~rightX
            const midX = leftX + (rightX - leftX) / 2;
            // org_chart_up: children above parent → bracket ABOVE children (vdir=-1=upward)
            // org_chart_down: children below parent → bracket BELOW children (vdir=1=downward)
            const vdir = layoutMode === 'org_chart_up' ? -1 : 1;
            const bracketY = layoutMode === 'org_chart_up'
                ? minY - 10   // above the spanned topics
                : maxY + 10;  // below the spanned topics
            return { vertical: true, bracketY, minX: leftX, maxX: rightX, midX, vdir, minY, maxY, leftX, rightX };
        }

        // Horizontal layout (default)
        let dir = 1;
        if (topicElements.length > 0) {
            const firstEl = topicElements[0];
            if (firstEl.offsetLeft < -50) {
                dir = -1;
            }
        }

        const bracketX = dir > 0 ? rightX + 20 : leftX - 20;
        const midY = minY + (maxY - minY) / 2;
        return { vertical: false, bracketX, minY, maxY, midY, dir, leftX, rightX };
    }

    addSummary(topicElements, summaryElement, options = {}) {
        if (!topicElements || topicElements.length === 0) return null;

        const summaryId = options.id || 'summary_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        const lineType = options.lineType || 'bracket';
        const lineColor = options.lineColor || '#666666';
        const lineWidth = options.lineWidth || 2;
        const layoutMode = options.layoutMode || '';

        const geo = this._computeBracketGeometry(topicElements, layoutMode);

        // Create SVG group for bracket + connection line
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.classList.add('summary-group');
        group.setAttribute('data-summary-id', summaryId);
        group.style.pointerEvents = 'stroke';
        group.style.cursor = 'pointer';

        // Draw bracket
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const d = this._generateBracketPath(lineType, geo);
        path.setAttribute('d', d);
        path.setAttribute('stroke', lineColor);
        path.setAttribute('stroke-width', lineWidth);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        path.classList.add('summary-path');
        group.appendChild(path);

        // Connection line: short stub from bracket tip outward
        // Summary node will be positioned at the end by _positionSummaryNode
        const connectionLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        if (geo.vertical) {
            const tipY = geo.bracketY + geo.vdir * 10;
            const lineEndY = geo.bracketY + geo.vdir * 38;
            connectionLine.setAttribute('x1', geo.midX);
            connectionLine.setAttribute('y1', tipY);
            connectionLine.setAttribute('x2', geo.midX);
            connectionLine.setAttribute('y2', lineEndY);
        } else {
            const dir = geo.dir || 1;
            const tipX = geo.bracketX + dir * 20;
            const lineEndX = geo.bracketX + dir * 38;
            connectionLine.setAttribute('x1', tipX);
            connectionLine.setAttribute('y1', geo.midY);
            connectionLine.setAttribute('x2', lineEndX);
            connectionLine.setAttribute('y2', geo.midY);
        }
        connectionLine.setAttribute('stroke', lineColor);
        connectionLine.setAttribute('stroke-width', lineWidth);
        connectionLine.setAttribute('stroke-linecap', 'round');
        connectionLine.classList.add('summary-connection');
        group.appendChild(connectionLine);

        this.svg.appendChild(group);

        // Don't store render-engine node in summaryNodeEl — clear() would remove it from DOM
        // summaryNodeEl is only for standalone DOM elements created by the renderer
        let summaryNodeEl = null;

        // Event listeners on SVG bracket
        const self = this;
        group.addEventListener('click', (e) => {
            e.stopPropagation();
            self.selectSummary(summaryId);
            if (self.onSummaryClick) self.onSummaryClick(summaryId, e);
        });
        group.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            e.stopPropagation();
            self.selectSummary(summaryId);
            if (self.onSummaryContextMenu) self.onSummaryContextMenu(summaryId, e);
        });

        const summaryData = {
            id: summaryId,
            group: group,
            path: path,
            connectionLine: connectionLine,
            summaryNodeEl: summaryNodeEl,
            topicElements: topicElements,
            summaryElement: summaryElement,
            options: options,
        };

        this.summaries.push(summaryData);
        return summaryId;
    }

    // Update summary positions when layout changes
    updatePositions(layoutMode) {
        if (!this.summaries || this.summaries.length === 0) return;

        for (const summary of this.summaries) {
            if (!summary.topicElements || summary.topicElements.length === 0) continue;

            const geo = this._computeBracketGeometry(summary.topicElements, layoutMode || '');
            const lineType = summary.options.lineType || 'bracket';
            const d = this._generateBracketPath(lineType, geo);

            summary.path.setAttribute('d', d);

            if (summary.connectionLine) {
                if (geo.vertical) {
                    const tipY = geo.bracketY + geo.vdir * 10;
                    const lineEndY = geo.bracketY + geo.vdir * 38;
                    summary.connectionLine.setAttribute('x1', geo.midX);
                    summary.connectionLine.setAttribute('y1', tipY);
                    summary.connectionLine.setAttribute('x2', geo.midX);
                    summary.connectionLine.setAttribute('y2', lineEndY);
                } else {
                    const dir = geo.dir || 1;
                    const tipX = geo.bracketX + dir * 20;
                    const lineEndX = geo.bracketX + dir * 38;
                    summary.connectionLine.setAttribute('x1', tipX);
                    summary.connectionLine.setAttribute('y1', geo.midY);
                    summary.connectionLine.setAttribute('x2', lineEndX);
                    summary.connectionLine.setAttribute('y2', geo.midY);
                }
            }
        }
    }

    // Get summary data by ID
    getSummaryById(summaryId) {
        return this.summaries.find(s => s.id === summaryId);
    }

    // Update summary options (for editing)
    updateSummaryOptions(summaryId, newOptions) {
        const summary = this.getSummaryById(summaryId);
        if (!summary) return;

        // Update options
        Object.assign(summary.options, newOptions);

        // Update visual appearance
        if (summary.path) {
            summary.path.setAttribute('stroke', newOptions.lineColor || summary.options.lineColor);
            summary.path.setAttribute('stroke-width', newOptions.lineWidth || summary.options.lineWidth);
        }

        if (summary.connectionLine) {
            summary.connectionLine.setAttribute('stroke', newOptions.lineColor || summary.options.lineColor);
            summary.connectionLine.setAttribute('stroke-width', newOptions.lineWidth || summary.options.lineWidth);
        }

        // Recalculate path if line type changed
        if (newOptions.lineType) {
            this.updatePositions();
        }
    }
}

/**
 * Marker Badge Renderer - Adds visual markers to topic nodes
 */
export class MarkerBadgeRenderer {
    constructor() {
        this.markerCache = {};
    }

    renderMarkers(nodeElement, markerCodes, availableMarkers) {
        // Remove existing markers
        const existingBadges = nodeElement.querySelector('.xmind-markers');
        if (existingBadges) {
            existingBadges.remove();
        }

        if (!markerCodes || markerCodes.length === 0) return;

        const badgeContainer = document.createElement('span');
        badgeContainer.className = 'xmind-markers';
        badgeContainer.style.display = 'inline-flex';
        badgeContainer.style.alignItems = 'center';
        badgeContainer.style.gap = '3px';
        badgeContainer.style.marginRight = '5px';
        badgeContainer.style.verticalAlign = 'middle';

        for (let code of markerCodes) {
            const marker = availableMarkers.find(m => m.code === code);
            if (marker) {
                const badge = document.createElement('span');
                badge.className = 'xmind-marker-badge';
                badge.style.display = 'inline-flex';
                badge.style.alignItems = 'center';
                badge.style.justifyContent = 'center';
                badge.style.width = '16px';
                badge.style.height = '16px';
                badge.style.fontSize = '12px';
                badge.style.lineHeight = '1';
                badge.style.flexShrink = '0';
                if (marker.short_label) {
                    // Icon + overlaid number/text (e.g., calendar icon with "1月" on top)
                    badge.style.position = 'relative';
                    badge.style.width = '18px';
                    badge.style.height = '18px';
                    badge.style.fontSize = '16px';
                    badge.innerHTML = `<i class="${marker.icon}" style="color:${marker.color}"></i>`
                        + `<span style="position:absolute;top:5px;left:0;right:0;text-align:center;`
                        + `font-size:6px;font-weight:bold;color:${marker.color};line-height:1;`
                        + `text-shadow:0 0 2px #fff,0 0 2px #fff;">${marker.short_label}</span>`;
                } else {
                    badge.innerHTML = `<i class="${marker.icon}" style="color:${marker.color}"></i>`;
                }
                badge.title = marker.name;
                badge.style.cursor = 'pointer';
                badge.dataset.markerCode = code;
                badgeContainer.appendChild(badge);
            }
        }

        // Insert before text span so node naturally expands
        const textSpan = nodeElement.querySelector('.xmind-topic-text');
        if (textSpan) {
            nodeElement.insertBefore(badgeContainer, textSpan);
        } else {
            nodeElement.appendChild(badgeContainer);
        }
    }
}

/**
 * Label Renderer - Adds text labels below topics
 */
export class LabelRenderer {
    renderLabels(nodeElement, labels) {
        // Remove existing labels
        const existingLabels = nodeElement.querySelector('.xmind-labels');
        if (existingLabels) {
            existingLabels.remove();
        }

        if (!labels || labels.length === 0) return;

        const labelContainer = document.createElement('div');
        labelContainer.className = 'xmind-labels';
        labelContainer.style.position = 'absolute';
        labelContainer.style.bottom = '-22px';
        labelContainer.style.left = '50%';
        labelContainer.style.transform = 'translateX(-50%)';
        labelContainer.style.display = 'flex';
        labelContainer.style.gap = '4px';
        labelContainer.style.whiteSpace = 'nowrap';

        for (let label of labels) {
            const badge = document.createElement('span');
            badge.className = 'xmind-label';
            badge.style.background = '#ffc107';
            badge.style.color = '#000';
            badge.style.padding = '1px 8px';
            badge.style.borderRadius = '12px';
            badge.style.fontSize = '11px';
            badge.style.fontWeight = '500';
            badge.textContent = label.trim();
            labelContainer.appendChild(badge);
        }

        nodeElement.style.position = 'relative';
        nodeElement.appendChild(labelContainer);
    }
}

/**
 * Note Indicator - Shows note icon on topics with notes
 */
export class NoteIndicator {
    addIndicator(nodeElement, hasNote) {
        const existing = nodeElement.querySelector('.xmind-note-indicator');
        if (existing) existing.remove();

        if (!hasNote) return;

        const indicator = document.createElement('span');
        indicator.className = 'xmind-note-indicator';
        indicator.style.position = 'absolute';
        indicator.style.top = '-8px';
        indicator.style.left = '-8px';
        indicator.style.width = '16px';
        indicator.style.height = '16px';
        indicator.style.borderRadius = '50%';
        indicator.style.background = '#17a2b8';
        indicator.style.color = '#fff';
        indicator.style.display = 'flex';
        indicator.style.alignItems = 'center';
        indicator.style.justifyContent = 'center';
        indicator.style.fontSize = '9px';
        indicator.style.cursor = 'pointer';
        indicator.innerHTML = '<i class="fa fa-sticky-note"></i>';
        indicator.title = _t('Has Note');

        nodeElement.style.position = 'relative';
        nodeElement.appendChild(indicator);
    }
}

/**
 * Callout Renderer - Creates callout bubbles
 */
export class CalloutRenderer {
    constructor(container) {
        this.container = container;
        this.callouts = [];
    }

    clear() {
        for (let callout of this.callouts) {
            if (callout.parentNode) {
                callout.parentNode.removeChild(callout);
            }
        }
        this.callouts = [];
    }

    addCallout(parentElement, options = {}) {
        // Use local coords
        const _ = 0; // placeholder

        const calloutDiv = document.createElement('div');
        calloutDiv.className = 'xmind-callout';
        calloutDiv.style.position = 'absolute';
        calloutDiv.style.left = (parentElement.offsetLeft + parentElement.offsetWidth + (options.offsetX || 10)) + 'px';
        calloutDiv.style.top = (parentElement.offsetTop + (options.offsetY || -30)) + 'px';
        calloutDiv.style.background = options.backgroundColor || '#fffacd';
        calloutDiv.style.color = options.textColor || '#333';
        calloutDiv.style.border = `2px solid ${options.borderColor || '#ffd700'}`;
        calloutDiv.style.borderRadius = '8px';
        calloutDiv.style.padding = '8px 12px';
        calloutDiv.style.fontSize = '12px';
        calloutDiv.style.boxShadow = '0 2px 8px rgba(0,0,0,0.15)';
        calloutDiv.style.zIndex = '10';
        calloutDiv.style.maxWidth = '200px';

        // Callout pointer
        if (options.shape === 'callout') {
            calloutDiv.style.position = 'relative';
            const pointer = document.createElement('div');
            pointer.style.position = 'absolute';
            pointer.style.bottom = '-10px';
            pointer.style.left = '20px';
            pointer.style.width = '0';
            pointer.style.height = '0';
            pointer.style.borderLeft = '10px solid transparent';
            pointer.style.borderRight = '10px solid transparent';
            pointer.style.borderTop = `10px solid ${options.borderColor || '#ffd700'}`;
            calloutDiv.appendChild(pointer);
        }

        if (options.title) {
            const title = document.createElement('strong');
            title.textContent = options.title;
            title.style.display = 'block';
            title.style.marginBottom = '4px';
            calloutDiv.appendChild(title);
        }

        if (options.content) {
            const content = document.createElement('span');
            content.textContent = options.content;
            calloutDiv.appendChild(content);
        }

        this.container.appendChild(calloutDiv);
        this.callouts.push(calloutDiv);
    }
}

/**
 * Image/Sticker Renderer
 */
export class ImageRenderer {
    renderImage(nodeElement, imageData, options = {}) {
        const existing = nodeElement.querySelector('.xmind-image');
        if (existing) existing.remove();

        if (!imageData) return;

        const imgContainer = document.createElement('div');
        imgContainer.className = 'xmind-image';
        imgContainer.style.textAlign = 'center';

        const img = document.createElement('img');
        img.src = imageData;
        img.style.maxWidth = (options.width || 100) + 'px';
        img.style.maxHeight = (options.height || 100) + 'px';
        img.style.borderRadius = '4px';
        img.style.boxShadow = '0 2px 4px rgba(0,0,0,0.2)';
        img.title = options.title || 'Attached image';

        imgContainer.appendChild(img);

        switch (options.position) {
            case 'above':
                imgContainer.style.marginBottom = '8px';
                nodeElement.insertBefore(imgContainer, nodeElement.firstChild);
                break;
            case 'below':
                imgContainer.style.marginTop = '8px';
                nodeElement.appendChild(imgContainer);
                break;
            case 'left':
                imgContainer.style.float = 'left';
                imgContainer.style.marginRight = '8px';
                nodeElement.insertBefore(imgContainer, nodeElement.firstChild);
                break;
            case 'right':
                imgContainer.style.float = 'right';
                imgContainer.style.marginLeft = '8px';
                nodeElement.appendChild(imgContainer);
                break;
            default: // inline
                imgContainer.style.marginTop = '4px';
                nodeElement.appendChild(imgContainer);
        }
    }

    createThumbnail(imageData, maxSize = 80) {
        const img = document.createElement('img');
        img.src = imageData;
        img.style.maxWidth = maxSize + 'px';
        img.style.maxHeight = maxSize + 'px';
        img.style.borderRadius = '4px';
        img.style.boxShadow = '0 1px 3px rgba(0,0,0,0.2)';
        return img;
    }
}

/**
 * Hyperlink Indicator - Shows link icon on topics with hyperlinks
 */
export class HyperlinkIndicator {
    addIndicator(nodeElement, url, title) {
        const existing = nodeElement.querySelector('.xmind-hyperlink-indicator');
        if (existing) existing.remove();

        if (!url) return;

        const indicator = document.createElement('a');
        indicator.className = 'xmind-hyperlink-indicator';
        indicator.href = url;
        indicator.target = '_blank';
        indicator.rel = 'noopener noreferrer';
        indicator.style.position = 'absolute';
        indicator.style.bottom = '-8px';
        indicator.style.right = '-8px';
        indicator.style.width = '18px';
        indicator.style.height = '18px';
        indicator.style.borderRadius = '50%';
        indicator.style.background = '#007bff';
        indicator.style.color = '#fff';
        indicator.style.display = 'flex';
        indicator.style.alignItems = 'center';
        indicator.style.justifyContent = 'center';
        indicator.style.fontSize = '10px';
        indicator.style.textDecoration = 'none';
        indicator.style.boxShadow = '0 1px 3px rgba(0,0,0,0.3)';
        indicator.style.cursor = 'pointer';
        indicator.innerHTML = '<i class="fa fa-link"></i>';
        indicator.title = title || url;

        indicator.addEventListener('click', function(e) {
            e.stopPropagation();
        });

        nodeElement.style.position = 'relative';
        nodeElement.appendChild(indicator);
    }

    removeIndicator(nodeElement) {
        const existing = nodeElement.querySelector('.xmind-hyperlink-indicator');
        if (existing) existing.remove();
    }
}

/**
 * Attachment Indicator - Shows paperclip icon on topics with attachments
 */
export class AttachmentIndicator {
    addIndicator(nodeElement, count) {
        const existing = nodeElement.querySelector('.xmind-attachment-indicator');
        if (existing) existing.remove();

        if (!count || count <= 0) return;

        const indicator = document.createElement('span');
        indicator.className = 'xmind-attachment-indicator';
        indicator.style.position = 'absolute';
        indicator.style.top = '-8px';
        indicator.style.left = '50%';
        indicator.style.transform = 'translateX(-50%)';
        indicator.style.background = '#6c757d';
        indicator.style.color = '#fff';
        indicator.style.padding = '1px 6px';
        indicator.style.borderRadius = '10px';
        indicator.style.fontSize = '10px';
        indicator.style.boxShadow = '0 1px 3px rgba(0,0,0,0.3)';
        indicator.innerHTML = `<i class="fa fa-paperclip"></i> ${count}`;
        indicator.title = count + ' attachment(s)';

        nodeElement.style.position = 'relative';
        nodeElement.appendChild(indicator);
    }
}

