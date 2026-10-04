# -*- coding: utf-8 -*-
"""官方畫面 → Odoo 官方文件（K20）。

沒被我們改過的官方畫面不自己寫說明，直接連到 Odoo 18 官方文件的對應章節。
★ 網址由 AI 提議、系統驗證：實際 GET 得到 200，而且最後落在官方文件網址底下才自動
  核准；驗證不過的留給人審。模型會編網址，不能直接信。
"""
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

DEFAULT_BASE = 'https://www.odoo.com/documentation/18.0/'


class KnowledgeOfficialDoc(models.Model):
    _name = 'corpaas.knowledge.official_doc'
    _description = '官方文件對照'
    _order = 'state, id desc'

    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True)
    url = fields.Char(required=True)
    title = fields.Char()
    state = fields.Selection([('proposed', '待審'), ('approved', '已核准'),
                              ('rejected', '不採用')], default='proposed', index=True)
    verified = fields.Boolean(readonly=True, help='系統實際連線驗證過網址存在')
    auto_approved = fields.Boolean(readonly=True)
    note = fields.Char()

    _sql_constraints = [('feature_unique', 'unique(feature_id)', '一個功能點一筆官方文件對照')]

    @api.model
    def _base(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.official_doc_base') or DEFAULT_BASE

    @api.model
    def _verify_url(self, url):
        base = self._base()
        if not url or not url.startswith(base):
            return False
        try:
            r = requests.get(url, timeout=10, allow_redirects=True,
                             headers={'User-Agent': 'CorPaaS-Knowledge/1.0'})
        except requests.RequestException as e:
            _logger.info('[knowledge] 官方文件網址驗證失敗 %s：%s', url, e)
            return False
        return r.status_code == 200 and (r.url or url).startswith(base)

    def _check_approver(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_approver'):
            raise AccessError(_('只有知識核准者可以核准官方文件對照。'))

    def action_approve(self):
        self._check_approver()
        self.write({'state': 'approved'})
        return True

    def action_reject(self):
        self._check_approver()
        self.write({'state': 'rejected'})
        return True
