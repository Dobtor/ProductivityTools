# -*- coding: utf-8 -*-
"""白標經銷商 API —— 目錄項的行銷內容（給經銷商自己的商品頁）。

    GET /api/v1/catalog/<catalog_ref>/marketing                  已核准上線的能力卡片＋本期新增
                                                                  （圖片以 corpaas-image:<id> 標記；
                                                                  ETag＝content_hash，If-None-Match 命中回 304）
    GET /api/v1/catalog/<catalog_ref>/marketing/image/<att_id>   卡片裡的圖片（只限目前匯出引用到的）

★ 所有經銷商都能用（不需要知識節點），範圍＝GET /api/v1/catalog 給他看的目錄項；
  看不到、已下架都回 404，對方據此清掉商品頁上的內容。
★ 經銷商帳號是 portal 使用者：一律 sudo＋明確的經銷商範圍，不靠 API 使用者的模型權限。
"""
import logging

from odoo import http, _
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dobtor_infrastructure.controllers.provision_api import (
    _authenticate, _json_response, _error,
)

_logger = logging.getLogger(__name__)


class CatalogMarketingApi(http.Controller):

    def _package(self, catalog_ref):
        """(目錄項, 錯誤回應)。"""
        try:
            reseller = _authenticate()
        except AccessError as e:
            return None, _error(str(e), code='unauthorized', status=401)
        pkg = request.env['infrastructure.solution.package'].sudo()._reseller_catalog_package(
            catalog_ref, reseller)
        if not pkg:
            return None, _error(_('Catalog item not found.'), code='not_found', status=404)
        return pkg, None

    @http.route('/api/v1/catalog/<string:catalog_ref>/marketing', type='http', auth='public',
                methods=['GET'], csrf=False)
    def catalog_marketing(self, catalog_ref, **kw):
        pkg, err = self._package(catalog_ref)
        if err:
            return err
        payload, _images = pkg._reseller_marketing_export()
        payload = dict(payload, catalog_ref=pkg.catalog_ref)
        etag = '"%s"' % payload['content_hash'] if payload.get('content_hash') else None
        if etag and request.httprequest.headers.get('If-None-Match') == etag:
            return request.make_response('', headers=[('ETag', etag)], status=304)
        resp = _json_response(payload)
        if etag:
            resp.headers['ETag'] = etag
        return resp

    @http.route('/api/v1/catalog/<string:catalog_ref>/marketing/image/<int:att_id>',
                type='http', auth='public', methods=['GET'], csrf=False)
    def catalog_marketing_image(self, catalog_ref, att_id, **kw):
        pkg, err = self._package(catalog_ref)
        if err:
            return err
        _payload, images = pkg._reseller_marketing_export()
        att = request.env['ir.attachment'].sudo().browse(att_id).exists() \
            if att_id in images else None
        raw = att.raw if att else None
        if not raw:
            return _error(_('Image not found.'), code='not_found', status=404)
        return request.make_response(
            raw, headers=[('Content-Type', att.mimetype or 'application/octet-stream'),
                          ('Cache-Control', 'private, max-age=3600')])
