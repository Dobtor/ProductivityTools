# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.tools.translate import _


class project_project(models.Model):
    _inherit = "project.project"

    # region model operation (Create,Deep Copy)
    # TODO [IMP][REF]
    @api.multi
    def reference_checklist(self, new_project):
        for task in new_project.tasks:
            for checklist in task.checklist_ids:
                self.env['dobtor.checklist.core'].browse(checklist.id).write(
                    {'parent_model': 'project.project,' + str(new_project.id)})
        return True

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        project = super(project_project, self).copy(default)
        self.reference_checklist(project)
        return project

    @api.model
    def create(self, vals):
        if vals.get('picked_template'):
            analytic_account_id = None if not vals.get('analytic_account_id') else vals.get('analytic_account_id')
            item = self.browse(vals['picked_template'])
            project_id = item.new_project(
                {'name': vals['name']}, analytic_account_id)
        else:
            project_id = super(project_project, self).create(vals)
        return project_id
    # endregion

    # region form action

    @api.multi
    def action_set_template(self):
        """ Action """
        self.ensure_one()
        self.update({'state_id': 'template', 'sequence_state': 1})

    @api.multi
    def new_project(self, default=None, analytic_account_id=None):
        self.ensure_one()
        project_id = self.copy(default)
        if analytic_account_id:
            project_id.write({
                'state_id': 'new',
                'sequence_state': 0,
                'analytic_account_id': analytic_account_id,
                'use_tasks': True,
            })
        else :
            project_id.write({
                'state_id': 'new',
                'sequence_state': 0
            })
        return project_id

    @api.multi
    def action_new_project(self, default=None):
        """ Action """
        project_id = self.new_project(default)
        return {
            'name': _('new project'),
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': self._name,
            'type': 'ir.actions.act_window',
            'target': 'current',
            'res_id': project_id.id,
        }

    @api.multi
    def action_reset_project(self):
        """ Action """
        self.ensure_one()
        self.write({
            'state_id': 'new',
            'sequence_state': 0
        })
        return
    # endregion

    state_id = fields.Selection(
        string='state',
        selection=[('new', 'New'), ('template', 'Template')],
        default='new',
    )
    sequence_state = fields.Integer(
        compute="count_sequence", string="State Check")

    @api.multi
    def count_sequence(self):
        for item in self:
            if item.state_id == "template":
                item.sequence_state = 1
            else:
                item.sequence_state = 0

    @api.multi
    def _get_template(self):
        return [(x.id, x.name) for x in self.search([('state_id', '=', 'template')])]

    picked_template = fields.Selection(
        string='Project Template',
        selection='_get_template'
    )

    # region upload freature (Attchment)
    @api.multi
    def _get_checklist_ids(slef, obj):
        checklist_ids = []
        for task in obj.task_ids:
            for checklist in task.checklist_ids.ids:
                checklist_ids.append(checklist)
        return checklist_ids


    @api.multi
    def _get_attachment_domain(self):
        for obj in self:
            domain = super(project_project, obj)._get_attachment_domain()
            checklist_domain = [
                '&',
                ('res_model', '=', 'dobtor.checklist.core'),
                ('res_id', 'in', self._get_checklist_ids(obj))
            ]
            return ['|'] + domain + checklist_domain
