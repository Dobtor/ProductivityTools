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
    id = 0

    def with_context(self, *args, **kwargs):
        return self

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


class _RefreshBase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tmpl = cls.env['product.template'].create({'name': '測試方案', 'type': 'service'})
        cls.pkg = cls.env['infrastructure.solution.package'].create(
            {'product_tmpl_id': tmpl.id, 'knowledge_enabled': True})
        cls.master = _FakeMaster({'base': 'abc'})

    def _exec_shell(self, env, instance, db_name, script, **kw):
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


@tagged('post_install', '-at_install')
class TestRefresh(_RefreshBase):

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
        # 增量重算只看「變動模組」：實機上畫面改變一定伴隨模組改版，這裡模擬 base 改版。
        self.master.manifest['base'] = 'abc2'
        self.addCleanup(self.master.manifest.__setitem__, 'base', 'abc')
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


@tagged('post_install', '-at_install')
class TestOfficialScope(_RefreshBase):
    """Odoo 官方模組納入盤點範圍：只盤選單與選單動作、排除清單、範圍變動與消失判定。"""

    INSTALLED_OFFICIAL = {'base', 'mail', 'web'}

    def _refresh(self, official_installed=None):
        Pkg = type(self.pkg)
        installed = self.INSTALLED_OFFICIAL if official_installed is None \
            else official_installed
        with patch.object(Pkg, '_knowledge_golden_installed',
                          lambda s, g, official_only=False: set(installed)):
            return super()._refresh()

    def _features(self, module=None):
        domain = [('package_ids', 'in', self.pkg.id)]
        if module:
            domain.append(('module', '=', module))
        return self.env['corpaas.knowledge.feature'].search(domain)

    def test_scope_excludes_and_dedupes_bom(self):
        Pkg = type(self.pkg)
        with patch.object(Pkg, '_knowledge_golden_installed',
                          lambda s, g, official_only=False:
                          {'base', 'web', 'mail', 'sale_x', 'l10n_tw', 'auth_totp'}), \
                patch.object(Pkg, '_provision_module_names', lambda s: ['base']):
            bom, official, _all = self.pkg._knowledge_scope_modules(self.master.golden)
            self.assertEqual(bom, ['base'])
            self.assertEqual(official, ['mail', 'sale_x'],
                             'BOM 裡的不重複列；web、l10n_*、auth_* 預設排除')
            self.pkg.knowledge_official_exclude = 'sale_*'
            self.assertEqual(self.pkg._knowledge_scope_modules(self.master.golden)[1],
                             ['mail'], '方案追加的排除清單')
            self.pkg.knowledge_include_official = False
            self.assertEqual(self.pkg._knowledge_scope_modules(self.master.golden)[1], [])

    def test_official_module_only_menus_and_menu_actions(self):
        self._refresh()
        mail = self._features('mail')
        self.assertTrue(mail, '範圍內的官方模組（mail）要盤到選單')
        self.assertEqual(set(mail.mapped('kind')) - {'action', 'client', 'setting'}, set(),
                         '官方模組只盤畫面（加上已設定的參數型開關），不盤報表、按鈕、精靈')
        self.assertEqual(set(mail.mapped('module_origin')), {'odoo'})
        for f in mail.filtered(lambda f: f.kind != 'setting'):
            self.assertIn('menu', f.entry_ids.mapped('kind'),
                          '官方畫面只收有選單入口的：%s' % f.feature_key)
        tech = self.env.ref('mail.mail_alias_menu', raise_if_not_found=False)
        if tech:
            anchors = self._features().mapped('entry_ids.anchor')
            self.assertNotIn('mail.mail_alias_menu', anchors,
                             '技術選單（路徑上只開給技術群組）不盤')

    def test_screen_is_one_feature_with_menu_entries(self):
        """選單是入口、畫面才是功能點：不再有 kind=menu 的功能點，選單路徑記在入口上。"""
        self._refresh()
        feats = self._features()
        self.assertFalse(feats.filtered(lambda f: f.kind == 'menu'))
        users = feats.filtered(lambda f: f.anchor == 'base.action_res_users')
        self.assertEqual(len(users), 1)
        self.assertTrue(users.entry_ids.filtered(lambda e: e.kind == 'menu'))
        self.assertEqual(users.menu_path, users.entry_ids.filtered(
            lambda e: e.kind == 'menu').sorted(lambda e: len(e.path or ''))[:1].path)

    def test_entry_groups_hide_feature_from_help(self):
        self._refresh()
        users = self._features().filtered(lambda f: f.anchor == 'base.action_res_users')
        users.entry_ids.write({'group_xmlids': 'base.group_system'})
        self.assertFalse(users.visible_to(['base.group_user']))
        self.assertTrue(users.visible_to(['base.group_user', 'base.group_system']))

    def _fp_keys(self):
        """跑一次更新，回傳送進指紋腳本的功能點鍵。"""
        sent = []
        real = scripts.fingerprint_script

        def spy(items, roles, lang='zh_TW'):
            sent.extend(i['key'] for i in items)
            return real(items, roles, lang)

        with patch.object(scripts, 'fingerprint_script', side_effect=spy):
            self._refresh()
        return set(sent)

    def test_incremental_fingerprint_only_changed_modules(self):
        first = self._fp_keys()
        self.assertTrue(first, '第一次沒有基準：全算')
        self.assertEqual(self._fp_keys(), set(), '沒有模組變動：一個都不重算')
        # 挑一個確實出現在某些畫面繼承鏈、但不是全部畫面都有的模組來「改版」
        feats = self._features().filtered(lambda f: f.attr_for(self.pkg, 'view_modules'))
        mods_of = {f: f.attr_for(self.pkg, 'view_modules').split(',') for f in feats}
        counts = {}
        for f in feats:
            for m in mods_of[f]:
                counts[m] = counts.get(m, 0) + 1
        mod = next(m for m, c in sorted(counts.items(), key=lambda x: -x[1])
                   if c < len(feats))
        self.master.manifest[mod] = 'changed'
        self.addCleanup(self.master.manifest.pop, mod, None)
        third = self._fp_keys()
        expected = set(f.feature_key for f in feats if mod in mods_of[f])
        self.assertEqual(third, expected, '%s 改版：只重算繼承鏈含它的畫面' % mod)

    def test_image_change_forces_full_fingerprint(self):
        self._refresh()
        state = json.loads(self.pkg.knowledge_fp_manifest)
        self.assertEqual(self.pkg._knowledge_fp_changed(state), set())
        self.pkg.knowledge_image_digest = 'sha256:new'
        self.assertIsNone(self.pkg._knowledge_fp_changed(state), '映像換了：全算')

    def test_menu_path_change_marks_dirty(self):
        self._refresh()
        users = self._features().filtered(lambda f: f.anchor == 'base.action_res_users')
        users.menu_path = 'old/path'
        self.assertIn(users.feature_key, self._fp_keys(),
                      '入口路徑變了（指紋範圍看路徑）：增量也要重算')
    def test_list_and_kanban_buttons_are_inventoried(self):
        self._refresh()
        btn = self._features('base').filtered(
            lambda f: f.kind == 'button' and f.view_mode in ('list', 'kanban'))
        if not btn:
            # base 的清單／看板視圖沒有 type=object 按鈕時，至少 type=action 按鈕要成為入口
            entries = self._features().mapped('entry_ids').filtered(
                lambda e: e.kind in ('button', 'smart_button'))
            self.assertTrue(entries, '清單／看板／表單裡的 type=action 按鈕要成為畫面入口')
        else:
            self.assertEqual(btn[0].views_for_fingerprint()[0][1], btn[0].view_mode)

    def test_website_menus_become_routes(self):
        if 'website.menu' not in self.env:
            self.skipTest('沒有安裝 website')
        Pkg = type(self.pkg)
        with patch.object(Pkg, '_provision_module_names', lambda s: ['base', 'website']):
            with patch.object(remote, 'shell_json', side_effect=self._exec_shell), \
                    patch.object(Pkg, '_knowledge_master',
                                 lambda s, raise_if_missing=True: self.master), \
                    patch.object(Pkg, '_knowledge_golden_installed',
                                 lambda s, g, official_only=False: set()):
                self.pkg.solution_package_knowledge_refresh(full=False, reason='test')
        routes = self._features('website').filtered(lambda f: f.kind == 'route')
        if self.env['ir.model.data'].search_count([('module', '=', 'website'),
                                                   ('model', '=', 'website.menu')]):
            self.assertTrue(routes)
            self.assertFalse(routes[0].views_for_fingerprint(), '前台路由不算後台指紋')

    def test_bom_module_still_gets_every_kind(self):
        self._refresh()
        base = self._features('base')
        self.assertTrue(set(base.mapped('kind')) - {'action', 'client'},
                        'BOM 模組照舊盤全部種類')

    def test_module_leaving_scope_marks_features_missing(self):
        self._refresh()
        mail = self._features('mail')
        self.assertTrue(mail)
        events = self._refresh(official_installed={'base'})
        self.assertFalse(self._features('mail'), 'mail 不在範圍了，功能點要從方案移除')
        self.assertTrue(all(f.missing for f in mail))
        changed = events.filtered(lambda e: e.type == 'modules_changed')
        self.assertEqual(len(changed), 1)
        self.assertIn('mail', json.loads(changed.payload)['removed'])

    def test_first_refresh_records_scope_without_event(self):
        events = self._refresh()
        self.assertFalse(events.filtered(lambda e: e.type == 'modules_changed'))
        self.assertIn('mail', json.loads(self.pkg.knowledge_scope_snapshot))

    def test_empty_inventory_never_retires_everything(self):
        self._refresh()
        before = self._features()
        Pkg = type(self.pkg)
        real = self._exec_shell

        def shell(env, instance, db_name, script, **kw):
            if "'features'" in script and 'OFFICIAL' in script:
                return {'features': []}
            return real(env, instance, db_name, script)

        with patch.object(remote, 'shell_json', side_effect=shell), \
                patch.object(Pkg, '_knowledge_master',
                             lambda s, raise_if_missing=True: self.master), \
                patch.object(Pkg, '_provision_module_names', lambda s: ['base']), \
                patch.object(Pkg, '_knowledge_golden_installed',
                             lambda s, g, official_only=False: set(self.INSTALLED_OFFICIAL)):
            self.pkg.solution_package_knowledge_refresh(full=False, reason='test')
        self.assertEqual(self._features(), before)

    def test_ai_catalog_puts_own_modules_first(self):
        Feature = self.env['corpaas.knowledge.feature']
        own = Feature.create({'feature_key': 'x_own.menu:a', 'module': 'x_own',
                              'kind': 'menu', 'anchor': 'a', 'name': '自有',
                              'package_ids': [(4, self.pkg.id)], 'classify_pending': True})
        off = Feature.create({'feature_key': 'sale.menu:b', 'module': 'sale',
                              'kind': 'menu', 'anchor': 'b', 'name': '官方',
                              'module_origin': 'odoo', 'usage_score': 999,
                              'package_ids': [(4, self.pkg.id)], 'classify_pending': True})
        prompts = []
        Ai = type(self.env['corpaas.knowledge.ai'])
        with patch.object(Ai, 'ask', lambda s, kind, prompt, **kw: prompts.append(prompt)
                          or {'items': []}):
            self.pkg._knowledge_ai_catalog(Feature, 'tok')
        self.assertLess(prompts[0].index(own.feature_key), prompts[0].index(off.feature_key))

    def test_capability_with_dependency_module_is_available(self):
        """sale 是相依裝進來的（不在 BOM）：能力不能被判成加購或缺少。"""
        Feature = self.env['corpaas.knowledge.feature']
        f = Feature.create({'feature_key': 'sale_dep.menu:c', 'module': 'sale_dep',
                            'kind': 'menu', 'anchor': 'c', 'name': '訂單',
                            'module_origin': 'odoo', 'package_ids': [(4, self.pkg.id)]})
        cap = self.env['corpaas.knowledge.capability'].create(
            {'name': '接單', 'code': 'order_t', 'feature_ids': [(4, f.id)]})
        Pkg = type(self.pkg)
        with patch.object(Pkg, '_knowledge_master',
                          lambda s, raise_if_missing=True: self.master), \
                patch.object(Pkg, '_provision_module_names', lambda s: ['base']), \
                patch.object(Pkg, '_knowledge_golden_installed',
                             lambda s, g, official_only=False: {'base', 'sale_dep'}):
            self.assertEqual(cap.availability_for(self.pkg)[0], 'available')

    def test_golden_module_change_enqueues_incremental_refresh(self):
        Pkg = type(self.pkg)
        Inst = type(self.env['infrastructure.instance'])
        inst = self.env['infrastructure.instance'].new({'template_package_id': self.pkg.id})
        db = self.env['infrastructure.database'].new(
            {'is_golden_template': True, 'instance_id': inst})
        calls = []
        with patch.object(Inst, '_knowledge_is_doc_master', lambda s: True), \
                patch.object(Pkg, '_provision_module_names', lambda s: ['base']), \
                patch.object(Pkg, 'knowledge_enqueue_refresh',
                             lambda s, full=False, reason='', delay_minutes=0:
                             calls.append((full, reason))):
            db._on_installed_modules_changed(['l10n_tw'], [])
            self.assertEqual(calls, [], '排除清單裡的模組變動不觸發')
            db._on_installed_modules_changed(['sale'], [])
            self.assertEqual(calls, [(False, 'modules')])
            db.with_context(knowledge_skip_modules_trigger=True) \
                ._on_installed_modules_changed(['crm'], [])
            self.assertEqual(len(calls), 1, '知識更新自己同步黃金庫時不再排一張')
