# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SurveyConfigSetting(models.TransientModel):
    _name = 'dobtor_todolist_core.config.settings'
    _inherit = 'res.config.settings'

    module_dobtor_todolist_survey = fields.Selection([
        (0, 'TodoList do not require Survey'),
        (1, 'Allow TodoList with survey')
    ],
        string="TodoList Survey",
    )
