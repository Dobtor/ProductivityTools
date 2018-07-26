# -*- coding: utf-8 -*-

from odoo import models, fields, api


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    # TODO [FIX] : if user modify name field
    @api.multi
    def get_stage_new(self):
        return self.search([('name', '=', 'New')], limit=1)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # TODO [IMP][REF] : batch create record and performance,
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

    is_template = fields.Boolean(
        string='Is Setting',
    )

    @api.multi
    def new_opportunity(self, default=None):
        stage_obj = self.env['crm.stage']
        if stage_obj.get_stage_new():
            default.update({'stage_id': stage_obj.get_stage_new().id})
        crm_lead_id = self.copy(default)
        return crm_lead_id

    @api.model
    def create(self, vals):
        if vals['picked_template']:
            item = self.browse(vals['picked_template'])
            opportunity_id = item.new_opportunity({'name': vals['name']})
        else:
            opportunity_id = super(CrmLead, self).create(vals)
        return opportunity_id

    @api.multi
    def _get_template(self):
        return [(x.id, x.name) for x in self.search([('is_template', '=', 'True')])]

    picked_template = fields.Selection(
        string='Opportunity Template',
        selection='_get_template'
    )


    @api.multi
    def set_as_template(self):
        for item in self:
            item.is_template = True

    @api.multi
    def reset_as_origin(self):
        for item in self:
            item.is_template = False
