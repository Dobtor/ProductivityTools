/** @odoo-module **/

// Adds a "create / open mind map" button to the dobtor_project Gantt toolbar.
// Lives in dobtor_xmind (one-way: dobtor_xmind depends on dobtor_project), so the
// button only exists when this module is installed.

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { useState, onWillStart } from "@odoo/owl";
import { GanttController } from "@dobtor_project/components/gantt_view/gantt_controller";

patch(GanttController.prototype, {
    setup() {
        super.setup();
        // null = not loaded / no project selected → button hidden.
        this.xmindState = useState({ count: null });
        onWillStart(() => this._loadXmindWorkbookCount());
    },

    async _loadXmindWorkbookCount() {
        const projectId = this._getProjectIdFromContext();
        if (!projectId) {
            this.xmindState.count = null;
            return;
        }
        try {
            const recs = await this.orm.read(
                "project.project", [projectId], ["xmind_workbook_count"]
            );
            this.xmindState.count = recs?.[0]?.xmind_workbook_count ?? 0;
        } catch {
            this.xmindState.count = null;
        }
    },

    get showMindmapButton() {
        // Only when a single project is in scope (count loaded).
        return this.xmindState.count !== null;
    },

    get showCreateMindmap() {
        return this.xmindState.count === 0;
    },

    get showOpenMindmap() {
        return (this.xmindState.count || 0) > 0;
    },

    async onCreateMindmap() {
        const projectId = this._getProjectIdFromContext();
        if (!projectId) {
            this.notification.add(_t("請先選擇專案。"), { type: "warning" });
            return;
        }
        // action_create_mindmap creates (if missing), syncs, and returns the
        // editor client action.
        const action = await this.orm.call(
            "project.project", "action_create_mindmap", [[projectId]]
        );
        this.xmindState.count = 1;
        if (action) {
            await this.action.doAction(action);
        }
    },

    async onOpenMindmap() {
        const projectId = this._getProjectIdFromContext();
        if (!projectId) {
            this.notification.add(_t("請先選擇專案。"), { type: "warning" });
            return;
        }
        const action = await this.orm.call(
            "project.project", "action_open_mindmaps", [[projectId]]
        );
        if (action) {
            await this.action.doAction(action);
        }
    },
});
