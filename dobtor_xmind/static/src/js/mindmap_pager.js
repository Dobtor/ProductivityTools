/** @odoo-module **/

/**
 * Top-right record pager for the mind map editor.
 *
 * The MindmapEditor is an imperative (non-reactive) god-component that mounts
 * jsMind into a raw DOM ref, so — exactly like MindmapProjectBar — we isolate the
 * reactive Odoo Pager widget inside this tiny self-contained child. Its state
 * changes re-render ONLY this component, never the parent → the canvas is untouched.
 *
 * The pager walks ALL readable workbooks (newest-edited first). Selecting another
 * page calls the parent's onNavigate(newId); the parent re-dispatches the client
 * action (stackPosition replaceCurrentAction), which tears the whole editor down
 * (autosave-on-exit runs) and mounts it fresh on the new id — so this child is
 * recreated with the new workbookId and naturally re-syncs its offset. No reload
 * API is needed.
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Pager } from "@web/core/pager/pager";

export class MindmapPager extends Component {
    static template = "dobtor_xmind.MindmapPager";
    static components = { Pager };
    static props = {
        workbookId: { type: [Number, Boolean], optional: true },
        onNavigate: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.ids = [];
        this.currentId = this.props.workbookId || null;
        this.state = useState({ total: 0, offset: 0 });
        onWillStart(async () => {
            await this._load();
        });
    }

    async _load() {
        try {
            this.ids = await this.orm.search("xmind.workbook", [], {
                order: "write_date desc",
            });
        } catch {
            this.ids = [];
        }
        const idx = this.ids.indexOf(this.currentId);
        this.state.total = this.ids.length;
        this.state.offset = idx >= 0 ? idx : 0;
    }

    /** Pager onUpdate → ask the parent to open the workbook at the new offset. */
    onPagerUpdate({ offset }) {
        const newId = this.ids[offset];
        if (newId && newId !== this.currentId) {
            this.state.offset = offset;
            this.props.onNavigate && this.props.onNavigate(newId);
        }
    }
}
