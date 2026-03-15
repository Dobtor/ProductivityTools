/** @odoo-module **/

/**
 * XMind 2 Advanced Features - Visual Rendering
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

        const sourceRect = sourceElement.getBoundingClientRect();
        const targetRect = targetElement.getBoundingClientRect();
        const containerRect = this.container.getBoundingClientRect();

        const sx = sourceRect.left - containerRect.left + sourceRect.width / 2;
        const sy = sourceRect.top - containerRect.top + sourceRect.height / 2;
        const tx = targetRect.left - containerRect.left + targetRect.width / 2;
        const ty = targetRect.top - containerRect.top + targetRect.height / 2;

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
        path.setAttribute('stroke', options.lineColor || '#999999');
        path.setAttribute('stroke-width', options.lineWidth || 2);
        path.setAttribute('stroke-dasharray', '5,5');
        path.setAttribute('fill', 'none');
        path.setAttribute('marker-end', 'url(#arrowhead)');
        group.appendChild(path);

        // Add label if provided
        if (options.title) {
            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', midX);
            text.setAttribute('y', midY - 10);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('fill', '#666');
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
        this.svg.style.zIndex = '1';
        this.container.appendChild(this.svg);
    }

    clear() {
        this.svg.innerHTML = '';
        this.boundaries = [];
    }

    addBoundary(topicElements, options = {}) {
        if (!topicElements || topicElements.length === 0) return;

        const containerRect = this.container.getBoundingClientRect();

        // Calculate bounding box
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

        for (let element of topicElements) {
            const rect = element.getBoundingClientRect();
            const x = rect.left - containerRect.left;
            const y = rect.top - containerRect.top;
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, x + rect.width);
            maxY = Math.max(maxY, y + rect.height);
        }

        // Add padding
        const padding = 15;
        minX -= padding;
        minY -= padding;
        maxX += padding;
        maxY += padding;

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

        // Calculate position based on titlePosition
        let textX, textY, textAnchor = 'start';
        const padding = 8;
        const fontSize = options.titleFontSize || 14;

        switch (options.titlePosition || 'top-center') {
            case 'top-left':
                textX = minX + padding;
                textY = minY - padding;
                textAnchor = 'start';
                break;
            case 'top-center':
                textX = minX + width / 2;
                textY = minY - padding;
                textAnchor = 'middle';
                break;
            case 'top-right':
                textX = minX + width - padding;
                textY = minY - padding;
                textAnchor = 'end';
                break;
            case 'bottom-left':
                textX = minX + padding;
                textY = minY + height + fontSize + padding;
                textAnchor = 'start';
                break;
            case 'bottom-center':
                textX = minX + width / 2;
                textY = minY + height + fontSize + padding;
                textAnchor = 'middle';
                break;
            case 'bottom-right':
                textX = minX + width - padding;
                textY = minY + height + fontSize + padding;
                textAnchor = 'end';
                break;
        }

        // Create text element
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', textX);
        text.setAttribute('y', textY);
        text.setAttribute('text-anchor', textAnchor);
        text.setAttribute('dominant-baseline', 'middle');
        text.setAttribute('fill', options.titleColor || '#856404');
        text.setAttribute('font-size', fontSize);

        if (options.titleBold) {
            text.setAttribute('font-weight', 'bold');
        }
        if (options.titleItalic) {
            text.setAttribute('font-style', 'italic');
        }

        text.textContent = options.title;
        titleGroup.appendChild(text);

        // Add background if needed
        if (options.titleBackground) {
            setTimeout(() => {
                const bbox = text.getBBox();
                const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                bgRect.setAttribute('x', bbox.x - 4);
                bgRect.setAttribute('y', bbox.y - 2);
                bgRect.setAttribute('width', bbox.width + 8);
                bgRect.setAttribute('height', bbox.height + 4);
                bgRect.setAttribute('fill', '#ffffff');
                bgRect.setAttribute('stroke', options.borderColor || '#ffc107');
                bgRect.setAttribute('stroke-width', '1');
                bgRect.setAttribute('rx', '3');
                titleGroup.insertBefore(bgRect, text);
            }, 10);
        }

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
        this.svg.style.zIndex = '3';
        this.container.appendChild(this.svg);
    }

    clear() {
        this.svg.innerHTML = '';
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
            if (summary.group) {
                summary.group.remove();
            }
            this.summaries.splice(index, 1);
        }
    }

    addSummary(topicElements, summaryElement, options = {}) {
        if (!topicElements || topicElements.length === 0) return null;

        const summaryId = options.id || 'summary_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        const containerRect = this.container.getBoundingClientRect();
        const lineType = options.lineType || 'bracket';
        const lineColor = options.lineColor || '#666666';
        const lineWidth = options.lineWidth || 2;

        // Calculate the vertical span of topics
        let minY = Infinity, maxY = -Infinity;
        let rightX = -Infinity;

        for (let element of topicElements) {
            const rect = element.getBoundingClientRect();
            const x = rect.left - containerRect.left + rect.width;
            const y = rect.top - containerRect.top;
            minY = Math.min(minY, y);
            maxY = Math.max(maxY, y + rect.height);
            rightX = Math.max(rightX, x);
        }

        const bracketX = rightX + 20;
        const bracketHeight = maxY - minY;
        const midY = minY + bracketHeight / 2;

        // Create a group for all summary elements
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.classList.add('summary-group');
        group.setAttribute('data-summary-id', summaryId);
        group.style.pointerEvents = 'stroke';
        group.style.cursor = 'pointer';

        // Draw summary line based on type
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        let d = '';

        switch (lineType) {
            case 'bracket':
                d = `M ${bracketX - 10} ${minY}
                     L ${bracketX} ${minY}
                     L ${bracketX} ${midY - 5}
                     L ${bracketX + 10} ${midY}
                     L ${bracketX} ${midY + 5}
                     L ${bracketX} ${maxY}
                     L ${bracketX - 10} ${maxY}`;
                break;

            case 'brace':
                // Curly brace shape
                d = `M ${bracketX - 10} ${minY}
                     Q ${bracketX} ${minY}, ${bracketX} ${minY + 10}
                     L ${bracketX} ${midY - 15}
                     Q ${bracketX} ${midY - 5}, ${bracketX + 10} ${midY}
                     Q ${bracketX} ${midY + 5}, ${bracketX} ${midY + 15}
                     L ${bracketX} ${maxY - 10}
                     Q ${bracketX} ${maxY}, ${bracketX - 10} ${maxY}`;
                break;

            case 'straight':
                // Simple straight vertical line
                d = `M ${bracketX} ${minY}
                     L ${bracketX} ${maxY}
                     M ${bracketX} ${midY}
                     L ${bracketX + 10} ${midY}`;
                break;

            case 'curved':
                // Smooth curved bracket
                d = `M ${bracketX - 10} ${minY}
                     C ${bracketX + 5} ${minY}, ${bracketX + 5} ${midY - 20}, ${bracketX + 10} ${midY}
                     C ${bracketX + 5} ${midY + 20}, ${bracketX + 5} ${maxY}, ${bracketX - 10} ${maxY}`;
                break;

            case 'square':
                // Square bracket [ shape
                d = `M ${bracketX} ${minY} L ${bracketX - 10} ${minY} L ${bracketX - 10} ${maxY} L ${bracketX} ${maxY}
                     M ${bracketX - 10} ${midY} L ${bracketX + 10} ${midY}`;
                break;

            case 'angle':
                // Angle bracket < shape
                d = `M ${bracketX - 5} ${minY} L ${bracketX + 10} ${midY} L ${bracketX - 5} ${maxY}`;
                break;

            case 'round':
                // Round arc bracket
                const radius = (maxY - minY) / 2;
                d = `M ${bracketX - 5} ${minY} A ${radius * 0.6} ${radius} 0 0 1 ${bracketX - 5} ${maxY}
                     M ${bracketX - 5 + radius * 0.3} ${midY} L ${bracketX + 10} ${midY}`;
                break;

            default:
                d = `M ${bracketX - 10} ${minY}
                     L ${bracketX} ${minY}
                     L ${bracketX} ${midY - 5}
                     L ${bracketX + 10} ${midY}
                     L ${bracketX} ${midY + 5}
                     L ${bracketX} ${maxY}
                     L ${bracketX - 10} ${maxY}`;
        }

        path.setAttribute('d', d);
        path.setAttribute('stroke', lineColor);
        path.setAttribute('stroke-width', lineWidth);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        path.classList.add('summary-path');

        group.appendChild(path);

        // Draw line to summary topic
        let connectionLine = null;
        if (summaryElement) {
            const summaryRect = summaryElement.getBoundingClientRect();
            const sx = summaryRect.left - containerRect.left;
            const sy = summaryRect.top - containerRect.top + summaryRect.height / 2;

            connectionLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            connectionLine.setAttribute('x1', bracketX + 10);
            connectionLine.setAttribute('y1', midY);
            connectionLine.setAttribute('x2', sx);
            connectionLine.setAttribute('y2', sy);
            connectionLine.setAttribute('stroke', lineColor);
            connectionLine.setAttribute('stroke-width', lineWidth);
            connectionLine.setAttribute('stroke-linecap', 'round');
            connectionLine.classList.add('summary-connection');
            group.appendChild(connectionLine);
        }

        this.svg.appendChild(group);

        // Add event listeners
        const self = this;
        group.addEventListener('click', function(e) {
            e.stopPropagation();
            self.selectSummary(summaryId);
            if (self.onSummaryClick) {
                self.onSummaryClick(summaryId, e);
            }
        });

        group.addEventListener('contextmenu', function(e) {
            e.preventDefault();
            e.stopPropagation();
            self.selectSummary(summaryId);
            if (self.onSummaryContextMenu) {
                self.onSummaryContextMenu(summaryId, e);
            }
        });

        const summaryData = {
            id: summaryId,
            group: group,
            path: path,
            connectionLine: connectionLine,
            topicElements: topicElements,
            summaryElement: summaryElement,
            options: options
        };

        this.summaries.push(summaryData);
        return summaryId;
    }

    // Update summary positions when layout changes
    updatePositions() {
        if (!this.summaries || this.summaries.length === 0) return;

        const containerRect = this.container.getBoundingClientRect();

        for (let summary of this.summaries) {
            if (!summary.topicElements || summary.topicElements.length === 0) continue;

            let minY = Infinity, maxY = -Infinity;
            let rightX = -Infinity;

            for (let element of summary.topicElements) {
                const rect = element.getBoundingClientRect();
                const x = rect.left - containerRect.left + rect.width;
                const y = rect.top - containerRect.top;
                minY = Math.min(minY, y);
                maxY = Math.max(maxY, y + rect.height);
                rightX = Math.max(rightX, x);
            }

            const bracketX = rightX + 20;
            const midY = minY + (maxY - minY) / 2;
            const lineType = summary.options.lineType || 'bracket';

            let d = '';
            switch (lineType) {
                case 'bracket':
                    d = `M ${bracketX - 10} ${minY}
                         L ${bracketX} ${minY}
                         L ${bracketX} ${midY - 5}
                         L ${bracketX + 10} ${midY}
                         L ${bracketX} ${midY + 5}
                         L ${bracketX} ${maxY}
                         L ${bracketX - 10} ${maxY}`;
                    break;
                case 'brace':
                    d = `M ${bracketX - 10} ${minY}
                         Q ${bracketX} ${minY}, ${bracketX} ${minY + 10}
                         L ${bracketX} ${midY - 15}
                         Q ${bracketX} ${midY - 5}, ${bracketX + 10} ${midY}
                         Q ${bracketX} ${midY + 5}, ${bracketX} ${midY + 15}
                         L ${bracketX} ${maxY - 10}
                         Q ${bracketX} ${maxY}, ${bracketX - 10} ${maxY}`;
                    break;
                case 'straight':
                    d = `M ${bracketX} ${minY}
                         L ${bracketX} ${maxY}
                         M ${bracketX} ${midY}
                         L ${bracketX + 10} ${midY}`;
                    break;
                case 'curved':
                    d = `M ${bracketX - 10} ${minY}
                         C ${bracketX + 5} ${minY}, ${bracketX + 5} ${midY - 20}, ${bracketX + 10} ${midY}
                         C ${bracketX + 5} ${midY + 20}, ${bracketX + 5} ${maxY}, ${bracketX - 10} ${maxY}`;
                    break;
                case 'square':
                    d = `M ${bracketX} ${minY} L ${bracketX - 10} ${minY} L ${bracketX - 10} ${maxY} L ${bracketX} ${maxY}
                         M ${bracketX - 10} ${midY} L ${bracketX + 10} ${midY}`;
                    break;
                case 'angle':
                    d = `M ${bracketX - 5} ${minY} L ${bracketX + 10} ${midY} L ${bracketX - 5} ${maxY}`;
                    break;
                case 'round': {
                    const radius = (maxY - minY) / 2;
                    d = `M ${bracketX - 5} ${minY} A ${radius * 0.6} ${radius} 0 0 1 ${bracketX - 5} ${maxY}
                         M ${bracketX - 5 + radius * 0.3} ${midY} L ${bracketX + 10} ${midY}`;
                    break;
                }
            }

            summary.path.setAttribute('d', d);

            // Update connection line if exists
            if (summary.connectionLine && summary.summaryElement) {
                const summaryRect = summary.summaryElement.getBoundingClientRect();
                const sx = summaryRect.left - containerRect.left;
                const sy = summaryRect.top - containerRect.top + summaryRect.height / 2;

                summary.connectionLine.setAttribute('x1', bracketX + 10);
                summary.connectionLine.setAttribute('y1', midY);
                summary.connectionLine.setAttribute('x2', sx);
                summary.connectionLine.setAttribute('y2', sy);
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

        const badgeContainer = document.createElement('div');
        badgeContainer.className = 'xmind-markers';
        badgeContainer.style.position = 'absolute';
        badgeContainer.style.top = '-10px';
        badgeContainer.style.right = '-10px';
        badgeContainer.style.display = 'flex';
        badgeContainer.style.gap = '2px';

        for (let code of markerCodes) {
            const marker = availableMarkers.find(m => m.code === code);
            if (marker) {
                const badge = document.createElement('span');
                badge.className = 'xmind-marker-badge';
                badge.style.width = '18px';
                badge.style.height = '18px';
                badge.style.borderRadius = '50%';
                badge.style.background = '#fff';
                badge.style.display = 'flex';
                badge.style.alignItems = 'center';
                badge.style.justifyContent = 'center';
                badge.style.fontSize = '10px';
                badge.style.boxShadow = '0 1px 3px rgba(0,0,0,0.3)';
                badge.innerHTML = `<i class="${marker.icon}" style="color:${marker.color}"></i>`;
                badge.title = marker.name;
                badgeContainer.appendChild(badge);
            }
        }

        nodeElement.style.position = 'relative';
        nodeElement.appendChild(badgeContainer);
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
        const containerRect = this.container.getBoundingClientRect();
        const parentRect = parentElement.getBoundingClientRect();

        const calloutDiv = document.createElement('div');
        calloutDiv.className = 'xmind-callout';
        calloutDiv.style.position = 'absolute';
        calloutDiv.style.left = (parentRect.left - containerRect.left + (options.offsetX || 50)) + 'px';
        calloutDiv.style.top = (parentRect.top - containerRect.top + (options.offsetY || -30)) + 'px';
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

