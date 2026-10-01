# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHelpMatch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Pkg = cls.env['infrastructure.solution.package']
        cls.pkg = Pkg.search([], limit=1)
        if not cls.pkg:
            # ★ is_package=True 會觸發「需要 Branch 屬性」的驗證；測試只需要一筆方案記錄。
            tmpl = cls.env['product.template'].create({'name': '測試方案', 'type': 'service'})
            cls.pkg = Pkg.create({'product_tmpl_id': tmpl.id})
        F = cls.env['corpaas.knowledge.feature']
        cls.f_quote = F.create({
            'feature_key': 'sale.action:sale.action_quotations', 'module': 'sale',
            'kind': 'action', 'anchor': 'sale.action_quotations', 'name': '報價單',
            'model': 'sale.order', 'action_xmlid': 'sale.action_quotations',
            'menu_path': '銷售/訂單/報價單', 'intents': '開報價\n建立估價單',
            'package_ids': [(4, cls.pkg.id)]})
        cls.f_inv = F.create({
            'feature_key': 'account.action:account.action_move_out_invoice', 'module': 'account',
            'kind': 'action', 'anchor': 'account.action_move_out_invoice', 'name': '客戶發票',
            'model': 'account.move', 'menu_path': '會計/客戶/發票',
            'package_ids': [(4, cls.pkg.id)]})

    def test_fast_path_by_action(self):
        res = self.env['corpaas.knowledge.help']._match(
            self.pkg, action_xmlid='sale.action_quotations')
        self.assertEqual(res[0][0], self.f_quote)
        self.assertEqual(res[0][1], 1.0)

    def test_natural_language(self):
        res = self.env['corpaas.knowledge.help']._match(self.pkg, query='我要怎麼建立估價單')
        self.assertTrue(res)
        self.assertEqual(res[0][0], self.f_quote)

    def test_missing_features_excluded(self):
        # ★ 存在與否以方案為單位：從這個方案拿掉＝這個方案查不到
        self.f_quote.package_ids = [(3, self.pkg.id)]
        res = self.env['corpaas.knowledge.help']._match(
            self.pkg, action_xmlid='sale.action_quotations')
        self.assertFalse([f for f, s in res if f == self.f_quote])

    def test_help_log_missed(self):
        log = self.env['corpaas.knowledge.help.log'].create(
            {'package_id': self.pkg.id, 'query': 'xyz', 'hits': 0})
        self.assertTrue(log.missed)


@tagged('post_install', '-at_install')
class TestHelpTrim(TransactionCase):

    def test_trim_keeps_one_upsell_slot(self):
        from ..controllers.help_api import KnowledgeHelpApi
        m = [{'kind': 'manual', 'i': i} for i in range(6)]
        u = [{'kind': 'upsell', 'i': 9}]
        out = KnowledgeHelpApi._trim(m + u, 5)
        self.assertEqual(len(out), 5)
        self.assertEqual(out[-1]['kind'], 'upsell')
        self.assertEqual(len(KnowledgeHelpApi._trim(m, 5)), 5)
        self.assertEqual(len(KnowledgeHelpApi._trim(u * 3, 2)), 2)
