# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ProjectProject(models.Model):
    """專案擴展 - CRM 商機關聯

    在專案上新增 CRM 商機的反向關聯，
    提供智慧按鈕快速查看關聯商機。

    （原 dobtor_mail_activity_timesheet 併入。）
    """
    _inherit = 'project.project'

    lead_ids = fields.One2many(
        'crm.lead', 'project_id',
        string='CRM Leads',
    )
    lead_count = fields.Integer(
        string='Lead Count',
        compute='_compute_lead_count',
    )

    @api.depends('lead_ids')
    def _compute_lead_count(self):
        lead_data = self.env['crm.lead']._read_group(
            [('project_id', 'in', self.ids)],
            ['project_id'],
            ['__count'],
        )
        mapped_count = {project.id: count for project, count in lead_data}
        for project in self:
            project.lead_count = mapped_count.get(project.id, 0)

    def action_view_leads(self):
        """開啟關聯的 CRM 商機列表或表單視圖"""
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _("%(name)s's Leads", name=self.name),
            'res_model': 'crm.lead',
            'context': {'default_project_id': self.id},
            'domain': [('project_id', '=', self.id)],
        }
        if self.lead_count == 1:
            action['view_mode'] = 'form'
            action['res_id'] = self.lead_ids.id
        else:
            action['view_mode'] = 'list,form'
        return action
