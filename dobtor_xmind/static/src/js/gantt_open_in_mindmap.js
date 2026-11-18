/** @odoo-module **/

/**
 * 甘特圖任務右鍵「在心智圖中開啟」。
 *
 * dobtor_project 的甘特圖不知道心智圖的存在（單向相依：dobtor_xmind 依賴
 * dobtor_project），所以從這邊 patch：
 *  - GanttModel._getFieldsToFetch：任務模型有 xmind_topic_id 時一併讀取；
 *  - GanttContextMenu.menuItems：任務連到心智圖主題時多一個選項；
 *  - GanttContextMenu.onMenuItemClick：自己處理這個選項（呼叫
 *    project.task.action_open_in_mindmap，開編輯器並選取該主題），
 *    不交給甘特圖的 onContextAction（它不認得這個 id）。
 */
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { GanttModel } from "@dobtor_project/components/gantt_view/gantt_model";
import { GanttContextMenu } from "@dobtor_project/components/gantt_view/gantt_context_menu";

const ITEM_ID = "dobtor_xmind_open_in_mindmap";

patch(GanttModel.prototype, {
    _getFieldsToFetch() {
        const fields = super._getFieldsToFetch(...arguments);
        if (this.fields && "xmind_topic_id" in this.fields && !fields.includes("xmind_topic_id")) {
            fields.push("xmind_topic_id");
        }
        return fields;
    },
});

patch(GanttContextMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.xmindOrm = useService("orm");
        this.xmindAction = useService("action");
    },

    get menuItems() {
        const items = super.menuItems;
        const record = this.record;
        if (record && !record._isMilestoneRecord && record.xmind_topic_id) {
            const pos = items.findIndex((i) => i.id === "open");
            items.splice(pos >= 0 ? pos + 1 : 0, 0, {
                id: ITEM_ID,
                label: _t("Open in Mind Map"),
                icon: "fa-share-alt",
            });
        }
        return items;
    },

    async onMenuItemClick(itemId) {
        if (itemId !== ITEM_ID) {
            return super.onMenuItemClick(...arguments);
        }
        this.state.visible = false;
        const action = await this.xmindOrm.call(
            "project.task", "action_open_in_mindmap", [[this.state.recordId]]);
        if (action) {
            await this.xmindAction.doAction(action);
        }
    },
});
