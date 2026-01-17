/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * ActivityBox 組件
 * 用於在其他視圖中顯示活動摘要盒子
 */
export class ActivityBox extends Component {
    static template = "dobtor_mail_activity.ActivityBox";
    static props = {
        activity: { type: Object },
        showActions: { type: Boolean, optional: true },
        compact: { type: Boolean, optional: true },
    };
    static defaultProps = {
        showActions: true,
        compact: false,
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            isHovered: false,
        });
    }

    /**
     * 取得優先級 CSS class
     */
    get priorityClass() {
        const { urgency, importance } = this.props.activity;
        const classes = ['o_activity_box'];

        if (urgency === 'urgent') {
            classes.push('border-danger');
        } else if (urgency === 'flexible') {
            classes.push('border-success');
        }

        if (importance === 'important') {
            classes.push('bg-warning-subtle');
        }

        return classes.join(' ');
    }

    /**
     * 取得狀態徽章
     */
    get stateInfo() {
        const state = this.props.activity.activity_state || 'active';
        switch (state) {
            case 'done':
                return { label: _t('完成'), class: 'bg-success', icon: 'fa-check' };
            case 'cancelled':
                return { label: _t('取消'), class: 'bg-danger', icon: 'fa-times' };
            default:
                return { label: _t('進行中'), class: 'bg-primary', icon: 'fa-clock-o' };
        }
    }

    /**
     * 取得時間性標籤
     */
    get urgencyLabel() {
        const urgency = this.props.activity.urgency;
        switch (urgency) {
            case 'urgent':
                return { label: _t('緊急'), class: 'text-danger', icon: 'fa-exclamation-circle' };
            case 'flexible':
                return { label: _t('彈性'), class: 'text-success', icon: 'fa-leaf' };
            default:
                return null;
        }
    }

    /**
     * 開啟活動表單
     */
    async openActivity() {
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'mail.activity',
            res_id: this.props.activity.id,
            views: [[false, 'form']],
            target: 'new',
        });
    }

    /**
     * 標記完成
     */
    async markDone() {
        await this.orm.call(
            'mail.activity',
            'action_done_wizard',
            [[this.props.activity.id]]
        ).then(action => {
            this.actionService.doAction(action);
        });
    }

    /**
     * 延期
     */
    async postpone() {
        await this.orm.call(
            'mail.activity',
            'action_postpone_wizard',
            [[this.props.activity.id]]
        ).then(action => {
            this.actionService.doAction(action);
        });
    }

    /**
     * 開啟關聯文件
     */
    async openDocument() {
        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: this.props.activity.res_model,
            res_id: this.props.activity.res_id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    onMouseEnter() {
        this.state.isHovered = true;
    }

    onMouseLeave() {
        this.state.isHovered = false;
    }
}
