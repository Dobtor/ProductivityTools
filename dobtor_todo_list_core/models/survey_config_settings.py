# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SurveyConfigSetting(models.TransientModel):
    _name = 'dobtor_todo_list_core.config.settings'
    _inherit = 'res.config.settings'

    module_dobtor_todo_list_survey = fields.Selection([
        (0, 'Todo-List do not require Survey'),
        (1, 'Allow Todo-List with survey')
    ],
        string="Todo-List Survey",
    )
