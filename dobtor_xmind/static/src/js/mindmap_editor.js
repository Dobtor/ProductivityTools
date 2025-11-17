odoo.define('dobtor_xmind.MindmapEditor', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var rpc = require('web.rpc');
    var Dialog = require('web.Dialog');

    var _t = core._t;
    var QWeb = core.qweb;

    var MindmapEditor = AbstractAction.extend({
        template: 'dobtor_xmind.MindmapEditorTemplate',
        hasControlPanel: true,

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.workbookId = action.params && action.params.workbook_id;
            this.jm = null;
            this.autoSaveInterval = null;
            this.isDirty = false;
        },

        willStart: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                if (!self.workbookId) {
                    return Promise.reject('No workbook ID provided');
                }
                return self._loadMindmapData();
            });
        },

        start: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._initMindmap();
                self._setupEventHandlers();
                self._startAutoSave();
                self._updateControlPanel();
            });
        },

        destroy: function () {
            if (this.autoSaveInterval) {
                clearInterval(this.autoSaveInterval);
            }
            if (this.jm) {
                // Cleanup jsMind if needed
            }
            this._super.apply(this, arguments);
        },

        _loadMindmapData: function () {
            var self = this;
            return rpc.query({
                route: '/xmind/workbook/' + this.workbookId + '/data',
                params: {},
            }).then(function (data) {
                self.mindmapData = data;
            });
        },

        _initMindmap: function () {
            var self = this;
            var container = this.$('.o_xmind_canvas')[0];

            if (!container) {
                console.error('Mindmap container not found');
                return;
            }

            // Check if jsMind is available
            if (typeof jsMind === 'undefined') {
                console.error('jsMind library not loaded');
                this._showFallbackEditor();
                return;
            }

            var options = {
                container: container,
                editable: true,
                theme: 'primary',
                view: {
                    engine: 'canvas',
                    hmargin: 100,
                    vmargin: 50,
                    line_width: 2,
                    line_color: '#555'
                },
                layout: {
                    hspace: 30,
                    vspace: 20,
                    pspace: 13
                },
                shortcut: {
                    enable: true,
                    handles: {},
                    mapping: {
                        addchild: 45,  // Insert
                        addbrother: 13,  // Enter
                        editnode: 113,  // F2
                        delnode: 46,  // Delete
                        toggle: 32,  // Space
                        left: 37,
                        up: 38,
                        right: 39,
                        down: 40,
                    }
                }
            };

            this.jm = new jsMind(options);
            this.jm.show(this.mindmapData);

            // Set up jsMind events
            this.jm.add_event_listener(function (type, data) {
                self._onMindmapEvent(type, data);
            });
        },

        _showFallbackEditor: function () {
            // Fallback to simple tree view if jsMind not available
            var self = this;
            var $container = this.$('.o_xmind_canvas');
            $container.html('<div class="alert alert-warning">' +
                '<i class="fa fa-exclamation-triangle"></i> ' +
                _t('Visual editor not available. Please install jsMind library.') +
                '</div>' +
                '<div class="o_xmind_tree_fallback"></div>');

            // Simple tree rendering
            this._renderTreeFallback(this.mindmapData.data, $container.find('.o_xmind_tree_fallback'));
        },

        _renderTreeFallback: function (node, $parent, level) {
            level = level || 0;
            var self = this;
            var $item = $('<div class="o_xmind_tree_item" style="margin-left: ' + (level * 20) + 'px">');
            var $title = $('<span class="o_xmind_tree_title">' + _.escape(node.topic) + '</span>');
            $item.append($title);

            $title.on('dblclick', function () {
                var newTitle = prompt(_t('Edit topic:'), node.topic);
                if (newTitle && newTitle !== node.topic) {
                    node.topic = newTitle;
                    $title.text(newTitle);
                    self.isDirty = true;
                }
            });

            $parent.append($item);

            if (node.children) {
                node.children.forEach(function (child) {
                    self._renderTreeFallback(child, $parent, level + 1);
                });
            }
        },

        _setupEventHandlers: function () {
            var self = this;

            // Toolbar buttons
            this.$('.o_xmind_btn_add_child').on('click', function () {
                self._addChildTopic();
            });

            this.$('.o_xmind_btn_add_sibling').on('click', function () {
                self._addSiblingTopic();
            });

            this.$('.o_xmind_btn_delete').on('click', function () {
                self._deleteTopic();
            });

            this.$('.o_xmind_btn_save').on('click', function () {
                self._saveMindmap();
            });

            this.$('.o_xmind_btn_export').on('click', function () {
                self._exportMindmap();
            });

            this.$('.o_xmind_btn_expand_all').on('click', function () {
                if (self.jm) {
                    self.jm.expand_all();
                }
            });

            this.$('.o_xmind_btn_collapse_all').on('click', function () {
                if (self.jm) {
                    self.jm.collapse_all();
                }
            });

            this.$('.o_xmind_btn_zoom_in').on('click', function () {
                if (self.jm && self.jm.view) {
                    self.jm.view.zoomIn();
                }
            });

            this.$('.o_xmind_btn_zoom_out').on('click', function () {
                if (self.jm && self.jm.view) {
                    self.jm.view.zoomOut();
                }
            });

            // Note editor
            this.$('.o_xmind_note_input').on('change', function () {
                self._updateTopicNote($(this).val());
            });

            // Theme selector
            this.$('.o_xmind_theme_select').on('change', function () {
                var theme = $(this).val();
                if (self.jm) {
                    self.jm.set_theme(theme);
                }
            });
        },

        _onMindmapEvent: function (type, data) {
            this.isDirty = true;

            switch (type) {
                case 1:  // jsMind.event_type.show
                    console.log('Mindmap loaded');
                    break;
                case 2:  // jsMind.event_type.resize
                    break;
                case 3:  // jsMind.event_type.edit
                    this._onTopicEdit(data);
                    break;
                case 4:  // jsMind.event_type.select
                    this._onTopicSelect(data);
                    break;
            }
        },

        _onTopicSelect: function (data) {
            var node = this.jm.get_selected_node();
            if (node) {
                this.$('.o_xmind_selected_topic').text(node.topic);
                this.$('.o_xmind_note_input').val(node.data && node.data.note || '');
            }
        },

        _onTopicEdit: function (data) {
            // Topic was edited
            this.isDirty = true;
        },

        _addChildTopic: function () {
            if (!this.jm) return;

            var selectedNode = this.jm.get_selected_node();
            if (!selectedNode) {
                this._showNotification(_t('Please select a topic first'), 'warning');
                return;
            }

            var newId = 'topic_' + Date.now();
            var newTopic = _t('New Topic');
            this.jm.add_node(selectedNode, newId, newTopic);
            this.isDirty = true;
        },

        _addSiblingTopic: function () {
            if (!this.jm) return;

            var selectedNode = this.jm.get_selected_node();
            if (!selectedNode || selectedNode.isroot) {
                this._showNotification(_t('Cannot add sibling to root topic'), 'warning');
                return;
            }

            var newId = 'topic_' + Date.now();
            var newTopic = _t('New Topic');
            this.jm.insert_node_after(selectedNode, newId, newTopic);
            this.isDirty = true;
        },

        _deleteTopic: function () {
            if (!this.jm) return;

            var selectedNode = this.jm.get_selected_node();
            if (!selectedNode) {
                this._showNotification(_t('Please select a topic first'), 'warning');
                return;
            }

            if (selectedNode.isroot) {
                this._showNotification(_t('Cannot delete root topic'), 'danger');
                return;
            }

            Dialog.confirm(this, _t('Delete this topic and all its children?'), {
                confirm_callback: function () {
                    this.jm.remove_node(selectedNode);
                    this.isDirty = true;
                }.bind(this)
            });
        },

        _updateTopicNote: function (note) {
            if (!this.jm) return;

            var selectedNode = this.jm.get_selected_node();
            if (selectedNode) {
                if (!selectedNode.data) {
                    selectedNode.data = {};
                }
                selectedNode.data.note = note;
                this.isDirty = true;
            }
        },

        _saveMindmap: function () {
            var self = this;
            if (!this.jm) return Promise.resolve();

            var data = this.jm.get_data('node_tree');

            return rpc.query({
                route: '/xmind/workbook/' + this.workbookId + '/save',
                params: { data: data },
            }).then(function (result) {
                if (result.success) {
                    self.isDirty = false;
                    self._showNotification(_t('Mind map saved successfully'), 'success');
                } else {
                    self._showNotification(_t('Failed to save mind map'), 'danger');
                }
            }).catch(function (error) {
                self._showNotification(_t('Error saving mind map: ') + error, 'danger');
            });
        },

        _exportMindmap: function () {
            window.location.href = '/xmind/export/' + this.workbookId;
        },

        _startAutoSave: function () {
            var self = this;
            // Auto-save every 60 seconds if dirty
            this.autoSaveInterval = setInterval(function () {
                if (self.isDirty) {
                    self._saveMindmap();
                }
            }, 60000);
        },

        _updateControlPanel: function () {
            this.updateControlPanel({
                title: this.mindmapData.meta ? this.mindmapData.meta.name : _t('Mind Map Editor'),
            });
        },

        _showNotification: function (message, type) {
            this.displayNotification({
                title: _t('XMind Editor'),
                message: message,
                type: type || 'info',
            });
        },
    });

    core.action_registry.add('xmind_editor', MindmapEditor);

    return MindmapEditor;
});
