/** @odoo-module **/
/**
 * MessagingPartnerCard
 *
 * Avatar-card popover for res.partner records that have NO linked res.users
 * (external messaging contacts created from inbound webhooks). Odoo's native
 * AvatarCardPopover reads `res.users` by `persona.userId`; for these userless
 * partners that id is `false`, which crashes ("Invalid ids list: false").
 *
 * This provider-agnostic component reads `res.partner` directly so any platform
 * (LINE, Telegram, ...) can show the contact's name, email, phone and a button
 * to open the full contact form.
 */

import { Component, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class MessagingPartnerCard extends Component {
    static template = "dobtor_messaging_base.MessagingPartnerCard";

    static props = {
        id: { type: Number, required: true }, // res.partner id
        close: { type: Function, required: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.partner = {};
        onWillStart(async () => {
            const records = await this.orm.read("res.partner", [this.props.id], this.fieldNames);
            this.partner = records[0] || {};
        });
    }

    get fieldNames() {
        return ["name", "email", "phone", "mobile", "function"];
    }

    get avatarUrl() {
        return `/web/image/res.partner/${this.props.id}/avatar_128`;
    }

    async onClickViewContact() {
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: this.props.id,
            views: [[false, "form"]],
            target: "current",
        });
        this.props.close();
    }
}
