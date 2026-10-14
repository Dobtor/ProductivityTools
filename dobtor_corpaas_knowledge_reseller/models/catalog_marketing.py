# -*- coding: utf-8 -*-
"""目錄項的行銷內容（能力卡片、本期新增）給所有白標經銷商的商品頁。

★ 不需要知識節點：經銷商的連接器同步目錄時順便拉，只看得到目錄本來就給他看的方案。
★ 行銷出口（dobtor_corpaas_knowledge_marketing）是軟相依：沒裝就回空的內容，
  不在 manifest 加硬相依（這個橋接模組是 auto_install，加了會把行銷出口一起拉進來）。
★ 目錄 payload 帶 marketing_hash：內容變了目錄的 ETag 就跟著變，經銷商才會重拉；
  hash 沒變的目錄項，對方不必逐項打行銷 API。
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

EMPTY_MARKETING = {'cards': [], 'release_note': None, 'content_hash': False}


class SolutionPackageCatalogMarketing(models.Model):
    _inherit = 'infrastructure.solution.package'

    @api.model
    def _reseller_catalog_package(self, catalog_ref, reseller):
        """這位經銷商看得到、而且還在販售的目錄項；看不到或已下架回空集。

        ★ 與 GET /api/v1/catalog 同一套可見性（`_published_catalog`）：已發布、
          且沒有被這位經銷商的價格規則設成不可見。已下架（withdrawn）的不給行銷內容
          ——對方應該停售，商品頁上的內容也跟著撤。
        """
        if not catalog_ref or not reseller:
            return self.browse()
        pkg = self.sudo()._resolve_published(catalog_ref)
        if not pkg:
            return self.browse()
        hidden = self.env['reseller.price.rule'].sudo().search_count([
            ('reseller_id', '=', reseller.id), ('visible', '=', False),
            ('package_id', '=', pkg.id)])
        return self.browse() if hidden else pkg

    def _reseller_marketing_export(self):
        """(payload, 圖片附件 id 集合)；沒裝行銷出口或沒有上線內容 → 空內容、hash False。"""
        self.ensure_one()
        if not hasattr(self, '_marketing_export'):
            return dict(EMPTY_MARKETING), set()
        return self.sudo()._marketing_export()

    def _catalog_payload(self, reseller=None):
        payload = super()._catalog_payload(reseller=reseller)
        if not self.is_published:
            payload['marketing_hash'] = False
            return payload
        # ☠️ 目錄是所有經銷商同步的入口：行銷內容組不出來不能讓整份目錄 500。
        #   這時乾脆不帶 marketing_hash（對方視為「這次不知道」、維持現狀），
        #   帶 False 的話對方會把商品頁上的內容清掉。
        try:
            with self.env.cr.savepoint():
                payload['marketing_hash'] = self._reseller_marketing_export()[0]['content_hash']
        except Exception:  # noqa: BLE001
            _logger.exception('[knowledge] 目錄項行銷內容組裝失敗：%s', self.catalog_ref)
        return payload
