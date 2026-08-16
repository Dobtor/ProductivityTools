/** @odoo-module **/

/**
 * Command Pattern Implementation for Style Undo/Redo
 * Based on 's org.xmind.gef.command.CommandStack
 */

/**
 * Base Command Class - All commands inherit from this
 */
export class Command {
    constructor(label) {
        this.label = label || 'Command';
        this.canUndo = true;
    }

    execute() {
        throw new Error('execute() must be implemented');
    }

    undo() {
        throw new Error('undo() must be implemented');
    }

    redo() {
        this.execute();
    }

    getLabel() {
        return this.label;
    }
}

/**
 * Add Node Command
 */
export class AddNodeCommand extends Command {
    constructor(jm, parentId, nodeId, topic, data) {
        super('Add Node');
        this.jm = jm;
        this.parentId = parentId;
        this.nodeId = nodeId;
        this.topic = topic;
        this.data = data || {};
    }

    execute() {
        this.jm.add_node(this.parentId, this.nodeId, this.topic, this.data);
    }

    undo() {
        this.jm.remove_node(this.nodeId);
    }
}

/**
 * Remove Node Command
 */
export class RemoveNodeCommand extends Command {
    constructor(jm, nodeId) {
        super('Remove Node');
        this.jm = jm;
        this.nodeId = nodeId;
        this.nodeData = null;
        this.parentId = null;
        this.children = [];
    }

    execute() {
        const node = this.jm.get_node(this.nodeId);
        if (node) {
            this.nodeData = {
                id: node.id,
                topic: node.topic,
                data: JSON.parse(JSON.stringify(node.data || {})),
                expanded: node.expanded,
            };
            this.parentId = node.parent ? node.parent.id : null;
            this.children = this._saveChildren(node);
            this.jm.remove_node(this.nodeId);
        }
    }

    _saveChildren(node) {
        const children = [];
        if (node.children) {
            for (let child of node.children) {
                children.push({
                    id: child.id,
                    topic: child.topic,
                    data: JSON.parse(JSON.stringify(child.data || {})),
                    expanded: child.expanded,
                    children: this._saveChildren(child),
                });
            }
        }
        return children;
    }

    undo() {
        if (this.nodeData && this.parentId) {
            this.jm.add_node(this.parentId, this.nodeData.id, this.nodeData.topic, this.nodeData.data);
            this._restoreChildren(this.nodeData.id, this.children);
            if (!this.nodeData.expanded) {
                this.jm.collapse_node(this.nodeData.id);
            }
        }
    }

    _restoreChildren(parentId, children) {
        for (let child of children) {
            this.jm.add_node(parentId, child.id, child.topic, child.data);
            this._restoreChildren(child.id, child.children);
            if (!child.expanded) {
                this.jm.collapse_node(child.id);
            }
        }
    }
}

/**
 * Update Node Command
 */
export class UpdateNodeCommand extends Command {
    constructor(jm, nodeId, newTopic, oldTopic) {
        super('Update Node');
        this.jm = jm;
        this.nodeId = nodeId;
        this.newTopic = newTopic;
        this.oldTopic = oldTopic;
    }

    execute() {
        this.jm.update_node(this.nodeId, this.newTopic);
    }

    undo() {
        this.jm.update_node(this.nodeId, this.oldTopic);
    }
}

/**
 * Update Node Style Command
 */
export class UpdateNodeStyleCommand extends Command {
    constructor(jm, nodeId, newStyle, oldStyle) {
        super('Update Style');
        this.jm = jm;
        this.nodeId = nodeId;
        this.newStyle = newStyle;
        this.oldStyle = oldStyle;
    }

    execute() {
        const node = this.jm.get_node(this.nodeId);
        if (node) {
            node.data = node.data || {};
            node.data.style = this.newStyle;
            this._applyStyle(node);
        }
    }

    undo() {
        const node = this.jm.get_node(this.nodeId);
        if (node) {
            node.data = node.data || {};
            node.data.style = this.oldStyle;
            this._applyStyle(node);
        }
    }

    _applyStyle(node) {
        const element = this.jm.view.get_node_element(node.id);
        if (element && node.data && node.data.style) {
            const style = node.data.style;
            if (style.background) {
                element.style.backgroundColor = style.background;
            }
            if (style.color) {
                element.style.color = style.color;
            }
            if (style['font-size']) {
                element.style.fontSize = style['font-size'];
            }
            if (style['font-weight']) {
                element.style.fontWeight = style['font-weight'];
            }
            if (style['border-color']) {
                element.style.borderColor = style['border-color'];
            }
            if (style['border-width']) {
                element.style.borderWidth = style['border-width'];
            }
        }
    }
}

/**
 * Toggle Expand Command
 */
export class ToggleExpandCommand extends Command {
    constructor(jm, nodeId, expand) {
        super(expand ? 'Expand Node' : 'Collapse Node');
        this.jm = jm;
        this.nodeId = nodeId;
        this.expand = expand;
    }

    execute() {
        if (this.expand) {
            this.jm.expand_node(this.nodeId);
        } else {
            this.jm.collapse_node(this.nodeId);
        }
    }

    undo() {
        if (this.expand) {
            this.jm.collapse_node(this.nodeId);
        } else {
            this.jm.expand_node(this.nodeId);
        }
    }
}

/**
 * Command Stack - Manages command history (like )
 * Supports up to 200 undo steps (configurable)
 */
export class CommandStack {
    constructor(maxHistory = 200) {
        this.undoStack = [];
        this.redoStack = [];
        this.maxHistory = maxHistory;
        this.listeners = [];
        this.isDirty = false;
    }

    execute(command) {
        command.execute();
        this.undoStack.push(command);
        this.redoStack = [];

        if (this.undoStack.length > this.maxHistory) {
            this.undoStack.shift();
        }

        this.isDirty = true;
        this._notifyListeners();
    }

    undo() {
        if (this.canUndo()) {
            const command = this.undoStack.pop();
            command.undo();
            this.redoStack.push(command);
            this._notifyListeners();
            return command;
        }
        return null;
    }

    redo() {
        if (this.canRedo()) {
            const command = this.redoStack.pop();
            command.redo();
            this.undoStack.push(command);
            this._notifyListeners();
            return command;
        }
        return null;
    }

    canUndo() {
        return this.undoStack.length > 0;
    }

    canRedo() {
        return this.redoStack.length > 0;
    }

    getUndoLabel() {
        if (this.canUndo()) {
            return this.undoStack[this.undoStack.length - 1].getLabel();
        }
        return '';
    }

    getRedoLabel() {
        if (this.canRedo()) {
            return this.redoStack[this.redoStack.length - 1].getLabel();
        }
        return '';
    }

    clear() {
        this.undoStack = [];
        this.redoStack = [];
        this.isDirty = false;
        this._notifyListeners();
    }

    markSaved() {
        this.isDirty = false;
    }

    addListener(callback) {
        this.listeners.push(callback);
    }

    removeListener(callback) {
        const index = this.listeners.indexOf(callback);
        if (index > -1) {
            this.listeners.splice(index, 1);
        }
    }

    _notifyListeners() {
        for (let listener of this.listeners) {
            listener({
                canUndo: this.canUndo(),
                canRedo: this.canRedo(),
                undoLabel: this.getUndoLabel(),
                redoLabel: this.getRedoLabel(),
                commandCount: this.undoStack.length,
                isDirty: this.isDirty,
            });
        }
    }

    getCommandCount() {
        return this.undoStack.length;
    }
}
