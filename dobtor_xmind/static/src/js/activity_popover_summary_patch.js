/** @odoo-module **/

import { ActivityListPopover } from "@mail/core/web/activity_list_popover";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// When the xmind activity clock opens this popover it passes a default summary
// (the node/task title). On "Schedule activity" we open the same unified
// "Create To-do" wizard the rest of the app uses (mail.activity.create.wizard,
// provided by dobtor_mail_activity — so its extended fields are present) with
// the summary pre-filled. The override only kicks in when the optional prop is
// set, so chatter / list-view popovers are untouched; if the unified wizard is
// not installed it falls back to the standard schedule flow.
ActivityListPopover.props = [...ActivityListPopover.props, "scheduleDefaultSummary?"];

patch(ActivityListPopover.prototype, {
    async onClickAddActivityButton() {
        const summary = this.props.scheduleDefaultSummary;
        if (!summary) {
            return super.onClickAddActivityButton();
        }
        const { resModel, resId, defaultActivityTypeId, onActivityChanged } = this.props;
        const resIds = this.props.resIds ? this.props.resIds : [resId];
        const context = {
            active_model: resModel,
            active_ids: resIds,
            active_id: resId,
            ...(defaultActivityTypeId !== undefined
                ? { default_activity_type_id: defaultActivityTypeId }
                : {}),
            default_summary: summary,
        };
        const action = this.env.services.action;
        const store = this.store;
        this.props.close();
        try {
            await action.doAction(
                {
                    type: "ir.actions.act_window",
                    name: _t("Create To-do"),
                    res_model: "mail.activity.create.wizard",
                    view_mode: "form",
                    views: [[false, "form"]],
                    target: "new",
                    context,
                },
                { onClose: () => onActivityChanged?.() }
            );
        } catch {
            // Unified wizard unavailable → standard schedule flow (no summary).
            await store.scheduleActivity(resModel, resIds, defaultActivityTypeId);
            onActivityChanged?.();
        }
    },
});
