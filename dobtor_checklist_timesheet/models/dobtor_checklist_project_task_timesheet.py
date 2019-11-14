# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import Warning as UserError
from odoo.addons.sale_timesheet.models.account import AccountAnalyticLine

class DobtorCheckListCore(models.Model):
    _inherit = 'dobtor.checklist.core'

    @api.multi
    def _get_default_analytic_account_id(self):
        res = self.env['account.analytic.account'].search(
            [('name', '=', 'Undefined')])
        return res and res[0] or False

    remaining_hours = fields.Float(
        compute='_hours_get', string="Remaining Hours", store=True, default=0, 
        help='Total remaining time, can be re-estimated periodically by the assignee of the todo.')
    effective_hours = fields.Float(
        compute='_hours_get', string='Hours Spent', store=True, default=0,
        help="Computed using the sum of the todo work done.",)
    total_hours = fields.Float(
        compute='_hours_get', string='Total',  store=True, default=0,
        help="Computed as: Time Spent + Remaining Time.")
    progress = fields.Float(
        compute='_hours_get', string='Working Time Progress (%)', group_operator="avg", store=True, default=0,
        help="If the task has a progress of 99.99% you should close the task if it's finished or reevaluate the time")
    delay_hours = fields.Float(
        compute='_hours_get', string='Delay Hours', default=0, store=True,
        help="Computed as difference between planned hours by the project manager and the total hours of the task.")
    timesheet_ids = fields.One2many('account.analytic.line', 'checklist_id', 'Timesheets')
    analytic_account_id = fields.Many2one('account.analytic.account',
                                          'Analytic Account', default=_get_default_analytic_account_id, store=True)

    @api.onchange('planned_hours', 'remaining_hours', 'timesheet_ids')
    def change_unit_amount(self):
        pass

    # @api.onchange('ref_model')
    # def change_parent(self):
    #     super().change_parent()



    @api.multi
    def _hours_get(self):
        for record in self:
            aa_id = self.env['account.analytic.line'].browse(record.id)
            if aa_id:
                record.effective_hours = aa_id.unit_amount
                record.remaining_hours = record.planned_hours - aa_id.unit_amount
                record.total_hours = record.remaining_hours + aa_id.unit_amount
                record.delay_hours = record.total_hours - record.planned_hours
                record.progress = 0
                if (record.panned_hours > 0.0 ):
                    record.progress = round(min(100 * aa_id.amount) / record.plananed_hours, 99.99)
                if record.state == 'done':
                    record.progress = 100.0

    @api.multi
    def create_timesheet(self):
        self.ensure_one()
        default_ref_model = None
        default_parent_model = None
        default_project_id = None
        default_task_id = None
        account_id = self.env['account.analytic.account'].search([('name', '=', 'Undefined')])
        if self.ref_model:
            default_ref_model = self.ref_name + "," + str(self.ref_id)
            if self.ref_name == 'project.task':
                default_task_id = self.ref_id
        if self.parent_model:
            default_parent_model = self.parent_name + "," + str(self.parent_id)
            if self.parent_name == 'project.project':
                default_project_id = self.parent_id
                account_id = self.env['project.project'].search(
                    [('id', '=', self.parent_id)])[0].analytic_account_id
    
        
        res = {
            'type': 'ir.actions.act_window',
            'view_id': self.env.ref('dobtor_checklist_timesheet.dobtor_checklist_project_task_timesheet_wizard').id,
            'name': 'Todo Time Sheet',
            'target': 'new',
            'res_model': 'account.analytic.line',
            'view_type': 'form',
            'view_mode': 'form',

            'context': {
                'default_user_id': self.env.user.id,
                'default_checklist_id': self.id,
                'default_account_id': account_id and account_id[0].id or False,
                'default_todo_ref': default_ref_model,
                'default_todo_ref_parent': default_parent_model,
                'default_project_id': default_project_id,
                'default_task_id': default_task_id,
            }
        }
        return res


def referenceable_models(self):
    return self.env['res.request.link'].search([])
     


class AccountAnalyticLineExtend(models.Model):
    _inherit = "account.analytic.line"

    checklist_id = fields.Many2one('dobtor.checklist.core', 'Todo')
    todo_ref = fields.Reference(referenceable_models, "Refer To", default=None)
    todo_ref_parent = fields.Reference(
        referenceable_models, "Parent", default=None)
        
    @api.multi
    def submit_time_sheet(self):
        pass


class AccountAnalyticLine(AccountAnalyticLine):
    _inherit = "account.analytic.line"

    def _get_timesheet_cost(self, values):
        values = values if values is not None else {}
        result = dict(values or {})
        if (values.get('project_id') or self.project_id) or (values.get('account_id') or self.account_id):
            if values.get('amount'):
                return {}
            unit_amount = values.get('unit_amount', 0.0) or self.unit_amount
            user_id = values.get(
                'user_id') or self.user_id.id or self._default_user()
            user = self.env['res.users'].browse([user_id])
            emp = self.env['hr.employee'].search(
                [('user_id', '=', user_id)], limit=1)
            cost = emp and emp.timesheet_cost or 0.0
            uom = (emp or user).company_id.project_time_mode_id
            # Nominal employee cost = 1 * company project UoM (project_time_mode_id)
            return {
                'amount': -unit_amount * cost,
                'product_uom_id': uom.id,
                'account_id': values.get('account_id') or self.account_id.id or emp.account_id.id,
            }
        return {}

