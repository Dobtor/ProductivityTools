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
     * 從 env 取得每日工時門檻
     */
    get _thresholds() {
        const hours = this.env.activityUserHours;
        return {
            target: hours?.dailyTarget ?? 8,
            max: hours?.dailyMax ?? 9,
        };
    }

    /**
     * 根據總工時計算進度條顏色
     * @returns {string} Bootstrap 顏色類名 (danger, success, warning)
     */
    get progressBarColor() {
        const totalHours = this.props.aggregate.value || 0;
        const { target, max } = this._thresholds;

        if (totalHours < target) {
            return 'danger';
        } else if (totalHours <= max) {
            return 'success';
        } else {
            return 'warning';
        }
    }

    /**
     * 取得進度條的提示文字
     */
    get progressTooltip() {
        const totalHours = this.props.aggregate.value || 0;
        const { target, max } = this._thresholds;

        if (totalHours < target) {
            return `${totalHours.toFixed(1)} hours (under ${target.toFixed(1)} hours)`;
        } else if (totalHours <= max) {
            return `${totalHours.toFixed(1)} hours (${target.toFixed(1)}-${max.toFixed(1)} hours target achieved)`;
        } else {
            return `${totalHours.toFixed(1)} hours (over ${max.toFixed(1)} hours)`;
        }
    }

    /**
     * 計算進度百分比（以 max 小時為100%）
     */
    get progressPercentage() {
        const totalHours = this.props.aggregate.value || 0;
        const { max } = this._thresholds;
        const percentage = (totalHours / max) * 100;
        return Math.min(percentage, 100);
    }

    async onBarClick(bar) {
        await this.props.onBarClicked(bar);
    }
}
