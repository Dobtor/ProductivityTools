/** @odoo-module **/

/**
 * Context bridge: expose "insert mind map" in every rich-text (html) field.
 *
 * html_field.js's getConfig() already provides { resModel, resId } through
 * config.getRecordInfo(); this patch only:
 *   1. adds XmindPowerboxPlugin to config.Plugins (the "/" command), and
 *   2. registers the live mind map embedding in embedded_components.
 *
 * Mounted only when the field enables embeddedComponents (widget="html" default),
 * since both the command and the embedded block depend on that plugin.
 */
import { patch } from "@web/core/utils/patch";
import { HtmlField } from "@html_editor/fields/html_field";
import { XmindPowerboxPlugin } from "@dobtor_xmind/editor/xmind_powerbox_plugin";
import {
    xmindMindmapEmbedding,
    readonlyXmindMindmapEmbedding,
} from "@dobtor_xmind/editor/xmind_mindmap_embedding";

patch(HtmlField.prototype, {
    getConfig() {
        const config = super.getConfig();
        if (this.props.embeddedComponents) {
            config.Plugins = [...config.Plugins, XmindPowerboxPlugin];
            config.resources = config.resources || {};
            config.resources.embedded_components = [
                ...(config.resources.embedded_components || []),
                xmindMindmapEmbedding,
            ];
        }
        return config;
    },

    getReadonlyConfig() {
        const config = super.getReadonlyConfig();
        if (this.props.embeddedComponents) {
            config.embeddedComponents = [
                ...(config.embeddedComponents || []),
                readonlyXmindMindmapEmbedding,
            ];
        }
        return config;
    },
});
