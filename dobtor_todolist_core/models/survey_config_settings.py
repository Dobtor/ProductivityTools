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

    # Is_open_dobtor_todolist_project_task = fields.Selection([
    #     (0, 'Project task do not require Survey'),
    #     (1, 'Allow Project Task with survey')
    # ],
    #     string="Project Task",
    # )

    # Is_open_dobtor_todolist_crm_lead = fields.Selection([
    #     (0, 'Crm Opportunity do not require Survey'),
    #     (1, 'Allow Crm Opportunity with survey')
    # ],
    #     string="Crm Opportunity",
    # )

    # def set_Is_open_dobtor_todolist_project_task(self):
    #     self.env['ir.config_parameter'].set_param(
    #         'Is_open_dobtor_todolist_project_task', self.Is_open_dobtor_todolist_project_task, groups=['base.group_system'])

    # def get_default_Is_open_dobtor_todolist_project_task(self, fields):
    #     Is_open_dobtor_todolist_project_task = self.env['ir.config_parameter'].get_param(
    #         'Is_open_dobtor_todolist_project_task', default=False)
    #     return dict(Is_open_dobtor_todolist_project_task=Is_open_dobtor_todolist_project_task)

    # def set_Is_open_dobtor_todolist_crm_lead(self):
    #     self.env['ir.config_parameter'].set_param(
    #         'Is_open_dobtor_todolist_crm_lead', self.Is_open_dobtor_todolist_crm_lead, groups=['base.group_system'])

    # def get_default_Is_open_dobtor_todolist_crm_lead(self, fields):
    #     Is_open_dobtor_todolist_crm_lead = self.env['ir.config_parameter'].get_param(
    #         'Is_open_dobtor_todolist_crm_lead', default=False)
    #     return dict(Is_open_dobtor_todolist_crm_lead=Is_open_dobtor_todolist_crm_lead)
