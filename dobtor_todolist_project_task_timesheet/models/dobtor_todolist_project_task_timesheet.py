# -*- coding: utf-8 -*-

from openerp import models, fields, api
from openerp.exceptions import Warning as UserError
from openerp.tools.translate import _ 
from openerp.addons.base.res import res_request

class DobtorTodoListCore(models.Model):
    _inherit = 'dobtor.todolist.core'

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
    timesheet_ids = fields.One2many('account.analytic.line', 'todo_id', 'Timesheets')
    #analytic_account_id = fields.Many2one('account.analytic.account', compute='_get_default_analytic_account_id', store=True)
    analytic_account_id = fields.Many2one('account.analytic.account',
                                          'Analytic Account', default='_get_default_analytic_account_id', store=True)

    @api.onchange('planned_hours', 'remaining_hours', 'timesheet_ids')
    def change_unit_amount(self):
        pass

    @api.onchange('ref_model')
    def change_parent(self):
        super(DobtorTodoListCore, self).change_parent()

    @api.multi
    def _get_default_analytic_account_id(self):
        res = self.env['account.analytic.account'].search([('name', '=', 'Undefined')])
        return res and res[0] or False

    @api.multi
    def _hours_get(self):
        for record in self:
            aa_id = self.env['account.analytic.line'].browse('todo_id', '=', self.id)
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
        if self.ref_model:
            default_ref_model = self.ref_name + "," + str(self.ref_id)
        if self.parent_model:
            default_parent_model = self.parent_name + "," + str(self.parent_id)
        account_id = self.env['account.analytic.account'].search([('name', '=', 'Undefined')])
        res = {
            'type': 'ir.actions.act_window',
            'view_id': self.env.ref('dobtor_todolist_project_task_timesheet.dobtor_todolist_project_task_timesheet_wizard').id,
            'name': 'Todo Time Sheet',
            'target': 'new',
            'res_model': 'account.analytic.line',
            'view_type': 'form',
            'view_mode': 'form',
            # 'context': {
            #     'default_ref_model': default_ref_model, 
            #     'default_parent_model': default_parent_model}
            'context': {
                'default_user_id': self.env.user.id,
                'default_todo_id': self.id,
                'default_is_timesheet': True,
                'default_account_id': account_id and account_id[0].id or False,
                'default_todo_ref': default_ref_model,
                'default_todo_ref_parent': default_parent_model,
            }
        }
        return res

def referencable_models(self):
    return res_request.referencable_models(
        self, self.env.cr, self.env.uid, context=self.env.context)

class account_analytic_line(models.Model):
    _inherit = "account.analytic.line"

    todo_id = fields.Many2one('dobtor.todolist.core', 'Todo')
    todo_ref = fields.Reference(referencable_models, "Refer To", default=None)
    todo_ref_parent = fields.Reference(referencable_models, "Parent", default=None)

    @api.multi
    def submit_time_sheet(self):
        pass
        # print('submit_time_sheet - 1')
        # print(self.analytic_account_id.id)
        # print(self.name)
        # print(self.self.id)
        # print(self.user_id)
        # print(fields.Datetime.now())
        # print('submit_time_sheet - 2')
        # self.env['account.analytic.line'].create({
        #     'unit_amount': 0,
        #     'account_id': self.analytic_account_id.id,
        #     'name': self.name,
        #     'is_timesheet': True,
        #     'date': fields.Datetime.now(),
        #     'todo_id': self.id,
        #     'user_id': self.user_id
        # })