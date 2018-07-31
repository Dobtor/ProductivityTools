# -*- coding: utf-8 -*-

from odoo import models, fields, api


class DobtorTodoListCore(models.Model):
    _inherit = 'dobtor.todolist.core'

    @api.model
    def set_ref_models(self):
        selection = super(DobtorTodoListCore, self).set_ref_models()
        selection.append(('crm.lead', 'Crm Lead'))
        return selection
