# -*- coding: utf-8 -*-
"""第五期：專案客戶知識——以客戶測試實例為基準；絕不寫入客戶測試庫；說明庫用臨時 Odoo 拍。"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .test_usage_flow import make_database


@tagged('post_install', '-at_install')
class TestProjectKnowledge(TransactionCase):

    def setUp(self):
        super().setUp()
        self.db = make_database(self.env, 9501)
        self.inst = self.db.instance_id
        self.env.cr.execute("UPDATE infrastructure_instance SET state='active' WHERE id=%s", (self.inst.id,))
        self.env.cr.execute("UPDATE infrastructure_database SET state='active' WHERE id=%s", (self.db.id,))
        self.inst.invalidate_recordset(); self.db.invalidate_recordset()
        self.partner = self.env['res.partner'].create({'name': '駿伸測試客戶', 'is_company': True})
        self.W = self.env['corpaas.knowledge.project.wizard']

    def _create(self):
        w = self.W.with_context(default_instance_id=self.inst.id).create({
            'database_id': self.db.id, 'partner_id': self.partner.id,
            'consent': True, 'consent_note': '合約第 9 條'})
        with patch.object(type(self.env['infrastructure.solution.package']), 'knowledge_enqueue_refresh',
                          lambda s, full=False, reason='': None):
            w.action_confirm()
        return self.env['infrastructure.solution.package'].search(
            [('knowledge_kind', '=', 'project'), ('knowledge_project_instance_id', '=', self.inst.id)])

    def test_wizard_requires_consent_and_stamps_it(self):
        w = self.W.with_context(default_instance_id=self.inst.id).create(
            {'database_id': self.db.id, 'partner_id': self.partner.id})
        with self.assertRaises(UserError):
            w.action_confirm()
        pkg = self._create()
        self.assertEqual(len(pkg), 1)
        self.assertTrue(pkg.knowledge_enabled)
        self.assertEqual(pkg.knowledge_project_consent_user_id, self.env.user, '勾選人由系統寫')
        self.assertTrue(pkg.knowledge_project_consent_at)
        self.assertFalse(pkg.product_tmpl_id.sale_ok, '不賣')
        if 'ai_source_mount' in self.inst._fields:
            self.assertTrue(self.inst.ai_source_mount, '開 AI 讀原始碼')
        with self.assertRaises(UserError):
            self._create()   # 同一座只能建一次

    def test_base_is_test_instance_and_never_written(self):
        pkg = self._create()
        self.assertEqual(pkg._knowledge_master(), self.inst, '基準實例＝測試實例（不要求說明主機、上架版本）')
        self.assertEqual(self.inst._knowledge_base_db(), self.db)
        self.assertTrue(self.db._knowledge_base_ok())
        self.assertTrue(self.db._knowledge_needs_purge(), '客戶資料：說明庫一律清除')
        Db = type(self.db)
        with patch.object(Db, '_corpaas_golden_sync_code', side_effect=AssertionError('不可寫入客戶測試庫')):
            self.db._knowledge_base_sync_code()

    def test_scope_is_whole_customer_system(self):
        pkg = self._create()
        DM = self.env['infrastructure.database_module'].sudo()
        for name, kind, state in (('x_trade_import', 'custom', 'installed'), ('sale', 'odoo', 'installed'),
                                  ('x_removed', 'custom', 'uninstalled')):
            DM.create({'database_id': self.db.id, 'module_name': name, 'module_type': kind, 'state': state})
        custom, official, installed_official = pkg._knowledge_scope_modules(self.db)
        self.assertIn('x_trade_import', custom, '客戶已安裝的自訂模組全部納入')
        self.assertNotIn('x_removed', custom)
        self.assertIn('sale', installed_official)

    def test_sandbox_uses_serve_and_t1_warns_without_ai_access(self):
        pkg = self._create()
        sc = self.env['corpaas.knowledge.scenario'].create({'name': '專案情境', 'code': 'kbproj_sc'})
        sb = self.env['corpaas.knowledge.sandbox'].create({
            'package_id': pkg.id, 'scenario_id': sc.id, 'master_instance_id': self.inst.id,
            'db_name': 'docsbx-p%s-s%s' % (pkg.id, sc.id)})
        self.assertTrue(sb._knowledge_needs_serve(), '測試站有 dbfilter：拍照改用只服務說明庫的臨時 Odoo')
        if 'ai_source_mount' not in self.inst._fields:
            return
        self.inst.ai_source_mount = False
        plan = self.env['corpaas.knowledge.plan'].create({'package_id': pkg.id})
        c10 = [r for r in plan._checks_t1() if r['code'] == 'C10']
        self.assertEqual(c10[0]['state'], 'warn')
        self.assertIn('允許 AI 讀原始碼', c10[0]['reason'])

    def test_regular_package_unchanged(self):
        tmpl = self.env['product.template'].create({'name': '一般方案', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        self.assertEqual(pkg.knowledge_kind, 'package')
        self.assertFalse(pkg._knowledge_master(raise_if_missing=False), '一般方案仍要說明主機上的母體')

    def test_help_maps_customer_db_to_project(self):
        pkg = self._create()
        prod = make_database(self.env, 9502)
        dup = self.env['res.partner'].create({'name': '駿伸測試客戶', 'is_company': True})
        self.env.cr.execute('UPDATE infrastructure_database SET partner_id=%s WHERE id=%s', (dup.id, prod.id))
        prod.invalidate_recordset()
        self.assertEqual(self.env['corpaas.knowledge.help']._package_for_database(prod.name), pkg,
                         '客戶正式機的「此畫面說明」對到專案知識（同名的重複聯絡人也算）')
