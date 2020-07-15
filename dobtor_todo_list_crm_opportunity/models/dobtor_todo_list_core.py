# -*- coding: utf-8 -*-

from odoo import models, fields, api


class DobtorTodoListCore(models.Model):
    _inherit = 'dobtor.todo.list.core'

    @api.model
    def set_ref_models(self):
        selection = super().set_ref_models()
        selection.append(('crm.lead', 'Crm Lead'))
        return selection


    # @api.multi
    # def _handle_vals(self, vals):
    #     ref_model = vals.get('ref_model')
    #     if ref_model:
    #         if 'crm.lead' in str(ref_model):
    #             lead = self.env['crm.lead'].browse(int(vals['ref_model'].split(',')[1]))
    #             if lead and lead.analytic_account_id:
    #                 vals.update(
    #                     {'parent_model': 'account.analytic.account,' + str(lead.analytic_account_id.id)})
    #     return vals

    # @api.depends('ref_model')
    # def change_parent(self):
    #     for record in self:
    #         if record.ref_model:
    #             if ('crm.lead' in str(record.ref_model)) and record.ref_model :
    #                 record.parent_model = self.env["ir.model"].search([("name", "=", "crm.lead")], limit=1).id
    #         pass
