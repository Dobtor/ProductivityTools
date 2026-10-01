# -*- coding: utf-8 -*-
from odoo import fields, models


class KnowledgeRejectWizard(models.TransientModel):
    _name = 'corpaas.knowledge.reject.wizard'
    _description = '退回（必填理由）'

    res_model = fields.Char(required=True)
    res_ids = fields.Char(required=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        ids = [int(i) for i in self.res_ids.split(',') if i.strip().isdigit()]
        self.env[self.res_model].browse(ids).action_reject(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
