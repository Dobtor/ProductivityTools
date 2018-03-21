# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SurveyConfigSetting(models.Model):
    _name = 'dobtor_todolist_survey.config.settings'
    _inherit = 'res.config.settings'

    module_dobtor_todolist_survey_task = fields.Selection([
        (0, 'Project task do not require Survey'),
        (1, 'Allow Project Task with survey')
    ],
        string="Project Task",
        help="Install the dobtor_tolist_survey_task module"
    )

