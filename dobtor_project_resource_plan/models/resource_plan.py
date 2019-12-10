# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class ResourcePlan(models.Model):
    _name = 'resource.plan'
    _description = 'Project Resource Plan'
    _inherit = 'dobtor.todo.list.core'

    task_id = fields.Many2one('project.task', 'Task', ondelete="cascade")
    todo_ids = fields.One2many('dobtor.todo.list.core', 'plan_id', 'Todo')
    planned_people = fields.Integer(string='people')
    planned_people_str = fields.Char(string='Manpower',
                                     compute="_compute_planned_people_str")
    # state = fields.Selection(string='Status',selection=[('valor1', 'valor1'), ('valor2', 'valor2')])
    limit = fields.Boolean(string='limit')
    user_ids = fields.Many2many(string='Assign to', comodel_name='res.users')

    is_limited = fields.Boolean(string='limited',default=False)

    state = fields.Selection(string='state',
                             selection=[('unavailable', 'Unavailable'),
                                        ('achieve', 'Achieve')],
                             default='unavailable',
                             compute="compute_states")
    request_ids = fields.One2many(string='requests',
                                  comodel_name='resource.plan.request',
                                  inverse_name='plan_id',
                                  domain=[('state', 'in', ('draft', 'confirm'))
                                          ])
    request_number = fields.Integer(string='requests num',
                                    compute="_compute_requests_num")

    @api.depends('todo_ids')
    def compute_states(self):
        for plan in self:
            if len(plan.todo_ids) >= plan.planned_people:
                plan.state = 'achieve'
            else:
                plan.state = 'unavailable'

    @api.depends('request_ids')
    def _compute_requests_num(self):
        for record in self:
            record.request_number = len(record.request_ids)

    @api.multi
    def action_get_requests_view(self):
        for record in self:
            return {
                'name': _('Requests'),
                'type': 'ir.actions.act_window',
                'res_model': 'resource.plan.request',
                'view_type': 'form',
                'view_mode': 'tree,form',
                'context': {
                    'default_plan_id': record.id,
                }
            }

    @api.depends('planned_people', 'todo_ids')
    def _compute_planned_people_str(self):
        for rec in self:
            if not rec.todo_ids and not rec.is_limited:
                rec.planned_people_str = _('0 applied, unlimited')
            elif not rec.todo_ids and rec.planned_people:
                rec.planned_people_str = (_("0 applied, %s planned") %
                                          (str(rec.planned_people)))
            if rec.todo_ids and rec.planned_people > 0:
                rec.planned_people_str = (
                    _("%s applied, %s planned") %
                    (str(len(rec.todo_ids)), str(rec.planned_people)))
            if rec.todo_ids and rec.planned_people <= 0:
                rec.planned_people_str = (_("%s applied, unlimited") %
                                          (str(len(rec.todo_ids))))
            if rec.is_limited==False:
                rec.limit = False
            elif rec.planned_people > 0 and rec.planned_people == len(rec.todo_ids) and rec.is_limited==True:
                rec.limit = True
            else:
                rec.limit = False

    @api.multi
    def apply_todo_request(self):
        for record in self:
            return {
                'name':
                _('Apply Resource Plan'),
                'type':
                'ir.actions.act_window',
                'res_model':
                'resource.plan.request.wizard',
                'view_type':
                'form',
                'view_mode':
                'form',
                'view_id':
                self.env.ref(
                    'dobtor_project_recource_plan.resource_plan_request_wizard'
                ).id,
                'target':
                'new',
                'context': {
                    'default_plan_id': record.id,
                }
            }
