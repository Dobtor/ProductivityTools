# -*- coding: utf-8 -*-
"""課程頁預設排序。

☠️ 文件型 channel 在 promote_strategy 為 specific/none 時預設 `latest`（依發佈日期），
  章節與步驟順序全亂。knowledge_managed 的 channel 沒指定 sorting 時改用 `sequence`。
★ 繼承真正擁有這條 route 的 class（WebsiteSlides）；`@http.route()` 不帶參數＝
  沿用父類別的全部路由設定（網址、sitemap、handle_params_access_error）。
"""
from odoo import http
from odoo.http import request

from odoo.addons.website_slides.controllers.main import WebsiteSlides


class KnowledgeWebsiteSlides(WebsiteSlides):

    @http.route()
    def channel(self, channel=False, channel_id=False, category=None, category_id=False,
                tag=None, page=1, slide_category=None, uncategorized=False, sorting=None,
                search=None, **kw):
        if not sorting:
            target = channel
            if not target and channel_id:
                target = request.env['slide.channel'].sudo().browse(abs(int(channel_id))).exists()
            if target and target.sudo().knowledge_managed:
                sorting = 'sequence'
        return super().channel(channel=channel, channel_id=channel_id, category=category,
                               category_id=category_id, tag=tag, page=page,
                               slide_category=slide_category, uncategorized=uncategorized,
                               sorting=sorting, search=search, **kw)
