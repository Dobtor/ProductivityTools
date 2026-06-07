# -*- coding: utf-8 -*-
"""能力開關設定 — 客戶方案 L1–L4 + 專家能力包。

- bpmn_plan_level：客戶方案選擇器（一鍵套用 ≤ 該級累加能力）。
- bpmn_enable_*：各能力布林，config_parameter='dobtor_approval.<key>'。
  介面層（wizard/visual_editor/basic_approval）預設 True；其餘預設關閉。
- 相依校驗：開啟某能力前須先開啟其前置（FEATURE_DEPS）。
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from . import feature_registry as FR


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # 客戶方案選擇器
    bpmn_plan_level = fields.Selection(
        [(lv, FR.PLAN_LEVEL_LABELS[lv]) for lv in FR.PLAN_LEVELS],
        string='客戶方案', default='l1',
        config_parameter='dobtor_approval.plan_level',
        help='選一個最貼近你組織的方案，一鍵套用該級（含以下各級）全部能力；下方可再細調。')

    # 目前實際等級（依已開能力反推，唯讀顯示；解決一鍵只加不減造成的 stale）
    bpmn_effective_plan_label = fields.Char(
        string='目前實際等級', compute='_compute_effective_plan', readonly=True)

    # ── 介面層（預設 ON）──
    # 註：basic_approval 為恆開執行核心，刻意不顯示於設定頁（res_company 視為 default-on）；
    #     僅 wizard / visual_editor 兩個「介面」可由 admin 隱藏。
    bpmn_enable_wizard = fields.Boolean(
        string='精靈建立流程',
        config_parameter='dobtor_approval.wizard', default=True)
    bpmn_enable_visual_editor = fields.Boolean(
        string='視覺流程編輯器',
        config_parameter='dobtor_approval.visual_editor', default=True)
    bpmn_enable_basic_approval = fields.Boolean(
        string='基本簽核',
        config_parameter='dobtor_approval.basic_approval', default=True)

    # ── L2 標準 ──
    bpmn_enable_conditional = fields.Boolean(
        string='條件分歧（互斥閘道）',
        config_parameter='dobtor_approval.conditional')
    bpmn_enable_cosign = fields.Boolean(
        string='會簽 / 依序簽核',
        config_parameter='dobtor_approval.cosign')
    bpmn_enable_delegation = fields.Boolean(
        string='職務代理（代簽核）',
        config_parameter='dobtor_approval.delegation')
    bpmn_enable_action_gate = fields.Boolean(
        string='Action 攔截閘門',
        config_parameter='dobtor_approval.action_gate')
    bpmn_enable_field_resolver = fields.Boolean(
        string='單據欄位簽核人解析',
        config_parameter='dobtor_approval.field_resolver')

    # ── L3 進階 ──
    bpmn_enable_escalation = fields.Boolean(
        string='主管自主加簽 / 上呈',
        config_parameter='dobtor_approval.escalation')
    bpmn_enable_parallel_gw = fields.Boolean(
        string='平行 / 包容閘道',
        config_parameter='dobtor_approval.parallel_gw')
    bpmn_enable_sla_timer = fields.Boolean(
        string='SLA 逾時事件',
        config_parameter='dobtor_approval.sla_timer')
    bpmn_enable_incident = fields.Boolean(
        string='失敗重試 (Incident)',
        config_parameter='dobtor_approval.incident')
    bpmn_enable_multi_instance = fields.Boolean(
        string='真會簽 (Multi-instance)',
        config_parameter='dobtor_approval.multi_instance')

    # ── L4 企業治理 ──
    bpmn_enable_restricted_palette = fields.Boolean(
        string='受限調色盤（公民模式）',
        config_parameter='dobtor_approval.restricted_palette')
    bpmn_enable_lint = fields.Boolean(
        string='即時驗證 (bpmnlint)',
        config_parameter='dobtor_approval.lint')
    bpmn_enable_sandbox = fields.Boolean(
        string='沙箱模擬 (dry-run)',
        config_parameter='dobtor_approval.sandbox')
    bpmn_enable_governance = fields.Boolean(
        string='送審生命週期',
        config_parameter='dobtor_approval.governance')
    bpmn_enable_scope = fields.Boolean(
        string='公民 scope 權限限制',
        config_parameter='dobtor_approval.scope')

    # ── 專家能力包（橫向，僅實作者）──
    bpmn_enable_dmn = fields.Boolean(
        string='DMN 決策求值（總開關）',
        config_parameter='dobtor_approval.dmn')
    bpmn_enable_dmn_decision_table = fields.Boolean(
        string='DMN 決策表編輯器',
        config_parameter='dobtor_approval.dmn_decision_table')
    bpmn_enable_dmn_drd = fields.Boolean(
        string='DMN 決策需求圖（DRD 編排）',
        config_parameter='dobtor_approval.dmn_drd')
    bpmn_enable_dmn_feel = fields.Boolean(
        string='FEEL 運算式（進階）',
        config_parameter='dobtor_approval.dmn_feel')
    bpmn_enable_dmn_business_rule = fields.Boolean(
        string='商業規則任務（求值寫回）',
        config_parameter='dobtor_approval.dmn_business_rule')
    bpmn_enable_authority_matrix = fields.Boolean(
        string='核決權限表（決策矩陣）',
        config_parameter='dobtor_approval.authority_matrix')
    bpmn_enable_call_activity = fields.Boolean(
        string='子流程複用 (Call Activity)',
        config_parameter='dobtor_approval.call_activity')
    bpmn_enable_expert_mode = fields.Boolean(
        string='專家完整調色盤',
        config_parameter='dobtor_approval.expert_mode')
    bpmn_enable_migration = fields.Boolean(
        string='執行中實例遷移',
        config_parameter='dobtor_approval.migration')
    bpmn_enable_expression_resolver = fields.Boolean(
        string='Python 運算式簽核人解析',
        config_parameter='dobtor_approval.expression_resolver')

    # ------------------------------------------------------------------
    # 方案選擇器：一鍵套用 ≤ 該級累加能力
    # ------------------------------------------------------------------
    @api.onchange('bpmn_plan_level')
    def _onchange_plan_level(self):
        if not self.bpmn_plan_level:
            return
        for key in FR.plan_cumulative_features(self.bpmn_plan_level):
            setattr(self, 'bpmn_enable_%s' % key, True)

    @api.onchange(*['bpmn_enable_%s' % k for k in FR.ALL_FEATURES])
    def _onchange_cascade_off(self):
        """關閉某能力時，自動連動關閉所有（遞迴）依賴它的能力，
        避免「父關子留」存檔時被相依校驗擋下而報錯。"""
        changed = True
        while changed:
            changed = False
            for feat, requires in FR.FEATURE_DEPS.items():
                if self._bpmn_is_on(feat) and any(
                        not self._bpmn_is_on(r) for r in requires):
                    setattr(self, 'bpmn_enable_%s' % feat, False)
                    changed = True

    @api.depends(*['bpmn_enable_%s' % k for k in FR.ALL_FEATURES])
    def _compute_effective_plan(self):
        for rec in self:
            on = {k for k in FR.ALL_FEATURES if rec._bpmn_is_on(k)} | FR.BASE_FEATURES
            eff = 'l1'
            for lv in FR.PLAN_LEVELS:
                if FR.plan_cumulative_features(lv) <= on:
                    eff = lv
            extras = len(on - FR.plan_cumulative_features(eff))
            label = FR.PLAN_LEVEL_LABELS[eff]
            if extras:
                label += _('（另開 %s 項越級/專家能力）') % extras
            rec.bpmn_effective_plan_label = label

    # ------------------------------------------------------------------
    # 相依校驗
    # ------------------------------------------------------------------
    def _bpmn_is_on(self, feature_key):
        return bool(getattr(self, 'bpmn_enable_%s' % feature_key, False))

    @api.constrains(*['bpmn_enable_%s' % k for k in FR.ALL_FEATURES])
    def _check_feature_dependencies(self):
        for rec in self:
            for feat, requires in FR.FEATURE_DEPS.items():
                if rec._bpmn_is_on(feat):
                    missing = [r for r in requires if not rec._bpmn_is_on(r)]
                    if missing:
                        raise ValidationError(_(
                            "啟用「%(feat)s」需先啟用：%(deps)s。",
                            feat=FR.FEATURE_LABELS.get(feat, feat),
                            deps=", ".join(
                                FR.FEATURE_LABELS.get(m, m) for m in missing)))
