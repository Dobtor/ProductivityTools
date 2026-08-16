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
        // syncing = a sync RPC is in flight (shows a spinner, blocks double-clicks).
        this.xmindState = useState({ count: null, syncing: false });
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
            this.notification.add(_t("Please select a project first."), { type: "warning" });
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
            this.notification.add(_t("Please select a project first."), { type: "warning" });
            return;
        }
        const action = await this.orm.call(
            "project.project", "action_open_mindmaps", [[projectId]]
        );
        if (action) {
            await this.action.doAction(action);
        }
    },

    /**
     * 重新同步：把目前的任務樹推進既有心智圖（專案 → 心智圖，單向）。
     *
     * 「建立心智圖」那顆本身就含一次同步，但之後按鈕會換成「開啟」，原本沒有
     * 任何從甘特圖再同步的入口 —— 得跳回專案表單按 header 的「同步心智圖」。
     *
     * action_sync_mindmap 回傳的是 display_notification 這種 client action，
     * 不會導頁，所以 doAction 之後留在甘特圖上。同步只寫 xmind 端、不動任務，
     * 因此不需要重載甘特資料。
     */
    async onSyncMindmap() {
        const projectId = this._getProjectIdFromContext();
        if (!projectId) {
            this.notification.add(_t("Please select a project first."), { type: "warning" });
            return;
        }
        if (this.xmindState.syncing) {
            return;
        }
        this.xmindState.syncing = true;
        try {
            const action = await this.orm.call(
                "project.project", "action_sync_mindmap", [[projectId]]
            );
            if (action) {
                await this.action.doAction(action);
            }
        } finally {
            this.xmindState.syncing = false;
        }
    },
});
