# -*- coding: utf-8 -*-
"""
Messaging Partner Link Wizard

Binds an external (messaging-only) contact into an existing customer, across any
provider. After binding:

  - the external ``messaging.account`` rows move to the target customer (so future
    inbound messages auto-attribute to it);
  - past messages authored by the source contact are re-pointed to the customer;
  - messaging channel memberships are transferred to the customer;
  - the now-orphan source contact is archived (or deleted).

This is the provider-agnostic generalization of LINE's ``line.partner.link``.
"""
import logging

from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class MessagingPartnerLink(models.TransientModel):
    _name = 'messaging.partner.link'
    _description = 'Link Messaging Contact to Existing Customer'

    def _default_info_message(self):
        return Markup(
            '<p class="mb-0"><strong>%s</strong><br/>%s</p>'
            '<ul class="mb-0"><li>%s</li><li>%s</li><li>%s</li></ul>'
        ) % (
            _('This wizard binds a messaging contact into an existing customer.'),
            _('After binding:'),
            _('The customer receives the external account(s); future messages attach to it'),
            _('Past messages and conversations move to the customer'),
            _('The duplicate contact is archived'),
        )

    def _default_warning_message(self):
        return Markup('<strong>%s</strong> %s') % (
            _('Warning:'),
            _('Messages and memberships of the source contact will be re-assigned '
              'to the target customer.'),
        )

    info_message = fields.Html(default=_default_info_message, sanitize=False)
    warning_message = fields.Html(default=_default_warning_message, sanitize=False)

    source_partner_id = fields.Many2one(
        'res.partner', string='Messaging Contact', required=True,
        help='The external-only contact to merge away (it will be archived).',
    )
    target_partner_id = fields.Many2one(
        'res.partner', string='Existing Customer', required=True,
        help='The customer to keep; it will receive the conversations.',
    )
    archive_source = fields.Boolean(
        string='Archive Source Contact', default=True,
        help='Archive the duplicate after binding. Uncheck to delete it instead.',
    )

    source_preview = fields.Html(compute='_compute_previews')
    target_preview = fields.Html(compute='_compute_previews')

    @api.depends('source_partner_id', 'target_partner_id')
    def _compute_previews(self):
        for wizard in self:
            wizard.source_preview = wizard._partner_preview(wizard.source_partner_id) \
                or '<div class="p-2 text-muted">Select a messaging contact</div>'
            wizard.target_preview = wizard._partner_preview(wizard.target_partner_id) \
                or '<div class="p-2 text-muted">Select a customer</div>'

    def _partner_preview(self, partner):
        if not partner:
            return False
        channels = self.env['discuss.channel.member'].search_count([
            ('partner_id', '=', partner.id),
            ('channel_id.is_messaging_channel', '=', True),
        ])
        messages = self.env['mail.message'].sudo().search_count([
            ('author_id', '=', partner.id),
            ('model', '=', 'discuss.channel'),
        ])
        accounts = ', '.join(partner.messaging_account_ids.mapped('display_name')) or '-'
        return f"""
        <div class="p-2 bg-light rounded">
            <p><strong>Name:</strong> {partner.name or '-'}</p>
            <p><strong>Email:</strong> {partner.email or '-'}</p>
            <p><strong>Accounts:</strong> {accounts}</p>
            <p><strong>Conversations:</strong> {channels}</p>
            <p><strong>Authored messages:</strong> {messages}</p>
        </div>
        """

    @api.constrains('source_partner_id', 'target_partner_id')
    def _check_partners(self):
        for wizard in self:
            source, target = wizard.source_partner_id, wizard.target_partner_id
            if not (source and target):
                continue
            if source == target:
                raise ValidationError(_('Cannot bind a contact into itself.'))
            if not source.messaging_account_ids:
                raise ValidationError(
                    _('The source contact has no messaging account to move.'))

    def action_link_partner(self):
        self.ensure_one()
        source, target = self.source_partner_id, self.target_partner_id

        _logger.info("Binding messaging contact %s (ID:%s) into customer %s (ID:%s)",
                     source.name, source.id, target.name, target.id)

        accounts_moved = self._move_accounts(source, target)
        messages_moved = self._reassign_messages(source, target)
        members_moved = self._transfer_memberships(source, target)

        if not target.image_1920 and source.image_1920:
            target.sudo().image_1920 = source.image_1920

        if self.archive_source:
            source.active = False
        else:
            source.unlink()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Binding Successful'),
                'message': _(
                    'Bound into "%(target)s": %(accounts)d account(s), '
                    '%(messages)d message(s), %(members)d conversation(s).',
                    target=target.name, accounts=accounts_moved,
                    messages=messages_moved, members=members_moved,
                ),
                'type': 'success',
                'sticky': True,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _move_accounts(self, source, target):
        accounts = source.messaging_account_ids
        accounts.sudo().write({'partner_id': target.id})
        return len(accounts)

    def _reassign_messages(self, source, target):
        messages = self.env['mail.message'].sudo().search([
            ('author_id', '=', source.id),
        ])
        if messages:
            messages.write({'author_id': target.id})
        return len(messages)

    def _transfer_memberships(self, source, target):
        Member = self.env['discuss.channel.member'].sudo()
        moved = 0
        for member in Member.search([('partner_id', '=', source.id)]):
            other = Member.search([
                ('channel_id', '=', member.channel_id.id),
                ('partner_id', '=', target.id),
            ], limit=1)
            if other:
                member.unlink()
            else:
                member.partner_id = target.id
            moved += 1
        return moved
