# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class CrmLead(models.Model):
    _name = 'crm.lead'
    _inherit = ['crm.lead', 'abstract.todolist']

    is_template = fields.Boolean(
        string='Is Setting',
        copy=False
    )

    @api.constrains('stage_id')
    def restrict(self):
        if self.stage_id and self.lock_stage:
            todo_list = self.env['dobtor.todolist.core'].search(
                [('ref_name', '=', self._name), ('ref_id', '=', self.id)])
            if todo_list:
                for todo in todo_list:
                    if todo.state in ('todo', 'waiting'):
                        raise ValidationError(
                            _("You can't move it to next stage. Some todos are not completed yet.!"))

    @api.multi
    def copy_default_extend(self, default, new_obj):
        default.update({
            'ref_model': self._name + ',' + str(new_obj.id),
        })

    @api.multi
    def new_opportunity(self, default=None):
        stage_obj = self.env['crm.stage']
        if stage_obj.get_stage_new():
            default.update({'stage_id': stage_obj.get_stage_new().id})
        crm_lead_id = self.copy(default)
        return crm_lead_id

    @api.model
    def create(self, vals):
        if 'picked_template' in vals:
            if vals['picked_template']:
                item = self.browse(vals['picked_template'])
                opportunity_id = item.new_opportunity({'name': vals['name']})
                return opportunity_id
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
