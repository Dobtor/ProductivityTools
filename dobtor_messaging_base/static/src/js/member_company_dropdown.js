/** @odoo-module */
/**
 * MemberCompanyDropdown
 *
 * Per-member "assign company" dropdown for the Discuss member panel.
 *
 * Root-cause fix: previously this dropdown lived inline inside the
 * ``dobtor_messaging_base.channel_member`` template, which is rendered via
 * ``t-call`` inside nested ``t-foreach`` loops. Its menu is a lazily-rendered
 * slot, so the ``onSelected`` closures referencing the loop variable ``member``
 * could bind to a stale / re-bucketed member — clicking member A then assigned
 * member B.
 *
 * Making it a dedicated component with ``member`` as a **prop** isolates every
 * row: each instance carries its own ``props.member``, so the handler always
 * operates on the exact member whose dropdown was opened, regardless of OWL
 * instance reuse or slot timing.
 */

import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

export class MemberCompanyDropdown extends Component {
    static template = "dobtor_messaging_base.MemberCompanyDropdown";
    static components = { Dropdown, DropdownItem };
    static props = {
        member: { type: Object },
        companyChoices: { type: Array },
        // (member, companyId | false) => Promise<void> | void
        onAssign: { type: Function },
    };
}
