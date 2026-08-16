/** @odoo-module */

import { Store } from "@mail/core/common/store_service";
import { patch } from "@web/core/utils/patch";
import { openActivityWizard, ACTIVITY_WIZARDS } from "@dobtor_mail_activity/utils/activity_actions";

/**
 * 將原生 chatter「排程活動」/ 活動視圖排程導向統一的建立待辦 wizard
 * (mail.activity.create.wizard)，讓所有建立待辦 UX 共用同一畫面。
 *
 * 沿用原生傳入的 active_model/active_ids（→ 已知目標、唯讀顯示），
 * 因此單筆與批次（多選記錄排程）皆可運作。
 */
patch(Store.prototype, {
    async scheduleActivity(resModel, resIds, defaultActivityTypeId = undefined) {
        const context = {
            active_model: resModel,
            active_ids: resIds,
            active_id: resIds && resIds.length ? resIds[0] : false,
            ...(defaultActivityTypeId !== undefined
                ? { default_activity_type_id: defaultActivityTypeId }
                : {}),
        };
        return new Promise((resolve) =>
            openActivityWizard(
                this.env.services.action,
                ACTIVITY_WIZARDS.create,
                context,
                { onClose: resolve }
            )
        );
    },
});
