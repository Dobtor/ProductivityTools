/** @odoo-module **/

import { ActivityListPopover } from "@mail/core/web/activity_list_popover";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// Let a caller pre-fill the "Schedule Activity" wizard summary via an optional
// prop. The override only kicks in when the prop is set (the xmind activity
// clock passes it), so chatter / list-view popovers are untouched.
ActivityListPopover.props = [...ActivityListPopover.props, "scheduleDefaultSummary?"];

patch(ActivityListPopover.prototype, {
    onClickAddActivityButton() {
        const summary = this.props.scheduleDefaultSummary;
        if (!summary) {
            return super.onClickAddActivityButton();
        }
        const resIds = this.props.resIds ? this.props.resIds : [this.props.resId];
        this.env.services.action.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Schedule Activity"),
                res_model: "mail.activity.schedule",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: {
                    active_model: this.props.resModel,
                    active_ids: resIds,
                    active_id: this.props.resId,
                    ...(this.props.defaultActivityTypeId !== undefined
                        ? { default_activity_type_id: this.props.defaultActivityTypeId }
                        : {}),
                    default_summary: summary,
                },
            },
            { onClose: () => this.props.onActivityChanged() }
        );
        this.props.close();
    },
});
