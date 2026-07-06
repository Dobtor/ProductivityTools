/** @odoo-module **/

/**
 * Context bridge: expose "insert process diagram" in every rich-text (html) field.
 *
 * html_field.js's getConfig() already provides { resModel, resId } through
 * config.getRecordInfo(); this patch only:
 *   1. adds BpmnPowerboxPlugin to config.Plugins (the "/" command), and
 *   2. registers the live diagram embedding in embedded_components.
 *
 * Mounted only when the field enables embeddedComponents (widget="html" default),
 * since both the command and the embedded block depend on that plugin.
 */
import { patch } from "@web/core/utils/patch";
import { HtmlField } from "@html_editor/fields/html_field";
import { BpmnPowerboxPlugin } from "@dobtor_bpmn/editor/bpmn_powerbox_plugin";
import {
    bpmnDiagramEmbedding,
    readonlyBpmnDiagramEmbedding,
} from "@dobtor_bpmn/editor/bpmn_diagram_embedding";

patch(HtmlField.prototype, {
    getConfig() {
        const config = super.getConfig();
        if (this.props.embeddedComponents) {
            config.Plugins = [...config.Plugins, BpmnPowerboxPlugin];
            config.resources = config.resources || {};
            config.resources.embedded_components = [
                ...(config.resources.embedded_components || []),
                bpmnDiagramEmbedding,
            ];
        }
        return config;
    },

    getReadonlyConfig() {
        const config = super.getReadonlyConfig();
        if (this.props.embeddedComponents) {
            config.embeddedComponents = [
                ...(config.embeddedComponents || []),
                readonlyBpmnDiagramEmbedding,
            ];
        }
        return config;
    },
});
