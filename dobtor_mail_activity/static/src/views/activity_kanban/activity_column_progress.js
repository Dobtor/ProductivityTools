/** @odoo-module */

import { Component } from "@odoo/owl";
import { AnimatedNumber } from "@web/views/view_components/animated_number";

/**
 * 自訂活動進度條組件
 * 根據總工時顯示顏色：
 * - 未滿8小時 --> 紅色 (danger)
 * - 8～9小時 --> 綠色 (success)
 * - 9小時以上 --> 紅色 (danger)
 */
export class ActivityColumnProgress extends Component {
    static components = {
        AnimatedNumber,
    };
    static template = "dobtor_mail_activity.ActivityColumnProgress";
    static props = {
        aggregate: { type: Object },
        group: { type: Object },
        onBarClicked: { type: Function, optional: true },
        progressBar: { type: Object },
    };
    static defaultProps = {
        onBarClicked: () => {},
    };

    /**
     * 根據總工時計算進度條顏色
     * @returns {string} Bootstrap 顏色類名 (danger, success, warning)
     */
    get progressBarColor() {
        const totalHours = this.props.aggregate.value || 0;

        if (totalHours < 8) {
            return 'danger';   // 紅色：未滿8小時
        } else if (totalHours <= 9) {
            return 'success';  // 綠色：8～9小時
        } else {
            return 'warning';  // 黃色：超過9小時
        }
    }

    /**
     * 取得進度條的提示文字
     */
    get progressTooltip() {
        const totalHours = this.props.aggregate.value || 0;

        if (totalHours < 8) {
            return `${totalHours.toFixed(1)} hours (under 8 hours)`;
        } else if (totalHours <= 9) {
            return `${totalHours.toFixed(1)} hours (8-9 hours target achieved)`;
        } else {
            return `${totalHours.toFixed(1)} hours (over 9 hours)`;
        }
    }

    /**
     * 計算進度百分比（以9小時為100%）
     */
    get progressPercentage() {
        const totalHours = this.props.aggregate.value || 0;
        const percentage = (totalHours / 9) * 100;
        return Math.min(percentage, 100);
    }

    async onBarClick(bar) {
        await this.props.onBarClicked(bar);
    }
}
