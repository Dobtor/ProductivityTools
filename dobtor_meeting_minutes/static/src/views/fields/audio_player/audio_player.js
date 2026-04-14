/** @odoo-module */

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

/**
 * AudioPlayerField — 內嵌 HTML5 音訊播放器
 *
 * 用於在 list/form view 中直接播放音檔。
 * 綁定 Char 欄位（audio_url）。
 */
export class AudioPlayerField extends Component {
    static template = "dobtor_meeting_minutes.AudioPlayerField";
    static props = {
        ...standardFieldProps,
    };

    get audioUrl() {
        return this.props.record.data[this.props.name];
    }
}

registry.category("fields").add("audio_player", {
    component: AudioPlayerField,
    supportedTypes: ["char"],
});
