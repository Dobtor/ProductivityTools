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

    def test_library_restore_matches_uid_and_leaves_mirror_content(self):
        """#4：範本庫存回先以 kb_uid 對應（不靠代碼或名稱）；對到主體鏡像只掛關聯，不改內容。"""
        mirror = self.Cap.create({'name': '主體能力', 'code': 'cap_master'})
        mirror.with_context(knowledge_exchange_sync=EXCHANGE_SYNC).write({'kb_sync_state': 'mirror'})
        data = {'caps': [{'code': 'cap_other_code', 'uid': mirror.kb_uid, 'sequence': 5,
                          'values': {'name': '別的名稱'}, 'feature_keys': []}]}
        self.assertEqual(self.pkg._knowledge_restore_capabilities(data), 1)
        self.assertEqual(mirror.name, '主體能力', '鏡像內容不動')
        self.assertIn(self.pkg, mirror.package_ids, '關聯照常掛上')
        self.assertFalse(self.Cap.search([('code', '=', 'cap_other_code')]), '沒有因代碼不同多建一筆')

    def test_channel_per_host_switch(self):
        """#9：預設排同一列；打開後依母體主機分通道，上限沿用 knowledge 的設定。"""
        from unittest.mock import patch
        self.assertEqual(self.pkg._knowledge_channel(), 'knowledge')
        self.icp.set_param('corpaas_knowledge.channel_per_host', 'True')
        from .test_usage_flow import make_database
        inst = make_database(self.env, 9471).instance_id
        server = inst.server_id
        self.assertTrue(server)
        with patch.object(type(self.pkg), '_knowledge_master', lambda s, raise_if_missing=True: inst):
            self.assertEqual(self.pkg._knowledge_channel(), 'knowledge_s%s' % server.id)
        self.assertEqual(self.icp.get_param('corpaas.queue_channel_cap_knowledge_s%s' % server.id),
                         self.icp.get_param('corpaas.queue_channel_cap_knowledge') or '1')

    def test_sandbox_gc_drops_idle_only(self):
        """#5：閒置超過存活期限的說明庫刪掉；方案還有知識工作排隊的不動。"""
        from unittest.mock import patch
        Sb = self.env['corpaas.knowledge.sandbox'].sudo()
        dropped = []
        with patch.object(type(Sb), 'drop', lambda s: dropped.extend(s.ids)), \
                patch.object(type(Sb), 'search', lambda s, *a, **k: Sb.browse()):
            self.assertEqual(Sb._cron_knowledge_sandbox_gc(), 0)
        self.icp.set_param('corpaas_knowledge.sandbox_ttl_days', '0')
        self.assertEqual(Sb._cron_knowledge_sandbox_gc(), 0, '0＝不清')

    def test_public_base_url_seed_only_on_master(self):
        Pkg = self.env['infrastructure.solution.package']
        self.icp.set_param('corpaas_knowledge.public_base_url', '')
        self.icp.set_param('corpaas_knowledge.console_code', 'dobtor')
        Pkg._knowledge_seed_public_base_url()
        self.assertFalse(self.icp.get_param('corpaas_knowledge.public_base_url'), '從屬不種主體網域')
        self.icp.set_param('corpaas_knowledge.console_code', 'corpaas')
        Pkg._knowledge_seed_public_base_url()
        self.assertEqual(self.icp.get_param('corpaas_knowledge.public_base_url'), 'https://www.corpaas.com')
