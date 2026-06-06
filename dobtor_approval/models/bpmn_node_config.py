# -*- coding: utf-8 -*-
"""節點執行規格 overlay — DESIGN_MODULE_SPLIT.md §3.2。

每筆以設計圖的 bpmn element id 為鍵，描述「該節點怎麼執行」（角色/會簽方式/綁定動作）。
linked 模式：結構讀來源設計圖，執行規格全在 node.config（真正的設計/執行分離）。
forked 模式：結構與規格皆在 process.xml，node.config 仍可作為快取/補充。
"""
from odoo import api, fields, models


class BpmnNodeConfig(models.Model):
    _name = 'bpmn.node.config'
    _description = 'BPMN 節點執行規格 (overlay)'
    _order = 'process_id, sequence, id'

    process_id = fields.Many2one(
        'bpmn.executable.process', string='所屬流程',
        ondelete='cascade', required=True, index=True)
    sequence = fields.Integer(default=10)

    bpmn_element_id = fields.Char(string='BPMN 元素 ID', required=True,
                                  help='對應設計圖 XML 中的 element id')
    name = fields.Char(string='節點名稱')
    node_type = fields.Selection([
        ('start', '開始'),
        ('end', '結束'),
        ('user_task', '人工簽核'),
        ('service_task', '系統動作'),
        ('exclusive_gw', '互斥閘道(XOR)'),
        ('parallel_gw', '並行閘道(AND)'),
        ('inclusive_gw', '包容閘道(OR)'),
    ], string='節點型別')

    # UserTask 專用
    role_id = fields.Many2one('bpmn.role', string='簽核角色',
                              domain="[('process_id', '=', process_id)]")
    approval_mode = fields.Selection([
        ('any', '任一人核准即過'),
        ('all', '全部核准(會簽)'),
        ('sequential', '依序簽核'),
    ], string='簽核方式', default='any')
    allow_escalation = fields.Boolean(string='允許往上加簽', default=False)

    # ServiceTask 專用
    server_action_id = fields.Many2one('ir.actions.server', string='綁定 Server Action')
    bound_method = fields.Char(string='綁定方法名')

    # 動作插入點（DESIGN_APPROVAL_EDITOR §3.2）— 在節點上綁既有 Odoo 動作
    gate_timing = fields.Selection([
        ('before', '攔截：先簽核後執行'),
        ('after', '後置：執行後觸發'),
        ('replace', '核准後才執行原動作'),
    ], string='動作時機')
    gate_model_id = fields.Many2one('ir.model', string='目標模型')
    gate_method = fields.Char(string='目標方法/按鈕')
    gate_condition = fields.Text(string='觸發條件 (JSON)')

    # 出線（sequence flow）條件：dict {target_element_id: condition_expr}，存 JSON
    flow_conditions = fields.Text(string='出線條件 (JSON)',
                                  help='exclusive gateway 出線條件，key=目標元素id')

    _sql_constraints = [
        ('uniq_process_element',
         'unique(process_id, bpmn_element_id)',
         '同一流程內，每個 BPMN 元素 ID 只能有一筆執行規格。'),
    ]
