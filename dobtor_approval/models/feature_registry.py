# -*- coding: utf-8 -*-
"""能力開關（Feature Toggle）單一來源。

依 DESIGN_PROGRESSIVE_TIERS.md §2 定義 T0–T6 全部 `bpmn_enable_*` 開關。
UI（res.config.settings 視圖）、後端發佈守門（action_publish 的 _scan_used_features）、
前端 RPC（/dobtor_approval/enabled_features）皆共用本檔，避免多處定義不一致。

注意：所有 feature key 與 res.config.settings 上的欄位名 `bpmn_enable_<key>`、
以及 ir.config_parameter `dobtor_approval.<key>` 三者保持一一對應。
"""

# ---------------------------------------------------------------------------
# Tier 對照（T0–T6）
# ---------------------------------------------------------------------------
FEATURE_TIER = {
    # T0 入門·線性簽核（預設 ON，永遠啟用）
    'wizard': 'T0',
    'basic_approval': 'T0',
    # T1 條件與會簽
    'conditional': 'T1',
    'cosign': 'T1',
    'hr_resolvers': 'T1',
    'delegation': 'T1',
    # T2 業務動作整合
    'action_gate': 'T2',
    # T3 彈性例外
    'escalation': 'T3',
    'parallel_gw': 'T3',
    # T4 自助設計器
    'designer': 'T4',
    'lint': 'T4',
    'sandbox': 'T4',
    # T5 進階引擎
    'sla_timer': 'T5',
    'incident': 'T5',
    'multi_instance': 'T5',
    'dmn': 'T5',
    'call_activity': 'T5',
    # T6 治理與專家
    'governance': 'T6',
    'scope': 'T6',
    'expert_mode': 'T6',
    'migration': 'T6',
}

# 所有可切換的能力 key（不含永遠啟用的 BASE_FEATURES）
ALL_FEATURES = list(FEATURE_TIER.keys())

# T0 永遠啟用，不需開關（公司 _bpmn_enabled_features 一律 union 進來）
BASE_FEATURES = {'wizard', 'basic_approval'}

# ---------------------------------------------------------------------------
# 相依關係：開啟某能力前必須先開啟其前置（DESIGN_PROGRESSIVE_TIERS.md §2 表）
# key 依賴 value 中的所有 feature
# ---------------------------------------------------------------------------
FEATURE_DEPS = {
    'conditional': ['basic_approval'],
    'cosign': ['basic_approval'],
    'hr_resolvers': ['basic_approval'],
    'delegation': ['basic_approval'],
    'action_gate': ['basic_approval'],
    'escalation': ['cosign'],
    'parallel_gw': ['cosign'],
    'designer': ['conditional'],
    'lint': ['designer'],
    'sandbox': ['designer'],
    'sla_timer': ['action_gate'],
    'incident': ['action_gate'],
    'multi_instance': ['cosign'],
    'dmn': ['conditional'],
    'call_activity': ['designer'],
    'governance': ['designer'],
    'scope': ['governance'],
    'expert_mode': ['designer'],
    'migration': ['governance'],
}

# ---------------------------------------------------------------------------
# 人類可讀標籤（守門錯誤訊息、設定頁、文件共用）
# ---------------------------------------------------------------------------
FEATURE_LABELS = {
    'wizard': '精靈建立流程',
    'basic_approval': '基本簽核（開始/簽核/結束、任一核准）',
    'conditional': '條件分歧（互斥閘道）',
    'cosign': '會簽 / 依序簽核',
    'hr_resolvers': '進階 HR 簽核人解析',
    'delegation': '職務代理（代簽核）',
    'action_gate': 'Action 攔截閘門',
    'escalation': '主管自主加簽 / 上呈',
    'parallel_gw': '平行 / 包容閘道',
    'designer': '自助積木設計器',
    'lint': '即時驗證（bpmnlint）',
    'sandbox': '沙箱模擬（dry-run）',
    'sla_timer': 'SLA 逾時事件（Timer/Boundary）',
    'incident': '失敗重試（Error/Incident）',
    'multi_instance': '真會簽（Multi-instance 比例通過）',
    'dmn': 'DMN 決策表求值',
    'call_activity': '子流程複用（Call Activity）',
    'governance': '送審生命週期',
    'scope': '公民 scope 權限限制',
    'expert_mode': '專家完整調色盤',
    'migration': '執行中實例遷移',
}

# BPMN element 型別 → 所需能力 key（解析 XML 時掃描用）
NODE_FEATURE = {
    'bpmn:userTask': 'basic_approval',
    'bpmn:serviceTask': 'action_gate',
    'bpmn:businessRuleTask': 'dmn',
    'bpmn:exclusiveGateway': 'conditional',
    'bpmn:parallelGateway': 'parallel_gw',
    'bpmn:inclusiveGateway': 'parallel_gw',
    'bpmn:callActivity': 'call_activity',
    'bpmn:boundaryEvent': 'sla_timer',
    'bpmn:intermediateCatchEvent': 'sla_timer',
}


def all_config_param_keys():
    """回傳 [(feature_key, ir.config_parameter key)]，供守門/RPC 使用。"""
    return [(k, 'dobtor_approval.%s' % k) for k in ALL_FEATURES]
