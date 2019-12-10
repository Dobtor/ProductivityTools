# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class ResPartner(models.Model):
    _inherit = 'res.partner'

    caregiver_id  = fields.Many2one(string=u'Caregiver', comodel_name='res.partner')
    recipient_ids  = fields.One2many(string=u'Recipient',comodel_name='partner.recipient',inverse_name='partner_id')
    