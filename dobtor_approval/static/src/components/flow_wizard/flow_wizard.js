/** @odoo-module **/
// Copyright 2026 Dobtor Systems Integration
// License LGPL-3
/**
 * FlowWizardDialog — L1 簽核流程簡易精靈（真 Dialog，over list）。
 *
 * 由自訂 list controller 經 dialog service 開啟（FlowWizardListController）。
 * 風格比照 dobtor_finance_reports；整合：
 *   - 拖曳排序（useSortable）
 *   - 職位/人員 m2o/m2m autocomplete（AutoComplete + name_search）
 *   - 「誰會簽」dry-run 預覽（preview_wizard_approvers）
 * 送出 → bpmn.executable.process.generate_from_wizard(payload) → 開啟編輯器。
 */
import { Component, useState, useRef, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { useSortable } from "@web/core/utils/sortable_owl";

const MODEL = "bpmn.executable.process";

// 由誰簽（L1 精簡 5 項）→ 對映 bpmn.role.resolver_type（label 用純字串）
const RESOLVERS = [
    { value: "direct_manager", label: "直屬主管", param: null },
    { value: "department_manager", label: "部門經理", param: null },
    { value: "manager_level", label: "往上第 N 級主管", param: "level" },
    { value: "job_position", label: "指定職位", param: "job" },
    { value: "specific_user", label: "指定人員", param: "users" },
];
const MODES = [
    { value: "any", label: "單人核准" },
    { value: "all", label: "會簽（全部核准）" },
    { value: "sequential", label: "依序簽核" },
];
const SLA_ACTIONS = [
    { value: "remind", label: "提醒" },
    { value: "escalate", label: "自動往上加簽" },
    { value: "auto_approve", label: "視為核准" },
    { value: "reject", label: "退回" },
];

function emptyStep(seq) {
    return {
        label: "",
        resolver: "direct_manager",
        level: 2,
        job: null,        // {id, name}
        users: [],        // [{id, name}]
        mode: "any",
        escalate: false,
        _seq: seq,
    };
}

export class FlowWizardDialog extends Component {
    static template = "dobtor_approval.FlowWizard";
    static components = { Dialog, AutoComplete };
    static props = { close: { type: Function, optional: true } };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.RESOLVERS = RESOLVERS;
        this.MODES = MODES;
        this.SLA_ACTIONS = SLA_ACTIONS;

        this.state = useState({
            name: "",
            steps: [emptyStep(1)],
            advanced: { open: false, model: "", method: "", sla_hours: 0, sla_action: "remind" },
            preview: { applicant: null, results: [], loading: false },
            features: [],
            generating: false,
        });
        this._seq = 1;

        onWillStart(async () => {
            try {
                this.state.features = await rpc("/dobtor_approval/enabled_features");
            } catch {
                this.state.features = ["wizard", "visual_editor", "basic_approval"];
            }
        });

        this.stepsRef = useRef("stepsBody");
        useSortable({
            ref: this.stepsRef,
            elements: ".o_appr_step_row",
            handle: ".o_appr_drag",
            cursor: "grabbing",
            onDrop: ({ element, previous }) => {
                const from = parseInt(element.dataset.idx, 10);
                const to = previous ? parseInt(previous.dataset.idx, 10) + 1 : 0;
                this.moveStepTo(from, to);
            },
        });
    }

    // ==============================
    // 關卡：新增 / 移除 / 排序
    // ==============================
    onAddStep() {
        this._seq += 1;
        this.state.steps.push(emptyStep(this._seq));
    }

    onRemoveStep(idx) {
        if (this.state.steps.length <= 1) {
            this.notification.add(_t("至少需保留一個簽核關卡。"), { type: "warning" });
            return;
        }
        this.state.steps.splice(idx, 1);
    }

    moveStepTo(from, to) {
        if (from === to) return;
        const steps = this.state.steps;
        const item = steps[from];
        steps.splice(from, 1);
        steps.splice(from < to ? to - 1 : to, 0, item);
    }

    onResolverChange(step, ev) {
        step.resolver = ev.target.value;
    }

    paramKind(step) {
        const r = RESOLVERS.find((x) => x.value === step.resolver);
        return r ? r.param : null;
    }

    // 依已啟用能力顯隱進階選項
    _has(feature) {
        return this.state.features.includes(feature);
    }
    get availableModes() {
        // 未啟用會簽（cosign）時只給「單人核准」
        return this._has("cosign") ? MODES : MODES.filter((m) => m.value === "any");
    }
    get canEscalate() {
        return this._has("escalation");
    }
    get canBindDoc() {
        return this._has("action_gate");
    }

    // ==============================
    // Autocomplete 來源（職位 / 使用者 / 申請人）
    // ==============================
    async _nameSearch(model, name, domain = []) {
        const pairs = await this.orm.call(model, "name_search", [], {
            name: name || "",
            args: domain,
            operator: "ilike",
            limit: 8,
        });
        return pairs.map(([id, label]) => ({ id, label, cssClass: "" }));
    }

    get jobSources() {
        return [{ options: (req) => this._nameSearch("hr.job", req) }];
    }
    get userSources() {
        return [{ options: (req) => this._nameSearch("res.users", req, [["share", "=", false]]) }];
    }
    get applicantSources() {
        return [{ options: (req) => this._nameSearch("res.users", req, [["share", "=", false]]) }];
    }

    onPickJob(step, option) {
        step.job = { id: option.id, name: option.label };
    }
    onPickUser(step, option) {
        if (!step.users.some((u) => u.id === option.id)) {
            step.users.push({ id: option.id, name: option.label });
        }
    }
    removeUser(step, id) {
        step.users = step.users.filter((u) => u.id !== id);
    }
    onPickApplicant(option) {
        this.state.preview.applicant = { id: option.id, name: option.label };
    }

    // ==============================
    // 即時預覽鏈 / 能力提示
    // ==============================
    resolverLabel(step) {
        const r = RESOLVERS.find((x) => x.value === step.resolver);
        if (!r) return "";
        if (step.resolver === "manager_level") return _t("往上第 %s 級主管", step.level || 1);
        if (step.resolver === "job_position") return step.job ? step.job.name : _t("指定職位");
        if (step.resolver === "specific_user") return _t("指定 %s 人", (step.users || []).length);
        return r.label;
    }

    get previewChain() {
        const parts = [_t("申請")];
        for (const s of this.state.steps) {
            let p = this.resolverLabel(s);
            if (s.mode === "all") p += _t("(會簽)");
            else if (s.mode === "sequential") p += _t("(依序)");
            parts.push(p);
        }
        parts.push(_t("完成"));
        return parts.join(" → ");
    }

    get warnings() {
        const w = [];
        if (this.state.steps.some((s) => s.mode === "all" || s.mode === "sequential")) {
            w.push(_t("「會簽 / 依序」需啟用 T1 能力"));
        }
        if (this.state.steps.some((s) => s.escalate)) {
            w.push(_t("「往上加簽」需啟用 T3 能力"));
        }
        return w;
    }

    // ==============================
    // dry-run：誰會簽
    // ==============================
    async onRunPreview() {
        const applicantId = this.state.preview.applicant ? this.state.preview.applicant.id : false;
        this.state.preview.loading = true;
        try {
            const results = [];
            for (let i = 0; i < this.state.steps.length; i++) {
                const s = this.state.steps[i];
                const names = await this.orm.call(MODEL, "preview_wizard_approvers", [
                    this._stepPayload(s, i),
                    applicantId,
                ]);
                results.push({ label: s.label || _t("第%s關", i + 1), names: names || [] });
            }
            this.state.preview.results = results;
        } catch (err) {
            this.notification.add(_t("試算失敗：%s", err.message || String(err)), { type: "danger" });
        } finally {
            this.state.preview.loading = false;
        }
    }

    // ==============================
    // 送出 / 取消
    // ==============================
    _stepPayload(s, i) {
        return {
            label: s.label || _t("第%s關", i + 1),
            resolver: s.resolver,
            level: parseInt(s.level, 10) || 1,
            job_id: s.job ? s.job.id : false,
            user_ids: (s.users || []).map((u) => u.id),
            mode: s.mode,
            escalate: !!s.escalate,
        };
    }

    _buildPayload() {
        return {
            name: this.state.name,
            steps: this.state.steps.map((s, i) => this._stepPayload(s, i)),
            advanced: {
                model: (this.state.advanced.model || "").trim(),
                method: (this.state.advanced.method || "").trim(),
                sla_hours: parseFloat(this.state.advanced.sla_hours) || 0,
                sla_action: this.state.advanced.sla_action,
            },
        };
    }

    _validate() {
        if (!this.state.name.trim()) {
            this.notification.add(_t("請輸入流程名稱。"), { type: "warning" });
            return false;
        }
        for (let i = 0; i < this.state.steps.length; i++) {
            const s = this.state.steps[i];
            if (s.resolver === "job_position" && !s.job) {
                this.notification.add(_t("第 %s 關請選擇職位。", i + 1), { type: "warning" });
                return false;
            }
            if (s.resolver === "specific_user" && !(s.users || []).length) {
                this.notification.add(_t("第 %s 關請選擇人員。", i + 1), { type: "warning" });
                return false;
            }
        }
        const adv = this.state.advanced;
        if ((adv.model || "").trim() && !(adv.method || "").trim()) {
            this.notification.add(_t("綁定單據時，請填寫觸發動作。"), { type: "warning" });
            return false;
        }
        return true;
    }

    async onGenerate() {
        if (this.state.generating || !this._validate()) return;
        this.state.generating = true;
        try {
            const result = await this.orm.call(MODEL, "generate_from_wizard", [this._buildPayload()]);
            this.notification.add(_t("已產生簽核流程，請繼續設定或發佈。"), { type: "success" });
            // 先開啟編輯器（doAction 取代當前視圖），再關閉本 Dialog，避免關閉先行導致導頁被吞
            await this.action.doAction(result);
            if (this.props.close) {
                this.props.close();
            }
        } catch (err) {
            this.notification.add(
                _t("產生失敗：%s", err?.message?.data?.message || err?.message || String(err)),
                { type: "danger" }
            );
            this.state.generating = false;
        }
    }

    onCancel() {
        if (this.props.close) {
            this.props.close();
        }
    }
}
