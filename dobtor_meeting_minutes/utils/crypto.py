# -*- coding: utf-8 -*-
"""對稱加密（Fernet）— 用於 API key 等敏感 config 的 at-rest 加密

設計重點：
- Fernet key 的取得有優先序，最佳做法是放 env var / odoo.conf，避免 DB backup 洩漏
- 加密後用 ``ENC::`` prefix 區分，便於向後相容（舊純文字值仍可讀）
- 解密失敗時回退為當作純文字，模組仍能運作

金鑰優先序：
1. 環境變數 ``DOBTOR_MM_FERNET_KEY``（最佳）
2. ``odoo.conf`` 選項 ``dobtor_meeting_minutes_fernet_key``
3. ``ir.config_parameter`` key ``dobtor_meeting_minutes.fernet_key``
   （自動產生；WARNING 寫入 log，建議管理員改放 env/conf）
"""
import logging
import os

import odoo.tools as odoo_tools
from cryptography.fernet import Fernet, InvalidToken

_logger = logging.getLogger(__name__)

ENC_PREFIX = 'ENC::'
ENC_VERSIONED_PREFIX_RE = None  # initialized below

ENV_VAR_NAME = 'DOBTOR_MM_FERNET_KEY'
CONF_OPTION_NAME = 'dobtor_meeting_minutes_fernet_key'
CONFIG_PARAM_KEY = 'dobtor_meeting_minutes.fernet_key'

# 舊版 key（輪換後保留以便 re-encrypt）— 可放多把，由新到舊
# 環境變數 DOBTOR_MM_FERNET_KEY_OLD_1, _OLD_2, ... 或 odoo.conf 相同命名
ENV_OLD_KEY_PATTERN = 'DOBTOR_MM_FERNET_KEY_OLD_{}'
CONF_OLD_OPTION_PATTERN = 'dobtor_meeting_minutes_fernet_key_old_{}'

# 版本號 — 每次輪換遞增；format: ENC::v2::<ciphertext>
KEY_VERSION_PARAM = 'dobtor_meeting_minutes.fernet_key_version'

_KEY_CACHE = {'key': None, 'source': None, 'version': 1, 'old_keys': []}

import re
ENC_VERSIONED_PREFIX_RE = re.compile(r'^ENC::v(\d+)::')


def _load_key_from_env():
    value = os.environ.get(ENV_VAR_NAME)
    return value.encode() if value else None


def _load_key_from_conf():
    value = odoo_tools.config.get(CONF_OPTION_NAME)
    return value.encode() if value else None


def _load_key_from_db(env):
    """Load or generate Fernet key from ir.config_parameter.

    Auto-generates on first call. Logs warning because key should ideally
    live outside DB (env var or odoo.conf) to avoid DB-backup leak.
    """
    ICP = env['ir.config_parameter'].sudo()
    value = ICP.get_param(CONFIG_PARAM_KEY)
    if not value:
        new_key = Fernet.generate_key().decode()
        ICP.set_param(CONFIG_PARAM_KEY, new_key)
        _logger.warning(
            '[security] Fernet key auto-generated and stored in ir.config_parameter. '
            'For production, please migrate this key to environment variable '
            '%s or odoo.conf option %s to prevent leak via DB backup.',
            ENV_VAR_NAME, CONF_OPTION_NAME,
        )
        value = new_key
    return value.encode()


def _load_old_keys():
    """Load legacy keys (for decrypting old ciphertexts after rotation).

    Priority per slot: env var → odoo.conf. Stops at first missing slot.
    """
    keys = []
    for i in range(1, 10):
        v = os.environ.get(ENV_OLD_KEY_PATTERN.format(i))
        if not v:
            v = odoo_tools.config.get(CONF_OLD_OPTION_PATTERN.format(i))
        if not v:
            break
        keys.append(v.encode())
    return keys


def get_fernet(env=None):
    """Return a Fernet instance using the best available (current) key source."""
    if _KEY_CACHE['key']:
        return Fernet(_KEY_CACHE['key'])

    key = _load_key_from_env()
    source = 'env'
    if not key:
        key = _load_key_from_conf()
        source = 'conf'
    if not key and env is not None:
        key = _load_key_from_db(env)
        source = 'db'
    if not key:
        raise RuntimeError(
            f'No Fernet key available. Set {ENV_VAR_NAME} env var, '
            f'"{CONF_OPTION_NAME}" in odoo.conf, or provide env to auto-generate.'
        )
    _KEY_CACHE['key'] = key
    _KEY_CACHE['source'] = source
    _KEY_CACHE['old_keys'] = _load_old_keys()
    if env is not None:
        try:
            ICP = env['ir.config_parameter'].sudo()
            _KEY_CACHE['version'] = int(ICP.get_param(KEY_VERSION_PARAM, '1'))
        except Exception:
            _KEY_CACHE['version'] = 1
    _logger.info(
        '[security] Fernet key loaded from %s (version=%s, %d old keys available)',
        source, _KEY_CACHE['version'], len(_KEY_CACHE['old_keys']),
    )
    return Fernet(key)


def _get_multi_fernet(env=None):
    """Return (current_fernet, list_of_old_fernets) for decryption fallback."""
    current = get_fernet(env)
    olds = [Fernet(k) for k in _KEY_CACHE['old_keys']]
    return current, olds


def _parse_encrypted(value):
    """Parse an encrypted string → (version, token).

    Supports both legacy ``ENC::<token>`` (assumed version=1) and
    new ``ENC::v<N>::<token>`` formats.
    """
    if not isinstance(value, str) or not value.startswith(ENC_PREFIX):
        return None, None
    m = ENC_VERSIONED_PREFIX_RE.match(value)
    if m:
        return int(m.group(1)), value[m.end():]
    return 1, value[len(ENC_PREFIX):]


def encrypt(plaintext, env=None):
    """Encrypt plaintext with current key, returning ``ENC::v<N>::<token>``.

    Already-encrypted values (start with ENC::) are returned unchanged.
    """
    if plaintext is None or plaintext == '':
        return plaintext
    if isinstance(plaintext, str) and plaintext.startswith(ENC_PREFIX):
        return plaintext
    fernet = get_fernet(env)
    version = _KEY_CACHE.get('version', 1)
    token = fernet.encrypt(plaintext.encode('utf-8')).decode('utf-8')
    return f'ENC::v{version}::{token}'


def decrypt(ciphertext, env=None):
    """Decrypt a value, trying current key first then old keys (for rotation grace).

    Legacy plaintext values (no prefix) returned as-is.
    Invalid token returns input unchanged + warning log.
    """
    if ciphertext is None or ciphertext == '':
        return ciphertext
    if not isinstance(ciphertext, str) or not ciphertext.startswith(ENC_PREFIX):
        return ciphertext  # legacy plain-text

    version, token = _parse_encrypted(ciphertext)
    if token is None:
        return ciphertext

    current, old_keys = _get_multi_fernet(env)
    token_bytes = token.encode('utf-8')

    # Try current key first
    try:
        return current.decrypt(token_bytes).decode('utf-8')
    except InvalidToken:
        pass
    # Fallback through old keys
    for old_fernet in old_keys:
        try:
            return old_fernet.decrypt(token_bytes).decode('utf-8')
        except InvalidToken:
            continue

    _logger.error(
        '[security] Fernet decryption failed for version=%s (tried current + %d old keys)',
        version, len(old_keys),
    )
    return ciphertext


def is_encrypted(value):
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def get_ciphertext_version(value):
    """Return the key version of a ciphertext (1 for legacy, N for versioned)."""
    v, _ = _parse_encrypted(value)
    return v


def bump_key_version(env):
    """Increment and persist the key version counter.

    Called AFTER admin has:
    1. Moved old key to DOBTOR_MM_FERNET_KEY_OLD_1 / config option
    2. Set new key as DOBTOR_MM_FERNET_KEY / config option
    3. Cleared cache via ``clear_key_cache()``
    """
    ICP = env['ir.config_parameter'].sudo()
    current = int(ICP.get_param(KEY_VERSION_PARAM, '1'))
    new_version = current + 1
    ICP.set_param(KEY_VERSION_PARAM, str(new_version))
    clear_key_cache()
    _logger.warning(
        '[security] Fernet key version bumped to %s — existing ciphertexts will be '
        'decrypted via old key fallback until re-encrypted.',
        new_version,
    )
    return new_version


def clear_key_cache():
    """Reset the in-process key cache (used after rotation)."""
    _KEY_CACHE['key'] = None
    _KEY_CACHE['source'] = None
    _KEY_CACHE['version'] = 1
    _KEY_CACHE['old_keys'] = []
