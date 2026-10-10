# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class KbHardDoc(models.Model):
    """已撥款就不准刪（同佣金結算單）；只開放給自訂群組；有公司規則。"""
    _name = 'kb.hard.doc'
    _description = 'KB 別難單據'

    name = fields.Char(required=True)
    state = fields.Selection([('draft', '草稿'), ('paid', '已撥款')], default='draft')
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)

    def unlink(self):
        if any(r.state == 'paid' for r in self):
            raise UserError('已撥款的單據不能刪除')
        return super().unlink()

    def action_mark_paid(self):
        self.write({'state': 'paid'})
