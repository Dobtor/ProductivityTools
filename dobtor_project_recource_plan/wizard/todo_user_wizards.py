# -*- coding: utf-8 -*-

from odoo import api, fields, models


class TodoListCoreUser(models.TransientModel):
    _name = 'todo.list.core.user'
    _description = 'Todo-List Core User'

    todo_id = fields.Many2one(string='Todo',comodel_name='dobtor.todo.list.core')
    user_id = fields.Many2one('res.users', 'Assigned to' ,required=True)

    @api.multi
    def action_assign_user(self):
        for res in self:
            if res.user_id:
                res.todo_id.write({'user_id': res.user_id.id,'state':'assign'})
                