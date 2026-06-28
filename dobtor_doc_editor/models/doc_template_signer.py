"""
Phase 8 Template UI Builder（ADR-022）— 範本簽約人角色。

設計考量：
- 一個 doc.template 可有多個 signer（房東/業務/見證人 ...）。
- field（下個檔）透過 signer_id 歸屬，套用範本生成填值時可區分填寫者權限。
- 不放任何個人身分資訊（user_id / partner_id）—— 那屬於「文件實例」層次的綁定，
  在 doc.document 或未來 doc.signature 層處理；本表只定義角色。
"""
from odoo import fields, models


class DocTemplateSigner(models.Model):
    _name = 'doc.template.signer'
    _description = '文件範本簽約人角色'
    _order = 'template_id, sequence, id'

    template_id = fields.Many2one(
        'doc.template',
        string='所屬範本',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='角色名稱', required=True, default='簽約人')
    sequence = fields.Integer(string='順序', default=10)
    color = fields.Integer(
        string='顏色',
        default=0,
        help='Odoo 色票索引（0-11）。前端 chip 用 --signer-color CSS variable 渲染。',
    )
    field_ids = fields.One2many(
        'doc.template.field',
        'signer_id',
        string='所屬欄位',
    )
    field_count = fields.Integer(
        string='欄位數',
        compute='_compute_field_count',
    )

    def _compute_field_count(self):
        for rec in self:
            rec.field_count = len(rec.field_ids)
