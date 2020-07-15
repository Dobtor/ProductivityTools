# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class CrmLead(models.Model):
    _name = 'crm.lead'
    _inherit = ['crm.lead', 'abstract.todo.list']

    is_template = fields.Boolean(
        string='Is Setting',
        copy=False
    )
    # analytic_account_options = fields.Boolean(
    #     string='Choose Current',
    # )

    # @api.multi
    # def reference_todo_list(self, new_crm_lead):
    #     for case in new_crm_lead.case:
    #         for todo_list in case.todo_list_ids:
    #             self.env['dobtor.todo.list.core'].browse(todo_list.id).write(
    #                 {'parent_model': 'crm.lead,' + str(new_crm_lead.id)})
    #     return True

    @api.constrains('stage_id')
    @api.multi
    def restrict(self):
        self.ensure_one()
        if self.stage_id and self.lock_stage:
            todo_lists = self.env['dobtor.todo.list.core'].search(
                [('ref_model', '=', u'{0},{1}'.format(self._name, str(self.id)))])
            if todo_lists:
                for todo_list in todo_lists:
                    if todo_list.state in ('todo', 'waiting'):
                        raise ValidationError(
                            _("You can't move it to next stage. Some todos are not completed yet.!"))

    @api.multi
    def copy_default_extend(self, default, new_obj):
        default.update({
            'ref_model': self._name + ',' + str(new_obj.id),
        })

    @api.multi
    def new_opportunity(self, default=None):
        crm_lead_id = self.copy(default)
        return crm_lead_id

    @api.model
    def create(self, vals):
        if 'picked_template' in vals:
            if vals['picked_template']:
                item = self.browse(vals['picked_template'])
                opportunity_id = item.new_opportunity({'name': vals['name']})
                return opportunity_id
        opportunity_id = super(CrmLead, self).create(vals)
        return opportunity_id

    @api.multi
    def _get_template(self):
        return [(x.id, x.name) for x in self.search([('is_template', '=', 'True')])]

    picked_template = fields.Selection(
        string='Opportunity Template',
        selection='_get_template'
    )

    @api.multi
    def set_as_template(self):
        for item in self:
            item.is_template = True

    @api.multi
    def reset_as_origin(self):
        for item in self:
            item.is_template = False

    # allow_timesheets = fields.Boolean("Allow timesheets", default=True)
    # analytic_account_id = fields.Many2one('account.analytic.account', string="Analytic Account", copy=False, ondelete='set null',
    #                                       help="Link this crm lead to an analytic account if you need financial management on projects. "
    #                                       "It enables you to connect crm lead with budgets, planning, cost and revenue analysis, timesheets on projects, etc.")

    # @api.onchange('partner_id')
    # def _onchange_partner_id(self):
    #     domain = []
    #     if self.partner_id:
    #         domain = [('partner_id', '=', self.partner_id.id)]
    #     return {'domain': {'analytic_account_id': domain}}

    # @api.onchange('analytic_account_id')
    # def _onchange_analytic_account(self):
    #     if not self.analytic_account_id and self._origin:
    #         self.allow_timesheets = False

    # @api.constrains('allow_timesheets', 'analytic_account_id')
    # def _check_allow_timesheet(self):
    #     for crm in self:
    #         if crm.allow_timesheets and not crm.analytic_account_id:
    #             raise ValidationError(
    #                 _('To allow timesheet, your CRM %s should have an analytic account set.' % (crm.name,)))

    # @api.model
    # def name_create(self, name):
    #     """ Create a CRM Lead with name_create should generate analytic account creation """
    #     values = {
    #         'name': name,
    #         'allow_timesheets': True,
    #     }
    #     return self.create(values).name_get()[0]

    # @api.model
    # def create(self, values):
    #     """ Create an analytic account if CRM Lead allow timesheet and don't provide one
    #         Note: create it before calling super() to avoid raising the ValidationError from _check_allow_timesheet
    #     """
    #     allow_timesheets = values['allow_timesheets'] if 'allow_timesheets' in values else self.default_get(
    #         ['allow_timesheets'])['allow_timesheets']
    #     if allow_timesheets and not values.get('analytic_account_id'):
    #         analytic_account = self.env['account.analytic.account'].create({
    #             'name': values.get('name', _('Unknown Analytic Account')),
    #             'company_id': values.get('company_id', self.env.user.company_id.id),
    #             'partner_id': values.get('partner_id'),
    #             'active': True,
    #         })
    #         values['analytic_account_id'] = analytic_account.id
    #     return super().create(values)

    # @api.multi
    # def write(self, values):
    #     # create the AA for project still allowing timesheet
    #     if values.get('allow_timesheets'):
    #         for crm in self:
    #             if not crm.analytic_account_id and not values.get('analytic_account_id'):
    #                 crm._create_analytic_account()
    #     result = super().write(values)
    #     return result

    # @api.multi
    # def unlink(self):
    #     """ Delete the empty related analytic account """
    #     analytic_accounts_to_delete = self.env['account.analytic.account']
    #     for crm in self:
    #         if crm.analytic_account_id and not crm.analytic_account_id.line_ids:
    #             analytic_accounts_to_delete |= crm.analytic_account_id
    #     result = super(crm, self).unlink()
    #     analytic_accounts_to_delete.unlink()
    #     return result

    # @api.model
    # def _init_data_analytic_account(self):
    #     self.search([('analytic_account_id', '=', False),
    #                  ('allow_timesheets', '=', True)])._create_analytic_account()

    # def _create_analytic_account(self):
    #     for crm in self:
    #         analytic_account = self.env['account.analytic.account'].create({
    #             'name': crm.name,
    #             'company_id': crm.company_id.id,
    #             'partner_id': crm.partner_id.id,
    #             'active': True,
    #         })
    #         crm.write({'analytic_account_id': analytic_account.id})
