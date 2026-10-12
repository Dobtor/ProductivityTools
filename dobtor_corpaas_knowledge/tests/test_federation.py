# -*- coding: utf-8 -*-
"""知識主從的基礎：主控台代碼、全域識別、來源標記、鏡像「內容唯讀、關聯可寫」、方案全域識別。"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.federation import EXCHANGE_SYNC, console_code


@tagged('post_install', '-at_install')
class TestFederation(TransactionCase):

    def setUp(self):
        super().setUp()
        self.icp = self.env['ir.config_parameter'].sudo()
        tmpl = self.env['product.template'].create({'name': '主從測試方案', 'type': 'service'})
        self.pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        self.Cap = self.env['corpaas.knowledge.capability']

    def test_console_code(self):
        self.icp.set_param('corpaas_knowledge.console_code', '')
        self.icp.set_param('web.base.url', 'https://admin.dobtor.com')
        self.assertEqual(console_code(self.env), 'dobtor', '沒設依網域推：admin.dobtor.com → dobtor')
        self.icp.set_param('corpaas_knowledge.console_code', 'corpaas')
        self.assertEqual(console_code(self.env), 'corpaas')

    def test_uid_origin_and_hash(self):
        self.icp.set_param('corpaas_knowledge.console_code', 'corpaas')
        a = self.Cap.create({'name': '報價與接單', 'pain': '漏單'})
        b = self.Cap.create({'name': '出貨'})
        self.assertTrue(a.kb_uid and b.kb_uid and a.kb_uid != b.kb_uid)
        self.assertEqual(a.kb_origin, 'corpaas')
        self.assertEqual(a.kb_sync_state, 'local')
        self.assertEqual(a.kb_visibility, 'public', '範本類預設公開')
        before = a.kb_content_hash
        self.assertTrue(before)
        a.pain = '漏單、重複出貨'
        self.assertNotEqual(a.kb_content_hash, before, '內容改了雜湊跟著變')
        h = a.kb_content_hash
        a.package_ids = [(4, self.pkg.id)]
        self.assertEqual(a.kb_content_hash, h, '關聯不算內容')

    def test_mirror_content_readonly_relations_writable(self):
        cap = self.Cap.create({'name': '線上報名'})
        cap.with_context(knowledge_exchange_sync=EXCHANGE_SYNC).write({'kb_sync_state': 'mirror'})
        with self.assertRaises(UserError):
            cap.name = '亂改'
        cap.package_ids = [(4, self.pkg.id)]
        self.assertIn(self.pkg, cap.package_ids, '鏡像的關聯照常可寫（從屬的計畫要把方案掛上去）')
        cap.with_context(knowledge_exchange_sync=EXCHANGE_SYNC).write({'name': '線上報名（主體更新）'})
        self.assertEqual(cap.name, '線上報名（主體更新）', '交換同步可以改內容')

    def test_rpc_context_cannot_forge_sync(self):
        cap = self.Cap.create({'name': '收款'})
        cap.with_context(knowledge_exchange_sync=EXCHANGE_SYNC).write({'kb_sync_state': 'mirror'})
        with self.assertRaises(UserError):
            cap.with_context(knowledge_exchange_sync=True).write({'name': 'RPC 偽造'})

    def test_code_knowledge_private_by_default(self):
        d = self.env['corpaas.knowledge.code_def'].create(
            {'def_hash': 'abc123', 'method': 'action_confirm', 'module': 'sale'})
        self.assertEqual(d.kb_visibility, 'private', '程式知識預設私有，公開判定通過才公開')

    def test_package_global_key(self):
        self.icp.set_param('corpaas_knowledge.console_code', 'dobtor')
        tmpl = self.env['product.template'].create({'name': '從屬方案', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        self.assertEqual(pkg.knowledge_global_key, 'dobtor:pkg%s' % pkg.id)
        self.assertEqual(pkg.knowledge_match_key(), pkg.knowledge_global_key)
        pkg.knowledge_upstream_key = 'corpaas:pkg14'
        self.assertEqual(pkg.knowledge_match_key(), 'corpaas:pkg14', '從屬對應主體方案')
