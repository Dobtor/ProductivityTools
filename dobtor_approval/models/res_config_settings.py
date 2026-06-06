# -*- coding: utf-8 -*-
"""能力開關設定 — DESIGN_PROGRESSIVE_TIERS.md §2 / §8。

全部 bpmn_enable_* 布林，config_parameter='dobtor_approval.<key>'，預設關閉（T0 除外）。
相依校驗：開啟某能力前須先開啟其前置（FEATURE_DEPS）。
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from . import feature_registry as FR


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # T0（預設 ON，不可關）
    bpmn_enable_wizard = fields.Boolean(
        string='精靈建立流程',
        config_parameter='dobtor_approval.wizard', default=True)
    bpmn_enable_basic_approval = fields.Boolean(
        string='基本簽核',
        config_parameter='dobtor_approval.basic_approval', default=True)

    # T1
    bpmn_enable_conditional = fields.Boolean(
        string='條件分歧（互斥閘道）',
        config_parameter='dobtor_approval.conditional')
    bpmn_enable_cosign = fields.Boolean(
        string='會簽 / 依序簽核',
        config_parameter='dobtor_approval.cosign')
    bpmn_enable_hr_resolvers = fields.Boolean(
        string='進階 HR 簽核人解析',
        config_parameter='dobtor_approval.hr_resolvers')
    bpmn_enable_delegation = fields.Boolean(
        string='職務代理（代簽核）',
        config_parameter='dobtor_approval.delegation')

    # T2
    bpmn_enable_action_gate = fields.Boolean(
        string='Action 攔截閘門',
        config_parameter='dobtor_approval.action_gate')

    # T3
    bpmn_enable_escalation = fields.Boolean(
        string='主管自主加簽 / 上呈',
        config_parameter='dobtor_approval.escalation')
    bpmn_enable_parallel_gw = fields.Boolean(
        string='平行 / 包容閘道',
        config_parameter='dobtor_approval.parallel_gw')

    # T4
    bpmn_enable_designer = fields.Boolean(
        string='自助積木設計器',
        config_parameter='dobtor_approval.designer')
    bpmn_enable_lint = fields.Boolean(
        string='即時驗證 (bpmnlint)',
        config_parameter='dobtor_approval.lint')
    bpmn_enable_sandbox = fields.Boolean(
        string='沙箱模擬 (dry-run)',
        config_parameter='dobtor_approval.sandbox')

    # T5
    bpmn_enable_sla_timer = fields.Boolean(
        string='SLA 逾時事件',
        config_parameter='dobtor_approval.sla_timer')
    bpmn_enable_incident = fields.Boolean(
        string='失敗重試 (Incident)',
        config_parameter='dobtor_approval.incident')
    bpmn_enable_multi_instance = fields.Boolean(
        string='真會簽 (Multi-instance)',
        config_parameter='dobtor_approval.multi_instance')
    bpmn_enable_dmn = fields.Boolean(
        string='DMN 決策表求值',
        config_parameter='dobtor_approval.dmn')
    bpmn_enable_call_activity = fields.Boolean(
        string='子流程複用 (Call Activity)',
        config_parameter='dobtor_approval.call_activity')

    # T6
    bpmn_enable_governance = fields.Boolean(
        string='送審生命週期',
        config_parameter='dobtor_approval.governance')
    bpmn_enable_scope = fields.Boolean(
        string='公民 scope 權限限制',
        config_parameter='dobtor_approval.scope')
    bpmn_enable_expert_mode = fields.Boolean(
        string='專家完整調色盤',
        config_parameter='dobtor_approval.expert_mode')
    bpmn_enable_migration = fields.Boolean(
        string='執行中實例遷移',
        config_parameter='dobtor_approval.migration')

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
