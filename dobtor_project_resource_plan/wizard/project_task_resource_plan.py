# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProjectTaskResourcePlan(models.TransientModel):
    _name = 'project.task.resource.plan'
    _description = 'Project Resourece Plan'
    _inherit ='dobtor.todo.list.core'

    task_id = fields.Many2one(string='Task',comodel_name='project.task', ondelete='restrict',required=True)
    user_ids = fields.Many2many(string='Assign to', comodel_name='res.users', )
    planned_people = fields.Integer(string='Planned people',required=True,default=0)
    is_limited = fields.Boolean(string='limited',default=False)
    @api.multi
    def action_create_plan(self):
        for record in self:
            plan = self.env['resource.plan'].create({
                    'name':record.name,
                    'ref_model':'project.task'+','+str(record.task_id.id),
                    'user_ids':record.user_ids,
                    'description':record.description,
                    'reviewer_id':record.reviewer_id.id,
                    'date_assign':record.date_assign,
                    'date_deadline':record.date_deadline,
                    'planned_hours':record.planned_hours,
                    'is_limited':record.is_limited,
                    'planned_people':record.planned_people})
                    
            if len(record.user_ids)>0:
                for i in range(0,len(record.user_ids)):
                    self.env['resource.plan.request'].create({
                    'plan_id':plan.id,
                    'assigner':self.env.user.id,
                    'reviewer_id':plan.reviewer_id.id,
                    'user_id':record.user_ids[i].id,
                    'reviewer_check':True,
                  })
                    # self.env['dobtor.todo.list.core'].create({
                    #     'name':record.name,
                    #     'ref_model':'project.task'+','+str(record.task_id.id),
                    #     'user_id':record.user_ids[i].id,
                    #     'description':record.description,
                    #     'reviewer_id':record.reviewer_id.id,
                    #     'date_assign':record.date_assign,
                    #     'date_deadline':record.date_deadline,
                    #     'planned_hours':record.planned_hours,
                    #     'plan_id':plan.id,
                    # })

               
        return       
                
