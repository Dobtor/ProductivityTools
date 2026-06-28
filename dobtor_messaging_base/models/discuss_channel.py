# -*- coding: utf-8 -*-
"""Provider-agnostic messaging layer on discuss.channel.

This file carries two cooperating concerns of the base module:

1. **Messaging provider skeleton** (LINE / Telegram / ...): neutral identity
   fields (provider / source), an outbound sync skeleton (``message_post``
   override) that dispatches to a provider hook ``_<code>_send_message``, and
   reusable inbound helpers for provider controllers (get-or-create channel /
   partner, post inbound, member management). The module registers NO provider,
   so on a stand-alone install every dispatch path is inert.

2. **Company-centric member panel**: companies the panel shows as buckets
   (``panel_company_ids``) plus the actions the Discuss member panel calls to
   add a company bucket and assign a member to a company (writing
   ``res.partner.parent_id``). Both are surfaced to the frontend through
   ``_channel_basic_info``.
"""
import logging

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    _sql_constraints = [
        ('messaging_source_uniq',
         'UNIQUE(messaging_provider, messaging_source_id)',
         'A messaging source can only be synced to one channel.'),
    ]

    # ------------------------------------------------------------------
    # Messaging provider identity / classification
    # ------------------------------------------------------------------
    messaging_provider = fields.Selection(
        selection='_selection_messaging_provider',
        string='Messaging Provider',
        index=True,
        help='External messaging platform this channel is bound to.',
    )

    messaging_source_type = fields.Selection(
        [('user', 'Personal'), ('group', 'Group')],
        string='Source Type',
        index=True,
        help='Normalized conversation type (1-to-1 vs group).',
    )

    messaging_source_id = fields.Char(
        string='Source ID',
        index=True,
        help='Conversation identifier on the external platform '
             '(LINE userId/groupId, Telegram chat.id, ...).',
    )

    is_messaging_channel = fields.Boolean(
        compute='_compute_messaging_channel_info', store=True, index=True,
    )
    messaging_category = fields.Selection(
        [('group', 'Group'), ('personal', 'Personal')],
        compute='_compute_messaging_channel_info', store=True,
    )
    messaging_sort_sequence = fields.Integer(
        compute='_compute_messaging_channel_info', store=True,
    )

    messaging_sync_enabled = fields.Boolean(
        string='Messaging Sync Enabled', default=True,
        help='Enable bidirectional synchronization with the external platform.',
    )
    messaging_last_sync_date = fields.Datetime(
        string='Last Messaging Sync', readonly=True,
    )
    messaging_picture_url = fields.Char(string='Messaging Picture URL')

    # ------------------------------------------------------------------
    # Company-centric member panel
    # ------------------------------------------------------------------
    panel_company_ids = fields.Many2many(
        'res.partner',
        'discuss_channel_panel_company_rel',
        'channel_id', 'partner_id',
        string='Panel Companies',
        domain=[('is_company', '=', True)],
        help='Companies shown as buckets in the member panel (including empty '
             'buckets kept as assignment targets).',
    )

    # ------------------------------------------------------------------
    # Provider registry (extended by platform modules)
    # ------------------------------------------------------------------
    @api.model
    def _selection_messaging_provider(self):
        """Provider list — platform modules override and append their code."""
        return []

    @api.depends('messaging_source_id', 'messaging_provider', 'messaging_source_type')
    def _compute_messaging_channel_info(self):
        for channel in self:
            is_msg = bool(channel.messaging_provider and channel.messaging_source_id)
            channel.is_messaging_channel = is_msg
            if not is_msg:
                channel.messaging_category = False
                channel.messaging_sort_sequence = 30
            elif channel.messaging_source_type == 'group':
                channel.messaging_category = 'group'
                channel.messaging_sort_sequence = 10
            else:
                channel.messaging_category = 'personal'
                channel.messaging_sort_sequence = 20

    # ------------------------------------------------------------------
    # Outbound (Odoo -> platform)
    # ------------------------------------------------------------------
    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        if self and self._messaging_should_sync_outbound(kwargs):
            try:
                self._messaging_dispatch('send_message', message, kwargs)
            except Exception as e:  # noqa: BLE001 - never block Odoo posting
                _logger.error("Outbound messaging sync failed: %s", e, exc_info=True)
        return message

    def _messaging_should_sync_outbound(self, message_kwargs):
        self.ensure_one()
        if not (self.is_messaging_channel and self.messaging_provider):
            return False
        if not self.messaging_sync_enabled:
            return False
        if self.env.context.get('_from_messaging'):
            return False
        if message_kwargs.get('message_type', 'comment') != 'comment':
            return False
        subtype = message_kwargs.get('subtype_xmlid')
        if subtype and subtype != 'mail.mt_comment':
            return False
        return True

    def _messaging_dispatch(self, hook, *args):
        """Call ``_<provider>_<hook>`` on this channel (provider implements it)."""
        self.ensure_one()
        method = f'_{self.messaging_provider}_{hook}'
        if not hasattr(self, method):
            _logger.warning("Provider '%s' has no hook '%s'", self.messaging_provider, method)
            return None
        return getattr(self, method)(*args)

    def _messaging_touch_sync(self):
        self.sudo().write({'messaging_last_sync_date': fields.Datetime.now()})

    # ------------------------------------------------------------------
    # Inbound helpers (platform -> Odoo) — called from provider controllers
    # ------------------------------------------------------------------
    @api.model
    def _messaging_get_or_create_channel(self, provider, source_type, source_id, vals=None):
        """Return the channel for a conversation, creating it if needed."""
        Channel = self.env['discuss.channel'].sudo()
        source_id = str(source_id)
        channel = Channel.search([
            ('messaging_provider', '=', provider),
            ('messaging_source_id', '=', source_id),
        ], limit=1)
        if channel:
            return channel

        create_vals = {
            'name': f'{provider.title()} {source_type} {source_id[:8]}',
            'channel_type': 'group',
            'messaging_provider': provider,
            'messaging_source_type': source_type,
            'messaging_source_id': source_id,
            'messaging_sync_enabled': True,
        }
        if vals:
            create_vals.update(vals)

        try:
            channel = Channel.create(create_vals)
        except Exception as create_error:  # race: another request created it
            from psycopg2 import IntegrityError
            if isinstance(create_error.__cause__, IntegrityError) or \
               'unique' in str(create_error).lower() or \
               'duplicate' in str(create_error).lower():
                channel = Channel.search([
                    ('messaging_provider', '=', provider),
                    ('messaging_source_id', '=', source_id),
                ], limit=1)
                if channel:
                    return channel
            raise

        self._messaging_add_default_members(channel)
        return channel

    @api.model
    def _messaging_get_or_create_partner(self, provider, external_user_id, profile=None):
        """Resolve (or create) the res.partner behind an external account.

        :param profile: optional dict with keys ``display_name``, ``username``,
            ``status_message``, ``picture_url``, ``image_1920`` (base64).
        """
        if not external_user_id:
            return self.env['res.partner']
        external_user_id = str(external_user_id)
        Account = self.env['messaging.account'].sudo()
        account = Account.search([
            ('provider', '=', provider),
            ('external_user_id', '=', external_user_id),
        ], limit=1)
        if account:
            return account.partner_id

        profile = profile or {}
        partner_vals = {
            'name': profile.get('display_name') or f'{provider.title()} User {external_user_id[:8]}',
            'is_company': False,
        }
        if profile.get('image_1920'):
            partner_vals['image_1920'] = profile['image_1920']
        partner = self.env['res.partner'].sudo().create(partner_vals)

        Account.create({
            'partner_id': partner.id,
            'provider': provider,
            'external_user_id': external_user_id,
            'username': profile.get('username'),
            'external_display_name': profile.get('display_name'),
            'status_message': profile.get('status_message'),
            'picture_url': profile.get('picture_url'),
        })
        return partner

    def _messaging_post_inbound(self, author, body='', attachment_ids=None,
                                message_type='comment', subtype_xmlid='mail.mt_comment',
                                external_id=None):
        """Post an inbound message, tagged so the outbound sync won't echo it.

        :param external_id: the platform message id; stored on the created
            mail.message (with the channel's provider) so providers can later
            match edits/deletes back to it.
        """
        self.ensure_one()
        message = self.with_context(_from_messaging=True).message_post(
            body=body or '',
            message_type=message_type,
            subtype_xmlid=subtype_xmlid,
            author_id=author.id if author else None,
            attachment_ids=attachment_ids or [],
        )
        if message and (external_id or self.messaging_provider):
            vals = {}
            if external_id:
                vals['messaging_external_id'] = str(external_id)
            if self.messaging_provider:
                vals['messaging_provider'] = self.messaging_provider
            if vals:
                message.sudo().write(vals)
        return message

    def _messaging_ensure_member(self, partner):
        """Ensure a partner is a member of this channel."""
        self.ensure_one()
        if not partner:
            return
        Member = self.env['discuss.channel.member'].sudo()
        exists = Member.search([
            ('channel_id', '=', self.id),
            ('partner_id', '=', partner.id),
        ], limit=1)
        if not exists:
            self.sudo().write({
                'channel_member_ids': [Command.create({'partner_id': partner.id})],
            })

    @api.model
    def _messaging_add_default_members(self, channel, extra_partner=None):
        """Add OdooBot + configured operators (+ optional contact) to a channel."""
        existing = set(channel.channel_member_ids.mapped('partner_id.id'))
        to_add = set()

        odoobot = self.env.ref('base.partner_root', raise_if_not_found=False)
        if odoobot:
            to_add.add(odoobot.id)
        if extra_partner:
            to_add.add(extra_partner.id)

        operators = self.env['ir.config_parameter'].sudo().get_param(
            'messaging.operator_partner_ids')
        if operators:
            try:
                for pid in [int(p.strip()) for p in operators.split(',') if p.strip()]:
                    if self.env['res.partner'].browse(pid).exists():
                        to_add.add(pid)
            except (ValueError, AttributeError):
                pass
        else:
            admin = self.env.ref('base.user_admin', raise_if_not_found=False)
            if admin and admin.partner_id:
                to_add.add(admin.partner_id.id)

        to_add -= existing
        if to_add:
            channel.sudo().write({
                'channel_member_ids': [Command.create({'partner_id': pid}) for pid in to_add],
            })

    # ------------------------------------------------------------------
    # Member panel actions (called from the frontend)
    # ------------------------------------------------------------------
    def action_messaging_add_company(self, value):
        """Add a company bucket to the panel.

        :param value: an existing company id (int) or a new company name (str).
        """
        self.ensure_one()
        Partner = self.env['res.partner']
        if isinstance(value, bool) or value in (None, ''):
            raise UserError(_('Please provide a company.'))
        if isinstance(value, int):
            company = Partner.browse(value).exists()
            if not company:
                raise UserError(_('Company not found.'))
        else:
            company = Partner.create({'name': str(value).strip(), 'is_company': True})
        if company not in self.panel_company_ids:
            self.panel_company_ids = [Command.link(company.id)]
        return {'id': company.id, 'name': company.display_name}

    def action_messaging_assign_member_company(self, partner_id, company_id):
        """Assign a member (partner) to a company (writes res.partner.parent_id).

        ``company_id`` False -> unassign (clears parent_id, back to Unassigned).
        Returns the derived company so the frontend can update optimistically.
        """
        self.ensure_one()
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            raise UserError(_('Member contact not found.'))
        company = False
        if company_id:
            company = self.env['res.partner'].browse(company_id).exists()
            if not company or not company.is_company:
                raise UserError(_('Invalid company.'))
        partner.parent_id = company.id if company else False
        if company and company not in self.panel_company_ids:
            self.panel_company_ids = [Command.link(company.id)]
        # Report the actually-derived company (an internal user may fall back to
        # their Odoo company).
        derived = partner._get_messaging_company()
        return {
            'partner_id': partner.id,
            'company': {'id': derived.id, 'name': derived.display_name} if derived else False,
        }

    def _messaging_panel_companies_data(self):
        self.ensure_one()
        return [
            {'id': c.id, 'name': c.display_name}
            for c in self.panel_company_ids
        ]

    # ------------------------------------------------------------------
    # Frontend enrichment
    # ------------------------------------------------------------------
    def _channel_basic_info(self):
        info = super()._channel_basic_info()
        # The company member panel only renders for channels that show a member
        # list (channel / group); skip the m2m read for 1-1 chats.
        if self.channel_type in ('channel', 'group'):
            info['panelCompanies'] = self._messaging_panel_companies_data()
        else:
            info['panelCompanies'] = []
        if self.is_messaging_channel:
            info.update({
                'is_messaging_channel': True,
                'messaging_provider': self.messaging_provider,
                'messaging_source_type': self.messaging_source_type,
                'messaging_category': self.messaging_category,
                'messaging_sort_sequence': self.messaging_sort_sequence,
            })
        else:
            info['is_messaging_channel'] = False
        return info
