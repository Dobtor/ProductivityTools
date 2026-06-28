# -*- coding: utf-8 -*-
"""Partner messaging extensions (provider-agnostic).

Two concerns:

* the canonical external-identity link (``messaging_account_ids``) and the bind
  entry point used by the partner form;
* the "messaging company" a contact belongs to in the member panel, derived
  from ``commercial_partner_id`` (the parent company written by the panel) or,
  for internal users, their Odoo company.
"""
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    messaging_account_ids = fields.One2many(
        'messaging.account', 'partner_id', string='Messaging Accounts',
    )
    messaging_account_count = fields.Integer(
        compute='_compute_messaging_account_count',
    )
    messaging_channel_count = fields.Integer(
        string='Messaging Conversations',
        compute='_compute_messaging_channel_count',
        help='Number of external messaging conversations this contact is part of.',
    )

    @api.depends('messaging_account_ids')
    def _compute_messaging_account_count(self):
        for partner in self:
            partner.messaging_account_count = len(partner.messaging_account_ids)

    def _compute_messaging_channel_count(self):
        Member = self.env['discuss.channel.member']
        for partner in self:
            partner.messaging_channel_count = Member.search_count([
                ('partner_id', '=', partner.id),
                ('channel_id.is_messaging_channel', '=', True),
            ])

    def action_open_messaging_partner_link(self):
        """Open the wizard to bind this external contact into another customer."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bind Messaging Contact'),
            'res_model': 'messaging.partner.link',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_source_partner_id': self.id},
        }

    # ------------------------------------------------------------------
    # Member-panel company derivation
    # ------------------------------------------------------------------
    def _get_messaging_company(self):
        """Return the company (res.partner, is_company) this contact belongs to
        in the member panel.

        Priority:
          1. real parent company: ``commercial_partner_id`` (not self, a company)
             — "add to company" writes ``parent_id`` so commercial points to it.
          2. internal user fallback: ``user.company_id.partner_id``.
          3. neither -> empty (falls into "Unassigned").
        """
        self.ensure_one()
        commercial = self.commercial_partner_id
        if commercial and commercial.id != self.id and commercial.is_company:
            return commercial
        internal_user = self.user_ids.filtered(lambda u: not u.share)[:1]
        if internal_user and internal_user.company_id:
            return internal_user.company_id.partner_id
        return self.browse()

    def _to_store(self, store, /, **kwargs):
        """Attach each partner persona's owning company so the frontend can group
        members by company."""
        super()._to_store(store, **kwargs)
        for partner in self:
            try:
                company = partner.sudo()._get_messaging_company()
            except Exception as e:  # noqa: BLE001 - derive failure must not break persona serialization
                _logger.debug('messaging company derive failed for %s: %s', partner.id, e)
                company = self.browse()
            store.add(partner, {
                'messagingCompanyId': company.id if company else False,
                'messagingCompanyName': company.display_name if company else False,
            })
