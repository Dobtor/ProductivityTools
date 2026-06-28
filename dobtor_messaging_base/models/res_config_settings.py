# -*- coding: utf-8 -*-
"""Provider-agnostic messaging settings.

Platform modules add their own credential fields (LINE secret/token, Telegram
bot token/secret) in their own res.config.settings inherit; here we only keep
the cross-provider operator routing.
"""
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    messaging_operator_partner_ids = fields.Many2many(
        'res.partner',
        'messaging_operator_settings_rel',
        string='Messaging Operators',
        help='Staff added to every new external messaging conversation '
             '(across all providers).',
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        param = self.env['ir.config_parameter'].sudo().get_param(
            'messaging.operator_partner_ids', default='')
        ids = [int(p) for p in param.split(',') if p.strip().isdigit()]
        res['messaging_operator_partner_ids'] = [(6, 0, ids)]
        return res

    def set_values(self):
        super().set_values()
        ids = ','.join(str(pid) for pid in self.messaging_operator_partner_ids.ids)
        self.env['ir.config_parameter'].sudo().set_param(
            'messaging.operator_partner_ids', ids)
