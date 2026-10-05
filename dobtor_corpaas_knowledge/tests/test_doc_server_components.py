# -*- coding: utf-8 -*-
"""說明主機的主機元件：字型與截圖映像只對說明主機是必要；建好映像後知識改用新標籤。"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDocServerComponents(TransactionCase):

    def test_requirements_and_image_switch(self):
        Server = self.env['infrastructure.server']
        if not hasattr(Server, '_host_component_catalog'):
            self.skipTest('PAAS 主機元件尚未安裝')
        partner = self.env['res.partner'].create({'name': 'DS'})
        config = self.env['infrastructure.server_configuration'].create(
            {'name': 'DS', 'distrib_codename': 'ubuntu'})
        srv = Server.create({'name': 'ds-test', 'main_hostname': 'ds.example.com',
                             'user_name': 'odoo', 'server_configuration_id': config.id,
                             'holder_id': partner.id, 'owner_id': partner.id})
        self.assertIn('kb_shooter', Server._host_component_catalog())
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('corpaas_knowledge.doc_server_id', '')
        self.assertNotIn('kb_shooter', srv._host_component_requirements())
        icp.set_param('corpaas_knowledge.doc_server_id', str(srv.id))
        req = srv._host_component_requirements()
        self.assertIn('kb_shooter', req)
        self.assertIn('cjk_fonts', req)
        srv._kb_shooter_installed('corpaas/kb-shooter:1.48.0-abcd1234')
        self.assertEqual(icp.get_param('corpaas_knowledge.playwright_image'),
                         'corpaas/kb-shooter:1.48.0-abcd1234')
