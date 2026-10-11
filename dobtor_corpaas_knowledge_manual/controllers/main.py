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


class KnowledgeFeedbackController(http.Controller):
    """前台課程頁的說明書意見（限租戶管理員群組；每人每小時有上限）。"""

    @http.route('/knowledge/feedback/<int:slide_id>', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def knowledge_feedback(self, slide_id, body='', selected_text='', **kw):
        from datetime import timedelta

        from odoo import fields
        slide = request.env['slide.slide'].browse(slide_id).exists()
        if not slide or not slide._knowledge_feedback_allowed():
            return request.not_found()
        env = request.env
        limit = int(env['ir.config_parameter'].sudo().get_param('corpaas_knowledge.feedback_hourly_limit') or 10)
        since = fields.Datetime.now() - timedelta(hours=1)
        used = env['corpaas.knowledge.feedback'].sudo().search_count(
            [('user_id', '=', env.uid), ('source', '=', 'portal'), ('create_date', '>=', since)])
        body = (body or '').strip()
        if body and used < limit:
            art = slide.sudo()._knowledge_feedback_article()
            art._knowledge_feedback_create(body, source='portal',
                                           anchor={'selected_text': (selected_text or '')[:300] or None},
                                           user=env.user)
        # website_url 有網站網域時是完整網址：local=False 才不會被改成站內相對路徑
        return request.redirect('%s?kb_feedback=1' % slide.website_url, local=False)
