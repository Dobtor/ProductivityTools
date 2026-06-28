"""文件範本欄位的自訂選項。

對應 canvas-editor 的 IValueSet（{ value, code }）：
    - value：顯示給使用者看的文字（下拉選項標籤）
    - code ：內部值；留空時等同 value

只在 doc.template.field.option_source='custom' 時使用；
option_source='odoo' 走 Selection 欄位的 _description_selection，不經此表。
"""
from odoo import fields, models


class DocTemplateFieldOption(models.Model):
    _name = 'doc.template.field.option'
    _description = '文件範本欄位選項'
    _order = 'field_id, sequence, id'

    field_id = fields.Many2one(
        'doc.template.field',
        string='所屬欄位',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string='順序', default=10)
    value = fields.Char(string='顯示文字', required=True)
    code = fields.Char(string='內部值', help='留空時等同「顯示文字」')
