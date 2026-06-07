# -*- coding: utf-8 -*-
"""能力開關（Feature Toggle）單一來源 — 客戶方案 L1–L4 + 專家能力包 + SI 實作者。

分級改為「以 TA 為主軸」：
- 介面層（L1，預設啟用）：wizard / visual_editor / basic_approval。
- 客戶方案階梯（累加）：L1 輕簡 → L2 標準 → L3 進階 → L4 企業治理。
- 專家能力包（橫向 à-la-carte，僅 group_bpmn_implementer 可開，任一方案皆可加）：
  dmn / call_activity / expert_mode / migration / expression_resolver。

UI（res.config.settings）、發佈守門（_scan_used_features）、前端 RPC
（/dobtor_approval/enabled_features）皆共用本檔。

對應規則：feature key ↔ res.config.settings 欄位 `bpmn_enable_<key>` ↔
ir.config_parameter `dobtor_approval.<key>` 三者一一對應。
"""

# ---------------------------------------------------------------------------
# 介面層（預設啟用，除非明確關閉）
# ---------------------------------------------------------------------------
INTERFACE_FEATURES = ('wizard', 'visual_editor', 'basic_approval')

# 預設 ON（介面/基本核心）：未明確設為 'False' 即視為啟用
BASE_FEATURES = set(INTERFACE_FEATURES)

# ---------------------------------------------------------------------------
# 客戶方案階梯：每一級「新增」的能力（套用某級＝累加 ≤ 該級全部）
# ---------------------------------------------------------------------------
PLAN_LEVELS = ('l1', 'l2', 'l3', 'l4')
PLAN_LEVEL_LABELS = {
    'l1': 'L1 輕簡（小微·填表）',
    'l2': 'L2 標準（中小·拖拉）',
    'l3': 'L3 進階（成長·設計）',
    'l4': 'L4 企業治理（大型·公民+治理）',
}
PLAN_LEVEL_ADD = {
    'l1': ['wizard', 'visual_editor', 'basic_approval'],
    'l2': ['conditional', 'cosign', 'delegation', 'action_gate', 'field_resolver'],
    'l3': ['escalation', 'parallel_gw', 'sla_timer', 'incident', 'multi_instance'],
    'l4': ['restricted_palette', 'lint', 'sandbox', 'governance', 'scope'],
}

# ---------------------------------------------------------------------------
# 專家能力包（橫向，不綁階梯，僅實作者可開）
# ---------------------------------------------------------------------------
EXPERT_FEATURES = ('dmn', 'authority_matrix', 'call_activity', 'expert_mode',
                   'migration', 'expression_resolver')

# 全部可切換 key（順序：方案階梯 + 專家包，去重）
_LADDER = [k for lv in PLAN_LEVELS for k in PLAN_LEVEL_ADD[lv]]
ALL_FEATURES = list(dict.fromkeys(_LADDER + list(EXPERT_FEATURES)))

# key → 級別（'l1'/'l2'/'l3'/'l4'/'expert'），供 UI 分組/標籤
FEATURE_LEVEL = {}
for _lv in PLAN_LEVELS:
    for _k in PLAN_LEVEL_ADD[_lv]:
        FEATURE_LEVEL.setdefault(_k, _lv)
for _k in EXPERT_FEATURES:
    FEATURE_LEVEL[_k] = 'expert'


def plan_cumulative_features(level):
    """回傳 ≤ level 的累加 feature 集合（不含專家包）。"""
    out = set()
    for lv in PLAN_LEVELS:
        out.update(PLAN_LEVEL_ADD[lv])
        if lv == level:
            break
    return out


# ---------------------------------------------------------------------------
# 相依：開啟某能力前須先開啟其前置
# ---------------------------------------------------------------------------
FEATURE_DEPS = {
    # L2
    'conditional': ['basic_approval'],
    'cosign': ['basic_approval'],
    'delegation': ['basic_approval'],
    'action_gate': ['basic_approval'],
    'field_resolver': ['basic_approval'],
    # L3
    'escalation': ['cosign'],
    'parallel_gw': ['cosign'],
    'sla_timer': ['action_gate'],
    'incident': ['action_gate'],
    'multi_instance': ['cosign'],
    # L4
    'restricted_palette': ['visual_editor'],
    'lint': ['restricted_palette'],
    'sandbox': ['restricted_palette'],
    'governance': ['visual_editor'],
    'scope': ['governance'],
    # 專家包
    'dmn': ['conditional'],
    'authority_matrix': ['basic_approval'],
    'call_activity': ['visual_editor'],
    'expert_mode': ['visual_editor'],
    'migration': ['governance'],
    'expression_resolver': ['field_resolver'],
}

# ---------------------------------------------------------------------------
# 人類可讀標籤
# ---------------------------------------------------------------------------
FEATURE_LABELS = {
    'wizard': '精靈建立流程',
    'visual_editor': '視覺流程編輯器',
    'basic_approval': '基本簽核（線性、六種簽核人、任一核准）',
    'conditional': '條件分歧（互斥閘道）',
    'cosign': '會簽 / 依序簽核',
    'delegation': '職務代理（代簽核）',
    'action_gate': 'Action 攔截閘門',
    'field_resolver': '單據欄位簽核人解析',
    'escalation': '主管自主加簽 / 上呈',
    'parallel_gw': '平行 / 包容閘道',
    'sla_timer': 'SLA 逾時事件',
    'incident': '失敗重試（Incident）',
    'multi_instance': '真會簽（Multi-instance 比例通過）',
    'restricted_palette': '受限調色盤（公民模式）',
    'lint': '即時驗證（bpmnlint）',
    'sandbox': '沙箱模擬（dry-run）',
    'governance': '送審生命週期',
    'scope': '公民 scope 權限限制',
    'dmn': 'DMN 決策表求值',
    'authority_matrix': '核決權限表（決策矩陣）',
    'call_activity': '子流程複用（Call Activity）',
    'expert_mode': '專家完整調色盤',
    'migration': '執行中實例遷移',
    'expression_resolver': 'Python 運算式簽核人解析',
}

# BPMN element 型別 → 所需能力（解析 XML 掃描用）
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

# bpmn.role.resolver_type → 所需能力（守門掃描 role 用）
RESOLVER_FEATURE = {
    'field_on_record': 'field_resolver',
    'expression': 'expression_resolver',
    'authority_matrix': 'authority_matrix',
}


def all_config_param_keys():
    """回傳 [(feature_key, ir.config_parameter key)]，供守門/RPC 使用。"""
    return [(k, 'dobtor_approval.%s' % k) for k in ALL_FEATURES]
