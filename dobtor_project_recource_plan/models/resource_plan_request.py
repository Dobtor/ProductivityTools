# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class ResourcePlanRequest(models.Model):
    _name = 'resource.plan.request'
    _description = 'Project Resource Plan'
    
    plan_id = fields.Many2one('resource.plan','Plan')
    assigner = fields.Many2one('res.partner','Assigner',default=lambda self: self.env.user)
    user_id = fields.Many2one('res.users','User')
    reviewer_id = fields.Many2one(related="plan_id.reviewer_id")
    description = fields.Html(string='Description')
    
    state = fields.Selection(string='State',selection=[
            ('draft', 'New'),
            ('confirm', 'Approval'),
            ('refuse', 'Refused'),
            ('validate', 'Approved'),
            ('cancel', 'Cancelled')])
    
    