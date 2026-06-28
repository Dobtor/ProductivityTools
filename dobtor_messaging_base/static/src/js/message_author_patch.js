/** @odoo-module **/
/**
 * Message author avatar patch (provider-agnostic).
 *
 * In a messaging channel, message authors are res.partner records without a
 * linked res.users, so Odoo's native author card (gated on `author.userId`) is
 * never clickable. Here we make the avatar clickable inside messaging channels
 * and open our MessagingPartnerCard (res.partner). Non-messaging channels keep
 * the native behaviour untouched.
 */

import { Message } from "@mail/core/common/message";
import { markEventHandled } from "@web/core/utils/misc";
import { usePopover } from "@web/core/popover/popover_hook";
import { patch } from "@web/core/utils/patch";
import { MessagingPartnerCard } from "./messaging_partner_card";

patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        this.messagingPartnerCard = usePopover(MessagingPartnerCard, { position: "bottom" });
    },
    hasAuthorClickable() {
        if (super.hasAuthorClickable()) {
            return true;
        }
        return Boolean(this.message.thread?.isMessagingChannel && this.message.author?.id);
    },
    onClickAuthor(ev) {
        if (this.message.author?.userId) {
            return super.onClickAuthor(ev);
        }
        if (this.message.thread?.isMessagingChannel && this.message.author?.id) {
            markEventHandled(ev, "Message.ClickAuthor");
            if (!this.messagingPartnerCard.isOpen) {
                this.messagingPartnerCard.open(ev.currentTarget, { id: this.message.author.id });
            }
        }
    },
});
