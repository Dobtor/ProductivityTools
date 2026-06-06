# -*- coding: utf-8 -*-
"""執行 token — DESIGN.md §3.5。

token 在圖上移動：抵達 user_task 產生簽核活動；活動完成推進 token。
並行閘道展開多個 token，join 時消耗匯聚。
"""
from odoo import api, fields, models


class BpmnToken(models.Model):
    _name = 'bpmn.token'
    _description = 'BPMN 執行 Token'
    _order = 'id'

    instance_id = fields.Many2one('bpmn.process.instance', string='流程實例',
                                  ondelete='cascade', required=True, index=True)
    bpmn_element_id = fields.Char(string='所在節點 (element id)', required=True)
    node_name = fields.Char(string='節點名稱')
    state = fields.Selection([
        ('active', '活躍'),
        ('consumed', '已消耗'),
    ], string='狀態', default='active', index=True)

    activity_link_ids = fields.One2many('bpmn.activity.link', 'token_id',
                                        string='簽核活動連結')

    def consume(self):
        """消耗 token（推進後）。"""
        self.write({'state': 'consumed'})
