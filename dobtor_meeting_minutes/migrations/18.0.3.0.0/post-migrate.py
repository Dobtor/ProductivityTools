# -*- coding: utf-8 -*-
"""筆記自 dobtor_mail_activity 搬入本模組後：補做筆記階段的擁有者重算，並重算日曆會議記錄數。

dobtor_mail_activity 18.0.1.9.0 的同名修正在跨版升級時已無法執行（本模組在它
之後才載入，當下沒有 note.note）。冪等。
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env['note.note']._recompute_owner_stages()
    if count:
        _logger.info('note.note: recomputed owner stage for %d notes', count)
    env['note.note']._recompute_calendar_note_counts()
    # 「Re-encrypt API Keys」cron 原本指向 res.company（方法其實在 res.config.settings），
    # 啟用後每次執行都 AttributeError；cron 是 noupdate，既有資料庫要在這裡改。
    cron = env.ref('dobtor_meeting_minutes.ir_cron_reencrypt_api_keys', raise_if_not_found=False)
    settings_model = env['ir.model']._get('res.config.settings')
    if cron and cron.model_id != settings_model:
        cron.model_id = settings_model
