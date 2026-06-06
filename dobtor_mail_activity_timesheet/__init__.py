# -*- coding: utf-8 -*-

from . import models
from . import wizards


def _create_timesheet_transfer_configs(env):
    """為 CRM / 專案 / 銷售訂單建立待辦關聯設定（若尚未存在）。

    用 post_init（而非 XML data）以避免與既有資料衝突：舊版單體模組可能已
    在 DB 建立過這些 mail.activity.transfer.config（model_id 有 UNIQUE 約束），
    XML data 無法對「非本 xmlid 建立」的既存列去重，會觸發 UniqueViolation。
    此處以 model 為鍵去重，安全地只補建缺少的設定。
    """
    Config = env['mail.activity.transfer.config'].sudo()
    models_seq = [
        ('crm.lead', 20),
        ('project.project', 30),
        ('project.task', 40),
        ('sale.order', 50),
    ]
    for model_name, sequence in models_seq:
        model = env['ir.model'].search([('model', '=', model_name)], limit=1)
        if not model:
            continue
        if Config.search_count([('model_id', '=', model.id)]):
            continue
        Config.create({'model_id': model.id, 'sequence': sequence})


def _post_init_hook(env):
    """Post-init hook."""
    _create_timesheet_transfer_configs(env)
