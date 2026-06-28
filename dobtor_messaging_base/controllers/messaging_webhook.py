# -*- coding: utf-8 -*-
"""Shared webhook scaffolding for messaging providers.

Odoo HTTP controllers cannot be merged via ``_inherit`` like models, so this is
a plain mixin class. A provider controller subclasses both ``http.Controller``
and ``MessagingWebhookMixin``, declares its own ``@http.route`` and implements
the abstract hooks. The mixin centralizes the inbound orchestration that is
identical across providers (channel + partner resolution, posting).

Provider-specific (must implement):
  * route + ``_messaging_verify_request`` (HMAC for LINE, secret_token+IP for Telegram)
  * ``_messaging_parse_updates`` -> list of normalized inbound dicts
  * media retrieval / sending (in the provider's API service)

Each normalized inbound dict produced by ``_messaging_parse_updates`` should be::

    {
        'source_type': 'user' | 'group',
        'source_id': '<conversation id>',
        'author_external_id': '<sender id>' | None,
        'author_profile': {...} | None,   # display_name, username, image_1920, ...
        'channel_vals': {...} | None,      # extra vals when creating the channel
        'body': '<html/text>' | '',
        'attachment_ids': [<ir.attachment id>, ...] | None,
    }
"""
import logging

from odoo import SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


class MessagingWebhookMixin:
    """Reusable inbound orchestration. ``provider_code`` must be set by subclass."""

    provider_code = None  # e.g. 'line', 'telegram'

    # ------------------------------------------------------------------
    # Abstract hooks — provider controllers must implement these.
    # ------------------------------------------------------------------
    def _messaging_verify_request(self, raw_body):
        """Return True if the incoming request is authentic. Provider-specific."""
        raise NotImplementedError

    def _messaging_parse_updates(self, payload):
        """Return a list of normalized inbound dicts (see module docstring)."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared orchestration
    # ------------------------------------------------------------------
    def _messaging_env(self):
        return request.env(user=SUPERUSER_ID)

    def _messaging_dispatch_inbound(self, normalized):
        """Resolve channel + author and post each normalized inbound message."""
        env = self._messaging_env()
        Channel = env['discuss.channel']
        provider = self.provider_code

        for item in normalized:
            try:
                source_id = item.get('source_id')
                if not source_id:
                    _logger.warning("[%s] inbound item missing source_id", provider)
                    continue

                channel = Channel._messaging_get_or_create_channel(
                    provider,
                    item.get('source_type', 'user'),
                    source_id,
                    item.get('channel_vals'),
                )

                author = env['res.partner']
                if item.get('author_external_id'):
                    author = Channel._messaging_get_or_create_partner(
                        provider,
                        item['author_external_id'],
                        item.get('author_profile'),
                    )
                    if author:
                        channel._messaging_ensure_member(author)

                channel._messaging_post_inbound(
                    author,
                    body=item.get('body', ''),
                    attachment_ids=item.get('attachment_ids'),
                    external_id=item.get('external_message_id'),
                )
                channel._messaging_touch_sync()
            except Exception as e:  # noqa: BLE001 - one bad event must not drop the batch
                _logger.error("[%s] failed to process inbound item: %s", provider, e, exc_info=True)
