/** @odoo-module */

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { RelatedNotes } from "@dobtor_mail_activity/components/related_notes/related_notes";
import { patch } from "@web/core/utils/patch";

/**
 * Chatter Patch - 添加關聯筆記顯示
 *
 * 在文件的 Chatter 中顯示從 note.note 轉移過來的活動所關聯的筆記
 */
patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
    },
});

// 添加 RelatedNotes 組件到 Chatter
patch(Chatter, {
    components: {
        ...Chatter.components,
        RelatedNotes,
    },
});
