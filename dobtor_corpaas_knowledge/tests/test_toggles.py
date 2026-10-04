# -*- coding: utf-8 -*-
"""設定開關與功能分類：基礎／進階 × 標準／專用 ＋ 方案核心。"""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..services import scripts
from . import test_refresh as base


@tagged('post_install', '-at_install')
class TestClassifyRules(TransactionCase):
    """判定規則（不碰黃金庫，直接餵開關與相依圖）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pkg = cls.env['infrastructure.solution.package'].create({
            'product_tmpl_id': cls.env['product.template'].create(
                {'name': 'TG 方案', 'type': 'service'}).id})
        cls.T = cls.env['corpaas.knowledge.toggle']
        cls.F = cls.env['corpaas.knowledge.feature']

    def _f(self, module, anchor, origin='custom', kind='action', model='x.m', **kw):
        return self.F.create(dict({
            'feature_key': self.F.make_key(module, kind, anchor), 'module': module,
            'kind': kind, 'anchor': anchor, 'name': anchor, 'model': model,
            'module_origin': origin, 'package_ids': [(4, self.pkg.id)]}, **kw))

    def _t(self, name, kind, target='', **kw):
        return self.T.create(dict({'name': name, 'kind': kind, 'target': target,
                                   'package_ids': [(4, self.pkg.id)]}, **kw))

    def _classify(self, feats, toggles, graph, bom, official=()):
        self.pkg._knowledge_classify(feats, toggles, graph, bom, set(official), 'tok')
        return {f: f.class_for(self.pkg) for f in feats}

    def setUp(self):
        super().setUp()
        p = patch.object(type(self.pkg), '_provision_module_names',
                         lambda s: ['x_adv', 'x_bom'])
        p.start()
        self.addCleanup(p.stop)

    def test_module_toggle_is_advanced_even_when_in_bom(self):
        f_adv = self._f('x_adv', 'a')
        f_base = self._f('x_bom', 'b')
        t = self._t('module_x_adv', 'module', 'x_adv', downstream='x_other')
        res = self._classify(f_adv | f_base, t, {'x_adv': [], 'x_bom': []},
                             bom=['x_adv', 'x_bom'])
        self.assertEqual((res[f_adv].tier, res[f_adv].basis), ('advanced', 'module'))
        self.assertTrue(res[f_adv].core, 'BOM 直接列的＝方案核心（與進階並存）')
        self.assertEqual(res[f_adv].classification, 'own_adv')
        self.assertEqual(res[f_base].classification, 'own_base')
        self.assertFalse(t.locks_bom(self.pkg))

    def test_toggle_that_would_remove_bom_modules_is_base(self):
        """做法 2：關掉會連帶移除 BOM 模組（例：account → sale…）＝關不掉，算基礎。"""
        f_acc = self._f('account', 'acc', origin='odoo')
        f_dep = self._f('x_accdep', 'd', origin='odoo')
        t = self._t('module_account', 'module', 'account', downstream='x_bom,x_other')
        res = self._classify(f_acc | f_dep, t, {'account': ['x_accdep'], 'x_accdep': [],
                                                'x_bom': ['account']},
                             bom=['x_bom'], official=['account', 'x_accdep'])
        self.assertEqual((res[f_acc].tier, res[f_acc].classification), ('base', 'std_base'))
        self.assertEqual(res[f_dep].tier, 'base', '開關不算數時，它的相依也不跟著變進階')
        self.assertTrue(t.locks_bom(self.pkg))
        self.assertEqual(t.downstream_bom(self.pkg), ['x_bom'])

    def test_exclusive_dependency_follows_toggle(self):
        f_dep = self._f('x_dep', 'd', origin='odoo')
        f_shared = self._f('x_shared', 's', origin='odoo')
        t = self._t('module_x_adv', 'module', 'x_adv')
        graph = {'x_adv': ['x_dep', 'x_shared'], 'x_dep': [], 'x_shared': [],
                 'x_bom': ['x_shared']}
        res = self._classify(f_dep | f_shared, t, graph, bom=['x_bom'], official=['x_dep'])
        self.assertEqual((res[f_dep].basis, res[f_dep].classification),
                         ('module_dep', 'std_adv'), '只因開關才裝的相依＝進階')
        self.assertEqual(res[f_shared].tier, 'base', 'BOM 其他模組也需要的相依＝基礎')

    def test_group_toggle_gates_screen_or_elements(self):
        g = 'x.group_adv'
        t = self._t('group_adv', 'group', g, path='設定 › 銷售 › 進階',
                    elements_json=json.dumps([{'model': 'x.m', 'view': 'x.v',
                                               'element': 'field:discount', 'module': 'sale'}]))
        gated = self._f('x_bom', 'gated', group_xmlids=g)
        mixed = self._f('x_bom', 'mixed', group_xmlids=g + ',base.group_user')
        res = self._classify(gated | mixed, t, {}, bom=['x_bom'], official=['sale'])
        self.assertEqual((res[gated].tier, res[gated].basis), ('advanced', 'group'))
        self.assertEqual(res[mixed].tier, 'base', '一般使用者本來就看得到＝基礎')
        els = res[mixed].elements()
        self.assertEqual(els[0]['element'], 'field:discount')
        self.assertEqual(els[0]['origin'], 'odoo', '元素來源看加入它的模組：sale＝標準')

    def test_param_toggle_setting_and_behavior(self):
        t = self._t('x_quote_days', 'param', 'x.quote_days', value='30',
                    affected_models='x.m')
        setting = self._f('x_bom', 'x_quote_days', kind='setting', model='res.config.settings')
        screen = self._f('x_bom', 'screen')
        res = self._classify(setting | screen, t, {}, bom=['x_bom'])
        self.assertEqual((res[setting].tier, res[setting].basis), ('advanced', 'param'))
        self.assertEqual(res[screen].tier, 'base', '受參數影響的畫面層級不變')
        self.assertIn(t, res[screen].behavior_toggle_ids)

    def test_class_change_emits_event(self):
        f = self._f('x_adv', 'c')
        t = self._t('module_x_adv', 'module', 'x_adv')
        self._classify(f, t, {'x_adv': []}, bom=[])
        self._classify(f, self.T, {'x_adv': []}, bom=[])
        ev = self.env['corpaas.knowledge.event'].search(
            [('package_id', '=', self.pkg.id), ('type', '=', 'class_changed')])
        self.assertEqual(json.loads(ev.payload)[0]['new'], 'own_base')

    def test_unchecked_group_screens_excluded(self):
        items = [
            {'kind': 'action', 'anchor': 'a', 'groups': ['x.off']},
            {'kind': 'action', 'anchor': 'b', 'groups': [],
             'entries': [{'groups': ['x.off']}, {'groups': ['x.off']}]},
            {'kind': 'action', 'anchor': 'c', 'groups': [],
             'entries': [{'groups': ['x.off']}, {'groups': []}]},
            {'kind': 'action', 'anchor': 'd', 'groups': ['x.off', 'base.group_user']},
        ]
        out = self.pkg._knowledge_filter_off_groups(items, {'x.off'})
        self.assertEqual([i['anchor'] for i in out], ['c', 'd'], '沒勾的設定不屬於方案範圍')
        self.assertEqual(len(out[0]['entries']), 1)

    def test_toggle_change_forces_full_fingerprint(self):
        self.pkg.write({'knowledge_fp_manifest': json.dumps({'t:group_adv': 'on', 'x': '1'}),
                        'knowledge_fp_image': False})
        self.assertEqual(self.pkg._knowledge_fp_changed({'t:group_adv': 'on', 'x': '1'}), set())
        self.assertIsNone(self.pkg._knowledge_fp_changed({'x': '1'}))

    def test_outlet_payloads(self):
        t = self._t('module_x_adv', 'module', 'x_adv', path='設定 › 銷售 › X',
                    downstream='x_other')
        f = self._f('x_adv', 'p')
        self._classify(f, t, {'x_adv': []}, bom=['x_adv', 'x_bom'])
        p = f.class_for(self.pkg).as_payload()
        self.assertEqual(p['classification_label'], '專用進階')
        self.assertEqual(p['toggle_paths'], ['設定 › 銷售 › X'])
        self.assertEqual(p['downstream_bom'], [])
        try:
            from odoo.addons.dobtor_corpaas_knowledge_manual.services import prompts
        except ImportError:
            return
        note = prompts._class_note({'class': p})
        self.assertIn('【專用進階】', note)
        self.assertIn('設定 › 銷售 › X', note)
        self.assertIn('請勿關閉', note)


@tagged('post_install', '-at_install')
class TestToggleInventory(base._RefreshBase):
    """在測試庫跑真的 toggle_script（內容與實機相同）。"""

    def _run(self):
        Pkg = type(self.pkg)
        installed = set(self.env['ir.module.module'].search(
            [('state', '=', 'installed')]).mapped('name'))
        with patch.object(Pkg, '_knowledge_golden_installed',
                          lambda s, g, official_only=False: installed), \
                patch.object(Pkg, '_provision_module_names', lambda s: ['base']):
            with patch.object(base.remote, 'shell_json', side_effect=self._exec_shell), \
                    patch.object(Pkg, '_knowledge_master',
                                 lambda s, raise_if_missing=True: self.master):
                self.pkg.solution_package_knowledge_refresh(full=False, reason='test')

    def test_script_reports_only_enabled_toggles(self):
        installed = self.env['ir.module.module'].search([('state', '=', 'installed')])
        res = self._exec_shell(self.env, None, 'x',
                               scripts.toggle_script(installed.mapped('name')))
        for t in res['toggles']:
            if t['kind'] == 'module':
                self.assertIn(t['target'], installed.mapped('name'), '只收已安裝的模組開關')
            self.assertTrue(t['path'], t['name'])
        self.assertIsInstance(res['off_groups'], list)
        self.assertIn('base', res['graph'])

    def test_refresh_classifies_every_feature(self):
        self._run()
        feats = self.env['corpaas.knowledge.feature'].search([('package_ids', 'in', self.pkg.id)])
        classes = self.env['corpaas.knowledge.feature.class'].search(
            [('package_id', '=', self.pkg.id)])
        self.assertEqual(set(classes.mapped('feature_id').ids), set(feats.ids))
        settings = feats.filtered(lambda f: f.kind == 'setting')
        toggles = self.env['corpaas.knowledge.toggle'].search([('package_ids', 'in', self.pkg.id)])
        self.assertEqual(set(settings.mapped('anchor')),
                         set(toggles.filtered(lambda t: t.kind == 'param').mapped('name')),
                         '只有已設定的參數型開關成為功能點')
        self.assertTrue(all(c.tier == 'advanced'
                            for c in classes.filtered(lambda c: c.feature_id.kind == 'setting')))
