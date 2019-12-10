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
    apply_transfer = fields.Boolean(string='apply_transfer', default=False)

    plan_id = fields.Many2one('resource.plan', 'Plan', ondelete='cascade')



    @api.multi
    def action_assign_todo(self):
        for todo in self:
            return {
                    'name':
                    _('Assign Todo'),
                    'type':'ir.actions.act_window',
                    'res_model':'todo.user.wizard',
                    'view_type': 'form',
                    'view_mode':'form',
                    'view_id':self.env.ref('dobtor_project_resource_plan.todo_user_wizards').id,
                    'target': 'new',
                    'context': {
                        'default_todo_id': todo.id,
                    }
                }
    @api.multi
    def name_get(self):
        result = []
        for request in self:
            if request.user_id:
                result.append((request.id, request.user_id.name))
            else:
                result.append((request.id, request.name or request.description))
        return result

    @api.model
    def index_state(self):
        res = super().index_state()
        res.append((15, 'transfer'))
        return res

    @api.model
    def get_todo_state(self):
        res = super().get_todo_state()
        state = [('transfer', 'Transfer')]
        return self._sort_state(res + state)

    @api.multi
    def action_apply_transfer(self):
        for todo in self:
            todo.apply_transfer = True

    @api.multi
    def action_refused_transfer(self):
        for todo in self:
            todo.apply_transfer = False

    @api.multi
    def action_transfer_todo(self):
        for todo in self:
            todo.state='transfer'
            todo.user_id = None
            todo.apply_transfer = False

    # @api.multi
    # def send_transfer_todo_email(
    #         self,
    #         todo_name,
    #         todo_reviewer_id,
    #         todo_user_id,
    #         ref_model=None,
    # ):
    #     reviewer = self.env["res.users"].browse(todo_reviewer_id)
    #     user = self.env["res.users"].browse(todo_user_id)

    #     subtype = 'dobtor_todo_list_core.todo_list_core_subtype'

    #     body = ''
    #     partner_ids = []

    #     if self.env.user == reviewer:
    #         body = "The planned todo status has been changed to transfer, please check the plan."
    #         partner_ids = [user.partner_id.id]
    #     elif self.env.user == user:
    #         body = 'Your todo has been approved for transfer. Please help to find the right volunteer'
    #         partner_ids = [reviewer.partner_id.id]
    #     else:
    #         body = 'The planned todo status has been changed to transfer, please check the plan.'
    #         partner_ids = [user.partner_id.id, reviewer.partner_id.id]

    #     self.message_post(subject='Your todo list',
    #                       message_type='comment',
    #                       subtype=subtype,
    #                       body=body,
    #                       partner_ids=partner_ids)