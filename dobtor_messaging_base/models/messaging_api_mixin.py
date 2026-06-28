# -*- coding: utf-8 -*-
"""Shared API helpers for messaging provider services.

Provider API clients (e.g. ``line.api.service``, ``telegram.api.service``)
should ``_inherit = ['messaging.api.mixin']`` to reuse the SSRF-safe media
download and image validation utilities.
"""
import base64
import logging
from urllib.parse import urlparse

import requests

from odoo import models

_logger = logging.getLogger(__name__)


class MessagingApiMixin(models.AbstractModel):
    _name = 'messaging.api.mixin'
    _description = 'Messaging Provider API Mixin'

    # Default safety limits — providers may override.
    MESSAGING_MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
    MESSAGING_DOWNLOAD_TIMEOUT = 10  # seconds

    # Image magic bytes (file signatures) accepted by _validate_image_magic_bytes.
    _MESSAGING_IMAGE_SIGNATURES = [
        (b'\xff\xd8\xff', 'JPEG'),
        (b'\x89PNG\r\n\x1a\n', 'PNG'),
        (b'GIF87a', 'GIF'),
        (b'GIF89a', 'GIF'),
        (b'RIFF', 'WEBP'),  # followed by 'WEBP' at offset 8
    ]

    def _messaging_download_safe(self, url, trusted_domains, *, as_base64=True,
                                 require_image=True):
        """Download a remote asset with SSRF protection.

        :param url: source URL (must be HTTPS, host in ``trusted_domains``).
        :param trusted_domains: iterable of allowed lowercase hostnames.
        :param as_base64: return base64 str if True, else raw bytes.
        :param require_image: enforce image content-type + magic bytes.
        :return: base64 str / bytes, or None when rejected/failed.
        """
        if not url:
            return None

        trusted = {d.lower() for d in (trusted_domains or [])}
        try:
            parsed = urlparse(url)
            if parsed.scheme != 'https':
                _logger.warning("SECURITY: rejected non-HTTPS URL: %s", url[:100])
                return None

            hostname = (parsed.hostname or '').lower()
            if hostname not in trusted:
                _logger.warning("SECURITY: rejected URL from untrusted host: %s", hostname)
                return None

            response = requests.get(
                url,
                timeout=self.MESSAGING_DOWNLOAD_TIMEOUT,
                stream=True,
                headers={'User-Agent': 'Odoo-Messaging-Integration/1.0'},
            )
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '')
            if require_image and not content_type.startswith('image/'):
                _logger.warning("SECURITY: rejected non-image content type: %s", content_type)
                return None
            if require_image and 'svg' in content_type.lower():
                _logger.warning("SECURITY: rejected SVG to prevent XSS")
                return None

            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > self.MESSAGING_MAX_IMAGE_SIZE:
                _logger.warning("SECURITY: rejected oversized asset: %s bytes", content_length)
                return None

            content = b''
            for chunk in response.iter_content(chunk_size=8192):
                content += chunk
                if len(content) > self.MESSAGING_MAX_IMAGE_SIZE:
                    _logger.warning("SECURITY: asset exceeded size limit during download")
                    return None

            if require_image and not self._messaging_validate_image_magic_bytes(content):
                _logger.warning("SECURITY: invalid image magic bytes")
                return None

            return base64.b64encode(content).decode('utf-8') if as_base64 else content

        except requests.RequestException as e:
            _logger.warning("Failed to download messaging asset: %s", e)
            return None
        except Exception as e:  # noqa: BLE001 - never let a download break the flow
            _logger.error("Error downloading messaging asset: %s", e)
            return None

    def _messaging_validate_image_magic_bytes(self, content):
        """Validate image content by checking known file signatures."""
        if not content or len(content) < 12:
            return False
        for magic, _fmt in self._MESSAGING_IMAGE_SIGNATURES:
            if content.startswith(magic):
                if magic == b'RIFF' and content[8:12] != b'WEBP':
                    continue
                return True
        return False
