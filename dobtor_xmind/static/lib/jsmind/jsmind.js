/**
 * jsMind - Mind Mapping Library
 * Open Source (MIT License)
 * Adapted for Odoo XMind Editor
 * Namespaced as OdooXMind to avoid conflicts with other jsMind versions
 */
(function (factory) {
    if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        // Use unique namespace to avoid conflicts with other jsMind libraries
        console.log('[OdooXMind] Loading custom jsMind library...');
        window.OdooXMind = factory();
        console.log('[OdooXMind] Registered as window.OdooXMind:', typeof window.OdooXMind);
        // Also provide jsMind alias if not already defined
        if (!window.jsMind) {
            window.jsMind = window.OdooXMind;
            console.log('[OdooXMind] Also registered as window.jsMind (no conflict)');
        } else {
            console.warn('[OdooXMind] WARNING: window.jsMind already exists! Not overwriting. Using OdooXMind namespace.');
        }
    }
}(function () {
    'use strict';

    // Utility functions
    const $w = window;
    const $d = document;

    // Use .bind() to ensure proper context for DOM methods
    const $g = function (id) {
        return document.getElementById(id);
    };

    const $c = function (tag) {
        return document.createElement(tag);
    };

    const $t = function (n, t) {
        if (n.hasChildNodes()) {
            n.firstChild.nodeValue = t;
        } else {
            n.appendChild(document.createTextNode(t));
        }
    };

    const $h = function (n, t) {
        n.innerHTML = t;
    };

    // Version marker - if you see this, the correct library is loaded
    const ODOO_XMIND_VERSION = '1.0.0-odoo-custom';
    console.log('[OdooXMind] Version:', ODOO_XMIND_VERSION, '- Custom library loaded successfully');

    const logger = {
        log: function () { },
        debug: function () { },
        info: function (msg) { console.info('[jsMind]', msg); },
        warn: function (msg) { console.warn('[jsMind]', msg); },
        error: function (msg) { console.error('[jsMind]', msg); }
    };

    // Node class
    class MindNode {
        constructor(sId, iIndex, sTopic, oData, bIsRoot, oParent, eDirection, bExpanded) {
            this.id = sId;
            this.index = iIndex;
            this.topic = sTopic;
            this.data = oData || {};
            this.isroot = bIsRoot;
            this.parent = oParent;
            this.direction = eDirection;
            this.expanded = bExpanded !== false;
            this.children = [];
            this._data = {};
        }
    }

    // Mind class - manages the mind map data
    class Mind {
        constructor() {
            this.name = null;
            this.author = null;
            this.version = null;
            this.root = null;
            this.selected = null;
            this.nodes = {};
        }

        get_node(nodeid) {
            if (nodeid in this.nodes) {
                return this.nodes[nodeid];
            }
            return null;
        }

        set_root(nodeid, topic, data) {
            if (this.root == null) {
                this.root = new MindNode(nodeid, 0, topic, data, true, null, 0, true);
                this._put_node(this.root);
            } else {
                logger.error('root node already exist');
            }
        }

        add_node(parent_node, nodeid, topic, data, direction, expanded) {
            if (parent_node.isroot) {
                const c = parent_node.children.length;
                direction = (c % 2 === 0) ? -1 : 1;
            } else {
                direction = parent_node.direction;
            }
            const node = new MindNode(nodeid, c, topic, data, false, parent_node, direction, expanded);
            if (this._put_node(node)) {
                parent_node.children.push(node);
            } else {
                logger.error('node id is already exist');
            }
            return node;
        }

        remove_node(node) {
            if (node.isroot) {
                logger.error('can not remove root node');
                return false;
            }
            if (this.selected != null && this.selected.id === node.id) {
                this.selected = null;
            }
            const children = node.children.slice(0);
            for (let child of children) {
                this.remove_node(child);
            }
            delete this.nodes[node.id];
            const siblings = node.parent.children;
            const index = siblings.indexOf(node);
            if (index > -1) {
                siblings.splice(index, 1);
            }
            return true;
        }

        _put_node(node) {
            if (node.id in this.nodes) {
                logger.warn('node id already exist: ' + node.id);
                return false;
            }
            this.nodes[node.id] = node;
            return true;
        }
    }

    // Data provider for node_tree format
    const DataProvider = {
        node_tree: {
            get_mind: function (source) {
                const mind = new Mind();
                mind.name = source.meta.name;
                mind.author = source.meta.author;
                mind.version = source.meta.version;
                this._parse(mind, source.data);
                return mind;
            },
            _parse: function (mind, node_root) {
                const data = this._extract_data(node_root);
                mind.set_root(node_root.id, node_root.topic, data);
                if ('children' in node_root) {
                    const children = node_root.children;
                    for (let i = 0; i < children.length; i++) {
                        this._extract_node(mind, mind.root, children[i]);
                    }
                }
            },
            _extract_node: function (mind, parent_node, json_node) {
                const data = this._extract_data(json_node);
                const node = mind.add_node(parent_node, json_node.id, json_node.topic, data, null, json_node.expanded);
                if ('children' in json_node) {
                    const children = json_node.children;
                    for (let i = 0; i < children.length; i++) {
                        this._extract_node(mind, node, children[i]);
                    }
                }
            },
            _extract_data: function (node_json) {
                const data = {};
                for (let k in node_json) {
                    if (k !== 'id' && k !== 'topic' && k !== 'children' && k !== 'direction' && k !== 'expanded') {
                        data[k] = node_json[k];
                    }
                }
                if ('data' in node_json) {
                    return node_json.data;
                }
                return data;
            },
            get_data: function (mind) {
                const json = {
                    meta: {
                        name: mind.name,
                        author: mind.author,
                        version: mind.version
                    },
                    format: 'node_tree',
                    data: this._build_node(mind.root)
                };
                return json;
            },
            _build_node: function (node) {
                const json_node = {
                    id: node.id,
                    topic: node.topic,
                    expanded: node.expanded,
                };
                if (node.data && Object.keys(node.data).length > 0) {
                    json_node.data = node.data;
                }
                if (node.children.length > 0) {
                    json_node.children = [];
                    for (let child of node.children) {
                        json_node.children.push(this._build_node(child));
                    }
                }
                return json_node;
            }
        }
    };

    // Layout provider
    class LayoutProvider {
        constructor(jm) {
            this.jm = jm;
            this.bounds = null;
            this.cache_valid = false;
        }

        reset() {
            this.bounds = { n: 0, s: 0, w: 0, e: 0 };
        }

        layout() {
            this.reset();
            this._layout_root();
            this._layout_offset();
        }

        _layout_root() {
            const root = this.jm.mind.root;
            const layout_data = root._data.layout || {};
            layout_data.direction = 0;
            layout_data.side_index = 0;

            const children = root.children;
            const children_count = children.length;

            const left_children = [];
            const right_children = [];

            for (let i = 0; i < children_count; i++) {
                if (children[i].direction === -1) {
                    left_children.push(children[i]);
                } else {
                    right_children.push(children[i]);
                }
            }

            layout_data.left_nodes = left_children;
            layout_data.right_nodes = right_children;
            layout_data.outer_height_left = this._layout_children_nodes(left_children, -1);
            layout_data.outer_height_right = this._layout_children_nodes(right_children, 1);

            root._data.layout = layout_data;
        }

        _layout_children_nodes(children, direction) {
            let total_height = 0;
            const count = children.length;
            if (count === 0) return total_height;

            const parent_offset = this.jm.view.layout.pspace;
            const sibling_offset = this.jm.view.layout.vspace;

            let i = count;
            let outer_height = 0;

            while (i--) {
                outer_height = this._layout_node(children[i], direction);
                children[i]._data.layout.outer_height = outer_height;
                total_height += outer_height;
            }

            if (count > 1) {
                total_height += sibling_offset * (count - 1);
            }

            let y = total_height / -2;
            for (let i = 0; i < count; i++) {
                const child = children[i];
                const child_data = child._data.layout;
                child_data.offset_y = y + child_data.outer_height / 2;
                y += child_data.outer_height + sibling_offset;
            }

            return total_height;
        }

        _layout_node(node, direction) {
            const layout_data = {};
            layout_data.direction = direction;
            layout_data.side_index = 0;

            const view_data = node._data.view || {};
            const width = view_data.width || 0;
            const height = view_data.height || 0;

            let outer_height = 0;

            if (node.expanded && node.children.length > 0) {
                outer_height = this._layout_children_nodes(node.children, direction);
            }

            outer_height = Math.max(height, outer_height);
            layout_data.outer_height = outer_height;
            layout_data.offset_x = this.jm.view.layout.hspace * direction;

            node._data.layout = layout_data;
            return outer_height;
        }

        _layout_offset() {
            const root = this.jm.mind.root;
            const view_data = root._data.view || {};
            const root_width = view_data.width || 100;
            const root_height = view_data.height || 30;

            const layout_data = root._data.layout;
            layout_data.offset_x = 0;
            layout_data.offset_y = 0;

            // Layout left side
            let left_y_start = -(layout_data.outer_height_left / 2);
            for (let node of layout_data.left_nodes) {
                this._layout_offset_node(node, -root_width / 2, 0);
            }

            // Layout right side
            let right_y_start = -(layout_data.outer_height_right / 2);
            for (let node of layout_data.right_nodes) {
                this._layout_offset_node(node, root_width / 2, 0);
            }

            this._update_bounds();
        }

        _layout_offset_node(node, parent_x, parent_y) {
            const layout_data = node._data.layout;
            const view_data = node._data.view || {};

            const abs_x = parent_x + layout_data.offset_x;
            const abs_y = parent_y + layout_data.offset_y;

            layout_data.abs_x = abs_x;
            layout_data.abs_y = abs_y;

            // Update bounds
            const w = view_data.width || 50;
            const h = view_data.height || 20;

            this.bounds.w = Math.min(this.bounds.w, abs_x - w / 2);
            this.bounds.e = Math.max(this.bounds.e, abs_x + w / 2);
            this.bounds.n = Math.min(this.bounds.n, abs_y - h / 2);
            this.bounds.s = Math.max(this.bounds.s, abs_y + h / 2);

            if (node.expanded && node.children.length > 0) {
                for (let child of node.children) {
                    this._layout_offset_node(child, abs_x, abs_y);
                }
            }
        }

        _update_bounds() {
            const root = this.jm.mind.root;
            const view_data = root._data.view || {};
            const w = view_data.width || 100;
            const h = view_data.height || 30;

            this.bounds.w = Math.min(this.bounds.w, -w / 2);
            this.bounds.e = Math.max(this.bounds.e, w / 2);
            this.bounds.n = Math.min(this.bounds.n, -h / 2);
            this.bounds.s = Math.max(this.bounds.s, h / 2);
        }

        get_node_offset(node) {
            const layout_data = node._data.layout;
            return {
                x: layout_data.abs_x || 0,
                y: layout_data.abs_y || 0
            };
        }

        get_min_size() {
            const nodes = this.jm.mind.nodes;
            let min_width = 0;
            let min_height = 0;

            for (let id in nodes) {
                const node = nodes[id];
                const layout_data = node._data.layout || {};
                const view_data = node._data.view || {};
                const x = Math.abs(layout_data.abs_x || 0);
                const y = Math.abs(layout_data.abs_y || 0);
                const w = view_data.width || 50;
                const h = view_data.height || 20;
                min_width = Math.max(min_width, x + w);
                min_height = Math.max(min_height, y + h);
            }

            return { w: min_width * 2 + 100, h: min_height * 2 + 100 };
        }
    }

    // View provider (renders the mind map)
    class ViewProvider {
        constructor(jm, container) {
            this.jm = jm;
            this.container = container;
            this.e_panel = null;
            this.e_nodes = null;
            this.e_canvas = null;
            this.canvas_ctx = null;
            this.size = { w: 0, h: 0 };
            this.selected_node = null;
            this.editing_node = null;
            this.layout = {
                hspace: 30,
                vspace: 20,
                pspace: 13,
            };
        }

        init_nodes() {
            const f = $c('div');
            f.className = 'jmnodes theme-' + this.jm.options.theme;
            this.e_nodes = f;
            this.e_panel.appendChild(f);
        }

        init_canvas() {
            const f = $c('canvas');
            f.className = 'jsmind';
            this.e_canvas = f;
            this.canvas_ctx = f.getContext('2d');
            this.e_panel.appendChild(f);
        }

        add_event(node, event_name, handler) {
            node.addEventListener(event_name, handler);
        }

        reset() {
            this.selected_node = null;
            this.clear_lines();
            this.clear_nodes();
            this.reset_theme();
        }

        reset_theme() {
            if (this.e_nodes) {
                this.e_nodes.className = 'theme-' + this.jm.options.theme;
            }
        }

        clear_nodes() {
            const mind = this.jm.mind;
            if (mind == null) return;

            const nodes = mind.nodes;
            for (let node_id in nodes) {
                const node = nodes[node_id];
                node._data.view = null;
            }
            if (this.e_nodes) {
                this.e_nodes.innerHTML = '';
            }
        }

        clear_lines() {
            if (this.canvas_ctx) {
                this.canvas_ctx.clearRect(0, 0, this.size.w, this.size.h);
            }
        }

        show(mind) {
            this.reset();
            this.init_nodes();
            this._show(mind);
        }

        _show(mind) {
            const root = mind.root;
            this.create_node_element(root);

            const nodes = mind.nodes;
            for (let id in nodes) {
                const node = nodes[id];
                if (!node.isroot) {
                    this.create_node_element(node);
                }
            }

            // Layout
            this.jm.layout.layout();

            // Position nodes
            this.resize_container();
            this.position_nodes();
            this.draw_lines();
        }

        create_node_element(node) {
            const d = $c('jmnode');
            const d_topic = $c('span');
            $t(d_topic, node.topic);
            d.appendChild(d_topic);

            if (node.isroot) {
                d.className = 'root';
            }

            d.setAttribute('nodeid', node.id);
            d.style.display = 'none';
            this.e_nodes.appendChild(d);

            // Add event listener
            const jm = this.jm;
            this.add_event(d, 'click', function (e) {
                jm.select_node(node.id);
                e.stopPropagation();
            });

            this.add_event(d, 'dblclick', function (e) {
                jm.begin_edit(node.id);
                e.stopPropagation();
            });

            // Store in node data
            node._data.view = node._data.view || {};
            node._data.view.element = d;

            // Measure size
            d.style.visibility = 'hidden';
            d.style.display = '';
            const rect = d.getBoundingClientRect();
            node._data.view.width = rect.width;
            node._data.view.height = rect.height;
            d.style.visibility = '';

            // Create expander if has children
            if (node.children.length > 0 && !node.isroot) {
                this._create_expander(node);
            }
        }

        _create_expander(node) {
            const e = $c('jmexpander');
            e.textContent = node.expanded ? '-' : '+';
            this.e_nodes.appendChild(e);

            node._data.view.expander = e;

            const jm = this.jm;
            this.add_event(e, 'click', function (ev) {
                jm.toggle_node(node.id);
                ev.stopPropagation();
            });
        }

        resize_container() {
            const min_size = this.jm.layout.get_min_size();
            const w = Math.max(min_size.w, this.container.clientWidth);
            const h = Math.max(min_size.h, this.container.clientHeight);

            this.size.w = w;
            this.size.h = h;

            if (this.e_canvas) {
                this.e_canvas.width = w;
                this.e_canvas.height = h;
            }
        }

        position_nodes() {
            const center_x = this.size.w / 2;
            const center_y = this.size.h / 2;

            const nodes = this.jm.mind.nodes;
            for (let id in nodes) {
                this._position_node(nodes[id], center_x, center_y);
            }
        }

        _position_node(node, center_x, center_y) {
            const view_data = node._data.view;
            if (!view_data || !view_data.element) return;

            const layout_data = node._data.layout || {};
            const x = layout_data.abs_x || 0;
            const y = layout_data.abs_y || 0;
            const w = view_data.width || 50;
            const h = view_data.height || 20;

            const left = center_x + x - w / 2;
            const top = center_y + y - h / 2;

            view_data.element.style.left = left + 'px';
            view_data.element.style.top = top + 'px';
            view_data.element.style.display = '';

            // Position expander
            if (view_data.expander) {
                const direction = layout_data.direction || 1;
                let exp_left, exp_top;
                if (direction === -1) {
                    exp_left = left - 8;
                } else {
                    exp_left = left + w - 8;
                }
                exp_top = top + h / 2 - 8;
                view_data.expander.style.left = exp_left + 'px';
                view_data.expander.style.top = exp_top + 'px';
                view_data.expander.style.display = node.children.length > 0 ? '' : 'none';
            }
        }

        draw_lines() {
            this.clear_lines();
            if (!this.canvas_ctx) return;

            const ctx = this.canvas_ctx;
            ctx.strokeStyle = this.jm.options.view.line_color || '#555';
            ctx.lineWidth = this.jm.options.view.line_width || 2;
            ctx.lineCap = 'round';

            const center_x = this.size.w / 2;
            const center_y = this.size.h / 2;

            const root = this.jm.mind.root;
            this._draw_lines_for_node(root, center_x, center_y);
        }

        _draw_lines_for_node(node, center_x, center_y) {
            if (!node.expanded) return;

            const children = node.children;
            const count = children.length;
            if (count === 0) return;

            const ctx = this.canvas_ctx;
            const view_data = node._data.view || {};
            const layout_data = node._data.layout || {};

            const p_x = center_x + (layout_data.abs_x || 0);
            const p_y = center_y + (layout_data.abs_y || 0);
            const p_w = view_data.width || 50;
            const p_h = view_data.height || 20;

            for (let i = 0; i < count; i++) {
                const child = children[i];
                const child_view = child._data.view || {};
                const child_layout = child._data.layout || {};

                const c_x = center_x + (child_layout.abs_x || 0);
                const c_y = center_y + (child_layout.abs_y || 0);
                const c_w = child_view.width || 50;
                const c_h = child_view.height || 20;

                // Draw bezier curve
                const direction = child_layout.direction || 1;
                let sp_x, ep_x;

                if (direction === -1) {
                    sp_x = p_x - p_w / 2;
                    ep_x = c_x + c_w / 2;
                } else {
                    sp_x = p_x + p_w / 2;
                    ep_x = c_x - c_w / 2;
                }

                const sp_y = p_y;
                const ep_y = c_y;

                ctx.beginPath();
                ctx.moveTo(sp_x, sp_y);

                const cp1_x = sp_x + (ep_x - sp_x) * 0.5;
                const cp1_y = sp_y;
                const cp2_x = sp_x + (ep_x - sp_x) * 0.5;
                const cp2_y = ep_y;

                ctx.bezierCurveTo(cp1_x, cp1_y, cp2_x, cp2_y, ep_x, ep_y);
                ctx.stroke();

                // Recursively draw for children
                this._draw_lines_for_node(child, center_x, center_y);
            }
        }

        select_node(node) {
            if (this.selected_node) {
                const prev_view = this.selected_node._data.view;
                if (prev_view && prev_view.element) {
                    prev_view.element.classList.remove('selected');
                }
            }

            this.selected_node = node;
            if (node && node._data.view && node._data.view.element) {
                node._data.view.element.classList.add('selected');
            }
        }

        select_clear() {
            if (this.selected_node) {
                const view_data = this.selected_node._data.view;
                if (view_data && view_data.element) {
                    view_data.element.classList.remove('selected');
                }
            }
            this.selected_node = null;
        }

        get_node_element(nodeid) {
            const node = this.jm.mind.get_node(nodeid);
            if (node && node._data.view) {
                return node._data.view.element;
            }
            return null;
        }

        get_bounding_rect(node) {
            const view_data = node._data.view;
            if (view_data && view_data.element) {
                return view_data.element.getBoundingClientRect();
            }
            return null;
        }

        set_theme(theme_name) {
            if (this.e_nodes) {
                this.e_nodes.className = 'theme-' + theme_name;
            }
        }

        update_node(node) {
            const view_data = node._data.view;
            if (view_data && view_data.element) {
                $t(view_data.element.firstChild, node.topic);
                // Recalculate size
                const rect = view_data.element.getBoundingClientRect();
                view_data.width = rect.width;
                view_data.height = rect.height;
            }
        }

        begin_edit(node) {
            const view_data = node._data.view;
            if (!view_data || !view_data.element) return;

            const element = view_data.element;
            const rect = element.getBoundingClientRect();
            const container_rect = this.container.getBoundingClientRect();

            const input = $c('input');
            input.className = 'jmnode-input';
            input.type = 'text';
            input.value = node.topic;
            input.style.width = Math.max(rect.width, 100) + 'px';
            input.style.left = (rect.left - container_rect.left) + 'px';
            input.style.top = (rect.top - container_rect.top) + 'px';

            this.container.appendChild(input);
            input.focus();
            input.select();

            this.editing_node = node;

            const self = this;
            const finish_edit = function () {
                const new_topic = input.value.trim();
                if (new_topic && new_topic !== node.topic) {
                    self.jm.update_node(node.id, new_topic);
                }
                self.container.removeChild(input);
                self.editing_node = null;
            };

            input.addEventListener('blur', finish_edit);
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    input.blur();
                } else if (e.key === 'Escape') {
                    input.value = node.topic;
                    input.blur();
                }
            });
        }

        remove_node(node) {
            const view_data = node._data.view;
            if (view_data) {
                if (view_data.element && view_data.element.parentNode) {
                    view_data.element.parentNode.removeChild(view_data.element);
                }
                if (view_data.expander && view_data.expander.parentNode) {
                    view_data.expander.parentNode.removeChild(view_data.expander);
                }
            }
        }

        refresh() {
            this.jm.layout.layout();
            this.resize_container();
            this.position_nodes();
            this.draw_lines();
        }
    }

    // Main jsMind class
    class jsMind {
        constructor(options) {
            this.options = {
                container: null,
                theme: 'primary',
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
                    enable: true,
                },
            };

            // Merge options (with defensive checks)
            if (options) {
                for (let key in options) {
                    if (typeof options[key] === 'object' && !Array.isArray(options[key]) && options[key] !== null) {
                        // Ensure the target object exists
                        if (!this.options[key] || typeof this.options[key] !== 'object') {
                            this.options[key] = {};
                        }
                        for (let subkey in options[key]) {
                            this.options[key][subkey] = options[key][subkey];
                        }
                    } else {
                        this.options[key] = options[key];
                    }
                }
            }

            this.mind = null;
            this.event_listeners = [];

            // Get container
            if (typeof this.options.container === 'string') {
                this.container = $g(this.options.container);
            } else {
                this.container = this.options.container;
            }

            if (!this.container) {
                throw new Error('jsMind: container not found');
            }

            // Create inner panel
            const panel = $c('div');
            panel.className = 'jsmind-inner';
            this.container.appendChild(panel);

            // Initialize components
            this.view = new ViewProvider(this, panel);
            this.view.e_panel = panel;
            this.view.layout = this.options.layout;
            this.layout = new LayoutProvider(this);

            // Initialize canvas
            this.view.init_canvas();

            logger.info('jsMind initialized');
        }

        show(mind_data) {
            this.mind = DataProvider.node_tree.get_mind(mind_data);
            this.view.show(this.mind);
        }

        get_data(format) {
            if (format === 'node_tree') {
                return DataProvider.node_tree.get_data(this.mind);
            }
            return null;
        }

        get_root() {
            return this.mind ? this.mind.root : null;
        }

        get_node(nodeid) {
            return this.mind ? this.mind.get_node(nodeid) : null;
        }

        add_node(parent_id, nodeid, topic, data) {
            const parent = this.mind.get_node(parent_id);
            if (!parent) {
                logger.error('parent node not found: ' + parent_id);
                return null;
            }

            const node = this.mind.add_node(parent, nodeid, topic, data || {});
            this.view.create_node_element(node);
            this.view.refresh();

            this._fire_event(1, { evt: 'add_node', node: nodeid });
            return node;
        }

        remove_node(nodeid) {
            const node = this.mind.get_node(nodeid);
            if (!node) {
                logger.error('node not found: ' + nodeid);
                return false;
            }

            if (this.view.selected_node === node) {
                this.view.select_clear();
            }

            // Remove from view
            this._remove_node_recursive(node);

            // Remove from model
            this.mind.remove_node(node);

            this.view.refresh();
            this._fire_event(1, { evt: 'remove_node', node: nodeid });
            return true;
        }

        _remove_node_recursive(node) {
            for (let child of node.children) {
                this._remove_node_recursive(child);
            }
            this.view.remove_node(node);
        }

        update_node(nodeid, topic) {
            const node = this.mind.get_node(nodeid);
            if (!node) {
                logger.error('node not found: ' + nodeid);
                return;
            }

            node.topic = topic;
            this.view.update_node(node);
            this.view.refresh();

            this._fire_event(2, { evt: 'update_node', node: nodeid });
        }

        move_node(nodeid, before_id, parent_id) {
            // Basic move implementation
            const node = this.mind.get_node(nodeid);
            if (!node) return;

            const new_parent = this.mind.get_node(parent_id);
            if (!new_parent) return;

            // Remove from current parent
            const old_parent = node.parent;
            const old_index = old_parent.children.indexOf(node);
            if (old_index > -1) {
                old_parent.children.splice(old_index, 1);
            }

            // Add to new parent
            node.parent = new_parent;
            node.direction = new_parent.isroot ? ((new_parent.children.length % 2 === 0) ? -1 : 1) : new_parent.direction;
            new_parent.children.push(node);

            this.view.refresh();
            this._fire_event(1, { evt: 'move_node', node: nodeid });
        }

        select_node(nodeid) {
            const node = this.mind.get_node(nodeid);
            if (node) {
                this.mind.selected = node;
                this.view.select_node(node);
                this._fire_event(1, { evt: 'select', node: nodeid });
            }
        }

        get_selected_node() {
            return this.mind ? this.mind.selected : null;
        }

        begin_edit(nodeid) {
            if (!this.options.editable) return;

            const node = this.mind.get_node(nodeid);
            if (node) {
                this.view.begin_edit(node);
            }
        }

        toggle_node(nodeid) {
            const node = this.mind.get_node(nodeid);
            if (node) {
                if (node.expanded) {
                    this.collapse_node(nodeid);
                } else {
                    this.expand_node(nodeid);
                }
            }
        }

        expand_node(nodeid) {
            const node = this.mind.get_node(nodeid);
            if (node && !node.expanded) {
                node.expanded = true;
                if (node._data.view && node._data.view.expander) {
                    node._data.view.expander.textContent = '-';
                }
                this.view.refresh();
                this._fire_event(1, { evt: 'expand', node: nodeid });
            }
        }

        collapse_node(nodeid) {
            const node = this.mind.get_node(nodeid);
            if (node && node.expanded) {
                node.expanded = false;
                if (node._data.view && node._data.view.expander) {
                    node._data.view.expander.textContent = '+';
                }
                this.view.refresh();
                this._fire_event(1, { evt: 'collapse', node: nodeid });
            }
        }

        expand_all() {
            const nodes = this.mind.nodes;
            for (let id in nodes) {
                nodes[id].expanded = true;
                if (nodes[id]._data.view && nodes[id]._data.view.expander) {
                    nodes[id]._data.view.expander.textContent = '-';
                }
            }
            this.view.refresh();
        }

        collapse_all() {
            const nodes = this.mind.nodes;
            for (let id in nodes) {
                if (!nodes[id].isroot) {
                    nodes[id].expanded = false;
                    if (nodes[id]._data.view && nodes[id]._data.view.expander) {
                        nodes[id]._data.view.expander.textContent = '+';
                    }
                }
            }
            this.view.refresh();
        }

        set_theme(theme_name) {
            this.options.theme = theme_name;
            this.view.set_theme(theme_name);
        }

        add_event_listener(callback) {
            if (typeof callback === 'function') {
                this.event_listeners.push(callback);
            }
        }

        _fire_event(type, data) {
            for (let listener of this.event_listeners) {
                listener(type, data);
            }
        }

        resize() {
            this.view.refresh();
        }
    }

    // Add version as static property (ES5 compatible)
    jsMind.version = '0.5.0-odoo';

    return jsMind;
}));
