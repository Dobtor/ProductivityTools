# -*- coding: utf-8 -*-
"""客戶專屬疊加（方案 B）：指令組裝防注入、準備流程、說明庫的指令都走掛了疊加的容器。"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..services import overlay as ov
from .test_usage_flow import make_database

OV = 'odoo.addons.dobtor_corpaas_knowledge.services.overlay'


@tagged('post_install', '-at_install')
class TestOverlayService(TransactionCase):

    def test_slug_and_injection_guards(self):
        self.assertEqual(ov.repo_slug('https://github.com/Dobtor/Sales.git'), 'dobtor-sales')
        for bad in ('git@github.com:x/y.git', 'https://evil.com/x/y', 'https://github.com/x/y;rm -rf /'):
            with self.assertRaises(ov.OverlayError):
                ov.repo_slug(bad)
        ov.check_ref('v18.0.1.2')
        for bad in ('-x', 'v1;rm', 'a..b', ''):
            with self.assertRaises(ov.OverlayError):
                ov.check_ref(bad)

    def test_docker_args_append_after_base_path(self):
        mount, addons = ov.docker_args('/opt/odoo/kb_overlay/3', ['dobtor-sales'], '/usr/lib/odoo/addons,/mnt/extra-addons')
        self.assertEqual(mount, '-v /opt/odoo/kb_overlay/3:/mnt/kb-overlay:ro')
        self.assertIn('/mnt/extra-addons,/mnt/kb-overlay/dobtor-sales', addons, '疊加接在母體路徑後面')
        with self.assertRaises(ov.OverlayError):
            ov.docker_args('/x', ['../etc'], '/a')


@tagged('post_install', '-at_install')
class TestOverlayModel(TransactionCase):

    def setUp(self):
        super().setUp()
        self.db = make_database(self.env, 9481)
        self.server = self.db.instance_id.server_id
        self.Ov = self.env['corpaas.knowledge.overlay']
        self.mods = [{'module': 'x_cust', 'repo_url': 'https://github.com/Dobtor/Cust', 'ref': 'v1', 'origin': 'dev'},
                     {'module': 'x_cust2', 'repo_url': 'https://github.com/Dobtor/Cust', 'ref': 'v1', 'origin': 'dev'}]

    def test_ensure_resets_on_change_and_prepare_fetches_once_per_repo(self):
        partner = self.env['res.partner'].create({'name': '客戶甲'})
        o = self.Ov._ensure_for(partner, self.server, self.mods)
        self.assertEqual((o.state, len(o.line_ids)), ('draft', 2))
        with patch(OV + '.fetch', return_value='a' * 40) as fetch, patch(OV + '.has_module', return_value=True):
            o.action_prepare()
        self.assertEqual(fetch.call_count, 1, '同一個 repo＋標籤只抓一次')
        self.assertEqual((o.state, o.repo_dirs()), ('ready', ['dobtor-cust']))
        self.assertEqual(self.Ov._ensure_for(partner, self.server, self.mods), o)
        self.assertEqual(o.state, 'ready', '內容沒變維持就緒')
        o2 = self.Ov._ensure_for(partner, self.server, self.mods[:1])
        self.assertEqual((o2, o2.state), (o, 'draft'), '模組變了回到待準備')

    def test_prepare_records_missing_module(self):
        o = self.Ov._ensure_for(None, self.server, self.mods[:1])
        with patch(OV + '.fetch', return_value='b' * 40), patch(OV + '.has_module', return_value=False):
            o.action_prepare()
        self.assertEqual(o.state, 'error')
        self.assertIn('x_cust', o.error)
        with self.assertRaises(UserError):
            o.docker_args(self.db.instance_id)


@tagged('post_install', '-at_install')
class TestSandboxOverlay(TransactionCase):

    def test_sandbox_shell_uses_overlay_container(self):
        db = make_database(self.env, 9482)
        tmpl = self.env['product.template'].create({'name': '疊加方案', 'type': 'service'})
        pkg = self.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        sc = self.env['corpaas.knowledge.scenario'].create({'name': '客戶情境', 'code': 'kbov_sc'})
        o = self.env['corpaas.knowledge.overlay']._ensure_for(
            None, db.instance_id.server_id,
            [{'module': 'x_cust', 'repo_url': 'https://github.com/Dobtor/Cust', 'ref': 'v1'}])
        o.line_ids.write({'repo_dir': 'dobtor-cust'})
        o.state = 'ready'
        sb = self.env['corpaas.knowledge.sandbox'].create({
            'package_id': pkg.id, 'scenario_id': sc.id, 'master_instance_id': db.instance_id.id,
            'db_name': 'docsbx-p%s-s%s' % (pkg.id, sc.id), 'overlay_id': o.id})
        with patch(OV + '.base_addons_path', return_value='/mnt/extra-addons'), \
                patch('odoo.addons.dobtor_corpaas_knowledge.services.remote.shell_json',
                      return_value={'installed': ['x_cust'], 'missing': []}) as sj:
            sb._install_overlay()
        overlay = sj.call_args.kwargs['overlay']
        self.assertIn('/mnt/kb-overlay', overlay[0])
        self.assertIn('/mnt/extra-addons,/mnt/kb-overlay/dobtor-cust', overlay[1])
        self.assertIn('x_cust', sb.overlay_report)
        with patch(OV + '.base_addons_path', return_value='/mnt/extra-addons'), \
                patch('odoo.addons.dobtor_corpaas_knowledge.services.remote.shell_json',
                      return_value={'installed': [], 'missing': ['x_cust']}):
            with self.assertRaises(UserError):
                sb._install_overlay()
