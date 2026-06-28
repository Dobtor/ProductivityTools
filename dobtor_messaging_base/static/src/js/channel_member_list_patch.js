/** @odoo-module */
/**
 * Channel member list patch.
 *
 * Two concerns merged here:
 *
 * 1. Company-centric panel: group members by company, add a company bucket from
 *    the top autocomplete, and assign a member to a company (writing
 *    res.partner.parent_id). Each bucket keeps the native online/offline split.
 *
 * 2. Userless-contact avatar: external messaging contacts are res.partner
 *    records without a linked res.users. The native avatar click opens the
 *    AvatarCardPopover with `persona.userId`; for these contacts that id is
 *    `false`, so `read("res.users", [false])` crashes. We intercept and open the
 *    provider-agnostic MessagingPartnerCard (res.partner) instead. Members
 *    backed by a real res.users keep the native behaviour.
 */

import { ChannelMemberList } from "@mail/discuss/core/common/channel_member_list";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/core/popover/popover_hook";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { CompanyAutocomplete } from "./company_autocomplete";
import { MessagingPartnerCard } from "./messaging_partner_card";

patch(ChannelMemberList.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.messagingPartnerCard = usePopover(MessagingPartnerCard, { position: "right" });
    },

    /** Public pages (livechat, ...) do not show the company-management UI. */
    get canManageCompanies() {
        return !this.store.inPublicPage;
    },

    /** Companies available in the assign dropdown (the panel's buckets). */
    get companyChoices() {
        return this.props.thread.panelCompanies || [];
    },

    /** Top "add a company": value is an existing company id or a new name. */
    async addCompany(value) {
        const company = await this.orm.call(
            "discuss.channel",
            "action_messaging_add_company",
            [[this.props.thread.id], value]
        );
        this._pushPanelCompany(company);
    },

    /** Assign a member to a company (companyId false -> unassign). */
    async assignMemberCompany(member, companyId) {
        const partnerId = member.persona?.id;
        if (!partnerId || member.persona?.type !== "partner") {
            return;
        }
        const result = await this.orm.call(
            "discuss.channel",
            "action_messaging_assign_member_company",
            [[this.props.thread.id], partnerId, companyId || false]
        );
        // Optimistically update this persona's company -> membersByCompany re-buckets.
        member.persona.messagingCompanyId = result.company ? result.company.id : false;
        member.persona.messagingCompanyName = result.company ? result.company.name : false;
        if (result.company) {
            this._pushPanelCompany(result.company);
        }
    },

    _pushPanelCompany(company) {
        if (!company) {
            return;
        }
        const list = this.props.thread.panelCompanies || [];
        if (!list.some((c) => c.id === company.id)) {
            this.props.thread.panelCompanies = [...list, company];
        }
    },

    onClickAvatar(ev, member) {
        if (!member.persona?.userId) {
            if (member.persona?.id && !this.messagingPartnerCard.isOpen) {
                this.messagingPartnerCard.open(ev.currentTarget, { id: member.persona.id });
            }
            return;
        }
        return super.onClickAvatar(ev, member);
    },
});

ChannelMemberList.components = {
    ...ChannelMemberList.components,
    CompanyAutocomplete,
    Dropdown,
    DropdownItem,
};
ChannelMemberList.template = "dobtor_messaging_base.ChannelMemberList";
