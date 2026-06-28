/** @odoo-module */
/**
 * Thread model patch.
 *
 * 1. Company-centric panel data: ``panelCompanies`` (bucket list from the
 *    backend) and ``membersByCompany`` (members grouped by their persona's
 *    company, each bucket split into online/offline).
 *
 * 2. Provider-agnostic messaging flags so other components (avatar/author
 *    patches, sidebar) can branch without knowing the provider.
 */

import { Thread } from "@mail/core/common/thread_model";
import { Record } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

const UNASSIGNED = 0;

patch(Thread.prototype, {
    setup() {
        super.setup();
        // Backend discuss.channel._channel_basic_info brings [{id, name}, ...].
        this.panelCompanies = Record.attr([]);
    },

    /** Any external messaging channel (LINE, Telegram, ...). */
    get isMessagingChannel() {
        return this.is_messaging_channel === true;
    },

    get messagingProvider() {
        return this.messaging_provider || false;
    },

    get isMessagingGroupChannel() {
        return this.isMessagingChannel && this.messaging_category === "group";
    },

    get isMessagingPersonalChannel() {
        return this.isMessagingChannel && this.messaging_category === "personal";
    },

    /**
     * Members grouped by company:
     *   [{ id, name, online: [members], offline: [members], count }]
     * - empty buckets are seeded from panelCompanies (assignment targets);
     * - each member is bucketed by persona.messagingCompanyId (0 -> Unassigned);
     * - within a bucket, split by the native onlineMemberStatuses;
     * - sorted by company name, Unassigned last.
     */
    get membersByCompany() {
        const store = this.store;
        const groups = new Map();
        const ensure = (id, name) => {
            if (!groups.has(id)) {
                groups.set(id, { id, name, members: [] });
            }
            return groups.get(id);
        };
        for (const company of this.panelCompanies || []) {
            ensure(company.id, company.name);
        }
        for (const member of this.channelMembers) {
            const companyId = member.persona?.messagingCompanyId || UNASSIGNED;
            const name =
                companyId === UNASSIGNED
                    ? _t("Unassigned")
                    : member.persona?.messagingCompanyName || _t("Company");
            ensure(companyId, name).members.push(member);
        }
        const isOnline = (member) =>
            store.onlineMemberStatuses.includes(member.persona?.im_status);
        const result = [...groups.values()].map((group) => ({
            id: group.id,
            name: group.name,
            online: group.members.filter(isOnline),
            offline: group.members.filter((member) => !isOnline(member)),
            count: group.members.length,
        }));
        result.sort((a, b) => {
            if (a.id === UNASSIGNED) {
                return 1;
            }
            if (b.id === UNASSIGNED) {
                return -1;
            }
            return (a.name || "").localeCompare(b.name || "");
        });
        return result;
    },
});
