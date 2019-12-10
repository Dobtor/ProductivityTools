# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class ProjectTask(models.Model):
    _inherit = 'project.task'

    
    plan_ids = fields.One2many(
        string='Plan',
        comodel_name='resource.plan',
        inverse_name='task_id',
    )
    
    @api.multi
    def create_resource_plan(self):
        for task in self:
            return {
                    'name':_('Project Resource Plan'),
                    'type':'ir.actions.act_window',
                    'res_model':'project.task.resource.plan',
                    'view_type': 'form',
                    'view_mode':'form',
                    'view_id':self.env.ref('dobtor_project_recource_plan.project_resource_plan_wizards').id,
                    'target': 'new',
                    'context': {
                        'default_task_id': task.id,
                    }
                    }