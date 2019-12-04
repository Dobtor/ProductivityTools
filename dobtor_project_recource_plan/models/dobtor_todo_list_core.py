# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class DobtorTodoListCore(models.Model):
    _inherit = 'dobtor.todo.list.core'

    user_id = fields.Many2one('res.users', 'Assigned to', required=False)
    type_ids = fields.Many2many('project.task.type',
                                'todo_task_type_rel',
                                'todo_id',
                                'type_id',
                                string='Todo Type')
    apply_transfer = fields.Boolean(string='apply_transfer',default=False)

    plan_id = fields.Many2one('resource.plan','Plan',ondelete='cascade')

    @api.model
    def index_state(self):
        res = super().index_state()
        res.append((15, 'assign'))
        res.append((16,'transfer'))
        return res

    @api.model
    def get_todo_state(self):
        res = super().get_todo_state()
        state = [('assign', "Assign"),('transfer','Transfer')]
        return self._sort_state(res + state)

    @api.multi
    def action_apply_transfer(self):
        for todo in self:
            todo.apply_transfer = True
    
    # @api.multi
    # def action_reject_transfer(self):
    #     for todo in self:
    #         todo.apply_transfer = True


    @api.multi
    def action_transfer_todo(self):
        for todo in self:
            todo.write({'state': 'transfer'})
            todo.user_id = None
            todo.apply_transfer = False

    @api.multi
    def action_assign_todo(self):
        for todo in self:
            if todo.user_id:
                todo.write({'state': 'assign'})
            else:
                return {
                    'name':
                    _('Assign Todo'),
                    'type':'ir.actions.act_window',
                    'res_model':'todo.list.core.user',
                    'view_type': 'form',
                    'view_mode':'form',
                    'view_id':self.env.ref('dobtor_project_recource_plan.todo_user_wizards').id,
                    'target': 'new',
                    'context': {
                        'default_todo_id': todo.id,
                    }
                }

    @api.multi
    def action_apply_todo(self):
        return