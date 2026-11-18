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

    # 成員重建時要帶過去的個人狀態（摺疊、已讀位置、釘選／關注時間、通知設定）
    _MEMBER_STATE_FIELDS = (
        'custom_channel_name', 'fetched_message_id', 'seen_message_id',
        'new_message_separator', 'fold_state', 'custom_notifications',
        'mute_until_dt', 'unpin_dt', 'last_interest_dt', 'last_seen_dt',
    )

    def _member_state_vals(self, member):
        Member = self.env['discuss.channel.member']
        vals = {}
        for fname in self._MEMBER_STATE_FIELDS:
            if fname not in Member._fields:
                continue
            value = member[fname]
            vals[fname] = value.id if isinstance(value, models.BaseModel) else value
        return vals

    def _transfer_memberships(self, source, target):
        """把來源聯絡人的對話成員資格轉給目標客戶。

        Odoo 18 禁止改寫 ``discuss.channel.member.partner_id``（AccessError
        「您不能在 partner_id 上書寫」），所以改為：目標尚非成員 → 以來源成員的
        個人狀態替目標建一筆新成員；最後刪掉來源成員（與 dobtor_line_message
        ``line.partner.link`` a0fd58c 相同做法）。

        ``chat``（1 對 1）頻道的 create 只允許在「頻道尚無成員」時建立成員，
        所以 chat 改成：整個頻道的成員刪掉後，以替換過的 vals 一次批次重建。
        """
        Member = self.env['discuss.channel.member'].sudo()
        moved = 0
        for member in Member.search([('partner_id', '=', source.id)]):
            channel = member.channel_id
            target_member = Member.search([
                ('channel_id', '=', channel.id),
                ('partner_id', '=', target.id),
            ], limit=1)
            if target_member:
                member.unlink()
            elif channel.channel_type == 'chat':
                members = channel.channel_member_ids
                vals_list = []
                for m in members:
                    vals = self._member_state_vals(m)
                    vals.update({
                        'channel_id': channel.id,
                        'partner_id': target.id if m == member else m.partner_id.id,
                        'guest_id': m.guest_id.id,
                    })
                    vals_list.append(vals)
                members.unlink()
                Member.create(vals_list)
            else:
                vals = self._member_state_vals(member)
                vals.update({'channel_id': channel.id, 'partner_id': target.id})
                Member.create(vals)
                member.unlink()
            moved += 1
        return moved
