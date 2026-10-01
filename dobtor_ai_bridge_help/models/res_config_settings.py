# -*- coding: utf-8 -*-
from odoo import api, fields, models

DEFAULT_CONSOLE_URL = 'https://admin.corpaas.com'
DEFAULT_PUBLIC_DOMAINS = 'www.corpaas.com'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_help_console_url = fields.Char(
        string='CorPaaS 主控台網址', config_parameter='dobtor_ai_help.console_url',
        default=DEFAULT_CONSOLE_URL,
        help='本站伺服器向它查說明連結；留空＝預設值。'
             '主控台下發金鑰時會一併寫入這個值（金鑰只在簽發它的主控台有效）。')
    ai_help_database = fields.Char(
        string='本庫名稱', config_parameter='dobtor_ai_help.database',
        help='主控台用這個名稱找出本庫屬於哪個方案。留空＝目前資料庫的名稱；'
             '只有資料庫在主控台登記的名字與實際不同時才需要填。')
    ai_help_public_domains = fields.Char(
        string='公開說明網域', config_parameter='dobtor_ai_help.public_domains',
        default=DEFAULT_PUBLIC_DOMAINS,
        help='說明頁所在的網域，逗號分隔。只有這些網域與主控台本身的 https 連結會顯示出來。')

    # ★ 只顯示「有沒有」，絕不把金鑰值送到瀏覽器：非 config_parameter、非儲存的
    #   compute 欄位，讀的是 bool，金鑰字串從頭到尾不離開伺服器。
    ai_help_key_set = fields.Boolean(
        string='已收到主控台金鑰', compute='_compute_ai_help_key_set',
        help='主控台下發到 ICP dobtor_ai_help.console_key 的簽章金鑰是否存在。')

    @api.depends('company_id')
    def _compute_ai_help_key_set(self):
        has_key = bool((self.env['ir.config_parameter'].sudo().get_param(
            'dobtor_ai_help.console_key') or '').strip())
        for rec in self:
            rec.ai_help_key_set = has_key
