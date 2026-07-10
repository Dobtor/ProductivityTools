# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .apikey_scope import PARAM_MAX_GROUPS, PARAM_MAX_DURATION


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Global "API Key rules" -- shown under Settings > Permissions > API Keys,
    # just before the native "Manage API Keys" button (admin only). These cap
    # what a NON-admin user may grant on a key; system admins are exempt.
    apikey_max_group_ids = fields.Many2many(
        'res.groups', 'apikey_cfg_max_group_rel', 'cfg_id', 'group_id',
        string='API Key maximum permission scope')
    apikey_max_duration = fields.Selection(
        selection=[
            ('1', '1 Day'), ('7', '1 Week'), ('30', '1 Month'),
            ('90', '3 Months'), ('180', '6 Months'), ('365', '1 Year'),
            ('custom', 'Custom Date'), ('persistent', 'Persistent Key'),
        ],
        string='API Key maximum duration',
        default='persistent',
        config_parameter=PARAM_MAX_DURATION)

    @api.model
    def get_values(self):
        res = super().get_values()
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_MAX_GROUPS) or ''
        ids = [int(x) for x in raw.split(',') if x.strip().isdigit()]
        if not ids:
            # Unset == no restriction; display all groups so the admin sees the
            # "all loaded" default (decision R4).
            ids = self.env['res.groups'].search([]).ids
        res['apikey_max_group_ids'] = [(6, 0, ids)]
        return res

    def set_values(self):
        super().set_values()
        all_ids = set(self.env['res.groups'].search([]).ids)
        selected = set(self.apikey_max_group_ids.ids)
        # If everything is selected, store empty == unlimited (avoids persisting
        # a huge id list and keeps "empty == all" semantics).
        value = '' if selected >= all_ids else ','.join(map(str, sorted(selected)))
        self.env['ir.config_parameter'].sudo().set_param(PARAM_MAX_GROUPS, value)
