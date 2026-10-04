# -*- coding: utf-8 -*-
"""一次性分析容器（優化 3）：指令內容、失敗自動退回母體容器、可關閉。"""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..services import remote


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def sudo(self):
        return self


@tagged('post_install', '-at_install')
class TestIsolatedAnalysis(TransactionCase):

    def _instance(self):
        img = _Obj(pull_name='dobtorsi/docker', odoo_etc_dir='/etc/odoo',
                   odoo_extra_addons_dir='/mnt/extra-addons')
        return _Obj(odoo_image_id=img, odoo_image_tag_id=_Obj(name='18.0'),
                    conf_path='/opt/odoo/env1/Prod/config',
                    sources_path='/opt/odoo/env1/Prod/sources',
                    server_id=_Obj(docker_network_name='CorPAAS'), odoo_container='odoo-x')

    def test_command_is_readonly_one_off_container(self):
        Db = type(self.env['infrastructure.database'])
        with patch.object(Db, '_instance_conf_path', lambda s, i: '/etc/odoo/odoo.conf'), \
                patch.object(Db, '_pg_direct_cli_args', lambda s, instance=None: ' --db_host=1.2.3.4'):
            cmd = remote._isolated_cmd(self.env, self._instance(), 'golden_db', '/tmp/x.py')
        self.assertIn('docker run --rm -i --network CorPAAS', cmd)
        self.assertIn('/opt/odoo/env1/Prod/sources:/mnt/extra-addons:ro', cmd)
        self.assertIn('/opt/odoo/env1/Prod/config:/etc/odoo:ro', cmd)
        self.assertIn('--entrypoint odoo dobtorsi/docker:18.0 shell', cmd)
        self.assertIn('--memory 1g', cmd)
        self.assertTrue(cmd.endswith('-d golden_db --db_host=1.2.3.4'))
        self.assertNotIn('docker exec', cmd, '不進正在服務租戶的母體容器')

    def test_falls_back_to_master_container(self):
        calls = []

        def fake(env, instance, db, script, isolated=False):
            calls.append(isolated)
            return 'boom' if isolated else remote.MARK + json.dumps({'ok': 1})

        with patch.object(remote, 'shell_exec', side_effect=fake):
            res = remote.shell_json(self.env, None, 'db', 'x', isolated=True)
        self.assertEqual(res, {'ok': 1})
        self.assertEqual(calls, [True, False], '一次性容器沒結果就退回母體容器')

    def test_can_be_disabled(self):
        self.env['ir.config_parameter'].sudo().set_param('corpaas_knowledge.isolated_analysis', '0')
        calls = []
        with patch.object(remote, 'shell_exec',
                          side_effect=lambda env, i, d, s, isolated=False:
                          calls.append(isolated) or remote.MARK + '{}'):
            remote.shell_json(self.env, None, 'db', 'x', isolated=True)
        self.assertEqual(calls, [False])


@tagged('post_install', '-at_install')
class TestShotSelftest(TransactionCase):
    """截圖自我檢查（優化 7）：解讀 runner 回報、寫出結果；不改任何資料。"""

    def _sandbox(self):
        inst = self.env['infrastructure.instance'].search([], limit=1)
        if not inst:
            self.skipTest('沒有 infrastructure.instance')
        pkg = self.env['infrastructure.solution.package'].create({
            'product_tmpl_id': self.env['product.template'].create(
                {'name': 'ST 方案', 'type': 'service'}).id})
        sc = self.env['corpaas.knowledge.scenario'].create({'name': 'ST', 'code': 'st_sc'})
        return self.env['corpaas.knowledge.sandbox'].sudo().create({
            'package_id': pkg.id, 'scenario_id': sc.id, 'master_instance_id': inst.id,
            'db_name': 'kbdoc_st', 'state': 'ready', 'role_logins': '{"admin": "doc_admin"}',
            'password': 'x'})

    def test_report_all_checks(self):
        from ..services import shooter
        sb = self._sandbox()
        result = {'cjk_fonts': ['Noto Sans CJK TC'], 'shots': {'selftest': {
            'ok': True, 'images': [
                {'name': 'entry', 'is_probe': True,
                 'probe': {'fields': [{'name': 'name'}], 'buttons': []}},
                {'name': 'selftest_list', 'file': 'selftest/selftest_list.png'}]}}}
        files = {'selftest/selftest_list.png': b'x' * 20000}
        Sb = type(sb)
        with patch.object(Sb, 'resolve_xmlids', lambda s, x: {}), \
                patch.object(shooter, 'run_shots', return_value=(result, files)):
            self.assertTrue(sb.selftest())
        self.assertTrue(sb.selftest_ok)
        self.assertIn('✓ 中文字型', sb.selftest_report)

    def test_missing_fonts_fails(self):
        from ..services import shooter
        sb = self._sandbox()
        result = {'cjk_fonts': [], 'shots': {'selftest': {'ok': True, 'images': [
            {'name': 'selftest_list', 'file': 'f.png'}]}}}
        Sb = type(sb)
        with patch.object(Sb, 'resolve_xmlids', lambda s, x: {}), \
                patch.object(shooter, 'run_shots', return_value=(result, {'f.png': b'x' * 20000})):
            self.assertFalse(sb.selftest())
        self.assertIn('✗ 中文字型', sb.selftest_report)
