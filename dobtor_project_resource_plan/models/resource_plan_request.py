# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ResourcePlanRequest(models.Model):
    _name = 'resource.plan.request'
    _description = 'Project Resource Plan'

    plan_id = fields.Many2one('resource.plan', 'Plan', required=True,ondelete="cascade")
    assigner = fields.Many2one('res.users',
                               'Assigner',
                               required=True,
                               default=lambda self: self.env.user)
    user_id = fields.Many2one('res.users', 'User', required=True)
    reviewer_id = fields.Many2one(related="plan_id.reviewer_id")
    description = fields.Html(string='Description')
    user_check = fields.Boolean(string='user_check', default=False)
    reviewer_check = fields.Boolean(string='reviewer_check', default=False)
    created_todo  = fields.Boolean(string='created_todo', default=False)
    state = fields.Selection(string='State',
                             selection=[('draft', 'New'),
                                        ('confirm', 'Approved'),
                                        ('refuse', 'Refused'),
                                        ('cancel', 'Cancelled'),('done','Done')],
                             default="draft")


    @api.multi
    def user_confirm_todo_request(self):
        for request in self:
            request.user_check = True
            if request.reviewer_check ==True:
                request.state ='confirm'

    @api.multi
    def reviewer_confirm_todo_request(self):
        for request in self:
            request.reviewer_check = True
            if request.user_check ==True:
                request.state ='confirm'

    @api.multi
    def user_refused_todo_request(self):
        for request in self:
            request.user_check = False
            request.state ='refuse'

    @api.multi
    def reviewer_refused_todo_request(self):
        for request in self:
            request.reviewer_check = False
            request.state ='refuse'

    @api.multi
    def create_plan_todo(self):
        for request in self:
            if request.plan_id.planned_people == 0 or len(request.plan_id.todo_ids)  < request.plan_id.planned_people and request.user_check and request.reviewer_check and request.created_todo == False:
                self.env['dobtor.todo.list.core'].create({
                    'name':
                    request.plan_id.name,
                    'ref_model':
                    'project.task' + ',' + str(request.plan_id.task_id.id),
                    'user_id':
                    request.user_id.id,
                    'description':
                    request.plan_id.description,
                    'reviewer_id':
                    request.plan_id.reviewer_id.id,
                    'date_deadline':
                    request.plan_id.date_deadline,
                    'planned_hours':
                    request.plan_id.planned_hours,
                    'plan_id':
                    request.plan_id.id,
                })
                request.created_todo = True
                request.state = 'done'
            elif  len(request.plan_id.todo_ids) >= request.plan_id.planned_people:
                raise ValidationError(_('The task has been scheduled, thanks for your support.'))

    @api.multi
    def name_get(self):
        result = []
        for request in self:
            result.append(
                (request.id, _("Applicant : %s" % (request.user_id.name))))
        return result