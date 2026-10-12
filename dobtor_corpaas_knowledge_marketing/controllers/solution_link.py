# -*- coding: utf-8 -*-
"""方案頁的穩定網址（主從計畫 #16）：/corpaas/s/<方案全域識別> → 該方案的變體頁。

★ 對外連結（加購連結、行銷文案）不帶本地變體 id；網址裡的 #錨點 瀏覽器會保留到轉址後的頁面。
"""
from odoo import http
from odoo.http import request


class KnowledgeSolutionLink(http.Controller):

    @http.route('/corpaas/s/<string:key>', type='http', auth='public', website=True, sitemap=False)
    def solution_by_key(self, key, **kw):
        env = request.env(su=True)
        pkg = env['infrastructure.solution.package'].search([('knowledge_global_key', '=', key[:120])], limit=1)
        variant = env['corpaas.knowledge.hooks']._marketing_variant(pkg) if pkg else None
        if not variant:
            raise request.not_found()
        return request.redirect('/corpaas/solution/%s' % variant.id, code=302)
