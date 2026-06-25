/** @odoo-module **/

/**
 * Context bridge：把「待辦 / 活動」功能掛進所有富文字（html）欄位。
 *
 * html_field.js 的 getConfig() 已經透過 config.getRecordInfo() 提供
 * { resModel, resId }，本 patch 只負責：
 *   1. 把 ActivityPowerboxPlugin 加入 config.Plugins（提供 / 斜線指令）。
 *   2. 把內嵌活動清單 embedding 加入 embedded_components 資源。
 *
 * 只有在欄位啟用 embeddedComponents（widget="html" 預設為 true）時才掛載，
 * 因為內嵌清單與插入指令都依賴 embeddedComponents plugin。
 */
import { patch } from "@web/core/utils/patch";
import { HtmlField } from "@html_editor/fields/html_field";
import { ActivityPowerboxPlugin } from "@dobtor_mail_activity/editor/activity_powerbox_plugin";
import {
    activityListEmbedding,
    readonlyActivityListEmbedding,
} from "@dobtor_mail_activity/editor/activity_list_embedding";
import {
    activityChipEmbedding,
    readonlyActivityChipEmbedding,
} from "@dobtor_mail_activity/editor/activity_chip_embedding";

patch(HtmlField.prototype, {
    getConfig() {
        const config = super.getConfig();
        if (this.props.embeddedComponents) {
            config.Plugins = [...config.Plugins, ActivityPowerboxPlugin];
            config.resources = config.resources || {};
            config.resources.embedded_components = [
                ...(config.resources.embedded_components || []),
                activityListEmbedding,
                activityChipEmbedding,
            ];
        }
        return config;
    },

    getReadonlyConfig() {
        const config = super.getReadonlyConfig();
        if (this.props.embeddedComponents) {
            config.embeddedComponents = [
                ...(config.embeddedComponents || []),
                readonlyActivityListEmbedding,
                readonlyActivityChipEmbedding,
            ];
        }
        return config;
    },
});
