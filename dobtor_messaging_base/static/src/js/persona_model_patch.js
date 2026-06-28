/** @odoo-module */

import { Persona } from "@mail/core/common/persona_model";
import { Record } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";

/**
 * 在 Persona 上掛「所屬公司」（由後端 res.partner._to_store 派生帶入），
 * 供成員面板依公司分組與指派。
 */
patch(Persona.prototype, {
    setup() {
        super.setup();
        this.messagingCompanyId = Record.attr(false);
        this.messagingCompanyName = Record.attr(false);
    },
});
