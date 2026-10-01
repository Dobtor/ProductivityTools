# -*- coding: utf-8 -*-
"""端到端：租戶端真正的簽章程式 → HTTP → 主控台真正的驗證程式。

★ 兩邊各自的單元測試通過，不代表兩邊算的是同一個東西（body 序列化、時間戳格式、
  標頭大小寫都可能不一致）。這裡讓租戶端的 `_post_json` 實際打 HTTP 到測試伺服器。
  只替換「依庫名找金鑰」（建一筆 infrastructure.database 要整串主機／環境／實例）。
"""
from unittest.mock import patch

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestSignatureEndToEnd(HttpCase):

    def test_tenant_client_against_console(self):
        try:
            from odoo.addons.dobtor_ai_bridge_help.models.ai_help_links import _post_json
        except ImportError:
            self.skipTest('dobtor_ai_bridge_help 未安裝')
        DB = type(self.env['infrastructure.database'])
        url = '%s/corpaas/knowledge/v1/help' % self.base_url()
        params = {'database': 'tenant_e2e', 'query': '報名'}
        self.env['ir.config_parameter'].sudo().set_param(
            'corpaas_knowledge.help_require_signature', 'True')
        with patch.object(DB, '_knowledge_help_key_for',
                          lambda s, db: 'e2e-key' if db == 'tenant_e2e' else False):
            ok = _post_json(url, params, 8, database='tenant_e2e', key='e2e-key')
            self.assertTrue(ok.get('ok'), ok)
            self.assertEqual(_post_json(url, params, 8, database='tenant_e2e').get('error'),
                             'unsigned')
            self.assertEqual(_post_json(url, params, 8, database='tenant_e2e',
                                        key='wrong').get('error'), 'bad_signature')
            spoof = dict(params, database='other_db')
            self.assertEqual(_post_json(url, spoof, 8, database='tenant_e2e',
                                        key='e2e-key').get('error'), 'bad_signature')
