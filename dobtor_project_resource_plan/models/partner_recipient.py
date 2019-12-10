# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class PartnerRecipient(models.Model):
    _name = 'partner.recipient'
    
    partner_id = fields.Many2one('res.partner', string="Member")
    task_id = fields.Many2one('project.task', string="Task")