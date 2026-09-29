# -*- coding: utf-8 -*-

from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestActivityCrmLink(TransactionCase):

    def test_timesheet_project_from_lead(self):
        project = self.env['project.project'].create({'name': 'Lead Project'})
        lead = self.env['crm.lead'].create({'name': 'Lead', 'project_id': project.id})
        act = self.env['mail.activity'].create({
            'summary': 'l', 'date_deadline': date.today(),
            'res_model_id': self.env['ir.model']._get_id('crm.lead'),
            'res_id': lead.id,
        })
        self.assertEqual(act._get_timesheet_project(), project)
        self.assertEqual(act._project_from_res('crm.lead', lead.id), project)
