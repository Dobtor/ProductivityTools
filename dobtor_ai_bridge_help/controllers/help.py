# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class AiHelpController(http.Controller):

    @http.route('/dobtor_ai/help/links', type='json', auth='user')
    def links(self, query=None, action=None, model=None, view_type=None, limit=5, **kw):
        """面板的「此畫面說明」與提問後附的說明連結。

        ★ 權限跟後台助理同一個群組：入口只在面板上，但任何登入者都能直接打這支路由，
          而它會替使用者對外發請求。
        """
        if not request.env['ai.assistant'].scope_allowed('backend'):
            return {'ok': False, 'error': 'forbidden', 'results': [], 'hosts': []}
        return request.env['ai.help.links'].fetch_links(
            query=query, action=action, model=model, view_type=view_type, limit=limit)
