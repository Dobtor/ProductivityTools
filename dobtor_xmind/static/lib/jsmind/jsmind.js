/**
 * XMind Renderer — Custom mind map engine matching XMind 2 visual design
 * Replaces jsMind with pixel-perfect XMind 2 rendering
 * Exposed as window.OdooXMind for compatibility
 */
(function () {
    'use strict';

    // =========================================================================
    // XMind 2 Default Styles (from defaultStyles.xml)
    // =========================================================================
    // Theme → root fill color mapping (XMind 2 theme-properties)
    const THEME_COLORS = {
        'default': '#97cbff', 'primary': '#428bca', 'warning': '#f0ad4e',
        'danger': '#d9534f', 'success': '#5cb85c', 'info': '#5bc0de',
        'greensea': '#16a085', 'nephrite': '#27ae60', 'belizehole': '#2980b9',
        'wisteria': '#8e44ad', 'asphalt': '#34495e', 'orange': '#f39c12',
        'pumpkin': '#d35400', 'pomegranate': '#c0392b', 'clouds': '#ecf0f1',
        'asbestos': '#7f8c8d',
    };

    // XMind 2 Professional Theme — exact values from themes.xml
    const STYLES = {
        central: {
            fontSize: 18, fontWeight: 'bold', color: '#376092', fill: '#DCE6F2',
            shape: 'roundedRect', corner: 8, textAlign: 'center',
            paddingH: 22, paddingV: 14,
            borderColor: '#558ED5', borderWidth: 5,
            lineClass: 'curve', lineColor: '#558ED5', lineWidth: 1, lineCorner: 8,
            spacingMajor: 20, spacingMinor: 10,
            fontFamily: "'Open Sans', 'Microsoft YaHei', sans-serif",
        },
        main: {
            fontSize: 13, fontWeight: 'normal', color: '#17375E', fill: '#DCE6F2',
            shape: 'roundedRect', corner: 5, textAlign: 'left',
            paddingH: 6, paddingV: 6, border: '#558ED5', borderColor: '#558ED5', borderWidth: 2,
            lineClass: 'curve', lineColor: '#558ED5', lineWidth: 1, lineCorner: 4,
            spacingMajor: 8, spacingMinor: 1,
            fontFamily: "'Open Sans', 'Microsoft YaHei', sans-serif",
        },
        sub: {
            fontSize: 10, fontWeight: 'normal', color: '#000000', fill: 'transparent',
            shape: 'underline', corner: 3, textAlign: 'left',
            paddingH: 4, paddingV: 1, border: '#558ED5', borderColor: '#558ED5', borderWidth: 3,
            lineClass: 'curve', lineColor: '#558ED5', lineWidth: 1, lineCorner: 4,
            spacingMajor: 8, spacingMinor: 1,
            fontFamily: "'Open Sans', 'Microsoft YaHei', sans-serif",
        },
        deep: {
            fontSize: 10, fontWeight: 'normal', color: '#000000', fill: 'transparent',
            shape: 'underline', corner: 3, textAlign: 'left',
            paddingH: 4, paddingV: 1, border: '#558ED5', borderColor: '#558ED5', borderWidth: 3,
            lineClass: 'curve', lineColor: '#558ED5', lineWidth: 1, lineCorner: 4,
            spacingMajor: 8, spacingMinor: 1,
            fontFamily: "'Open Sans', 'Microsoft YaHei', sans-serif",
        },
        // Special topic styles (XMind 2 defaultStyles.xml)
        callout: {
            fontSize: 13, fontWeight: 'normal', color: '#000000', fill: '#ffe866',
            shape: 'balloon', corner: 5, textAlign: 'left',
            paddingH: 6, paddingV: 6, border: '#b8860b',
            fontFamily: 'Verdana, sans-serif',
        },
        summaryTopic: {
            fontSize: 10, fontWeight: 'normal', color: '#FFFFFF', fill: '#77933C',
            shape: 'roundedRect', corner: 5, textAlign: 'left',
            paddingH: 4, paddingV: 4, border: 'none', borderWidth: 0,
            fontFamily: 'Georgia, serif', fontStyle: 'italic',
        },
        floating: {
            fontSize: 13, fontWeight: 'bold', color: '#FFFFFF', fill: '#558ED5',
            shape: 'roundedRect', corner: 8, textAlign: 'left',
            paddingH: 6, paddingV: 6, border: 'none', borderWidth: 0,
            fontFamily: "'Open Sans', 'Microsoft YaHei', sans-serif",
        },
        map: { fill: '#FFFFFF', opacity: 1.0 },
        relationship: {
            lineColor: '#77933C', lineWidth: 3, linePattern: 'dash',
            fontSize: 10, fontColor: '#595959', fontFamily: 'Georgia, serif',
            fontStyle: 'italic', textAlign: 'center',
        },
        boundary: {
            lineColor: '#77933C', lineWidth: 3, linePattern: 'dot',
            fill: '#C3D69B', opacity: 0.2,
            fontSize: 10, fontColor: '#FFFFFF', fontFamily: 'Georgia, serif',
            fontStyle: 'italic', textAlign: 'left',
        },
        summary: { lineColor: '#C3D69B', lineWidth: 5, linePattern: 'solid', lineCorner: 5 },
    };

    // XMind 2 rainbow branch palette — each root child gets a unique color
    const BRANCH_COLORS = [
        '#4A90D9', // blue
        '#F5A623', // orange
        '#7B68EE', // purple
        '#50C878', // green
        '#E74C3C', // red
        '#1ABC9C', // teal
        '#F39C12', // amber
        '#9B59B6', // violet
        '#3498DB', // light blue
        '#E67E22', // dark orange
        '#2ECC71', // emerald
        '#E84393', // pink
    ];

    function getStyleForDepth(depth) {
        if (depth === 0) return STYLES.central;
        if (depth === 1) return STYLES.main;
        if (depth === 2) return STYLES.sub;
        return STYLES.deep;
    }

    /** Check whether a node should be excluded from layout / branch-line drawing.
     *  Summary nodes and floating topic nodes are both managed by the editor layer. */
    function _isLayoutExcluded(node) {
        return node.data && (node.data._isSummaryNode || node.data._isFloatingTopic);
    }

    // =========================================================================
    // Data Model
    // =========================================================================
    class MindNode {
        constructor(id, topic, data, parent) {
            this.id = id;
            this.topic = topic || '';
            this.data = data || {};
            this.parent = parent;
            this.children = [];
            this.expanded = true;
            this.isroot = !parent;
            this.direction = 1; // 1=right, -1=left, 2=down
            // Layout
            this._x = 0;
            this._y = 0;
            this._w = 0;
            this._h = 0;
            this._depth = parent ? parent._depth + 1 : 0;
            this._branchColor = null; // Rainbow branch color (inherited from level-1 ancestor)
            // View
            this._el = null;
            this._expander = null;
        }
    }

    class MindData {
        constructor() {
            this.root = null;
            this.nodes = {};
        }

        get_node(id) {
            return this.nodes[id] || null;
        }

        add_node(parent, id, topic, data) {
            const node = new MindNode(id, topic, data, parent);
            if (parent) {
                node._depth = parent._depth + 1;
                parent.children.push(node);
            }
            this.nodes[id] = node;
            return node;
        }

        remove_node(id) {
            const node = this.nodes[id];
            if (!node) return;
            // Remove from parent
            if (node.parent) {
                const idx = node.parent.children.indexOf(node);
                if (idx > -1) node.parent.children.splice(idx, 1);
            }
            // Remove descendants
            const removeDesc = (n) => {
                for (const c of n.children) {
                    removeDesc(c);
                    delete this.nodes[c.id];
                }
            };
            removeDesc(node);
            delete this.nodes[id];
        }
    }

    // =========================================================================
    // Data Provider — Parse jsMind node_tree format
    // =========================================================================
    function parseMindData(mindData) {
        const md = new MindData();
        if (!mindData || !mindData.data) return md;

        const parseNode = (json, parent) => {
            const node = new MindNode(json.id, json.topic, json.data || {}, parent);
            node.expanded = json.expanded !== false;
            node._depth = parent ? parent._depth + 1 : 0;
            md.nodes[node.id] = node;

            if (!parent) {
                node.isroot = true;
                md.root = node;
            } else {
                parent.children.push(node);
            }

            const children = json.children || [];
            for (const child of children) {
                parseNode(child, node);
            }
            return node;
        };

        parseNode(mindData.data, null);
        return md;
    }

    function exportMindData(md) {
        if (!md || !md.root) return null;

        const exportNode = (node) => {
            const obj = {
                id: node.id,
                topic: node.topic,
                expanded: node.expanded,
                data: node.data || {},
                children: node.children.map(c => exportNode(c)),
            };
            return obj;
        };

        return {
            meta: { name: md.root.topic, author: '', version: '1.0' },
            format: 'node_tree',
            data: exportNode(md.root),
        };
    }

    // =========================================================================
    // Layout Engine
    // =========================================================================
    class LayoutEngine {
        constructor(hgap, vgap) {
            this.hgap = hgap || 30; // horizontal gap between parent edge and child edge
            this.vgap = vgap || 15; // vertical gap between siblings
        }

        layout(root, mode) {
            if (!root) return;
            this._currentMode = mode;  // 記錄當前 layout mode 供子節點 fallback
            this._measureAll(root);

            if (mode === 'org_chart_down') {
                this._layoutVertical(root);
            } else if (mode === 'org_chart_up') {
                this._layoutVerticalUp(root);
            } else if (mode === 'logic_right') {
                this._layoutSingleSide(root, 1);
            } else if (mode === 'logic_left') {
                this._layoutSingleSide(root, -1);
            } else if (mode === 'tree_right') {
                this._layoutTreeRoot(root, 1);
            } else if (mode === 'tree_left') {
                this._layoutTreeRoot(root, -1);
            } else if (mode === 'fishbone_right') {
                this._layoutFishbone(root, 1);
            } else if (mode === 'fishbone_left') {
                this._layoutFishbone(root, -1);
            } else if (mode === 'matrix_horizontal') {
                this._layoutMatrixH(root);
            } else if (mode === 'matrix_vertical' || mode === 'matrix') {
                // 'matrix' kept as a backward-compatible alias for the vertical table
                this._layoutMatrixV(root);
            } else if (mode === 'timeline_horizontal') {
                this._layoutTimelineH(root);
            } else if (mode === 'timeline_vertical') {
                this._layoutTimelineV(root);
            } else {
                // Default: map (balanced left/right)
                this._layoutBalanced(root);
            }
        }

        _measureAll(node) {
            const s = getStyleForDepth(node._depth);
            const charW = s.fontSize * 0.55;
            const estW = Math.max(node.topic.length * charW + s.paddingH * 2, 50);
            const estH = s.fontSize * 1.4 + s.paddingV * 2;

            if (node._el) {
                // Use offsetWidth/offsetHeight — NOT affected by CSS transform (zoom/pan)
                // getBoundingClientRect() returns scaled values which cause line offset at zoom ≠ 1
                const ow = node._el.offsetWidth;
                const oh = node._el.offsetHeight;
                node._w = (ow > 1) ? ow : estW;
                node._h = (oh > 1) ? oh : estH;
            } else {
                node._w = estW;
                node._h = estH;
            }
            if (node.expanded) {
                for (const c of node.children) this._measureAll(c);
            }
        }

        _subtreeHeight(node) {
            if (_isLayoutExcluded(node)) return 0; // summary nodes excluded from layout
            const layoutChildren = node.children.filter(c => !(_isLayoutExcluded(c)));
            if (!node.expanded || layoutChildren.length === 0) return node._h;
            let total = 0;
            for (const c of layoutChildren) {
                total += this._subtreeHeight(c);
            }
            total += this.vgap * (layoutChildren.length - 1);
            return Math.max(node._h, total);
        }

        /**
         * Calculate the total width needed for a subtree in vertical layout (org_chart_up/down).
         * At each level, children spread horizontally. The subtree width is the MAX of:
         *   - the node's own width
         *   - the sum of ALL children subtree widths + gaps
         * This ensures that deeply nested wide subtrees correctly reserve space.
         */
        _subtreeWidthVertical(node) {
            if (_isLayoutExcluded(node)) return 0;
            const layoutChildren = node.children.filter(c => !(_isLayoutExcluded(c)));
            if (!node.expanded || layoutChildren.length === 0) return node._w;
            const ps = getStyleForDepth(node._depth);
            // Org chart: use spacingMinor as horizontal gap between siblings
            const hgap = ps.spacingMinor || this.vgap;
            let total = 0;
            for (const c of layoutChildren) {
                // Each child's subtree width includes all its descendants
                total += this._subtreeWidthVertical(c);
            }
            total += hgap * (layoutChildren.length - 1);
            // Also add minimum padding to prevent tight packing
            const minPadding = 10;
            return Math.max(node._w + minPadding, total);
        }

        /**
         * Horizontal extent of a subtree laid out as a logic/tree branch
         * (children to one side, stacked vertically). Used by the secondary
         * layouts (Fishbone / Timeline / Matrix) to reserve the real
         * width a child's whole subtree occupies, instead of just the node box.
         * Using this for spacing is monotonic: it can only spread nodes apart,
         * never increase overlap.
         */
        _subtreeWidthHorizontal(node) {
            if (_isLayoutExcluded(node)) return 0;
            const layoutChildren = node.children.filter(c => !(_isLayoutExcluded(c)));
            if (!node.expanded || layoutChildren.length === 0) return node._w;
            const ps = getStyleForDepth(node._depth);
            const hgap = ps.spacingMajor || this.hgap;
            let maxChild = 0;
            for (const c of layoutChildren) {
                maxChild = Math.max(maxChild, this._subtreeWidthHorizontal(c));
            }
            return node._w + hgap + maxChild;
        }

        /**
         * Calculate the total height of a subtree in vertical layout (org_chart_up/down).
         * node height + vgap + max child subtree height (recursive).
         */
        _subtreeHeightVertical(node) {
            if (_isLayoutExcluded(node)) return 0;
            const layoutChildren = node.children.filter(c => !(_isLayoutExcluded(c)));
            if (!node.expanded || layoutChildren.length === 0) return node._h;
            const ps = getStyleForDepth(node._depth);
            // Org chart: use spacingMajor as vertical gap
            const vgap = ps.spacingMajor || this.hgap;
            let maxChildH = 0;
            for (const c of layoutChildren) {
                maxChildH = Math.max(maxChildH, this._subtreeHeightVertical(c));
            }
            return node._h + vgap + maxChildH;
        }

        _layoutBalanced(root) {
            root._x = 0;
            root._y = 0;

            // XMind 2 unbalanced layout: right-number controls how many go right
            // Only use _rightNumber when the topic's original structure is map-related
            // (ignore for org_chart, tree, fishbone etc. where right-number is irrelevant)
            const dataRN = root.data && root.data._rightNumber;
            const sc = (root.data && root.data.structure_class) || '';
            const isMapStructure = !sc || sc.startsWith('org.xmind.ui.map');
            let rightNum;
            if (isMapStructure && dataRN != null) {
                rightNum = dataRN === -1 ? root.children.length : dataRN;
            } else {
                rightNum = Math.ceil(root.children.length / 2);
            }

            // Assign rainbow branch colors + split by right-number
            const right = [], left = [];
            for (let i = 0; i < root.children.length; i++) {
                const child = root.children[i];
                child._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(child);

                if (i < rightNum) {
                    child.direction = 1;
                    right.push(child);
                } else {
                    child.direction = -1;
                    left.push(child);
                }
            }

            this._layoutBranch(root, right, 1);
            this._layoutBranch(root, left, -1);
        }

        // Propagate branch color to all descendants
        _propagateBranchColor(node) {
            for (const c of node.children) {
                c._branchColor = node._branchColor;
                this._propagateBranchColor(c);
            }
        }

        _layoutSingleSide(root, dir) {
            root._x = 0;
            root._y = 0;
            for (let i = 0; i < root.children.length; i++) {
                root.children[i].direction = dir;
                root.children[i]._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(root.children[i]);
            }
            this._layoutBranch(root, root.children, dir);
        }

        _layoutVertical(root) {
            root._x = 0;
            root._y = 0;
            for (let i = 0; i < root.children.length; i++) {
                root.children[i].direction = 2;
                root.children[i]._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(root.children[i]);
            }
            this._layoutVerticalChildren(root);
        }

        // Org Chart Up — children extend upward from root
        _layoutVerticalUp(root) {
            root._x = 0;
            root._y = 0;
            for (let i = 0; i < root.children.length; i++) {
                root.children[i].direction = 2; // uses direction 2 but positioned above
                root.children[i]._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(root.children[i]);
            }
            this._layoutVerticalChildrenUp(root);
        }

        _layoutVerticalChildrenUp(parent) {
            const children = parent.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;
            const ps = getStyleForDepth(parent._depth);
            // Org chart: vertical gap needs enough space for expander + visible curve arc
            const hgap = ps.spacingMinor || this.vgap;
            const vgap = ps.spacingMajor || this.hgap;

            // Extra gap for expander button (above node for org_chart_up)
            const expanderGap = (!parent.isroot && children.length > 0) ? 14 : 0;

            // Use subtree width to prevent horizontal overlapping
            const childWidths = children.map(c => this._subtreeWidthVertical(c));
            const totalW = childWidths.reduce((sum, w) => sum + w, 0) + hgap * (children.length - 1);
            let curX = parent._x - totalW / 2;

            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                const sw = childWidths[i];
                child._x = curX + sw / 2;
                // Children above parent, with gap for expander
                child._y = parent._y - parent._h / 2 - expanderGap - vgap - child._h / 2;
                child.direction = 2;
                curX += sw + hgap;

                if (child.expanded && child.children.length > 0) {
                    this._layoutChildrenWithStructure(child, 2);
                }
            }
        }

        // Fishbone layout — children alternate above/below a horizontal spine
        // direction = 7 (fishbone child) for 45° diagonal connection lines
        _layoutFishbone(root, dir) {
            root._x = 0;
            root._y = 0;

            const spineGap = 40; // horizontal gap along the spine
            // Ribs alternate above/below the spine, so each side gets its own
            // cursor. Advancing only the SAME side by the rib's subtree width
            // keeps same-side ribs from overlapping while letting opposite-side
            // ribs interleave (without over-stretching the whole spine).
            let dAbove = root._w / 2 + spineGap;
            let dDown = root._w / 2 + spineGap;

            for (let i = 0; i < root.children.length; i++) {
                const child = root.children[i];
                child._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(child);
                child.direction = 7; // fishbone child — uses diagonal line

                // Alternate above (even) and below (odd)
                const above = (i % 2 === 0);
                const subH = this._subtreeHeight(child);
                const ribW = this._subtreeWidthHorizontal(child);
                const d0 = above ? dAbove : dDown;
                child._x = dir * (d0 + child._w / 2);
                child._y = above ? -(subH / 2 + 20) : (subH / 2 + 20);
                child._fishboneAbove = above;
                child._fishboneDir = dir;

                if (above) {
                    dAbove = d0 + ribW + spineGap;
                } else {
                    dDown = d0 + ribW + spineGap;
                }

                // Layout child's own children as vertical branch extending away from spine
                if (child.expanded && child.children.length > 0) {
                    const vDir = above ? -1 : 1; // above: extend upward, below: extend downward
                    const hGap = 20;
                    const vGap = 5;
                    let gcY = child._y + (child._h / 2 + 10) * vDir;
                    for (const gc of child.children) {
                        if (_isLayoutExcluded(gc)) continue;
                        gc._x = child._x + (gc._w / 2 + hGap) * dir;
                        gc._y = gcY + (gc._h / 2) * vDir;
                        gc.direction = dir; // horizontal direction for further children
                        gcY += (gc._h + vGap) * vDir;
                        if (gc.expanded && gc.children.length > 0) {
                            this._layoutChildrenWithStructure(gc, dir);
                        }
                    }
                }
            }
        }

        // 橫表格圖 (Matrix Horizontal): top-level topics form a horizontal
        // header row; each header's whole subtree extends DOWNWARD as a column
        // (org-chart-down). Columns are spaced by their vertical subtree width.
        _layoutMatrixH(root) {
            root._x = 0;
            root._y = 0;
            const children = root.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;

            const gapX = 40;
            const widths = children.map(c => this._subtreeWidthVertical(c));
            const totalW = widths.reduce((s, w) => s + w, 0) + gapX * (children.length - 1);
            let curX = root._x - totalW / 2;
            const headerY = root._y + root._h / 2 + 50;

            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                child._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(child);
                child.direction = 2; // root → header connector goes down
                child._x = curX + widths[i] / 2;
                child._y = headerY + child._h / 2;
                curX += widths[i] + gapX;
                if (child.expanded && child.children.length > 0) {
                    this._layoutVerticalChildren(child);
                }
            }
        }

        // 直表格圖 (Matrix Vertical): top-level topics form a vertical header
        // column; each header's whole subtree extends RIGHTWARD as a row
        // (logic-right). Rows are spaced by their subtree height.
        _layoutMatrixV(root) {
            root._x = 0;
            root._y = 0;
            const children = root.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;

            const gapY = 24;
            const heights = children.map(c => this._subtreeHeight(c));
            const totalH = heights.reduce((s, h) => s + h, 0) + gapY * (children.length - 1);
            let curY = root._y - totalH / 2;
            const headerX = root._x + root._w / 2 + 60;

            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                child._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(child);
                child.direction = 1; // root → header connector goes right
                child._y = curY + heights[i] / 2;
                child._x = headerX + child._w / 2;
                curY += heights[i] + gapY;
                if (child.expanded && child.children.length > 0) {
                    this._layoutBranch(child, child.children, 1);
                }
            }
        }

        _layoutBranch(parent, children, dir) {
            // Filter out summary nodes — they are positioned by SummaryRenderer
            const layoutChildren = children.filter(c => !(_isLayoutExcluded(c)));
            if (layoutChildren.length === 0) return;

            // Per-depth spacing from STYLES (XMind 2: spacingMajor/spacingMinor)
            const ps = getStyleForDepth(parent._depth);
            const hgap = ps.spacingMajor || this.hgap;
            const vgap = ps.spacingMinor || this.vgap;

            const totalH = layoutChildren.reduce((sum, c) => sum + this._subtreeHeight(c), 0)
                + vgap * (layoutChildren.length - 1);

            let curY = parent._y - totalH / 2;

            // Extra gap for expander button (11px wide + 3px offset from node edge)
            const expanderGap = (!parent.isroot && layoutChildren.length > 0) ? 14 : 0;

            for (const child of layoutChildren) {
                const subH = this._subtreeHeight(child);
                child._y = curY + subH / 2;
                child._x = parent._x + (parent._w / 2 + expanderGap + hgap + child._w / 2) * dir;
                child.direction = dir;
                curY += subH + vgap;

                if (child.expanded && child.children.length > 0) {
                    this._layoutChildrenWithStructure(child, dir);
                }
            }
        }

        /**
         * Layout children of a node, respecting per-node childStructure override.
         * If node.data.childStructure is set, use that layout mode for its children.
         */
        // Layout modes that children should inherit from parent/sheet
        static _INHERITABLE_LAYOUTS = new Set([
            'org_chart_down', 'org_chart_up', 'tree_right', 'tree_left',
            'fishbone_right', 'fishbone_left', 'timeline_horizontal', 'timeline_vertical',
        ]);

        _layoutChildrenWithStructure(node, defaultDir) {
            const nodeStructure = node.data && node.data.childStructure;
            // 只有可繼承的佈局模式才 fallback 到 sheet layout mode
            const childStructure = nodeStructure
                || (LayoutEngine._INHERITABLE_LAYOUTS.has(this._currentMode) ? this._currentMode : '');
            if (!childStructure) {
                // Default: continue with standard branch layout (map, logic_right, logic_left)
                for (const gc of node.children) gc.direction = defaultDir;
                this._layoutBranch(node, node.children, defaultDir);
                return;
            }

            // Per-node child structure override
            switch (childStructure) {
                case 'logic_right':
                    for (const gc of node.children) gc.direction = 1;
                    this._layoutBranch(node, node.children, 1);
                    break;
                case 'logic_left':
                    for (const gc of node.children) gc.direction = -1;
                    this._layoutBranch(node, node.children, -1);
                    break;
                case 'tree_right':
                    this._layoutTreeChildren(node, 1);
                    break;
                case 'tree_left':
                    this._layoutTreeChildren(node, -1);
                    break;
                case 'org_chart_down':
                    this._layoutVerticalChildren(node);
                    break;
                case 'org_chart_up':
                    this._layoutVerticalUpChildren(node);
                    break;
                case 'map':
                    this._layoutBalancedChildren(node);
                    break;
                case 'fishbone_right':
                    this._layoutFishboneChildren(node, 1);
                    break;
                case 'fishbone_left':
                    this._layoutFishboneChildren(node, -1);
                    break;
                case 'timeline_horizontal':
                    this._layoutTimelineHChildren(node);
                    break;
                case 'timeline_vertical':
                    this._layoutTimelineVChildren(node);
                    break;
                default:
                    for (const gc of node.children) gc.direction = defaultDir;
                    this._layoutBranch(node, node.children, defaultDir);
                    break;
            }
        }

        _layoutVerticalChildren(parent) {
            const children = parent.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;
            const ps = getStyleForDepth(parent._depth);
            // Org chart: vertical gap needs enough space for expander + visible curve arc
            const hgap = ps.spacingMinor || this.vgap;
            const vgap = ps.spacingMajor || this.hgap;

            // Extra gap for expander (dir=2: below node)
            const expanderGap = (!parent.isroot && children.length > 0) ? 14 : 0;

            // Use subtree width to prevent overlapping
            const childWidths = children.map(c => this._subtreeWidthVertical(c));
            const totalW = childWidths.reduce((sum, w) => sum + w, 0)
                + hgap * (children.length - 1);

            let curX = parent._x - totalW / 2;

            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                const sw = childWidths[i];
                child._x = curX + sw / 2;
                child._y = parent._y + parent._h / 2 + expanderGap + vgap + child._h / 2;
                child.direction = 2;
                curX += sw + hgap;

                if (child.expanded && child.children.length > 0) {
                    // Keep descending vertically (down) unless the node overrides
                    // its own child structure — so the whole subtree stays an
                    // org-chart even when the sheet mode isn't org_chart_down.
                    if (child.data && child.data.childStructure) {
                        this._layoutChildrenWithStructure(child, 2);
                    } else {
                        this._layoutVerticalChildren(child);
                    }
                }
            }
        }

        /**
         * Layout children of a node using vertical-up style (children extend upward).
         */
        _layoutVerticalUpChildren(parent) {
            const children = parent.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;
            const ps = getStyleForDepth(parent._depth);
            // Org chart: swap spacing for vertical layout
            const hgap = ps.spacingMinor || this.vgap;
            const vgap = ps.spacingMajor || this.hgap;

            // Extra gap for expander button (above node for org_chart_up)
            const expanderGap = (!parent.isroot && children.length > 0) ? 14 : 0;

            // Use subtree width to prevent overlapping
            const childWidths = children.map(c => this._subtreeWidthVertical(c));
            const totalW = childWidths.reduce((sum, w) => sum + w, 0) + hgap * (children.length - 1);
            let curX = parent._x - totalW / 2;

            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                const sw = childWidths[i];
                child._x = curX + sw / 2;
                child._y = parent._y - parent._h / 2 - expanderGap - vgap - child._h / 2;
                child.direction = 2;
                curX += sw + hgap;
                if (child.expanded && child.children.length > 0) {
                    // Keep descending vertically (up) unless the node overrides.
                    if (child.data && child.data.childStructure) {
                        this._layoutChildrenWithStructure(child, 2);
                    } else {
                        this._layoutVerticalUpChildren(child);
                    }
                }
            }
        }

        /**
         * Layout children of a node using balanced (map) style — split left/right.
         */
        _layoutBalancedChildren(parent) {
            const children = parent.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;
            const half = Math.ceil(children.length / 2);
            const right = children.slice(0, half);
            const left = children.slice(half);
            for (const c of right) c.direction = 1;
            for (const c of left) c.direction = -1;
            this._layoutBranch(parent, right, 1);
            this._layoutBranch(parent, left, -1);
        }

        /**
         * Layout children of a node using fishbone style — alternate above/below.
         */
        _layoutFishboneChildren(parent, dir) {
            const children = parent.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;
            const spineGap = 40;
            let curX = parent._x + dir * (parent._w / 2 + spineGap);
            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                child.direction = dir;
                const above = (i % 2 === 0);
                const subH = this._subtreeHeight(child);
                child._x = curX + (child._w / 2) * dir;
                child._y = parent._y + (above ? -(subH / 2 + 20) : (subH / 2 + 20));
                curX += (child._w + spineGap) * dir;
                if (child.expanded && child.children.length > 0) {
                    this._layoutChildrenWithStructure(child, dir);
                }
            }
        }

        // =================================================================
        // Tree layout — children drop down vertically, then extend in dir
        // XMind Tree: parent → vertical drop → children stacked vertically
        // Connection line: parent bottom → vertical → horizontal → child left
        // =================================================================

        _layoutTreeRoot(root, dir) {
            root._x = 0;
            root._y = 0;
            for (let i = 0; i < root.children.length; i++) {
                root.children[i]._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(root.children[i]);
            }
            this._layoutTreeChildren(root, dir);
        }

        /**
         * Tree layout for children: each child is positioned below the parent,
         * indented from parent's reference point. Children stack vertically.
         * XMind Tree: x = parent.x + majorSpacing, y = parent.bottom + majorSpacing
         * direction = 3 (tree-right) or 4 (tree-left)
         */
        _layoutTreeChildren(parent, dir) {
            const children = parent.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;

            const ps = getStyleForDepth(parent._depth);
            const majorGap = ps.spacingMajor || this.hgap;
            const minorGap = ps.spacingMinor || this.vgap;

            // XMind Tree: children indent from parent's center x, drop below parent's bottom
            const indentX = parent._x + majorGap * dir;
            let curY = parent._y + parent._h / 2 + majorGap;

            for (const child of children) {
                const subH = this._treeSubtreeHeight(child, minorGap, majorGap);
                child._x = indentX + (child._w / 2) * dir;
                child._y = curY + child._h / 2;
                child.direction = dir > 0 ? 3 : 4;
                curY += subH + minorGap;

                if (child.expanded && child.children.length > 0) {
                    this._layoutTreeChildren(child, dir);
                }
            }
        }

        /** Compute total height of a tree subtree (vertical stacking). */
        _treeSubtreeHeight(node, minorGap, majorGap) {
            if (_isLayoutExcluded(node)) return 0;
            const children = node.children.filter(c => !(_isLayoutExcluded(c)));
            if (!node.expanded || children.length === 0) return node._h;
            let childrenH = 0;
            for (const c of children) {
                childrenH += this._treeSubtreeHeight(c, minorGap, majorGap);
            }
            childrenH += minorGap * (children.length - 1);
            return node._h + majorGap + childrenH;
        }

        // =================================================================
        // Timeline Horizontal — XMind style: head topic on left, children
        // along horizontal spine alternating above/below, each child's own
        // children extend vertically (tree-like).
        // direction = 5 (timeline-h) for spine connection lines.
        // =================================================================

        _layoutTimelineH(root) {
            root._x = 0;
            root._y = 0;

            const children = root.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;

            const majorGap = 50;
            const spineY = 0; // spine runs through root's y

            // Track x positions for upper and lower rows independently to avoid overlap
            let xUp = root._w / 2 + majorGap;
            let xDown = root._w / 2 + majorGap;

            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                child._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(child);

                const above = (i % 2 === 0);
                child.direction = 5; // timeline-h marker

                // Pick x: use the further of the two tracks to avoid overlap
                const curX = above
                    ? Math.max(xUp, xDown > xUp ? xDown : xUp)
                    : Math.max(xDown, xUp > xDown ? xUp : xDown);

                child._x = curX + child._w / 2;
                // Reserve the item's full subtree width (descendants extend right).
                const itemRight = child._x - child._w / 2 + this._subtreeWidthHorizontal(child);
                if (above) {
                    child._y = spineY - child._h / 2 - 30;
                    xUp = itemRight + majorGap;
                } else {
                    child._y = spineY + child._h / 2 + 30;
                    xDown = itemRight + majorGap;
                }

                // Children of each timeline item extend vertically (tree-like)
                if (child.expanded && child.children.length > 0) {
                    this._layoutTreeChildren(child, 1);
                }
            }
        }

        _layoutTimelineHChildren(parent) {
            this._layoutTimelineH_inner(parent);
        }

        _layoutTimelineH_inner(parent) {
            const children = parent.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;
            const majorGap = 40;
            let xUp = parent._x + parent._w / 2 + majorGap;
            let xDown = xUp;
            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                const above = (i % 2 === 0);
                child.direction = 5;
                const curX = Math.max(xUp, xDown);
                child._x = curX + child._w / 2;
                if (above) {
                    child._y = parent._y - child._h / 2 - 25;
                    xUp = child._x + child._w / 2 + majorGap;
                } else {
                    child._y = parent._y + child._h / 2 + 25;
                    xDown = child._x + child._w / 2 + majorGap;
                }
                if (child.expanded && child.children.length > 0) {
                    this._layoutTreeChildren(child, 1);
                }
            }
        }

        // =================================================================
        // Timeline Vertical — XMind style: head topic on top, children along
        // vertical spine alternating left/right.
        // direction = 6 (timeline-v) for spine connection lines.
        // =================================================================

        _layoutTimelineV(root) {
            root._x = 0;
            root._y = 0;

            const children = root.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;

            const majorGap = 35;
            const spineX = 0;
            let curY = root._h / 2 + majorGap;

            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                child._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(child);

                const goRight = (i % 2 === 0);
                child.direction = 6; // timeline-v marker

                const offset = child._w / 2 + 50;
                // Reserve the item's full subtree height (descendants stack vertically).
                const itemH = this._subtreeHeight(child);
                child._x = spineX + (goRight ? offset : -offset);
                child._y = curY + itemH / 2;
                curY += itemH + majorGap;

                if (child.expanded && child.children.length > 0) {
                    this._layoutChildrenWithStructure(child, goRight ? 1 : -1);
                }
            }
        }

        _layoutTimelineVChildren(parent) {
            const children = parent.children.filter(c => !(_isLayoutExcluded(c)));
            if (children.length === 0) return;
            const majorGap = 30;
            let curY = parent._y + parent._h / 2 + majorGap;
            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                const goRight = (i % 2 === 0);
                child.direction = 6;
                const offset = child._w / 2 + 40;
                child._x = parent._x + (goRight ? offset : -offset);
                child._y = curY + child._h / 2;
                curY += child._h + majorGap;
                if (child.expanded && child.children.length > 0) {
                    this._layoutChildrenWithStructure(child, goRight ? 1 : -1);
                }
            }
        }
    }

    // =========================================================================
    // View — DOM Nodes + SVG Lines
    // =========================================================================
    class XMindView {
        constructor(container, options) {
            this.container = container;
            this.options = options || {};
            this.mind = null;
            this._tapered = false; // Line tapering mode (XMind 2 tapered branches)
            this.layout = new LayoutEngine(
                this.options.layout?.hspace || 30,
                this.options.layout?.vspace || 15,
            );
            this.selected_node = null;
            this.editing_node = null;
            this._event_listeners = [];

            // Viewport
            this._panX = 0;
            this._panY = 0;
            this._zoom = 1;
            this._isPanning = false;
            this._panStartX = 0;
            this._panStartY = 0;

            // Build DOM
            this._buildDOM();
        }

        _buildDOM() {
            this.container.style.overflow = 'hidden';
            this.container.style.position = 'relative';
            // XMind 2: #f3f4f9 at 60% opacity → blended with white = #f7f8fb
            this.container.style.background = '#f7f8fb';
            this.container.style.cursor = 'grab';

            // World container (pans + zooms)
            this.world = document.createElement('div');
            this.world.className = 'xmind-world';
            this.world.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;transform-origin:0 0;';
            this.container.appendChild(this.world);

            // SVG layer for lines (behind nodes)
            this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            this.svg.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:visible;';
            this.world.appendChild(this.svg);

            // Nodes layer
            this.nodesLayer = document.createElement('div');
            this.nodesLayer.className = 'xmind-nodes';
            this.nodesLayer.style.cssText = 'position:absolute;top:0;left:0;';
            this.world.appendChild(this.nodesLayer);

            // Pan/zoom events
            this.container.addEventListener('mousedown', (e) => this._onPanStart(e));
            document.addEventListener('mousemove', (e) => this._onPanMove(e));
            document.addEventListener('mouseup', () => this._onPanEnd());
            this.container.addEventListener('wheel', (e) => this._onWheel(e), { passive: false });
        }

        _onPanStart(e) {
            // Only start pan with middle mouse button (button=1)
            // Left-click drag on empty canvas is reserved for rectangle selection
            if (e.button !== 1) return;
            if (e.target.closest('.xmind-node') || e.target.closest('.xmind-expander')) return;
            this._isPanning = true;
            this._panStartX = e.clientX - this._panX;
            this._panStartY = e.clientY - this._panY;
            this.container.style.cursor = 'grabbing';
            e.preventDefault();
        }

        _onPanMove(e) {
            if (!this._isPanning) return;
            this._panX = e.clientX - this._panStartX;
            this._panY = e.clientY - this._panStartY;
            this._applyTransform();
        }

        _onPanEnd() {
            if (!this._isPanning) return;
            this._isPanning = false;
            this.container.style.cursor = '';
        }

        _onWheel(e) {
            // macOS trackpad behavior:
            // - Two-finger scroll (no ctrlKey): pan/scroll the canvas
            // - Pinch-to-zoom (ctrlKey=true on macOS): zoom in/out
            if (e.ctrlKey || e.metaKey) {
                // Pinch-to-zoom (macOS sends ctrlKey=true for pinch gestures)
                e.preventDefault();
                const delta = e.deltaY > 0 ? 0.95 : 1.05;
                this._zoom = Math.max(0.3, Math.min(3, this._zoom * delta));
                this._applyTransform();
            } else {
                // Two-finger scroll → pan the canvas
                e.preventDefault();
                this._panX -= e.deltaX;
                this._panY -= e.deltaY;
                this._applyTransform();
            }
        }

        _applyTransform() {
            const cx = this.container.clientWidth / 2;
            const cy = this.container.clientHeight / 2;
            this.world.style.transform = `translate(${this._panX + cx}px, ${this._panY + cy}px) scale(${this._zoom})`;
        }

        getZoom() { return this._zoom; }

        setZoom(z) {
            this._zoom = Math.max(0.3, Math.min(3, z));
            this._applyTransform();
        }

        resetView() {
            this._panX = 0;
            this._panY = 0;
            this._zoom = 1;
            this._applyTransform();
        }

        // === Rendering ===

        show(mind, onReady) {
            // Clear previous render (prevent duplicates)
            this.nodesLayer.innerHTML = '';
            while (this.svg.firstChild) this.svg.removeChild(this.svg.firstChild);
            this.selected_node = null;
            this.editing_node = null;

            this.mind = mind;
            this._createAllNodes(mind.root);
            // First layout pass with estimated sizes
            this.refresh();
            // Second pass after browser renders DOM (accurate sizes)
            requestAnimationFrame(() => {
                this.refresh();
                // DOM is now fully ready — safe to render features
                if (onReady) onReady();
                this._fireEvent(3, {}); // show event
            });
        }

        refresh() {
            if (!this.mind || !this.mind.root) return;
            // Make all nodes visible for accurate measurement
            this._showAllForMeasure(this.mind.root);
            const mode = this.options.layout?.mode || 'map';
            this.layout.layout(this.mind.root, mode);
            // Position nodes (will re-hide collapsed descendants)
            this._positionAllNodes(this.mind.root);
            this._drawAllLines();
            this._applyTransform();
        }

        _createAllNodes(node) {
            if (!node) return;
            this._createNodeElement(node);
            for (const c of node.children) this._createAllNodes(c);
        }

        _createNodeElement(node) {
            const s = getStyleForDepth(node._depth);
            const el = document.createElement('div');
            el.className = `xmind-node xmind-level-${Math.min(node._depth, 3)}`;
            if (node.isroot) el.classList.add('xmind-root');
            el.setAttribute('data-nodeid', node.id);

            // Topic text
            const span = document.createElement('span');
            span.className = 'xmind-topic-text';
            span.textContent = node.topic;
            el.appendChild(span);

            // Apply style — XMind 2 Professional theme
            el.style.fontSize = s.fontSize + 'px';
            el.style.fontWeight = s.fontWeight;
            el.style.color = s.color;
            el.style.textAlign = s.textAlign;
            el.style.padding = `${s.paddingV}px ${s.paddingH}px`;
            el.style.position = 'absolute';
            el.style.whiteSpace = 'nowrap';
            el.style.cursor = 'default';
            el.style.userSelect = 'none';
            el.style.lineHeight = '1.4';
            if (s.fontFamily) el.style.fontFamily = s.fontFamily;
            if (s.fontStyle) el.style.fontStyle = s.fontStyle;

            const branchColor = node._branchColor;
            const bw = s.borderWidth || 1;

            if (s.shape === 'roundedRect') {
                el.style.borderRadius = s.corner + 'px';
                if (node.isroot) {
                    const theme = this.options && this.options.theme;
                    const rootFill = (theme && THEME_COLORS[theme]) || s.fill;
                    const isLight = theme === 'clouds' || theme === 'default' || !theme;
                    el.style.backgroundColor = rootFill;
                    if (!isLight && theme) el.style.color = '#ffffff';
                    el.style.border = `${bw}px solid ${s.borderColor || s.border || '#558ED5'}`;
                    el.style.boxShadow = '0 2px 6px rgba(0,0,0,0.12)';
                } else {
                    el.style.backgroundColor = s.fill;
                    el.style.border = `${bw}px solid ${s.border || s.borderColor || '#558ED5'}`;
                    el.style.boxShadow = '0 1px 3px rgba(0,0,0,0.08)';
                }
            } else if (s.shape === 'underline') {
                el.style.backgroundColor = s.fill !== 'transparent' ? s.fill : 'transparent';
                el.style.border = 'none';
                el.style.borderBottom = `${bw}px solid ${branchColor || s.border || s.lineColor || '#558ED5'}`;
                el.style.borderRadius = '0';
                el.style.boxShadow = 'none';
                if (s.fill && s.fill !== 'transparent') {
                    el.style.borderRadius = '2px 2px 0 0';
                }
            }

            // Custom data styles override defaults
            if (node.data && node.data.style) {
                const ds = node.data.style;
                if (ds.background) el.style.backgroundColor = ds.background;
                if (ds.color) el.style.color = ds.color;
                if (ds['font-size']) el.style.fontSize = ds['font-size'];
                if (ds['font-weight']) el.style.fontWeight = ds['font-weight'];
            }

            // Events
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                this._selectNode(node);
            });
            el.addEventListener('dblclick', (e) => {
                e.stopPropagation();
                this.begin_edit(node);
            });

            this.nodesLayer.appendChild(el);
            node._el = el;

            // Measure — use offsetWidth/Height (unaffected by CSS transform/zoom)
            node._w = el.offsetWidth || 50;
            node._h = el.offsetHeight || 20;

            // Expander
            if (node.children.length > 0 && !node.isroot) {
                this._createExpander(node);
            }
        }

        _createExpander(node) {
            if (node._expander) return;
            const btn = document.createElement('span');
            btn.className = 'xmind-expander';
            const isPlus = !node.expanded;
            btn.textContent = isPlus ? '+' : '−';
            // XMind 2 PlusMinusFigure exact colors
            const fillColor = isPlus ? 'rgb(250,250,250)' : 'rgb(160,196,234)';
            const borderColor = isPlus ? 'rgb(180,200,240)' : 'rgb(120,136,162)';
            const contentColor = isPlus ? 'rgb(150,160,200)' : 'rgb(48,64,96)';
            btn.style.cssText = `
                position:absolute; width:11px; height:11px; line-height:11px;
                text-align:center; font-size:9px; border-radius:50%;
                background:${fillColor}; border:1px solid ${borderColor}; color:${contentColor};
                cursor:pointer; user-select:none; z-index:5;
                font-weight:bold;
            `;
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                node.expanded = !node.expanded;
                const p = !node.expanded; // plus = collapsed
                btn.textContent = p ? '+' : '−';
                btn.style.background = p ? 'rgb(250,250,250)' : 'rgb(160,196,234)';
                btn.style.borderColor = p ? 'rgb(180,200,240)' : 'rgb(120,136,162)';
                btn.style.color = p ? 'rgb(150,160,200)' : 'rgb(48,64,96)';
                this.refresh();
                this._fireEvent(1, { evt: node.expanded ? 'expand' : 'collapse', node: node.id });
            });
            this.nodesLayer.appendChild(btn);
            node._expander = btn;
        }

        _positionAllNodes(node) {
            if (!node) return;
            this._positionNode(node);
            // Summary nodes: positioned by editor (_positionSummaryNode).
            // Only manage expand/collapse visibility here.
            if (node.data && node.data._isSummaryNode) {
                if (!node.expanded) {
                    this._hideDescendants(node);
                }
                return;
            }
            // Floating topics: positioned by editor — layout children as sub-tree
            if (node.data && node.data._isFloatingTopic) {
                this._layoutFloatingSubtree(node);
                return;
            }
            if (node.expanded) {
                for (const c of node.children) this._positionAllNodes(c);
            } else {
                // Hide collapsed descendants
                this._hideDescendants(node);
            }
        }

        _positionNode(node) {
            if (!node._el) return;
            // Summary nodes: positioned by SummaryRenderer
            if (node.data && node.data._isSummaryNode) {
                node._el.style.display = '';
                return;
            }
            // Floating topics: positioned at stored coordinates by the editor
            if (node.data && node.data._isFloatingTopic) {
                node._el.style.display = '';
                // Position will be set by _layoutFloatingSubtree or editor
                return;
            }
            node._el.style.left = (node._x - node._w / 2) + 'px';
            node._el.style.top = (node._y - node._h / 2) + 'px';
            node._el.style.display = '';

            // Position expander (11px circle, XMind 2 style)
            if (node._expander) {
                const dir = node.direction || 1;
                let ex, ey;
                if (dir === 2 || dir === 3 || dir === 4 || dir === 5 || dir === 6 || dir === 7) {
                    // Vertical/tree/timeline: expander below or above the node.
                    // "Up" when this node's own children sit above it (org_chart_up
                    // or Up-Down's upper half), decided by geometry not a global mode.
                    const firstChild = node.children.find(c => !_isLayoutExcluded(c));
                    const isUp = dir === 2 && firstChild && firstChild._y < node._y;
                    ex = node._x - 6;
                    ey = isUp
                        ? node._y - node._h / 2 - 13  // above node for org_chart_up
                        : node._y + node._h / 2 + 2;  // below node for others
                } else if (dir === -1) {
                    ex = node._x - node._w / 2 - 15;
                    ey = node._y - 6;
                } else {
                    ex = node._x + node._w / 2 + 3;
                    ey = node._y - 6;
                }
                node._expander.style.left = ex + 'px';
                node._expander.style.top = ey + 'px';
                node._expander.style.display = node.children.length > 0 ? '' : 'none';
            }
        }

        _hideDescendants(node) {
            for (const c of node.children) {
                if (c._el) c._el.style.display = 'none';
                if (c._expander) c._expander.style.display = 'none';
                this._hideDescendants(c);
            }
        }

        /** Layout a floating topic and its children as an independent sub-tree.
         *  Respects the topic's childStructure (org_chart_down = vertical, default = logic_right). */
        _layoutFloatingSubtree(ftNode) {
            const ftX = (ftNode.data && ftNode.data._ftX) || 0;
            const ftY = (ftNode.data && ftNode.data._ftY) || 0;
            const structure = (ftNode.data && ftNode.data.childStructure) || 'logic_right';
            const isVertical = structure === 'org_chart_down' || structure === 'org_chart_up';
            const extraV = (ftNode.data && ftNode.data._ftExtraVSpace) || 0;
            const hspace = isVertical ? 15 : 30;
            const vspace = (isVertical ? 20 : 8) + extraV;

            // Position the floating topic node itself
            if (ftNode._el) {
                ftNode._el.style.left = ftX + 'px';
                ftNode._el.style.top = ftY + 'px';
                ftNode._el.style.display = '';
            }
            ftNode._x = ftX + (ftNode._w || 80) / 2;
            ftNode._y = ftY + (ftNode._h || 20) / 2;

            if (!ftNode.expanded) {
                this._hideDescendants(ftNode);
                return;
            }

            const self = this;

            // Position expander for a node based on its direction
            const posExpander = (node) => {
                if (!node._expander) return;
                if (node.children.length === 0) { node._expander.style.display = 'none'; return; }
                node._expander.style.display = '';
                const dir = node.direction || 1;
                let ex, ey;
                if (dir === 2) {
                    ex = node._x - 6;
                    ey = node._y + (node._h || 20) / 2 + 2;
                } else if (dir === -1) {
                    ex = node._x - (node._w || 80) / 2 - 15;
                    ey = node._y - 6;
                } else {
                    ex = node._x + (node._w || 80) / 2 + 3;
                    ey = node._y - 6;
                }
                node._expander.style.left = ex + 'px';
                node._expander.style.top = ey + 'px';
            };

            // ---- Measure helpers ----
            // measureSpan: returns the span of a subtree along the SPREAD axis
            //   horizontal layout → spread = vertical (height)
            //   vertical layout   → spread = horizontal (width)
            const measureSpan = (node, vertical) => {
                const layoutKids = node.children.filter(c => !_isLayoutExcluded(c));
                if (!node.expanded || layoutKids.length === 0) {
                    return vertical ? (node._w || 80) : (node._h || 20);
                }
                const gap = vertical ? hspace : vspace;
                let total = 0;
                for (const c of layoutKids) {
                    total += measureSpan(c, vertical) + gap;
                }
                const own = vertical ? (node._w || 80) : (node._h || 20);
                return Math.max(own, total - gap);
            };

            // ---- Position children recursively ----
            const positionKids = (parent, px, py, vertical) => {
                const kids = parent.children.filter(c => !_isLayoutExcluded(c));
                if (kids.length === 0) return;

                const pw = parent._w || 80;
                const ph = parent._h || 20;
                const gap = vertical ? hspace : vspace;

                // Collect spans
                const spans = kids.map(c => measureSpan(c, vertical));
                const totalSpan = spans.reduce((a, b) => a + b, 0) + gap * (spans.length - 1);

                let cursor;
                if (vertical) {
                    // org_chart_down: children below parent, spread horizontally
                    const childY = py + ph + vspace;
                    cursor = px + pw / 2 - totalSpan / 2;
                    for (let i = 0; i < kids.length; i++) {
                        const c = kids[i];
                        c.direction = 2;
                        const cw = c._w || 80;
                        const cx = cursor + spans[i] / 2 - cw / 2;
                        if (c._el) {
                            c._el.style.left = cx + 'px';
                            c._el.style.top = childY + 'px';
                            c._el.style.display = '';
                            c._x = cx + cw / 2;
                            c._y = childY + (c._h || 20) / 2;
                        }
                        posExpander(c);
                        if (c.expanded && c.children.length > 0) {
                            positionKids(c, cx, childY, vertical);
                        } else if (!c.expanded) {
                            self._hideDescendants(c);
                        }
                        cursor += spans[i] + gap;
                    }
                } else {
                    // logic_right: children to the right, spread vertically
                    const childX = px + pw + hspace;
                    cursor = py + ph / 2 - totalSpan / 2;
                    for (let i = 0; i < kids.length; i++) {
                        const c = kids[i];
                        c.direction = 1;
                        const ch = c._h || 20;
                        const cy = cursor + spans[i] / 2 - ch / 2;
                        if (c._el) {
                            c._el.style.left = childX + 'px';
                            c._el.style.top = cy + 'px';
                            c._el.style.display = '';
                            c._x = childX + (c._w || 80) / 2;
                            c._y = cy + ch / 2;
                        }
                        posExpander(c);
                        if (c.expanded && c.children.length > 0) {
                            positionKids(c, childX, cy, vertical);
                        } else if (!c.expanded) {
                            self._hideDescendants(c);
                        }
                        cursor += spans[i] + gap;
                    }
                }
            };

            positionKids(ftNode, ftX, ftY, isVertical);

            // Handle summary/excluded children of the floating topic and its descendants.
            // These are skipped by positionKids but still need expand/collapse visibility.
            const handleExcluded = (parent) => {
                for (const c of parent.children) {
                    if (_isLayoutExcluded(c)) {
                        // Summary or nested floating: manage visibility
                        if (c._el) c._el.style.display = '';
                        posExpander(c);
                        if (c.expanded) {
                            const showTree = (n) => {
                                if (n._el) n._el.style.display = '';
                                posExpander(n);
                                if (n.expanded) n.children.forEach(ch => showTree(ch));
                                else self._hideDescendants(n);
                            };
                            c.children.forEach(ch => showTree(ch));
                        } else {
                            self._hideDescendants(c);
                        }
                    } else if (c.expanded) {
                        // Regular child — recurse to find excluded grandchildren
                        handleExcluded(c);
                    }
                }
            };
            handleExcluded(ftNode);

            // Position the floating topic's own expander
            ftNode.direction = isVertical ? 2 : 1;
            posExpander(ftNode);
        }

        // Temporarily make all nodes visible so getBoundingClientRect works
        _showAllForMeasure(node) {
            if (!node) return;
            if (node._el) node._el.style.display = '';
            for (const c of node.children) {
                this._showAllForMeasure(c);
            }
        }

        // === SVG Lines ===

        _drawAllLines() {
            // Clear
            while (this.svg.firstChild) this.svg.removeChild(this.svg.firstChild);

            if (!this.mind || !this.mind.root) return;

            // Draw spine lines (before branch lines so they're behind)
            const mode = this.options.layout?.mode || 'map';
            // Toggle a mode class so the central topic's own box border/background
            // can be hidden in fishbone mode (the fish head becomes its container).
            const world = this.svg.parentElement;
            if (world) {
                world.classList.toggle('xmind-mode-fishbone',
                    mode === 'fishbone_right' || mode === 'fishbone_left');
            }
            if (mode === 'timeline_horizontal' || mode === 'timeline_vertical') {
                this._drawTimelineSpine(this.mind.root, mode);
            } else if (mode === 'fishbone_right' || mode === 'fishbone_left') {
                this._drawFishboneSpine(this.mind.root, mode === 'fishbone_right' ? 1 : -1);
            } else if (mode === 'matrix_horizontal' || mode === 'matrix_vertical' || mode === 'matrix') {
                // matrix_horizontal → columns; matrix_vertical / legacy 'matrix' → rows
                this._drawMatrixGrid(this.mind.root, mode === 'matrix_horizontal' ? 'col' : 'row');
            }

            this._drawLinesForNode(this.mind.root);
        }

        /** Draw the timeline spine (axis line through all children). */
        _drawTimelineSpine(root, mode) {
            const children = root.children.filter(c =>
                !(_isLayoutExcluded(c)) && c._el && c._el.style.display !== 'none');
            if (children.length === 0) return;

            const spine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            spine.setAttribute('stroke', '#558ED5');
            spine.setAttribute('stroke-width', '2');
            spine.setAttribute('fill', 'none');
            spine.setAttribute('stroke-linecap', 'round');
            spine.setAttribute('opacity', '0.5');

            if (mode === 'timeline_horizontal') {
                // Horizontal spine from root right edge to last child x
                const lastX = Math.max(...children.map(c => c._x + c._w / 2));
                const y = root._y;
                spine.setAttribute('d', `M${root._x + root._w / 2},${y} L${lastX + 20},${y}`);
            } else {
                // Vertical spine from root bottom to last child y
                const lastY = Math.max(...children.map(c => c._y + c._h / 2));
                const x = root._x;
                spine.setAttribute('d', `M${x},${root._y + root._h / 2} L${x},${lastY + 20}`);
            }

            this.svg.appendChild(spine);
        }

        /**
         * Draw the fishbone spine with a fish head around the central topic
         * (nose pointing outward, away from the spine) and a forked fish tail
         * at the far end.  dir = +1 → spine runs right (head on the left);
         * dir = -1 → spine runs left (head on the right).
         */
        _drawFishboneSpine(root, dir) {
            const children = root.children.filter(c =>
                !(_isLayoutExcluded(c)) && c._el && c._el.style.display !== 'none');
            if (children.length === 0) return;

            const NS = 'http://www.w3.org/2000/svg';
            const color = root._branchColor || children[0]._branchColor || '#558ED5';
            const cx = root._x, cy = root._y;
            const hw = root._w / 2;
            const hh = root._h * 0.63;                 // fish-head half height

            const xs = children.map(c => c._x);
            const endX = dir > 0 ? Math.max(...xs) + 40 : Math.min(...xs) - 40;
            const backX = cx + dir * (hw + 8);         // spine emerges from head back
            const noseX = cx - dir * (hw + 42);        // head nose points outward

            // Fish head wrapping the central topic
            const head = document.createElementNS(NS, 'path');
            head.setAttribute('d',
                `M ${noseX},${cy} `
              + `C ${noseX},${cy - hh * 0.55} ${cx - dir * hw},${cy - hh} ${cx},${cy - hh} `
              + `C ${cx + dir * hw * 0.6},${cy - hh} ${backX},${cy - hh * 0.7} ${backX},${cy} `
              + `C ${backX},${cy + hh * 0.7} ${cx + dir * hw * 0.6},${cy + hh} ${cx},${cy + hh} `
              + `C ${cx - dir * hw},${cy + hh} ${noseX},${cy + hh * 0.55} ${noseX},${cy} Z`);
            head.setAttribute('fill', color);
            head.setAttribute('fill-opacity', '0.15');
            head.setAttribute('stroke', color);
            head.setAttribute('stroke-width', '2');
            head.setAttribute('stroke-linejoin', 'round');

            // Spine from head back to beyond the last child
            const spine = document.createElementNS(NS, 'path');
            spine.setAttribute('stroke', color);
            spine.setAttribute('stroke-width', '3');
            spine.setAttribute('fill', 'none');
            spine.setAttribute('stroke-linecap', 'round');
            spine.setAttribute('d', `M${backX},${cy} L${endX},${cy}`);

            // Forked fish tail at the far end, opening outward
            const tail = document.createElementNS(NS, 'path');
            tail.setAttribute('d',
                `M ${endX - dir * 6},${cy} `
              + `L ${endX + dir * 46},${cy - 30} `
              + `L ${endX + dir * 28},${cy} `
              + `L ${endX + dir * 46},${cy + 30} Z`);
            tail.setAttribute('fill', color);
            tail.setAttribute('fill-opacity', '0.15');
            tail.setAttribute('stroke', color);
            tail.setAttribute('stroke-width', '2');
            tail.setAttribute('stroke-linejoin', 'round');

            this.svg.appendChild(head);
            this.svg.appendChild(spine);
            this.svg.appendChild(tail);
        }

        /** Bounding box (world coords) of a node's whole visible subtree. */
        _subtreeBBox(node) {
            let minX = node._x - node._w / 2, maxX = node._x + node._w / 2;
            let minY = node._y - node._h / 2, maxY = node._y + node._h / 2;
            if (node.expanded) {
                for (const c of node.children) {
                    if (_isLayoutExcluded(c)) continue;
                    if (c._el && c._el.style.display === 'none') continue;
                    const b = this._subtreeBBox(c);
                    minX = Math.min(minX, b.minX); maxX = Math.max(maxX, b.maxX);
                    minY = Math.min(minY, b.minY); maxY = Math.max(maxY, b.maxY);
                }
            }
            return { minX, maxX, minY, maxY };
        }

        /**
         * Draw the table grid for matrix layouts: outer border, a title band for
         * the central topic, a header band for the top-level topics, and cell
         * separators wrapping each top-level subtree.
         *   orient = 'col' → top-level topics are columns (表格圖 直行)
         *   orient = 'row' → top-level topics are rows    (表格圖 橫列)
         */
        _drawMatrixGrid(root, orient) {
            const NS = 'http://www.w3.org/2000/svg';
            const children = root.children.filter(c =>
                !(_isLayoutExcluded(c)) && c._el && c._el.style.display !== 'none');
            if (children.length === 0) return;

            const grid = '#A6BCD9';
            const pad = 16;
            const isCol = (orient === 'col');

            // Per-top-level subtree bounding boxes + overall union (incl. central topic)
            const boxes = children.map(c => this._subtreeBBox(c));
            let minX = root._x - root._w / 2, maxX = root._x + root._w / 2;
            let minY = root._y - root._h / 2, maxY = root._y + root._h / 2;
            for (const b of boxes) {
                minX = Math.min(minX, b.minX); maxX = Math.max(maxX, b.maxX);
                minY = Math.min(minY, b.minY); maxY = Math.max(maxY, b.maxY);
            }
            minX -= pad; minY -= pad; maxX += pad; maxY += pad;

            const line = (x1, y1, x2, y2) => {
                const p = document.createElementNS(NS, 'path');
                p.setAttribute('d', `M${x1},${y1} L${x2},${y2}`);
                p.setAttribute('stroke', grid);
                p.setAttribute('stroke-width', '1');
                p.setAttribute('fill', 'none');
                this.svg.appendChild(p);
            };
            const band = (x, y, w, h) => {
                const r = document.createElementNS(NS, 'rect');
                r.setAttribute('x', x); r.setAttribute('y', y);
                r.setAttribute('width', w); r.setAttribute('height', h);
                r.setAttribute('fill', 'rgba(166,188,217,0.10)');
                r.setAttribute('stroke', 'none');
                this.svg.appendChild(r);
            };
            const border = (x, y, w, h) => {
                const r = document.createElementNS(NS, 'rect');
                r.setAttribute('x', x); r.setAttribute('y', y);
                r.setAttribute('width', w); r.setAttribute('height', h);
                r.setAttribute('fill', 'none');
                r.setAttribute('stroke', grid);
                r.setAttribute('stroke-width', '1.5');
                this.svg.appendChild(r);
            };

            if (isCol) {
                const titleBottom = root._y + root._h / 2 + pad / 2;
                const headerBottom = Math.max(...children.map(c => c._y + c._h / 2)) + pad / 2;
                band(minX, minY, maxX - minX, headerBottom - minY);   // title + header band
                border(minX, minY, maxX - minX, maxY - minY);          // outer
                line(minX, titleBottom, maxX, titleBottom);            // below title
                line(minX, headerBottom, maxX, headerBottom);          // below header row
                for (let i = 0; i < boxes.length - 1; i++) {
                    const x = (boxes[i].maxX + boxes[i + 1].minX) / 2;
                    line(x, titleBottom, x, maxY);                     // column separators
                }
            } else {
                const titleRight = root._x + root._w / 2 + pad / 2;
                const labelRight = Math.max(...children.map(c => c._x + c._w / 2)) + pad / 2;
                band(minX, minY, labelRight - minX, maxY - minY);      // title + label band
                border(minX, minY, maxX - minX, maxY - minY);          // outer
                line(titleRight, minY, titleRight, maxY);              // right of title
                line(labelRight, minY, labelRight, maxY);              // right of label column
                for (let i = 0; i < boxes.length - 1; i++) {
                    const y = (boxes[i].maxY + boxes[i + 1].minY) / 2;
                    line(minX, y, maxX, y);                            // row separators
                }
            }
        }

        _drawLinesForNode(node) {
            if (!node.expanded || node.children.length === 0) return;

            // Fix #3: Tree layout — draw shared vertical trunk for tree children
            const treeChildren = node.children.filter(c =>
                c._el && c._el.style.display !== 'none'
                && !(_isLayoutExcluded(c))
                && (c.direction === 3 || c.direction === 4));
            if (treeChildren.length > 0) {
                this._drawTreeTrunk(node, treeChildren);
            }

            for (const child of node.children) {
                if (child._el && child._el.style.display !== 'none') {
                    // Draw branch line (skipped for summary/floating nodes via _drawLine guard)
                    this._drawLine(node, child);
                    // Always recurse to draw sub-tree lines (including floating topic children)
                    this._drawLinesForNode(child);
                }
            }
        }

        /**
         * Draw the shared vertical trunk for tree layout.
         * One vertical line from parent bottom to the last child's y,
         * then each child gets a horizontal branch from the trunk.
         */
        _drawTreeTrunk(parent, treeChildren) {
            if (treeChildren.length < 2) return; // single child uses normal L-shape

            const s = getStyleForDepth(treeChildren[0]._depth);
            const bs = (treeChildren[0].data && treeChildren[0].data.branchStyle) || {};
            const lineColor = bs.lineColor || treeChildren[0]._branchColor || s.lineColor;
            const lineWidth = bs.lineWidth || s.lineWidth || 1;

            const trunkX = parent._x;
            const trunkStartY = parent._y + parent._h / 2;
            const lastChild = treeChildren[treeChildren.length - 1];
            const trunkEndY = lastChild._y;

            // Draw the vertical trunk line
            const trunk = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            trunk.setAttribute('d', `M${trunkX},${trunkStartY} L${trunkX},${trunkEndY}`);
            trunk.setAttribute('stroke', lineColor);
            trunk.setAttribute('stroke-width', lineWidth);
            trunk.setAttribute('fill', 'none');
            trunk.setAttribute('stroke-linecap', 'round');
            this.svg.appendChild(trunk);
        }

        _drawLine(parent, child) {
            // Never draw branch line to a summary node or to a floating topic from root
            if (child.data && child.data._isSummaryNode) return;
            if (child.data && child.data._isFloatingTopic) return;

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            const s = getStyleForDepth(child._depth);
            const ps = getStyleForDepth(parent._depth);

            // Per-node branch style override (stored in child.data.branchStyle)
            const bs = (child.data && child.data.branchStyle) || {};

            // Rainbow branch color → per-node override → style default
            const lineColor = bs.lineColor || child._branchColor || s.lineColor;
            // Line width: per-node override → depth default
            const lineWidth = bs.lineWidth || s.lineWidth || 1;
            // Line class: per-node override → depth default
            const lineClass = bs.lineType || s.lineClass || 'curve';
            // Line corner for rounded elbow
            const lineCorner = s.lineCorner || 4;

            // --- Determine if parent/child have underline shape ---
            // Underline topics: connection starts/ends at bottom-edge, not center-y
            const parentIsUnderline = ps.shape === 'underline'
                || (parent.data && parent.data.shape && parent.data.shape.type === 'underline');
            const childIsUnderline = s.shape === 'underline'
                || (child.data && child.data.shape && child.data.shape.type === 'underline');

            // Connection points
            let sx, sy, ex, ey;
            const dir = child.direction || 1;
            const hasExpander = parent._expander && parent.children.length > 0 && !parent.isroot;
            const expanderHalf = 5.5;

            // Fix #1: Underline shape — sy/ey at bottom edge instead of center
            const parentSy = parentIsUnderline
                ? parent._y + parent._h / 2   // bottom of underline
                : parent._y;
            const childEy = childIsUnderline
                ? child._y + child._h / 2     // bottom of underline
                : child._y;

            if (dir === 7) {
                // Fishbone: diagonal from spine intersection to child
                // Spine runs at parent._y, intersection at child._x offset back by height
                const above = child._fishboneAbove;
                const fbDir = child._fishboneDir || 1;
                const offset = Math.abs(child._y - parent._y); // vertical distance
                sx = child._x - offset * fbDir * 0.7; // 45° angle back along spine
                sy = parent._y; // on the spine
                ex = child._x - (child._w / 2) * fbDir;
                ey = child._y;
            } else if (dir === 5) {
                // Timeline horizontal: vertical stub from spine to child
                sx = child._x;
                sy = parent._y; // spine Y
                ex = child._x;
                ey = child._y > sy ? child._y - child._h / 2 : child._y + child._h / 2;
            } else if (dir === 6) {
                // Timeline vertical: horizontal stub from spine to child
                sx = parent._x; // spine X
                sy = child._y;
                ex = child._x > sx ? child._x - child._w / 2 : child._x + child._w / 2;
                ey = child._y;
            } else if (dir === 3 || dir === 4) {
                // Tree layout: vertical trunk from parent bottom, horizontal branch to child
                sx = parent._x;
                sy = parent._y + parent._h / 2;
                ex = child._x - (child._w / 2) * (dir === 3 ? 1 : -1);
                ey = child._y;
            } else if (dir === 2) {
                // Vertical connection: child below parent → parent bottom to child top
                //                      child above parent → parent top to child bottom
                // Decide by ACTUAL geometry, not a global mode, so Up-Down's upper
                // half and nested org_chart_up both curve the right way.
                const isUp = child._y < parent._y;
                sx = parent._x;
                if (isUp) {
                    sy = hasExpander
                        ? parent._y - parent._h / 2 - 2 - expanderHalf
                        : parent._y - parent._h / 2;
                    ex = child._x;
                    ey = child._y + child._h / 2;
                } else {
                    sy = hasExpander
                        ? parent._y + parent._h / 2 + 2 + expanderHalf
                        : parent._y + parent._h / 2;
                    ex = child._x;
                    ey = child._y - child._h / 2;
                }
            } else if (dir === -1) {
                // Fix #2: Root node (radial) — source from left edge for left children
                if (parent.isroot) {
                    sx = parent._x - parent._w / 2;
                    sy = parentSy;
                } else {
                    sx = hasExpander
                        ? parent._x - parent._w / 2 - 15 + expanderHalf
                        : parent._x - parent._w / 2;
                    sy = parentSy;
                }
                ex = child._x + child._w / 2;
                ey = childEy;
            } else { // dir === 1
                if (parent.isroot) {
                    sx = parent._x + parent._w / 2;
                    sy = parentSy;
                } else {
                    sx = hasExpander
                        ? parent._x + parent._w / 2 + 3 + expanderHalf
                        : parent._x + parent._w / 2;
                    sy = parentSy;
                }
                ex = child._x - child._w / 2;
                ey = childEy;
            }

            let d = '';

            // --- Fishbone: diagonal line from spine to child ---
            if (dir === 7) {
                d = `M${sx},${sy} L${ex},${ey}`;
                path.setAttribute('d', d);
                path.setAttribute('stroke', lineColor);
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke-width', lineWidth);
                path.setAttribute('stroke-linecap', 'round');
                path.setAttribute('data-parent-id', parent.id);
                path.setAttribute('data-child-id', child.id);
                this.svg.appendChild(path);
                return;
            }

            // --- Timeline: straight stub + circle dot at spine ---
            if (dir === 5 || dir === 6) {
                d = `M${sx},${sy} L${ex},${ey}`;
                path.setAttribute('d', d);
                path.setAttribute('stroke', lineColor);
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke-width', lineWidth);
                path.setAttribute('stroke-linecap', 'round');
                path.setAttribute('data-parent-id', parent.id);
                path.setAttribute('data-child-id', child.id);
                this.svg.appendChild(path);
                // Fix #4: Add circle dot at spine intersection
                const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                dot.setAttribute('cx', sx);
                dot.setAttribute('cy', sy);
                dot.setAttribute('r', '4');
                dot.setAttribute('fill', lineColor);
                this.svg.appendChild(dot);
                return;
            }

            // --- Tree: horizontal branch from vertical trunk to child ---
            if (dir === 3 || dir === 4) {
                // The vertical trunk is drawn by _drawTreeTrunk.
                // Here we only draw the horizontal branch: from trunk x to child edge.
                // For single-child case (no trunk), draw full L-shape.
                const siblings = parent.children.filter(c =>
                    !(_isLayoutExcluded(c)) && (c.direction === 3 || c.direction === 4));
                const hasTrunk = siblings.length >= 2;

                if (hasTrunk) {
                    // Horizontal branch: trunk (sx) → child left/right edge
                    const c = Math.min(lineCorner, Math.abs(ex - sx));
                    const sgnX = ex > sx ? 1 : -1;
                    if (c > 0 && Math.abs(ex - sx) > c) {
                        d = `M${sx},${ey} Q${sx + c * sgnX * 0.5},${ey} ${sx + c * sgnX},${ey} L${ex},${ey}`;
                    } else {
                        d = `M${sx},${ey} L${ex},${ey}`;
                    }
                } else {
                    // Single child — full L-shape
                    const c = Math.min(lineCorner, Math.abs(ey - sy), Math.abs(ex - sx));
                    const sgnX = ex > sx ? 1 : -1;
                    const sgnY = ey > sy ? 1 : -1;
                    if (c > 0 && Math.abs(ey - sy) > c && Math.abs(ex - sx) > c) {
                        d = `M${sx},${sy} L${sx},${ey - c * sgnY} Q${sx},${ey} ${sx + c * sgnX},${ey} L${ex},${ey}`;
                    } else {
                        d = `M${sx},${sy} L${sx},${ey} L${ex},${ey}`;
                    }
                }
                path.setAttribute('d', d);
                path.setAttribute('stroke', lineColor);
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke-width', lineWidth);
                path.setAttribute('stroke-linecap', 'round');
                path.setAttribute('stroke-linejoin', 'round');
                path.setAttribute('data-parent-id', parent.id);
                path.setAttribute('data-child-id', child.id);
                this.svg.appendChild(path);
                return;
            }

            if (lineClass === 'straight') {
                d = `M${sx},${sy} L${ex},${ey}`;
            } else if (lineClass === 'roundedElbow' || lineClass === 'rounded' || lineClass === 'angular') {
                const midX = (sx + ex) / 2;
                const corner = lineClass === 'angular' ? 0 : Math.min(lineCorner, Math.abs(ey - sy) / 2, Math.abs(midX - sx));

                if (Math.abs(ey - sy) < 1) {
                    d = `M${sx},${sy} L${ex},${ey}`;
                } else if (dir === 2) {
                    // XMind 2 Elbow for org_chart: horizontal first, then vertical
                    // Elbow point at (child.x, parent.y) — same Y as source, same X as target
                    const c = lineClass === 'angular' ? 0 : Math.min(lineCorner, Math.abs(ex - sx) / 2, Math.abs(ey - sy) / 2);
                    const sgnX = ex > sx ? 1 : -1;
                    const sgnY = ey > sy ? 1 : -1;
                    if (c > 0) {
                        // Path: source → horizontal to near child.x → round corner → vertical to child
                        d = `M${sx},${sy} L${ex - c * sgnX},${sy} Q${ex},${sy} ${ex},${sy + c * sgnY} L${ex},${ey}`;
                    } else {
                        d = `M${sx},${sy} L${ex},${sy} L${ex},${ey}`;
                    }
                } else {
                    const sgnY = ey > sy ? 1 : -1;
                    if (corner > 0) {
                        d = `M${sx},${sy} L${midX - corner * dir},${sy} Q${midX},${sy} ${midX},${sy + corner * sgnY} L${midX},${ey - corner * sgnY} Q${midX},${ey} ${midX + corner * dir},${ey} L${ex},${ey}`;
                    } else {
                        d = `M${sx},${sy} L${midX},${sy} L${midX},${ey} L${ex},${ey}`;
                    }
                }
            } else if (lineClass === 'none') {
                return;
            } else {
                // ======================================================
                // XMind 2 Quadratic Bezier — CPRatio = 1/3
                // Control point = source * (1 - 1/3) + target * (1/3)
                //   Horizontal target: cp.x = lerp(sx, ex, 1/3), cp.y = ey
                //   Vertical target:   cp.x = ex,                cp.y = lerp(sy, ey, 1/3)
                // ======================================================
                const R = 1 / 3; // XMind 2 CurveBranchConnection.CPRatio
                let cpx, cpy;
                if (dir === 2) {
                    // Vertical: target is below/above → targetHorizontal=false
                    cpx = ex;
                    cpy = sy * (1 - R) + ey * R;
                } else {
                    // Horizontal: target is left/right → targetHorizontal=true
                    cpx = sx * (1 - R) + ex * R;
                    cpy = ey;
                }
                d = `M${sx},${sy} Q${cpx},${cpy} ${ex},${ey}`;
            }

            path.setAttribute('d', d);
            path.setAttribute('stroke', lineColor);
            path.setAttribute('fill', 'none');
            path.setAttribute('stroke-linecap', 'round');
            path.setAttribute('stroke-linejoin', 'round');
            path.setAttribute('data-parent-id', parent.id);
            path.setAttribute('data-child-id', child.id);

            // XMind 2 Tapered mode: filled quadratic outline (source thick → target thin)
            if (this._tapered && (lineClass === 'curve' || lineClass === 'curved')) {
                const startW = lineWidth * 2;
                const endW = Math.max(lineWidth * 0.5, 0.5);
                const R = 1 / 3;
                let cpx, cpy;
                if (dir === 2) {
                    cpx = ex;
                    cpy = sy * (1 - R) + ey * R;
                } else {
                    cpx = sx * (1 - R) + ex * R;
                    cpy = ey;
                }
                // XMind 2: two quadratic outlines forming a filled shape
                // Upper edge: (sx, sy-startW/2) → Q(cpx, cpy-midW/2) → (ex, ey-endW/2)
                // Lower edge: (ex, ey+endW/2) → Q(cpx, cpy+midW/2) → (sx, sy+startW/2)
                const midW = (startW + endW) / 2;
                d = `M${sx},${sy - startW / 2} Q${cpx},${cpy - midW / 2} ${ex},${ey - endW / 2}`
                  + ` L${ex},${ey + endW / 2} Q${cpx},${cpy + midW / 2} ${sx},${sy + startW / 2} Z`;
                path.setAttribute('d', d);
                path.setAttribute('stroke', 'none');
                path.setAttribute('fill', lineColor);
            } else {
                path.setAttribute('stroke-width', lineWidth);
            }

            // Per-node dash style
            if (bs.lineStyle === 'dashed') {
                path.setAttribute('stroke-dasharray', '8, 4');
            } else if (bs.lineStyle === 'dotted') {
                path.setAttribute('stroke-dasharray', '2, 2');
            }

            this.svg.appendChild(path);
        }

        // === Selection ===

        _selectNode(node) {
            // Deselect previous
            if (this.selected_node && this.selected_node._el) {
                this.selected_node._el.classList.remove('xmind-selected');
            }
            this.selected_node = node;
            if (node._el) {
                node._el.classList.add('xmind-selected');
            }
            this._fireEvent(1, { node: node.id });
        }

        select_clear() {
            if (this.selected_node && this.selected_node._el) {
                this.selected_node._el.classList.remove('xmind-selected');
            }
            this.selected_node = null;
        }

        // === Editing ===

        begin_edit(node) {
            if (!node || !node._el) return;
            this.editing_node = node;

            const el = node._el;
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'xmind-edit-input';
            input.value = node.topic;
            input.style.cssText = `
                position:absolute; left:${el.style.left}; top:${el.style.top};
                width:${Math.max(node._w, 80)}px; height:${node._h}px;
                font-size:${el.style.fontSize}; font-weight:${el.style.fontWeight};
                border:2px solid #428bca; border-radius:4px; padding:2px 6px;
                outline:none; z-index:100; box-sizing:border-box;
                font-family:inherit; color:inherit; background:#fff;
            `;

            this.nodesLayer.appendChild(input);
            input.focus();
            input.select();

            const finish = () => {
                const newTopic = input.value.trim();
                if (newTopic && newTopic !== node.topic) {
                    this._updateNodeTopic(node, newTopic);
                }
                if (input.parentNode) input.parentNode.removeChild(input);
                this.editing_node = null;
                this._fireEvent(2, { node: node.id, topic: newTopic });
            };

            input.addEventListener('blur', finish);
            let isComposing = false;
            input.addEventListener('compositionstart', () => { isComposing = true; });
            input.addEventListener('compositionend', () => { isComposing = false; });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !isComposing && !e.isComposing) { e.preventDefault(); e.stopPropagation(); input.blur(); }
                if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); input.value = node.topic; input.blur(); }
            });
        }

        _updateNodeTopic(node, topic) {
            node.topic = topic;
            if (node._el) {
                const span = node._el.querySelector('.xmind-topic-text');
                if (span) span.textContent = topic;
                // Re-measure (offsetWidth/Height unaffected by zoom transform)
                node._w = node._el.offsetWidth || node._w;
                node._h = node._el.offsetHeight || node._h;
            }
            this.refresh();
        }

        // === Events ===

        _fireEvent(type, data) {
            for (const fn of this._event_listeners) {
                try { fn(type, data); } catch (e) { console.error(e); }
            }
        }

        // === Node management ===

        create_node_element(node) {
            this._createNodeElement(node);
            // Ensure parent gets expander
            if (node.parent && !node.parent._expander && node.parent.children.length > 0 && !node.parent.isroot) {
                this._createExpander(node.parent);
            }
        }

        get_node_element(nodeId) {
            const node = this.mind ? this.mind.get_node(nodeId) : null;
            return node ? node._el : null;
        }

        // panel reference for compatibility
        get e_panel() { return this.container; }
        get e_nodes() { return this.nodesLayer; }
        get e_lines() { return this.svg; }

        draw_lines() { this._drawAllLines(); }
        relayout() { this.refresh(); }
    }

    // =========================================================================
    // Main XMind Class (API compatible with jsMind interface used by editor)
    // =========================================================================
    class OdooXMind {
        constructor(options) {
            this.options = Object.assign({
                container: null,
                theme: 'primary',
                editable: true,
                view: { line_color: '#808080', line_width: 1, draggable: true },
                layout: { hspace: 30, vspace: 6, pspace: 13, mode: 'map' },
                shortcut: { enable: false },
            }, options);

            this.mind = null;
            this.view = new XMindView(this.options.container, this.options);
            this.layout = {
                mode: this.options.layout.mode || 'map',
                layout: () => { /* called by view.refresh */ },
                setLayoutMode: (m) => { this.layout.mode = m; this.options.layout.mode = m; },
            };
        }

        show(data, onReady) {
            this.mind = parseMindData(data);
            this.view.show(this.mind, onReady);
        }

        get_data(format) {
            if (format === 'node_tree') return exportMindData(this.mind);
            return null;
        }

        get_root() { return this.mind ? this.mind.root : null; }
        get_node(id) { return this.mind ? this.mind.get_node(id) : null; }

        add_node(parentId, nodeId, topic, data) {
            const parent = this.mind.get_node(parentId);
            if (!parent) return null;
            const node = this.mind.add_node(parent, nodeId, topic, data || {});
            node.direction = parent.direction || 1;
            // Inherit branch color from parent, or assign new if parent is root
            if (parent.isroot) {
                const idx = parent.children.length - 1;
                node._branchColor = BRANCH_COLORS[idx % BRANCH_COLORS.length];
            } else {
                node._branchColor = parent._branchColor;
            }
            this.view.create_node_element(node);
            this.view.refresh();
            this._fire_event(1, { evt: 'add_node', node: nodeId });
            return node;
        }

        remove_node(nodeId) {
            const node = this.mind.get_node(nodeId);
            if (!node) return false;
            if (this.view.selected_node === node) this.view.select_clear();
            // Remove DOM
            if (node._el && node._el.parentNode) node._el.parentNode.removeChild(node._el);
            if (node._expander && node._expander.parentNode) node._expander.parentNode.removeChild(node._expander);
            // Remove descendants DOM
            const removeDom = (n) => {
                for (const c of n.children) {
                    if (c._el && c._el.parentNode) c._el.parentNode.removeChild(c._el);
                    if (c._expander && c._expander.parentNode) c._expander.parentNode.removeChild(c._expander);
                    removeDom(c);
                }
            };
            removeDom(node);
            this.mind.remove_node(nodeId);
            this.view.refresh();
            return true;
        }

        update_node(nodeId, topic) {
            const node = this.mind.get_node(nodeId);
            if (!node) return;
            this.view._updateNodeTopic(node, topic);
        }

        select_node(nodeId) {
            const node = this.mind.get_node(nodeId);
            if (node) this.view._selectNode(node);
        }

        begin_edit(nodeId) {
            const node = typeof nodeId === 'string' ? this.mind.get_node(nodeId) : nodeId;
            if (node) this.view.begin_edit(node);
        }

        toggle_node(nodeId) {
            const node = this.mind.get_node(nodeId);
            if (!node) return;
            node.expanded = !node.expanded;
            if (node._expander) node._expander.textContent = node.expanded ? '−' : '+';
            this.view.refresh();
        }

        expand_node(nodeId) {
            const node = this.mind.get_node(nodeId);
            if (node && !node.expanded) { node.expanded = true; if (node._expander) node._expander.textContent = '−'; this.view.refresh(); }
        }

        collapse_node(nodeId) {
            const node = this.mind.get_node(nodeId);
            if (node && node.expanded) { node.expanded = false; if (node._expander) node._expander.textContent = '+'; this.view.refresh(); }
        }

        expand_all() {
            for (const id in this.mind.nodes) { this.mind.nodes[id].expanded = true; if (this.mind.nodes[id]._expander) this.mind.nodes[id]._expander.textContent = '−'; }
            this.view.refresh();
        }

        collapse_all() {
            for (const id in this.mind.nodes) {
                if (!this.mind.nodes[id].isroot) { this.mind.nodes[id].expanded = false; if (this.mind.nodes[id]._expander) this.mind.nodes[id]._expander.textContent = '+'; }
            }
            this.view.refresh();
        }

        move_node(nodeId, beforeId, parentId) {
            // Recalculate depth for the moved subtree
            const node = this.mind.get_node(nodeId);
            if (node) {
                this._recalcDepths(node);
            }
            this.view.refresh();
        }

        _recalcDepths(node) {
            node._depth = node.parent ? node.parent._depth + 1 : 0;
            // Update level class on DOM
            if (node._el) {
                const lvl = Math.min(node._depth, 3);
                node._el.className = `xmind-node xmind-level-${lvl}` +
                    (node.isroot ? ' xmind-root' : '') +
                    (node._el.classList.contains('xmind-selected') ? ' xmind-selected' : '');
            }
            for (const c of node.children) {
                this._recalcDepths(c);
            }
        }

        set_theme(theme) {
            this.options.theme = theme;
            // Apply theme color to root node
            if (this.mind && this.mind.root && this.mind.root._el) {
                const color = THEME_COLORS[theme] || STYLES.central.fill;
                this.mind.root._el.style.backgroundColor = color;
                // Adjust text color for light vs dark backgrounds
                const isLight = theme === 'clouds' || theme === 'default';
                this.mind.root._el.style.color = isLight ? '#2c3e50' : '#ffffff';
            }
        }

        add_event_listener(fn) {
            this.view._event_listeners.push(fn);
        }

        _fire_event(type, data) {
            this.view._fireEvent(type, data);
        }
    }

    // Expose globally
    window.OdooXMind = OdooXMind;

})();
