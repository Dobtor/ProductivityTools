# -*- coding: utf-8 -*-

from odoo import models, fields, api



class AbstractTodolistCopy(models.AbstractModel):
    _name = 'abstract.todolist.copy'

    @api.multi
    def copy_default_extend(self, default=None, new_obj=None):
        pass

    @api.multi
    def map_todolist(self, new_obj):
        for todolist in self.todolist_ids:
            defaults = todolist.defaults_copy()
            self.copy_default_extend(defaults, new_obj)
            self.browse(new_obj.id).write(
                {'todolist_ids': todolist.copy(defaults)})
        return True

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        new_obj = super(AbstractTodolistCopy, self).copy(default)
        if 'todolist_ids' not in default:
            self.map_todolist(new_obj)
        return new_obj
