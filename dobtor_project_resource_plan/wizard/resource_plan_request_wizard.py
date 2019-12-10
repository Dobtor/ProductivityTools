# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResourcePlanRequestWizard(models.TransientModel):
    _name = 'resource.plan.request.wizard'
    _description = 'Resource Plan Request wizard'

    plan_id = fields.Many2one('resource.plan', 'Plan',required=True)
    assigner = fields.Many2one('res.users','Assigner', default=lambda self: self.env.user,required=True)
    user_id = fields.Many2one('res.users', 'User', required=True)
    reviewer_id = fields.Many2one(related="plan_id.reviewer_id")
    description = fields.Html(string='Description')
    
    @api.multi
    def action_user_request(self):
        for res in self:
            request = self.env['resource.plan.request'].create({
                    'plan_id':res.plan_id.id,
                    'assigner':res.assigner.id,
                    'description':res.description,
                    'reviewer_id':res.reviewer_id.id,
                    'user_id':res.user_id.id,
                  })
            if request.assigner == request.user_id:
                request.user_check = True
