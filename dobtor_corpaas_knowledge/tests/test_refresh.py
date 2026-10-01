# -*- coding: utf-8 -*-
"""整條 knowledge_refresh（盤點 → 指紋 → 事件）的整合測試。

★ 遠端 odoo shell 換成「在測試庫內 exec 同一份腳本」：腳本內容與實機一字不差，
  只是跑在這個測試交易裡。說明庫與拍攝交給出口，這裡不涉及。
"""
import contextlib
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..services import remote, scripts


class _FakeInstance:
    def __init__(self, manifest):
        self.manifest = manifest

    def _corpaas_code_manifest(self):
        return dict(self.manifest)


class _FakeGolden:
    golden_state = 'verified'
    name = 'golden_test'

    def __init__(self, instance):
        self.instance_id = instance

    @contextlib.contextmanager
    def _corpaas_golden_lock(self):
        yield

    def _corpaas_golden_sync_code(self):
        return []


class _FakeMaster(_FakeInstance):
    display_name = 'fake master'

    def __init__(self, manifest):
        super().__init__(manifest)
        self.golden = _FakeGolden(self)

    def _corpaas_golden_db(self, version=None):
        return self.golden


@tagged('post_install', '-at_install')
class TestRefresh(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tmpl = cls.env['product.template'].create({'name': '測試方案', 'type': 'service'})
        cls.pkg = cls.env['infrastructure.solution.package'].create(
            {'product_tmpl_id': tmpl.id, 'knowledge_enabled': True})
        cls.master = _FakeMaster({'base': 'abc'})

    def _exec_shell(self, env, instance, db_name, script):
        readonly = 'env.cr.rollback()' in script
        script = script.replace('env.cr.rollback()', 'pass').replace('env.cr.commit()', 'pass')
        printed = []
        sp = self.env.cr.savepoint()
        try:
            exec(compile(script, '<shell>', 'exec'), {'env': self.env, 'print': printed.append})
        finally:
            # 唯讀腳本在實機結尾 rollback；這裡以 savepoint 回滾模擬
            sp.close(rollback=readonly)
        if readonly:
            self.env.invalidate_all()
        return json.loads(printed[-1][len(scripts.MARK):])

    def _refresh(self):
        Pkg = type(self.pkg)
        with patch.object(remote, 'shell_json', side_effect=self._exec_shell), \
                patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: self.master), \
                patch.object(Pkg, '_provision_module_names', lambda s: ['base']):
            self.pkg.solution_package_knowledge_refresh(full=False, reason='test')
        return self.env['corpaas.knowledge.event'].search(
            [('refresh_token', '=', self.pkg.knowledge_last_token)])

    def test_first_refresh_inventories_and_fingerprints(self):
        events = self._refresh()
        features = self.env['corpaas.knowledge.feature'].search([('package_ids', 'in', self.pkg.id)])
        self.assertTrue(features, '應該盤點出 base 模組的功能點')
        kinds = set(features.mapped('kind'))
        self.assertTrue({'menu', 'action'} & kinds, kinds)
        self.assertTrue(all(f.feature_key.startswith('base.') for f in features))
        self.assertEqual(len(events.filtered(lambda e: e.type == 'feature_added')), len(features))
        fps = self.env['corpaas.knowledge.fingerprint'].search([('package_id', '=', self.pkg.id)])
        self.assertTrue(fps.filtered('scope_hash'), '至少要算出一些指紋')

    def test_second_refresh_is_quiet_then_detects_change(self):
        self._refresh()
        quiet = self._refresh()
        self.assertFalse(quiet.filtered(lambda e: e.type in ('feature_added', 'scope_changed')),
                         '程式碼沒變時第二次更新不應產生事件')
        # 在「使用者」表單加一個欄位到腳本範圍內的元素旁 → 只觸發 form_changed
        feature = self.env['corpaas.knowledge.feature'].search(
            [('package_ids', 'in', self.pkg.id), ('model', '=', 'res.partner'),
             ('kind', '=', 'action')], limit=1)
        self.assertTrue(feature)
        self.env['ir.ui.view'].create({
            'name': 'kb test extra field', 'model': 'res.partner', 'type': 'form',
            'inherit_id': self.env.ref('base.view_partner_form').id,
            'arch': '<xpath expr="//field[@name=\'vat\']" position="after">'
                    '<field name="comment"/></xpath>'})
        changed = self._refresh()
        types = set(changed.filtered(lambda e: e.feature_id == feature).mapped('type'))
        self.assertIn('form_changed', types)
        self.assertNotIn('scope_changed', types, '沒有腳本元素時，範圍指紋只看選單與模式')

    def test_removed_feature_marked_missing(self):
        self._refresh()
        ghost = self.env['corpaas.knowledge.feature'].create({
            'feature_key': 'base.menu:base.ghost', 'module': 'base', 'kind': 'menu',
            'anchor': 'base.ghost', 'name': 'ghost', 'package_ids': [(4, self.pkg.id)]})
        events = self._refresh()
        self.assertTrue(ghost.missing)
        self.assertIn(ghost, events.filtered(lambda e: e.type == 'feature_removed').feature_id)

    def test_help_fingerprint_payload(self):
        self._refresh()
        fp = self.env['corpaas.knowledge.fingerprint'].search(
            [('package_id', '=', self.pkg.id), ('scope_hash', '!=', False)], limit=1)
        payload = fp.feature_id.help_fingerprint(self.pkg)
        self.assertEqual(payload['model'], fp.feature_id.model)
        self.assertIn(fp.scope_hash, payload['scope_hashes'])
        self.assertTrue(payload['views'])
        self.assertIn(payload['lang'], ('zh_TW', 'en_US'))
