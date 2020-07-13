# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError , ValidationError

class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    crm_lead_ids = fields.One2many(
        string='CRM Leads',
        comodel_name='crm.lead',
        inverse_name='analytic_account_id',
    )
    crm_leads_count = fields.Integer(
        "CRM leads Count", compute='_compute_crm_leads_count')


    @api.multi
    @api.depends('crm_lead_ids')
    def _compute_crm_leads_count(self):
        for analytic_account in self:
            analytic_account.crm_leads_count = len(analytic_account.crm_lead_ids)

    
    @api.multi
    def action_view_crm_leads(self):
        kanban_view_id = self.env.ref('crm.crm_case_kanban_view_leads').id
        result = {
            "type": "ir.actions.act_window",
            "res_model": "crm.lead",
            "views": [[kanban_view_id, "kanban"], [False, "form"]],
            "domain": [['analytic_account_id', '=', self.id]],
            "context": {"create": False},
            "name": "Pipeline",
        }
        if len(self.crm_lead_ids) == 1:
            result['views'] = [(False, "form")]
            result['res_id'] = self.crm_lead_ids.id
        return result

    @api.constrains('company_id')
    def _check_company_id(self):
        super()._check_company_id()
        for record in self:
            if record.crm_lead_ids:
                raise UserError(_('You cannot change the company of an analytical account if it is related to a CRM.'))
