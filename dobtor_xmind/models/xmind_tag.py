# -*- coding: utf-8 -*-
from odoo import models, fields


class XMindTagCategory(models.Model):
    _name = 'xmind.tag.category'
    _description = 'XMind Tag Category'
    _order = 'sequence, id'

    name = fields.Char('Name', required=True, translate=True)
    sequence = fields.Integer('Sequence', default=10)
    color = fields.Integer('Color Index')
    tag_ids = fields.One2many('xmind.tag', 'category_id', string='Tags')


class XMindTag(models.Model):
    _name = 'xmind.tag'
    _description = 'XMind Tag'
    _order = 'sequence, id'

    name = fields.Char('Name', required=True, translate=True)
    category_id = fields.Many2one(
        'xmind.tag.category', string='Category',
        index=True, ondelete='set null',
    )
    color = fields.Integer('Color Index')
    sequence = fields.Integer('Sequence', default=10)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Tag name must be unique!'),
    ]
