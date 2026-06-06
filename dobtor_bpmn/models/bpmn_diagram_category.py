from odoo import api, fields, models


class BpmnDiagramCategory(models.Model):
    _name = 'bpmn.diagram.category'
    _description = '流程設計圖分類'
    _parent_store = True
    _parent_name = 'parent_id'
    _order = 'complete_name'

    name = fields.Char(required=True, translate=True)
    parent_id = fields.Many2one(
        'bpmn.diagram.category', string='上層分類',
        ondelete='cascade', index=True)
    parent_path = fields.Char(index=True, unaccent=False)
    complete_name = fields.Char(
        compute='_compute_complete_name', recursive=True, store=True)
    child_ids = fields.One2many('bpmn.diagram.category', 'parent_id', string='下層分類')
    diagram_ids = fields.One2many('bpmn.diagram', 'category_id', string='設計圖')

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for cat in self:
            if cat.parent_id:
                cat.complete_name = f'{cat.parent_id.complete_name} / {cat.name}'
            else:
                cat.complete_name = cat.name


class BpmnDiagramTag(models.Model):
    _name = 'bpmn.diagram.tag'
    _description = '流程設計圖標籤'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer(string='顏色')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', '標籤名稱必須唯一。'),
    ]
