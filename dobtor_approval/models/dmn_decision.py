# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""DMN 決策 shadow 模型（DESIGN_DMN.md §3.1–3.2）。

由 `dmn.definitions._parse_dmn()` 從 DMN XML 解析重建（先刪後建）；
使用者不直接編輯（後台 readonly），求值引擎與覆蓋分析讀取此投影。
"""
from odoo import api, fields, models, _

TYPE_REFS = [
    ('number', '數值'),
    ('string', '字串'),
    ('boolean', '布林'),
    ('date', '日期'),
    ('time', '時間'),
    ('duration', '期間'),
    ('approver', '簽核人（鏈）'),
]

# approver 慣例輸出欄名（決策輸出符合此集合 → 可當簽核人鏈來源）
APPROVER_OUTPUT_NAMES = {'resolver', 'level', 'job', 'users', 'phase'}


class DmnDecision(models.Model):
    _name = 'dmn.decision'
    _description = 'DMN 決策'
    _order = 'definitions_id, sequence, id'

    definitions_id = fields.Many2one(
        'dmn.definitions', string='決策集', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    dmn_id = fields.Char(string='DMN 元素 ID', required=True,
                         help='對應 DMN XML 的 decision id')
    name = fields.Char(string='決策名稱', required=True)
    logic_type = fields.Selection([
        ('decision_table', '決策表'),
        ('literal_expression', 'FEEL 運算式'),
    ], string='邏輯型別', default='decision_table', required=True)
    output_type_ref = fields.Selection(TYPE_REFS, string='輸出型別')
    table_id = fields.Many2one('dmn.decision.table', string='決策表',
                               ondelete='set null')
    literal_expression = fields.Text(string='FEEL 運算式')
    requires_ids = fields.Many2many(
        'dmn.decision', 'dmn_decision_req_rel', 'decision_id', 'requires_id',
        string='資訊需求（依賴決策）',
        help='本決策求值前須先求值的上游決策')
    is_approver_output = fields.Boolean(
        string='簽核人輸出', compute='_compute_is_approver_output', store=True)

    @api.depends('output_type_ref', 'table_id.output_ids.name')
    def _compute_is_approver_output(self):
        for dec in self:
            if dec.output_type_ref == 'approver':
                dec.is_approver_output = True
            elif dec.table_id:
                names = set(dec.table_id.output_ids.mapped('name'))
                dec.is_approver_output = bool(names & APPROVER_OUTPUT_NAMES)
            else:
                dec.is_approver_output = False


class DmnDecisionTable(models.Model):
    _name = 'dmn.decision.table'
    _description = 'DMN 決策表'

    # 直接掛 definitions：reparse / 刪除決策集時可一併清除（避免孤兒累積）。
    # 決策→表為單向（dmn.decision.table_id）；不再保留反向 decision_id（冗餘）。
    definitions_id = fields.Many2one('dmn.definitions', ondelete='cascade', index=True)
    hit_policy = fields.Selection([
        ('unique', 'Unique（唯一命中）'),
        ('any', 'Any（多命中輸出須相同）'),
        ('priority', 'Priority（依優先序取一）'),
        ('first', 'First（取第一條）'),
        ('collect', 'Collect（收集全部）'),
        ('rule_order', 'Rule order（依規則序）'),
        ('output_order', 'Output order（依輸出序）'),
    ], string='命中策略', default='unique', required=True)
    aggregation = fields.Selection([
        ('none', '無'),
        ('sum', '加總'),
        ('min', '最小'),
        ('max', '最大'),
        ('count', '計數'),
    ], string='聚合（Collect）', default='none')
    input_ids = fields.One2many('dmn.decision.table.input', 'table_id', string='輸入欄')
    output_ids = fields.One2many('dmn.decision.table.output', 'table_id', string='輸出欄')
    rule_ids = fields.One2many('dmn.decision.table.rule', 'table_id', string='規則列')


class DmnDecisionTableInput(models.Model):
    _name = 'dmn.decision.table.input'
    _description = 'DMN 決策表輸入欄'
    _order = 'table_id, sequence, id'

    table_id = fields.Many2one('dmn.decision.table', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    label = fields.Char(string='顯示名')
    expression = fields.Char(string='FEEL 取值式', required=True,
                             help='如 amount、record.amount_total')
    type_ref = fields.Selection(TYPE_REFS, string='型別', default='string')
    allowed_values = fields.Char(string='列舉約束',
                                 help='逗號分隔；供 UI 下拉與覆蓋分析')


class DmnDecisionTableOutput(models.Model):
    _name = 'dmn.decision.table.output'
    _description = 'DMN 決策表輸出欄'
    _order = 'table_id, sequence, id'

    table_id = fields.Many2one('dmn.decision.table', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='輸出變數名', required=True,
                       help='如 resolver、sla_hours')
    label = fields.Char(string='顯示名')
    type_ref = fields.Selection(TYPE_REFS, string='型別', default='string')
    default_value = fields.Char(string='預設值 (FEEL)')
    allowed_values = fields.Char(string='優先序值',
                                 help='priority/output_order 用，逗號分隔由高到低')


class DmnDecisionTableRule(models.Model):
    _name = 'dmn.decision.table.rule'
    _description = 'DMN 決策表規則列'
    _order = 'table_id, sequence, id'

    table_id = fields.Many2one('dmn.decision.table', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    description = fields.Char(string='說明')
    entry_ids = fields.One2many('dmn.rule.entry', 'rule_id', string='規則格')


class DmnRuleEntry(models.Model):
    _name = 'dmn.rule.entry'
    _description = 'DMN 規則格'
    _order = 'rule_id, kind desc, sequence, id'

    rule_id = fields.Many2one('dmn.decision.table.rule', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    kind = fields.Selection([('input', '輸入'), ('output', '輸出')],
                            required=True)
    clause_input_id = fields.Many2one('dmn.decision.table.input', ondelete='cascade')
    clause_output_id = fields.Many2one('dmn.decision.table.output', ondelete='cascade')
    text = fields.Char(string='FEEL',
                       help='input 為 unary test（如 ">= 50000"、"[1000..5000]"、"-"）；'
                            'output 為 FEEL 運算式')
