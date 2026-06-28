# -*- coding: utf-8 -*-
"""Track the external-platform identity of a synced message.

These provider-agnostic columns let a platform module match an inbound message
back to its external counterpart (e.g. to apply an edit delivered later).
"""
from odoo import fields, models


class MailMessage(models.Model):
    _inherit = 'mail.message'

    messaging_external_id = fields.Char(
        string='External Message ID', index=True,
        help='Identifier of this message on the external platform (inbound).',
    )
    messaging_provider = fields.Char(
        string='Messaging Provider Code', index=True,
        help='Provider code of the channel this message was synced from.',
    )
