# -*- coding: utf-8 -*-
from odoo import _, api, fields, models

from .solution_package import OFFICIAL_EXCLUDE_DEFAULT


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    knowledge_doc_server_id = fields.Many2one(
        'infrastructure.server', string='說明主機',
        help='只在這台主機上的方案母體製作素材；方案沒有在這台上架就擋下。')
    knowledge_hub_url = fields.Char(string='AI Hub 網址',
                                    config_parameter='corpaas_knowledge.hub_url')
    knowledge_hub_key = fields.Char(string='AI Hub 金鑰',
                                    config_parameter='corpaas_knowledge.hub_key')
    knowledge_budget = fields.Float(string='每次更新 AI 預算（USD）',
                                    config_parameter='corpaas_knowledge.budget_usd_per_refresh',
                                    default=20.0)
    knowledge_phash_threshold = fields.Integer(
        string='換圖門檻（dHash 位元差）', default=10,
        config_parameter='corpaas_knowledge.phash_threshold')
    knowledge_rename_threshold = fields.Float(
        string='改名偵測相似度門檻', default=0.6,
        config_parameter='corpaas_knowledge.rename_threshold')
    knowledge_playwright_image = fields.Char(
        string='截圖映像', config_parameter='corpaas_knowledge.playwright_image',
        default='mcr.microsoft.com/playwright/python:v1.48.0-jammy')
    knowledge_fonts_dir = fields.Char(
        string='中文字型目錄（主機）', config_parameter='corpaas_knowledge.fonts_dir',
        default='/usr/share/fonts/opentype/noto')
    knowledge_official_exclude = fields.Char(
        string='官方模組排除清單', default=OFFICIAL_EXCLUDE_DEFAULT,
        config_parameter='corpaas_knowledge.official_exclude',
        help='逗號分隔，可用萬用字元。這些 Odoo 官方模組不納入知識盤點；清空會回到預設清單。')
    knowledge_public_base_url = fields.Char(
        string='說明頁網址前綴', config_parameter='corpaas_knowledge.public_base_url',
        help='help API 回傳的連結前綴，例如 https://www.corpaas.com')

    @api.model
    def get_values(self):
        res = super().get_values()
        sid = self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.doc_server_id')
        res['knowledge_doc_server_id'] = int(sid) if sid and sid.isdigit() else False
        return res

    def set_values(self):
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_param(
            'corpaas_knowledge.doc_server_id', self.knowledge_doc_server_id.id or '')

    def action_knowledge_prepare_doc_server(self):
        """一鍵準備說明主機：檢查並排入安裝缺的元件（中文字型、截圖映像…）。"""
        self.execute()
        server = self.knowledge_doc_server_id
        if not server:
            from odoo.exceptions import UserError
            raise UserError(_('請先選擇說明主機。'))
        return server.action_host_prepare_required()

    @api.model
    def knowledge_shot_settings(self):
        icp = self.env['ir.config_parameter'].sudo()
        return {
            'image': icp.get_param('corpaas_knowledge.playwright_image'),
            'fonts_dir': icp.get_param('corpaas_knowledge.fonts_dir'),
            'phash_threshold': int(icp.get_param('corpaas_knowledge.phash_threshold') or 10),
            'memory': '1.5g', 'cpus': 1,
        }
