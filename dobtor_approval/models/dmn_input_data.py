# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""DMN 輸入資料 / 知識模型 / DRD 邊 / 執行期綁定（DESIGN_DMN.md §3.3）。"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .dmn_decision import TYPE_REFS


class DmnInputData(models.Model):
    _name = 'dmn.input.data'
    _description = 'DMN 輸入資料'
    _order = 'definitions_id, name'

    definitions_id = fields.Many2one(
        'dmn.definitions', required=True, ondelete='cascade', index=True)
    dmn_id = fields.Char(string='DMN 元素 ID', required=True)
    name = fields.Char(string='名稱', required=True)
    type_ref = fields.Selection(TYPE_REFS, string='型別', default='string')


class DmnBkm(models.Model):
    _name = 'dmn.bkm'
    _description = 'DMN 商業知識模型'
    _order = 'definitions_id, name'

    definitions_id = fields.Many2one(
        'dmn.definitions', required=True, ondelete='cascade', index=True)
    dmn_id = fields.Char(string='DMN 元素 ID', required=True)
    name = fields.Char(string='名稱', required=True)
    logic_type = fields.Selection([
        ('decision_table', '決策表'),
        ('literal_expression', 'FEEL 運算式'),
    ], string='邏輯型別', default='literal_expression', required=True)
    table_id = fields.Many2one('dmn.decision.table', string='決策表', ondelete='cascade')
    literal_expression = fields.Text(string='FEEL 運算式')


class DmnRequirement(models.Model):
    _name = 'dmn.requirement'
    _description = 'DMN 需求邊（DRD）'
    _order = 'definitions_id, id'

    definitions_id = fields.Many2one(
        'dmn.definitions', required=True, ondelete='cascade', index=True)
    source_dmn_id = fields.Char(string='來源元素 ID', required=True)
    target_dmn_id = fields.Char(string='目標元素 ID', required=True)
    req_type = fields.Selection([
        ('information', '資訊需求'),
        ('knowledge', '知識需求'),
        ('authority', '授權需求'),
    ], string='需求型別', default='information', required=True)


class DmnInputBinding(models.Model):
    _name = 'dmn.input.binding'
    _description = 'DMN 變數綁定（執行期注入）'
    _order = 'definitions_id, variable'

    definitions_id = fields.Many2one(
        'dmn.definitions', required=True, ondelete='cascade', index=True)
    variable = fields.Char(string='DMN 變數名', required=True,
                           help='FEEL 取值式所引用的變數 / 輸入資料名')
    source_kind = fields.Selection([
        ('record_field', '單據欄位'),
        ('applicant', '申請人'),
        ('instance_ctx', '流程實例變數'),
        ('constant', '常數'),
    ], string='來源', default='record_field', required=True)
    record_field = fields.Char(
        string='欄位點路徑',
        help='source_kind=單據欄位；如 amount_total、partner_id.country_id.code')
    instance_key = fields.Char(string='實例變數鍵',
                               help='source_kind=流程實例變數')
    constant_value = fields.Char(string='常數值')

    @api.constrains('source_kind', 'record_field')
    def _check_record_field(self):
        for b in self:
            if b.source_kind == 'record_field' and not b.record_field:
                raise ValidationError(_('綁定「%s」來源為單據欄位，須填欄位點路徑。', b.variable))
            # 安全：禁止 dunder 逃逸
            if b.record_field and '__' in b.record_field:
                raise ValidationError(_('欄位點路徑「%s」不可包含 __。', b.record_field))
