# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.tools.translate import _


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    @api.multi
    def _get_template(self):
        return [(x.id, x.name) for x in self.env['project.project'].search([('state_id', '=', 'template')])]

    picked_template = fields.Selection(
        string='Project Template',
        selection='_get_template'
    )
    using_template = fields.Boolean(
        string='using template',
        default=False,
    )

    @api.model
    def create(self, vals):
        if vals.get('picked_template'):
            vals['using_template'] = True
        analytic_account = super(AccountAnalyticAccount, self).create(vals)
        return analytic_account

    @api.multi
    def write(self, vals):
        if vals.get('picked_template'):
            vals['using_template'] = True
        return super(AccountAnalyticAccount, self).write(vals)
    

    @api.multi
    def project_create(self, vals):
        '''
        This function is called at the time of analytic account creation and is used to create a project automatically linked to it if the conditions are meet.
        '''
        self.ensure_one()
        Project = self.env['project.project']
        project = Project.with_context(active_test=False).search(
            [('analytic_account_id', '=', self.id)])
        if not project and self._trigger_project_creation(vals):
            project_values = {
                'name': vals.get('name'),
                'analytic_account_id': self.id,
                'use_tasks': True,
                'picked_template': vals.get('picked_template'),
            }
            return Project.create(project_values).id
        return False
