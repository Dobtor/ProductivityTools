# -*- coding: utf-8 -*-
"""登入頁改成首頁彈窗：未登入開 /web/login → 導到 /?popup=login&redirect=…（同 94愛分享 的 dobtor_user_signup）。"""
from urllib.parse import quote

from odoo import http
from odoo.http import request

from odoo.addons.website.controllers.main import Website


class HardLogin(Website):

    @http.route()
    def web_login(self, *args, **kw):
        if request.httprequest.method == 'GET' and not request.session.uid:
            return request.redirect('/?popup=login&redirect=%s' % quote(kw.get('redirect') or '/'))
        return super().web_login(*args, **kw)
