# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SurveyConfigSetting(models.TransientModel):
    _name = 'dobtor_checklist_core.config.settings'
    _inherit = 'res.config.settings'

    module_dobtor_checklist_survey = fields.Selection([
        (0, 'Check-List do not require Survey'),
        (1, 'Allow Check-List with survey')
    ],
        string="Check-List Survey",
    )
