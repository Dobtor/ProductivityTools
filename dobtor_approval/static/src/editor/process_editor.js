/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

const MODEL = "bpmn.executable.process";

export class ApprovalProcessEditor extends Component {
    static template = "dobtor_approval.ProcessEditor";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.canvasRef = useRef("canvas");
        this.modeler = null;

        this.processId =
            (this.props.action && this.props.action.params &&
                this.props.action.params.process_id) || null;

        this.state = useState({
            loading: true,
            libMissing: false,
            error: "",
            process: {},
            nodesById: {},
            options: {},
            enabledFeatures: [],
            selectedId: null,
            panel: null,           // 目前編輯中的節點設定副本
            gateMethods: [],
            previewApplicantId: false,
            previewResults: [],
            lint: [],
            saving: false,
            previewMode: false,
        });
        this.walkOrder = [];
        this._walkTimers = [];

        onWillStart(async () => {
            // bpmn-js 已隨模組打包（manifest web.assets_backend），不需 runtime load
            this.state.libMissing = !window.BpmnJS;
            try {
                const data = await this.orm.call(MODEL, "get_editor_data", [[this.processId]]);
                this.state.process = data.process;
                this.state.options = data.options;
                this.state.enabledFeatures = data.enabled_features || [];
                const byId = {};
                for (const n of data.nodes) {
                    byId[n.element_id] = n;
                }
                this.state.nodesById = byId;
                this.walkOrder = data.walk_order || [];
                this._computeLint();
            } catch (e) {
                this.state.error = e?.message?.data?.message || e?.message || String(e);
            }
            this.state.loading = false;
        });

        onMounted(() => this._initCanvas());
        onWillUnmount(() => this._destroy());
    }

    // ---- canvas ----
    async _initCanvas() {
        if (this.state.libMissing || this.state.error || !window.BpmnJS) {
            if (!window.BpmnJS) this.state.libMissing = true;
            return;
        }
        try {
            this.modeler = new window.BpmnJS({ container: this.canvasRef.el });
            await this.modeler.importXML(this.state.process.xml || "");
            try {
                this.modeler.get("canvas").zoom("fit-viewport");
            } catch {
                /* noop */
            }
            this.modeler.on("selection.changed", (e) => {
                const sel = (e.newSelection || [])[0];
                this._onSelect(sel ? sel.id : null);
            });
            this._renderBadges();
        } catch (e) {
            this.state.error = e?.message || String(e);
        }
    }

    _renderBadges() {
        if (!this.modeler) return;
        let overlays;
        try {
            overlays = this.modeler.get("overlays");
        } catch {
            return;
        }
        for (const [id, node] of Object.entries(this.state.nodesById)) {
            let html = null;
            if (node.node_type === "user_task") {
                html = node.resolver_type
                    ? '<span class="o_appr_badge ok">✓</span>'
                    : '<span class="o_appr_badge warn">⚠</span>';
            } else if (node.node_type === "service_task" && node.gate_timing) {
                html = '<span class="o_appr_badge act">⚡</span>';
            }
            if (html) {
                try {
                    overlays.add(id, { position: { top: -10, right: 10 }, html });
                } catch {
                    /* element not in diagram */
                }
            }
        }
    }

    _refreshBadges() {
        if (!this.modeler) return;
        try {
            this.modeler.get("overlays").clear();
        } catch {
            /* noop */
        }
        this._renderBadges();
    }

    // ---- A6 預覽模式：token 走訪動畫 ----
    togglePreview() {
        this.state.previewMode = !this.state.previewMode;
        if (this.state.previewMode) {
            this._animateWalk();
        } else {
            this._clearWalk();
        }
    }

    _animateWalk() {
        this._clearWalk();
        if (!this.modeler || !this.walkOrder.length) return;
        const canvas = this.modeler.get("canvas");
        this.walkOrder.forEach((id, i) => {
            this._walkTimers.push(setTimeout(() => {
                try {
                    canvas.addMarker(id, "o_appr_walk");
                } catch {
                    /* element not in diagram */
                }
            }, i * 600));
        });
    }

    _clearWalk() {
        this._walkTimers.forEach((t) => clearTimeout(t));
        this._walkTimers = [];
        if (this.modeler) {
            const canvas = this.modeler.get("canvas");
            this.walkOrder.forEach((id) => {
                try {
                    canvas.removeMarker(id, "o_appr_walk");
                } catch {
                    /* noop */
                }
            });
        }
    }

    // ---- A5 閘道出線條件 builder ----
    addCond(targetId) {
        const flow = (this.state.panel.outgoing || []).find((o) => o.target_id === targetId);
        if (flow) {
            flow.rows = [...(flow.rows || []), { field: "", op: "=", value: "", join: "and", vtype: "text" }];
        }
    }

    removeCond(targetId, idx) {
        const flow = (this.state.panel.outgoing || []).find((o) => o.target_id === targetId);
        if (flow) {
            flow.rows.splice(idx, 1);
        }
    }

    setCond(targetId, idx, key, value) {
        const flow = (this.state.panel.outgoing || []).find((o) => o.target_id === targetId);
        if (flow && flow.rows[idx]) {
            flow.rows[idx][key] = value;
        }
    }

    _destroy() {
        this._clearWalk();
        if (this.modeler) {
            try {
                this.modeler.destroy();
            } catch {
                /* noop */
            }
            this.modeler = null;
        }
    }

    // ---- selection / panel ----
    _onSelect(id) {
        this.state.selectedId = id;
        this.state.previewResults = [];
        if (id && this.state.nodesById[id]) {
            this.state.panel = { ...this.state.nodesById[id] };
            if (this.state.panel.node_type === "service_task" && this.state.panel.gate_model_id) {
                this._loadGateMethods(this.state.panel.gate_model_id);
            }
        } else {
            this.state.panel = null;
        }
    }

    feat(key) {
        return this.state.enabledFeatures.includes(key);
    }

    // 依能力顯隱簽核方式（會簽/依序需 cosign）與進階解析方式
    modeAllowed(code) {
        return code === "any" || this.feat("cosign");
    }
    resolverAllowed(code) {
        if (code === "field_on_record") {
            return this.feat("field_resolver");
        }
        if (code === "expression") {
            return this.feat("expression_resolver");
        }
        if (code === "authority_matrix") {
            return this.feat("authority_matrix");
        }
        if (code === "dmn_decision") {
            return this.feat("dmn_decision_table");
        }
        return true;
    }

    setField(field, value) {
        if (this.state.panel) {
            this.state.panel[field] = value;
        }
    }

    // OWL 模板表達式不提供 parseInt/parseFloat 等全域函式，故數字解析移至此
    setIntField(field, value, fallback = false) {
        this.setField(field, parseInt(value, 10) || fallback);
    }
    setFloatField(field, value, fallback = 0) {
        this.setField(field, parseFloat(value) || fallback);
    }

    onResolverTypeChange(ev) {
        this.setField("resolver_type", ev.target.value);
    }

    onUserMultiChange(ev) {
        const ids = Array.from(ev.target.selectedOptions).map((o) => parseInt(o.value, 10));
        this.setField("user_ids", ids);
    }

    async onGateModelChange(ev) {
        const id = ev.target.value ? parseInt(ev.target.value, 10) : false;
        this.setField("gate_model_id", id);
        this.setField("gate_method", "");
        await this._loadGateMethods(id);
    }

    async _loadGateMethods(modelId) {
        const model = (this.state.options.models || []).find((m) => m.id === modelId);
        if (!model) {
            this.state.gateMethods = [];
            return;
        }
        try {
            this.state.gateMethods = await this.orm.call(MODEL, "scan_model_actions", [model.name]);
        } catch {
            this.state.gateMethods = [];
        }
    }

    // ---- save ----
    async onSaveNode() {
        if (!this.state.panel || this.state.saving) return;
        this.state.saving = true;
        const p = this.state.panel;
        let vals = {};
        if (p.node_type === "user_task") {
            vals = {
                resolver_type: p.resolver_type || false,
                level: p.level || 1,
                specific_department_id: p.specific_department_id || false,
                job_id: p.job_id || false,
                group_id: p.group_id || false,
                user_ids: p.user_ids || [],
                record_field: p.record_field || false,
                expression: p.expression || false,
                matrix_id: p.matrix_id || false,
                decision_id: p.decision_id || false,
                approval_mode: p.approval_mode || "any",
                allow_escalation: !!p.allow_escalation,
            };
            if (this.feat("sla_timer")) {
                vals.sla_hours = p.sla_hours || 0;
                vals.sla_action = p.sla_action || false;
            }
        } else if (p.node_type === "service_task") {
            vals = {
                gate_timing: p.gate_timing || false,
                gate_model_id: p.gate_model_id || false,
                gate_method: p.gate_method || false,
            };
        } else if (p.node_type === "business_rule") {
            vals = {
                dmn_decision_id: p.dmn_decision_id || false,
                dmn_write_to_record: !!p.dmn_write_to_record,
            };
        } else if (["exclusive_gw", "inclusive_gw", "parallel_gw"].includes(p.node_type)) {
            const conds = {};
            for (const flow of p.outgoing || []) {
                const rows = (flow.rows || []).filter((r) => r.field);
                if (rows.length) {
                    conds[flow.target_id] = rows;
                }
            }
            vals = { flow_conditions: JSON.stringify(conds) };
            // 閘道可綁 DMN 決策（注入 dmn_result 供出線條件引用）
            if (p.dmn_decision_id !== undefined) {
                vals.dmn_decision_id = p.dmn_decision_id || false;
            }
        }
        try {
            await this.orm.call(MODEL, "set_node_config", [[this.processId], p.element_id, vals]);
            this.state.nodesById[p.element_id] = { ...p };
            this._computeLint();
            this._refreshBadges();
            this.notification.add(_t("已儲存節點設定。"), { type: "success" });
        } catch (e) {
            this.notification.add(_t("儲存失敗：%s", e?.message?.data?.message || e?.message || e), {
                type: "danger",
            });
        }
        this.state.saving = false;
    }

    // ---- dry-run ----
    async onPreview() {
        if (!this.state.selectedId) return;
        try {
            this.state.previewResults = await this.orm.call(
                MODEL, "preview_approvers",
                [[this.processId], this.state.selectedId, this.state.previewApplicantId || false]
            );
        } catch (e) {
            this.notification.add(_t("預覽失敗：%s", e?.message || e), { type: "danger" });
        }
    }

    onPreviewApplicantChange(ev) {
        this.state.previewApplicantId = ev.target.value ? parseInt(ev.target.value, 10) : false;
    }

    // ---- lint ----
    _computeLint() {
        const issues = [];
        for (const node of Object.values(this.state.nodesById)) {
            if (node.node_type === "user_task" && !node.resolver_type) {
                issues.push({ id: node.element_id, msg: _t("簽核節點「%s」尚未設定簽核人", node.name) });
            }
            if (node.node_type === "user_task" && node.resolver_type === "dmn_decision" && !node.decision_id) {
                issues.push({ id: node.element_id, msg: _t("簽核節點「%s」選了 DMN 決策但未綁定", node.name) });
            }
            if (node.node_type === "service_task" && node.gate_timing && !node.gate_method) {
                issues.push({ id: node.element_id, msg: _t("動作節點「%s」未選目標方法", node.name) });
            }
            if (node.node_type === "business_rule" && !node.dmn_decision_id) {
                issues.push({ id: node.element_id, msg: _t("商業規則節點「%s」尚未綁定 DMN 決策", node.name) });
            }
        }
        this.state.lint = issues;
    }

    // ---- 存回結構 XML ----
    async _saveXml() {
        // 把 modeler 目前 XML（含結構增刪）存回後端，使結構編輯持久化。
        if (!this.modeler) return true;
        try {
            const { xml } = await this.modeler.saveXML({ format: true });
            await this.orm.call(MODEL, "save_xml", [[this.processId], xml]);
            return true;
        } catch (e) {
            this.notification.add(
                _t("結構儲存失敗：%s", e?.message?.data?.message || e?.message || e),
                { type: "danger", sticky: true }
            );
            return false;
        }
    }

    async onSave() {
        this.state.saving = true;
        if (await this._saveXml()) {
            this.notification.add(_t("已儲存流程結構。"), { type: "success" });
        }
        this.state.saving = false;
    }

    async onPublish() {
        // 先存回目前結構，確保發佈用的是畫布最新 XML（而非匯入時的舊結構）。
        if (!(await this._saveXml())) {
            return;
        }
        try {
            await this.orm.call(MODEL, "action_publish", [[this.processId]]);
            this.notification.add(_t("流程已發佈。"), { type: "success" });
        } catch (e) {
            this.notification.add(_t("發佈失敗：%s", e?.message?.data?.message || e?.message || e), {
                type: "danger", sticky: true,
            });
        }
    }

    onBack() {
        this.action.doAction("dobtor_approval.action_bpmn_executable_process", {
            clearBreadcrumbs: true,
        });
    }
}

registry.category("actions").add("dobtor_approval.process_editor", ApprovalProcessEditor);
