# -*- coding: utf-8 -*-

from odoo import models, fields, api


class DobtorTodoListCore(models.Model):
    _inherit = 'dobtor.todo.list.core'

    @api.model
    def set_ref_models(self):
        selection = super().set_ref_models()
        selection.append(('crm.lead', 'Crm Lead'))
        return selection

    # @api.depends('ref_model')
    # def change_parent(self):
    #     for record in self:
    #         if record.ref_model:
    #             if ('crm.lead' in str(record.ref_model)) and record.ref_model :
    #                 record.parent_model = self.env["ir.model"].search([("name", "=", "crm.lead")], limit=1).id
    #         pass