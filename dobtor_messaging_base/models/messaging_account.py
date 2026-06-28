# -*- coding: utf-8 -*-
"""Canonical external-identity store.

A ``messaging.account`` links one ``res.partner`` to one external identity on a
given provider (e.g. a LINE userId, a Telegram user id). A single partner may
hold several accounts (LINE + Telegram + ...), which is why identity lives in a
dedicated model rather than as columns on res.partner.
"""
from odoo import api, fields, models


class MessagingAccount(models.Model):
    _name = 'messaging.account'
    _description = 'Messaging External Account'
    _rec_name = 'display_name'

    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        required=True,
        ondelete='cascade',
        index=True,
    )

    provider = fields.Selection(
        selection='_selection_messaging_provider',
        string='Provider',
        required=True,
        index=True,
    )

    external_user_id = fields.Char(
        string='External User ID',
        required=True,
        index=True,
        help='The user/account identifier on the external platform.',
    )

    username = fields.Char(string='Username')
    external_display_name = fields.Char(string='Platform Display Name')
    status_message = fields.Char(string='Status Message')
    picture_url = fields.Char(string='Picture URL')

    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('provider_user_uniq', 'UNIQUE(provider, external_user_id)',
         'This external account is already linked to a contact.'),
    ]

    @api.model
    def _selection_messaging_provider(self):
        """Provider list — extended by platform modules.

        Platform modules override this and append their own code, e.g.::

            def _selection_messaging_provider(self):
                return super()._selection_messaging_provider() + [('line', 'LINE')]
        """
        return []

    @api.depends('provider', 'external_display_name', 'username', 'external_user_id', 'partner_id.name')
    def _compute_display_name(self):
        provider_labels = dict(self._fields['provider']._description_selection(self.env))
        for account in self:
            label = provider_labels.get(account.provider, account.provider or '?')
            who = (account.external_display_name or account.username
                   or account.partner_id.name or account.external_user_id or '')
            account.display_name = f'[{label}] {who}'.strip()
