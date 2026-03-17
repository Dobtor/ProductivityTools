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
            fontFamily: "'Open Sans', sans-serif",
        },
        main: {
            fontSize: 13, fontWeight: 'normal', color: '#17375E', fill: '#DCE6F2',
            shape: 'roundedRect', corner: 5, textAlign: 'left',
            paddingH: 6, paddingV: 6, border: '#558ED5', borderWidth: 2,
            lineClass: 'curve', lineColor: '#558ED5', lineWidth: 1, lineCorner: 4,
            spacingMajor: 8, spacingMinor: 1,
            fontFamily: "'Open Sans', sans-serif",
        },
        sub: {
            fontSize: 10, fontWeight: 'normal', color: '#000000', fill: '#f0f0f0',
            shape: 'underline', corner: 3, textAlign: 'left',
            paddingH: 4, paddingV: 1, border: '#558ED5', borderWidth: 3,
            lineClass: 'curve', lineColor: '#558ED5', lineWidth: 1, lineCorner: 4,
            spacingMajor: 8, spacingMinor: 1,
            fontFamily: "'Open Sans', sans-serif",
        },
        deep: {
            fontSize: 10, fontWeight: 'normal', color: '#333333', fill: 'transparent',
            shape: 'underline', corner: 3, textAlign: 'left',
            paddingH: 4, paddingV: 1, border: '#558ED5', borderWidth: 1,
            lineClass: 'curve', lineColor: '#558ED5', lineWidth: 1, lineCorner: 4,
            spacingMajor: 6, spacingMinor: 1,
            fontFamily: "'Open Sans', sans-serif",
        },
        // Special topic styles (XMind 2 defaultStyles.xml)
        callout: {
            fontSize: 13, fontWeight: 'normal', color: '#000000', fill: '#ffe866',
            shape: 'balloon', corner: 5, textAlign: 'left',
            paddingH: 6, paddingV: 6, border: '#b8860b',
            fontFamily: 'Verdana, sans-serif',
        },
        summaryTopic: {
            fontSize: 9, fontWeight: 'normal', color: '#FFFFFF', fill: '#77933C',
            shape: 'roundedRect', corner: 5, textAlign: 'left',
            paddingH: 4, paddingV: 4, border: 'none', borderWidth: 0,
            fontFamily: 'Georgia, serif', fontStyle: 'italic',
        },
        floating: {
            fontSize: 13, fontWeight: 'bold', color: '#FFFFFF', fill: '#558ED5',
            shape: 'roundedRect', corner: 8, textAlign: 'left',
            paddingH: 6, paddingV: 6, border: 'none', borderWidth: 0,
            fontFamily: "'Open Sans', sans-serif",
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
            this._measureAll(root);

            if (mode === 'org_chart_down') {
                this._layoutVertical(root);
            } else if (mode === 'tree_right' || mode === 'logic_right') {
                this._layoutSingleSide(root, 1);
            } else if (mode === 'tree_left') {
                this._layoutSingleSide(root, -1);
            } else if (mode === 'fishbone_right') {
                this._layoutFishbone(root, 1);
            } else if (mode === 'fishbone_left') {
                this._layoutFishbone(root, -1);
            } else if (mode === 'matrix') {
                this._layoutMatrix(root);
            } else {
                // Default: map (balanced left/right)
                this._layoutBalanced(root);
            }
        }

        _measureAll(node) {
            const s = getStyleForDepth(node._depth);
            // Estimate size from text (always reliable, even before browser layout)
            const charW = s.fontSize * 0.55;
            const estW = Math.max(node.topic.length * charW + s.paddingH * 2, 50);
            const estH = s.fontSize * 1.4 + s.paddingV * 2;

            if (node._el) {
                const rect = node._el.getBoundingClientRect();
                // Use DOM measurement only if it's valid (> 0), otherwise fallback
                node._w = (rect.width > 1) ? rect.width : estW;
                node._h = (rect.height > 1) ? rect.height : estH;
            } else {
                node._w = estW;
                node._h = estH;
            }
            if (node.expanded) {
                for (const c of node.children) this._measureAll(c);
            }
        }

        _subtreeHeight(node) {
            if (!node.expanded || node.children.length === 0) return node._h;
            let total = 0;
            for (const c of node.children) {
                total += this._subtreeHeight(c);
            }
            total += this.vgap * (node.children.length - 1);
            return Math.max(node._h, total);
        }

        _layoutBalanced(root) {
            root._x = 0;
            root._y = 0;

            // XMind 2 unbalanced layout: right-number controls how many go right
            // Default: 3 right, rest left (matches XMind 2 default)
            const rightNum = this._rightNumber || Math.ceil(root.children.length / 2);

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

        // Fishbone layout — children alternate above/below a horizontal spine
        _layoutFishbone(root, dir) {
            root._x = 0;
            root._y = 0;

            const spineGap = 40; // horizontal gap along the spine
            let curX = dir * (root._w / 2 + spineGap);

            for (let i = 0; i < root.children.length; i++) {
                const child = root.children[i];
                child._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(child);
                child.direction = dir;

                // Alternate above (odd) and below (even)
                const above = (i % 2 === 0);
                const subH = this._subtreeHeight(child);
                child._x = curX + (child._w / 2) * dir;
                child._y = above ? -(subH / 2 + 20) : (subH / 2 + 20);

                curX += (child._w + spineGap) * dir;

                // Layout child's own children as a vertical branch
                if (child.expanded && child.children.length > 0) {
                    for (const gc of child.children) gc.direction = above ? -1 : 1;
                    const childDir = above ? -1 : 1;
                    // Stack grandchildren vertically from the child
                    let gcY = child._y + (above ? -child._h / 2 - 10 : child._h / 2 + 10);
                    for (const gc of child.children) {
                        gc._x = child._x + (gc._w / 2 + 20) * dir;
                        gc._y = gcY + (above ? -gc._h / 2 : gc._h / 2);
                        gc.direction = dir;
                        gcY += (gc._h + 5) * (above ? -1 : 1);
                        // Deep children use standard branch
                        if (gc.expanded && gc.children.length > 0) {
                            this._layoutBranch(gc, gc.children, dir);
                        }
                    }
                }
            }
        }

        // Matrix/Spreadsheet layout — children in a grid (rows × cols)
        _layoutMatrix(root) {
            root._x = 0;
            root._y = 0;

            const children = root.children;
            if (children.length === 0) return;

            const cols = Math.ceil(Math.sqrt(children.length));
            const cellW = 180; // cell width
            const cellH = 80;  // cell height
            const gapX = 30;
            const gapY = 20;
            const startX = -(cols * (cellW + gapX)) / 2;
            const startY = root._h / 2 + 40;

            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                child._branchColor = BRANCH_COLORS[i % BRANCH_COLORS.length];
                this._propagateBranchColor(child);
                child.direction = 2; // down

                const col = i % cols;
                const row = Math.floor(i / cols);
                child._x = startX + col * (cellW + gapX) + cellW / 2;
                child._y = startY + row * (cellH + gapY) + cellH / 2;

                // Children of matrix cells go right
                if (child.expanded && child.children.length > 0) {
                    for (const gc of child.children) gc.direction = 1;
                    this._layoutBranch(child, child.children, 1);
                }
            }
        }

        _layoutBranch(parent, children, dir) {
            if (children.length === 0) return;

            // Per-depth spacing from STYLES (XMind 2: spacingMajor/spacingMinor)
            const ps = getStyleForDepth(parent._depth);
            const hgap = ps.spacingMajor || this.hgap;
            const vgap = ps.spacingMinor || this.vgap;

            const totalH = children.reduce((sum, c) => sum + this._subtreeHeight(c), 0)
                + vgap * (children.length - 1);

            let curY = parent._y - totalH / 2;

            for (const child of children) {
                const subH = this._subtreeHeight(child);
                child._y = curY + subH / 2;
                child._x = parent._x + (parent._w / 2 + hgap + child._w / 2) * dir;
                child.direction = dir;
                curY += subH + vgap;

                if (child.expanded && child.children.length > 0) {
                    for (const gc of child.children) gc.direction = dir;
                    this._layoutBranch(child, child.children, dir);
                }
            }
        }

        _layoutVerticalChildren(parent) {
            const children = parent.children.filter(() => true);
            if (children.length === 0) return;

            const totalW = children.reduce((sum, c) => sum + c._w, 0)
                + this.hgap * (children.length - 1);

            let curX = parent._x - totalW / 2;

            for (const child of children) {
                child._x = curX + child._w / 2;
                child._y = parent._y + parent._h / 2 + this.vgap + child._h / 2;
                child.direction = 2;
                curX += child._w + this.hgap;

                if (child.expanded && child.children.length > 0) {
                    this._layoutVerticalChildren(child);
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

        show(mind) {
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
            requestAnimationFrame(() => this.refresh());
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

            // Measure
            const rect = el.getBoundingClientRect();
            node._w = rect.width;
            node._h = rect.height;

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
            if (node.expanded) {
                for (const c of node.children) this._positionAllNodes(c);
            } else {
                // Hide collapsed descendants
                this._hideDescendants(node);
            }
        }

        _positionNode(node) {
            if (!node._el) return;
            node._el.style.left = (node._x - node._w / 2) + 'px';
            node._el.style.top = (node._y - node._h / 2) + 'px';
            node._el.style.display = '';

            // Position expander (11px circle, XMind 2 style)
            if (node._expander) {
                const dir = node.direction || 1;
                let ex, ey;
                if (dir === 2) {
                    ex = node._x - 6;
                    ey = node._y + node._h / 2 + 2;
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
            this._drawLinesForNode(this.mind.root);
        }

        _drawLinesForNode(node) {
            if (!node.expanded || node.children.length === 0) return;

            for (const child of node.children) {
                if (child._el && child._el.style.display !== 'none') {
                    this._drawLine(node, child);
                    this._drawLinesForNode(child);
                }
            }
        }

        _drawLine(parent, child) {
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            const s = getStyleForDepth(child._depth);

            // Per-node branch style override (stored in child.data.branchStyle)
            const bs = (child.data && child.data.branchStyle) || {};

            // Rainbow branch color → per-node override → style default
            const lineColor = bs.lineColor || child._branchColor || s.lineColor;
            // Line width: per-node override → depth default
            const lineWidth = bs.lineWidth || (parent.isroot ? 2 : s.lineWidth);
            // Line class: per-node override → depth default
            const lineClass = bs.lineType || (parent.isroot ? 'straight' : s.lineClass);
            // Line corner for rounded elbow
            const lineCorner = s.lineCorner;

            // Connection points
            let sx, sy, ex, ey;
            const dir = child.direction || 1;

            if (dir === 2) {
                sx = parent._x;
                sy = parent._y + parent._h / 2;
                ex = child._x;
                ey = child._y - child._h / 2;
            } else if (dir === -1) {
                sx = parent._x - parent._w / 2;
                sy = parent._y;
                ex = child._x + child._w / 2;
                ey = child._y;
            } else {
                sx = parent._x + parent._w / 2;
                sy = parent._y;
                ex = child._x - child._w / 2;
                ey = child._y;
            }

            let d = '';

            if (lineClass === 'straight') {
                d = `M${sx},${sy} L${ex},${ey}`;
            } else if (lineClass === 'roundedElbow' || lineClass === 'rounded' || lineClass === 'angular') {
                // Rounded elbow (or angular with corners)
                const midX = (sx + ex) / 2;
                const corner = lineClass === 'angular' ? 0 : Math.min(lineCorner, Math.abs(ey - sy) / 2, Math.abs(midX - sx));

                if (Math.abs(ey - sy) < 1) {
                    d = `M${sx},${sy} L${ex},${ey}`;
                } else if (dir === 2) {
                    const midY = (sy + ey) / 2;
                    const c = lineClass === 'angular' ? 0 : Math.min(lineCorner, Math.abs(ex - sx) / 2, Math.abs(midY - sy));
                    const sgnX = ex > sx ? 1 : -1;
                    if (c > 0) {
                        d = `M${sx},${sy} L${sx},${midY - c} Q${sx},${midY} ${sx + c * sgnX},${midY} L${ex - c * sgnX},${midY} Q${ex},${midY} ${ex},${midY + c} L${ex},${ey}`;
                    } else {
                        d = `M${sx},${sy} L${sx},${midY} L${ex},${midY} L${ex},${ey}`;
                    }
                } else {
                    const sgnY = ey > sy ? 1 : -1;
                    if (corner > 0) {
                        d = `M${sx},${sy} L${midX - corner * dir},${sy} Q${midX},${sy} ${midX},${sy + corner * sgnY} L${midX},${ey - corner * sgnY} Q${midX},${ey} ${midX + corner * dir},${ey} L${ex},${ey}`;
                    } else {
                        d = `M${sx},${sy} L${midX},${sy} L${midX},${ey} L${ex},${ey}`;
                    }
                }
            } else {
                // Bezier curve (default / 'curved') — XMind 2 uses 1/3 control point
                const ctrl = Math.abs(ex - sx) * 0.33;
                if (dir === 2) {
                    d = `M${sx},${sy} C${sx},${sy + ctrl} ${ex},${ey - ctrl} ${ex},${ey}`;
                } else {
                    d = `M${sx},${sy} C${sx + ctrl * dir},${sy} ${ex - ctrl * dir},${ey} ${ex},${ey}`;
                }
            }

            path.setAttribute('d', d);
            path.setAttribute('stroke', lineColor);
            path.setAttribute('fill', 'none');
            path.setAttribute('stroke-linecap', 'round');
            path.setAttribute('stroke-linejoin', 'round');
            path.setAttribute('data-parent-id', parent.id);
            path.setAttribute('data-child-id', child.id);

            // Line tapering: thicker at parent, thinner at child (XMind 2 tapered mode)
            if (this._tapered && lineClass === 'curve') {
                // Use a tapered path: draw as filled shape instead of stroke
                const startW = lineWidth * 2;
                const endW = Math.max(lineWidth * 0.5, 0.5);
                path.setAttribute('stroke', 'none');
                path.setAttribute('fill', lineColor);
                // Approximate taper by generating an outlined curve path
                const ctrl = Math.abs(ex - sx) * 0.33;
                const dir2 = child.direction || 1;
                if (dir2 !== 2) {
                    const c1x = sx + ctrl * dir2, c1y = sy;
                    const c2x = ex - ctrl * dir2, c2y = ey;
                    d = `M${sx},${sy - startW / 2} C${c1x},${c1y - startW / 2} ${c2x},${c2y - endW / 2} ${ex},${ey - endW / 2}`
                      + ` L${ex},${ey + endW / 2} C${c2x},${c2y + endW / 2} ${c1x},${c1y + startW / 2} ${sx},${sy + startW / 2} Z`;
                    path.setAttribute('d', d);
                } else {
                    path.setAttribute('stroke-width', lineWidth);
                }
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
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
                if (e.key === 'Escape') { input.value = node.topic; input.blur(); }
            });
        }

        _updateNodeTopic(node, topic) {
            node.topic = topic;
            if (node._el) {
                const span = node._el.querySelector('.xmind-topic-text');
                if (span) span.textContent = topic;
                // Re-measure
                const rect = node._el.getBoundingClientRect();
                node._w = rect.width;
                node._h = rect.height;
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

        show(data) {
            this.mind = parseMindData(data);
            this.view.show(this.mind);
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
