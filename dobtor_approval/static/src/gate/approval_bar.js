/** @odoo-module **/
// Copyright 2026 Dobtor Systems Integration — License LGPL-3
/**
 * ApprovalBar — 注入單據表單頂部的簽核狀態列（DESIGN_INLINE_APPROVAL.md）。
 * - 未送簽：每個被攔方法一顆「送出簽核：<名>」。
 * - 送簽中：摘要（到哪關/給誰/送出時間）+ 可展開時間軸；依角色顯示批准/駁回/例外鈕。
 * - 已核准/駁回：徽章 + 申請人重送。
 */
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { setGatedMethods } from "./approval_store";

const INST = "bpmn.process.instance";

export class ApprovalBar extends Component {
    static template = "dobtor_approval.ApprovalBar";
    static props = { record: Object };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ data: null, expanded: false, busy: false });
        onWillStart(() => this._load(this.props.record));
        onWillUpdateProps((np) => {
            if (this._key(np.record) !== this._key(this.props.record)) {
                this._load(np.record);
            }
        });
    }

    _key(record) {
        return record ? `${record.resModel}:${record.resId}` : "";
    }

    async _load(record) {
        if (!record || !record.resId) {
            this.state.data = null;
            return;
        }
        let data = null;
        try {
            data = await this.orm.call(INST, "get_record_approval_state", [
                record.resModel,
                record.resId,
            ]);
        } catch {
            data = null;
        }
        this.state.data = data;
        setGatedMethods(record.resModel, record.resId, (data && data.gated_methods) || []);
    }

    // ---- 顯示判斷 ----
    get visible() {
        const d = this.state.data;
        return !!(d && (d.gated_methods.length || d.instance));
    }
    get inst() {
        return this.state.data && this.state.data.instance;
    }
    get my() {
        return (this.state.data && this.state.data.my) || { can: {} };
    }
    get can() {
        return this.my.can || {};
    }
    get progressLabel() {
        const i = this.inst;
        if (!i) return "";
        return _t("第 %s/%s 關", i.done_steps + (i.current ? 1 : 0), i.total_steps || "?");
    }
    get currentApprovers() {
        const c = this.inst && this.inst.current;
        return c ? c.approvers.map((a) => a.name).join("、") : "";
    }

    // ---- 動作 ----
    async _refresh() {
        await this._load(this.props.record);
        await this.props.record.model.root.load();
    }

    async onSubmit(method) {
        this.state.busy = true;
        try {
            const r = await this.orm.call(INST, "submit_gate_for_record", [
                this.props.record.resModel,
                this.props.record.resId,
                method,
            ]);
            this.notification.add(
                _t("已送出簽核「%s」。", (r && r.process_name) || ""),
                { type: "success" }
            );
            await this._refresh();
        } catch (e) {
            this.notification.add(_t("送簽失敗：%s", e?.message?.data?.message || e?.message || e), {
                type: "danger",
            });
        }
        this.state.busy = false;
    }

    async onAct(action) {
        this.state.busy = true;
        try {
            const res = await this.orm.call(INST, "record_action", [
                this.inst.id,
                action,
                this.my.link_id || false,
            ]);
            if (res && res.type) {
                // wizard act_window（駁回/上簽/轉簽/會辦）
                await this.action.doAction(res, {
                    onClose: () => this._refresh(),
                });
            } else {
                await this._refresh();
            }
        } catch (e) {
            this.notification.add(_t("操作失敗：%s", e?.message?.data?.message || e?.message || e), {
                type: "danger",
            });
        }
        this.state.busy = false;
    }

    toggle() {
        this.state.expanded = !this.state.expanded;
    }
}
