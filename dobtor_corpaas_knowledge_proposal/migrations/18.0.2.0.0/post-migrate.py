# -*- coding: utf-8 -*-
"""2.0：建議書升級成「案件的版本」。沒有案件的舊建議書各自升為一個案件的 v1.0。

☠️ 不合併「同客戶」的舊建議書：以前的「複製新版」沒有記錄版本關係，
   用客戶去猜會把不同案件併在一起，而拆開比併錯容易修。
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env['corpaas.knowledge.case']._migrate_legacy_proposals()
    _logger.info('建議書 2.0 遷移：%s 份建議書各自升為案件的 v1.0', count)
    # 文件輸出（dobtor_doc_editor）：升級時 post_init_hook 不會跑，這裡補上範本與綁定
    env['corpaas.knowledge.proposal']._ensure_doc_template()
