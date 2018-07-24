# -*- coding: utf-8 -*-

from odoo import models, fields, api


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    @api.multi
    def map_todolist(self, new_crm_lead):
        for todolist in self.todolist_ids:
            defaults = {
                'name': todolist.name,
                'creater': todolist.creater.id,
                'reviewer_id': todolist.reviewer_id.id,
                'user_id': todolist.user_id.id,
                'ref_model': 'crm.lead,' + str(new_crm_lead.id),
            }
            self.browse(new_crm_lead.id).write(
                {'todolist_ids': todolist.copy(defaults)})
        return True

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        crm_lead = super(CrmLead, self).copy(default)
        if 'todolist_ids' not in default:
            self.map_todolist(crm_lead)
        return crm_lead

    # @api.multi
    # def _get_template(self):
    #     stage_type_obj = self.env['project.task.type']
    #     return [(x.id, x.name) for x in self.search([('stage_id', '=', stage_type_obj.get_type_template().id)])]

    # picked_template = fields.Selection(
    #     string='Project Template',
    #     selection='_get_template'
    # )
