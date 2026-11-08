# -*- coding: utf-8 -*-
"""pt-verify 單元測試：cd tools/verify && python3 -m unittest discover -s tests -v

不碰真實工作區／正式機：PT_VERIFY_GH／PT_VERIFY_ODOO／PT_VERIFY_KB_HOME 全指到暫存目錄。
"""
import datetime as dt
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pt_verify as pv  # noqa: E402


def write(path, text=''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(textwrap.dedent(text))


def mkmod(root, name, depends=(), version='18.0.1.0.0', installable=True, extra=None):
    write(os.path.join(root, name, '__manifest__.py'),
          repr({'name': name, 'version': version, 'depends': list(depends), 'installable': installable}))
    write(os.path.join(root, name, '__init__.py'))
    for rel, text in (extra or {}).items():
        write(os.path.join(root, name, rel), text)
    return os.path.join(root, name)


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@t')
    return subprocess.run(['git', '-C', repo] + list(args), check=True, capture_output=True, text=True, env=env).stdout


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ptv-test-')
        self.gh = os.path.join(self.tmp, 'GitHub')
        self.odoo = os.path.join(self.tmp, 'odoo-18.0')
        self.kb = os.path.join(self.tmp, 'kb')
        for d in (self.gh, os.path.join(self.odoo, 'addons'), os.path.join(self.odoo, 'odoo', 'addons'), self.kb):
            os.makedirs(d, exist_ok=True)
        mkmod(os.path.join(self.odoo, 'odoo', 'addons'), 'base')
        mkmod(os.path.join(self.odoo, 'addons'), 'web', ['base'])
        mkmod(os.path.join(self.odoo, 'addons'), 'mail', ['web'])
        self._env = {k: os.environ.get(k) for k in ('PT_VERIFY_GH', 'PT_VERIFY_ODOO', 'PT_VERIFY_KB_HOME')}
        os.environ.update(PT_VERIFY_GH=self.gh, PT_VERIFY_ODOO=self.odoo, PT_VERIFY_KB_HOME=self.kb)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- 路徑推導
class TestAddonsDerivation(Sandbox):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.gh, 'Mine')
        mkmod(self.repo, 'my_mod', ['their_mod', 'mail'])
        mkmod(os.path.join(self.gh, 'Theirs'), 'their_mod', ['oca_mod'])
        mkmod(os.path.join(self.gh, 'Theirs'), 'unrelated')
        mkmod(os.path.join(self.gh, 'OCA', 'web-tools'), 'oca_mod', ['web'])
        # 不該被掃到的：worktrees、Odoo 原碼樹、worktree 檢出
        mkmod(os.path.join(self.gh, 'Theirs-worktrees', 'x'), 'their_mod', ['web'], version='18.0.9.0.0')
        mkmod(os.path.join(self.gh, 'odoo14'), 'their_mod', version='18.0.99.0.0')
        write(os.path.join(self.gh, 'odoo14', 'odoo-bin'))
        mkmod(os.path.join(self.gh, 'Theirs-wt'), 'their_mod', version='18.0.98.0.0')
        write(os.path.join(self.gh, 'Theirs-wt', '.git'), 'gitdir: /x')

    def test_recursive_depends_and_order(self):
        idx = pv.ModuleIndex(exclude=[self.repo])
        r = pv.resolve_addons(['my_mod'], first=[self.repo], index=idx)
        self.assertEqual(r['blocked'], [])
        a = r['addons']
        self.assertEqual(a[0], self.repo, '受測 repo 排第一')
        self.assertIn(os.path.join(self.odoo, 'addons'), a)
        self.assertIn(os.path.join(self.gh, 'Theirs'), a)
        self.assertIn(os.path.join(self.gh, 'OCA', 'web-tools'), a, '一層子目錄（OCA/<repo>）也找得到')
        self.assertTrue(a.index(os.path.join(self.odoo, 'addons')) < a.index(os.path.join(self.gh, 'Theirs')))
        for bad in ('Theirs-worktrees', 'odoo14', 'Theirs-wt'):
            self.assertFalse(any(bad in x for x in a), bad)
        self.assertEqual(r['resolved']['their_mod'][1], os.path.join(self.gh, 'Theirs'))

    def test_missing_dependency_is_blocked_with_reason(self):
        mkmod(self.repo, 'needs_ghost', ['ghost_mod'])
        r = pv.resolve_addons(['needs_ghost'], first=[self.repo], index=pv.ModuleIndex(exclude=[self.repo]))
        self.assertEqual(len(r['blocked']), 1)
        self.assertIn('ghost_mod', r['blocked'][0])
        self.assertIn('needs_ghost 依賴它', r['blocked'][0])

    def test_wrong_series_is_not_used(self):
        mkmod(os.path.join(self.gh, 'Old14'), 'old_mod', version='14.0.1.0.0')
        mkmod(self.repo, 'needs_old', ['old_mod'])
        r = pv.resolve_addons(['needs_old'], first=[self.repo], index=pv.ModuleIndex(exclude=[self.repo]))
        self.assertTrue(r['blocked'])
        self.assertTrue(any('不相容' in n for n in r['notes']))

    def test_duplicate_prefers_series18_then_already_used_repo(self):
        mkmod(os.path.join(self.gh, 'AppsStore'), 'dup_mod', version='1.5')       # 沒系列
        mkmod(os.path.join(self.gh, 'Theirs'), 'dup_mod', version='18.0.1.0')      # 18 系列
        mkmod(os.path.join(self.gh, 'Customer'), 'dup_mod', version='18.0.5.0.0')  # 18 系列、版號較高
        mkmod(self.repo, 'uses_dup', ['their_mod', 'dup_mod'])
        r = pv.resolve_addons(['uses_dup'], first=[self.repo], index=pv.ModuleIndex(exclude=[self.repo]))
        # Theirs 已因 their_mod 被選用 → dup_mod 也取 Theirs（同一套相依盡量來自同一批 repo）
        self.assertEqual(r['resolved']['dup_mod'][1], os.path.join(self.gh, 'Theirs'))
        self.assertTrue(any('多個 repo' in n for n in r['notes']))
        self.assertFalse(any('遮蔽' in n for n in r['notes']))

    def test_layers_before_workspace(self):
        layer = os.path.join(self.tmp, 'prod', 'Theirs')
        mkmod(layer, 'their_mod', ['web'], version='18.0.0.1.0')
        r = pv.resolve_addons(['my_mod'], first=[self.repo], layers=[layer], index=pv.ModuleIndex(exclude=[self.repo]))
        self.assertEqual(r['resolved']['their_mod'][1], layer)

    def test_no_hardcoded_repo_list(self):
        src = open(pv.__file__, encoding='utf-8').read()
        for name in ('Google-API', 'Uniform-Invoice', 'eCommerce', "'Sales'"):
            self.assertNotIn(name, src, '不得寫死 repo 清單：%s' % name)

    def test_reverse_deps(self):
        u = {'a': mkmod(self.repo, 'a'), 'b': mkmod(self.repo, 'b', ['a']), 'c': mkmod(self.repo, 'c', ['b']),
             'd': mkmod(self.repo, 'd')}
        self.assertEqual(pv.reverse_deps({'a'}, u), {'b', 'c'})


# ---------------------------------------------------------------- V0
class TestV0(Sandbox):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.gh, 'Mine')
        mkmod(self.repo, 'my_mod', ['mail'], version='18.0.1.0.0', extra={
            'models/__init__.py': '',
            'models/a.py': "from odoo import models\nclass A(models.Model):\n    _name = 'my.a'\n",
            'security/ir.model.access.csv': 'id,name,model_id:id,group_id:id,perm_read\naccess_a,a,model_my_a,,1\n',
            'views/v.xml': '<odoo><record id="view_a" model="ir.ui.view"><field name="name">a</field></record></odoo>',
            'migrations/18.0.0.9.0/post-migrate.py': 'def migrate(cr, v):\n    pass\n',
        })
        git(self.repo, 'init', '-q')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'base')
        self.base = git(self.repo, 'rev-parse', 'HEAD').strip()

    def test_repo_info_worktree_main_repo(self):
        # git < 2.31 不認得 --path-format=absolute（會原樣印出），worktree 的 main_repo 曾因此變成垃圾路徑
        wt = os.path.join(self.gh, 'Mine-worktrees', 'feat')
        git(self.repo, 'worktree', 'add', '-q', '-b', 'feat', wt)
        info = pv.repo_info(wt)
        self.assertEqual(info['main_repo'], os.path.realpath(self.repo))
        self.assertEqual(info['name'], 'Mine')
        self.assertEqual(pv.repo_info(self.repo)['main_repo'], os.path.realpath(self.repo))

    def rules(self, issues, severity='error'):
        return sorted({i['rule'] for i in issues if i['severity'] == severity})

    def test_clean_change_passes(self):
        write(os.path.join(self.repo, 'my_mod', 'models', 'a.py'),
              "from odoo import models, fields\nclass A(models.Model):\n    _name = 'my.a'\n    x = fields.Char()\n")
        self.assertEqual(pv.v0_checks(self.repo, ['my_mod'], self.base), [])

    def test_rule1_new_migration_above_manifest(self):
        write(os.path.join(self.repo, 'my_mod', 'migrations', '1.1.0', 'post-migrate.py'), 'def migrate(cr, v): pass\n')
        iss = pv.v0_checks(self.repo, ['my_mod'], self.base)
        self.assertEqual(self.rules(iss), ['V0-1 migration'])
        self.assertIn('18.0.1.0.0', iss[0]['msg'])
        # 升版號到 1.1.0 就過（短版號與 18.0. 前綴等價）
        write(os.path.join(self.repo, 'my_mod', '__manifest__.py'),
              repr({'name': 'm', 'version': '18.0.1.1.0', 'depends': ['mail']}))
        self.assertEqual(self.rules(pv.v0_checks(self.repo, ['my_mod'], self.base)), [])

    def test_rule1_existing_migration_not_flagged(self):
        # 18.0.0.9.0 在基準就有 → 不算新的
        self.assertEqual(pv.v0_checks(self.repo, ['my_mod'], self.base), [])

    def test_rule1_warns_when_migration_not_above_base(self):
        write(os.path.join(self.repo, 'my_mod', 'migrations', '18.0.0.9.5', 'post-migrate.py'), 'def migrate(cr, v): pass\n')
        iss = pv.v0_checks(self.repo, ['my_mod'], self.base)
        self.assertEqual(self.rules(iss), [])
        self.assertEqual(self.rules(iss, 'warn'), ['V0-1 migration'])

    def test_rule2_new_name_exists_in_other_repo(self):
        mkmod(os.path.join(self.gh, 'Other'), 'other_mod', extra={
            'models/b.py': "from odoo import models\nclass B(models.Model):\n    _name = 'shared.thing'\n"})
        # worktrees 與自己的副本不算
        mkmod(os.path.join(self.gh, 'Mine-worktrees', 'wt'), 'my_mod', extra={
            'models/c.py': "from odoo import models\nclass C(models.Model):\n    _name = 'my.new'\n"})
        write(os.path.join(self.repo, 'my_mod', 'models', 'b.py'),
              "from odoo import models\nclass B(models.Model):\n    _name = 'shared.thing'\n"
              "class C(models.Model):\n    _name = 'my.new'\n")
        write(os.path.join(self.repo, 'my_mod', 'security', 'ir.model.access.csv'),
              'id,name,model_id:id,group_id:id,perm_read\naccess_a,a,model_my_a,,1\n'
              'access_s,s,model_shared_thing,,1\naccess_n,n,model_my_new,,1\n')
        iss = pv.v0_checks(self.repo, ['my_mod'], self.base, exclude_repos=[self.repo])
        dup = [i for i in iss if i['rule'] == 'V0-2 _name 重複']
        self.assertEqual(len(dup), 1)
        self.assertIn('shared.thing', dup[0]['msg'])
        self.assertIn('Other', dup[0]['msg'])

    def test_rule2_inherit_extension_not_new(self):
        write(os.path.join(self.repo, 'my_mod', 'models', 'p.py'),
              "from odoo import models\nclass P(models.Model):\n    _name = 'res.partner'\n    _inherit = 'res.partner'\n")
        self.assertEqual(pv.v0_checks(self.repo, ['my_mod'], self.base), [])

    def test_rule3_new_model_without_access(self):
        write(os.path.join(self.repo, 'my_mod', 'models', 'n.py'),
              "from odoo import models\nclass N(models.TransientModel):\n    _name = 'my.wizard'\n"
              "class Ab(models.AbstractModel):\n    _name = 'my.mixin'\n")
        iss = pv.v0_checks(self.repo, ['my_mod'], self.base)
        acc = [i for i in iss if i['rule'] == 'V0-3 存取權限']
        self.assertEqual(len(acc), 1, 'AbstractModel 不需要存取權限')
        self.assertIn('model_my_wizard', acc[0]['msg'])

    def test_rule4_xml_refs(self):
        write(os.path.join(self.repo, 'my_mod', 'views', 'w.xml'), '''<odoo>
          <record id="v2" model="ir.ui.view"><field name="inherit_id" ref="view_a"/></record>
          <record id="v3" model="ir.ui.view"><field name="inherit_id" ref="my_mod.view_missing"/></record>
          <record id="v4" model="ir.ui.view"><field name="inherit_id" ref="base.view_partner_form"/></record>
          <record id="v5" model="ir.actions.server"><field name="model_id" ref="model_my_a"/></record>
          <template id="t1" inherit_id="my_mod.tpl_missing"/>
          <record id="v6" model="x"><field name="groups_id" eval="[(4, ref('also_missing'))]"/></record>
        </odoo>''')
        iss = [i for i in pv.v0_checks(self.repo, ['my_mod'], self.base) if i['rule'].startswith('V0-4')]
        msgs = ' '.join(i['msg'] for i in iss)
        self.assertEqual(len(iss), 3, msgs)
        for bad in ('view_missing', 'tpl_missing', 'also_missing'):
            self.assertIn(bad, msgs)
        self.assertNotIn('base.view_partner_form', msgs, '別的 repo 的參照不檢查')

    def test_rule5_syntax(self):
        write(os.path.join(self.repo, 'my_mod', 'models', 'bad.py'), 'def x(:\n')
        self.assertEqual(self.rules(pv.v0_checks(self.repo, ['my_mod'], self.base)), ['V0-5 語法'])

    def test_changed_modules_includes_untracked(self):
        mkmod(self.repo, 'brand_new')
        write(os.path.join(self.repo, 'my_mod', 'x.txt'), 'x')
        self.assertEqual(pv.changed_modules_git(self.repo, self.base), ['brand_new', 'my_mod'])


# ---------------------------------------------------------------- 報告、log 解析、差集
SAMPLE_LOG = """\
2026-11-02 05:53:30,000 1 INFO db odoo.modules.migration: module my_mod: Running migration [18.0.1.1.0>] post-migrate
2026-11-02 05:53:33,336 1 ERROR db odoo.addons.my_mod.tests.test_a: FAIL: TestA.test_one
2026-11-02 05:53:33,337 1 ERROR db odoo.addons.my_mod.tests.test_a: ERROR: TestA.test_two (sub=1)
2026-11-02 05:53:33,338 1 ERROR db odoo.tests.suite: ERROR: setUpClass (odoo.addons.my_mod.tests.test_b.TestB)
2026-11-02 05:53:33,339 1 INFO db odoo.addons.my_mod.tests.test_c: skipped TestC.test_skip : no data
2026-11-02 05:53:33,339 1 INFO db odoo.addons.my_mod.tests.test_c: skipped TestC.test_skip : no data
2026-11-02 05:53:33,340 1 ERROR db odoo.sql_db: bad query: b'CREATE EXTENSION IF NOT EXISTS pg_trgm'
2026-11-02 05:53:30,100 1 INFO db odoo.modules.graph: module my_mod: Unmet dependencies: sale_crm, x_mod
2026-11-02 05:53:34,000 1 ERROR db odoo.tests.result: 1 failed, 2 error(s) of 23 tests when loading database 'db'
"""


class TestReportAndDiff(Sandbox):
    def test_parse_log(self):
        p = os.path.join(self.tmp, 'x.log')
        write(p, SAMPLE_LOG)
        r = pv.parse_log(p)
        self.assertEqual((r['tests_total'], r['failed'], r['errors'], r['skipped']), (23, 1, 2, 1))
        self.assertEqual(r['failures'], ['TestA.test_one', 'TestA.test_two', 'TestB.setUpClass'])
        self.assertEqual(r['migrations_ran'], ['my_mod 18.0.1.1.0> post-migrate'])
        self.assertEqual(r['load_errors'], [], 'Unmet dependencies（INFO）不算載入錯誤')
        self.assertEqual(r['unmet'], ['my_mod 需要 sale_crm, x_mod'])
        self.assertEqual(len(r['log_errors']), 1)

    def test_parse_log_registry_failure(self):
        p = os.path.join(self.tmp, 'y.log')
        write(p, '2026-11-03 01:27:01,019 1 ERROR db odoo.modules.registry: Failed to load registry\n'
                 '2026-11-03 01:27:01,019 1 CRITICAL db odoo.service.server: Failed to initialize database `db`.\n')
        r = pv.parse_log(p)
        self.assertTrue(r['load_errors'])
        rep = pv.new_report('V1', 'Mine')
        rep['load_errors'] = r['load_errors']
        self.assertEqual(pv.decide_verdict(rep, ['my_mod']), 'FAIL')

    def test_new_failures_baseline_and_flaky(self):
        repo = os.path.join(self.gh, 'Mine')
        write(os.path.join(repo, '.claude', 'skills', 'verify', 'known_flaky.txt'),
              '# 註解\nTestA.test_two  時間相依，偶發\n\nTestZ.test_x\n')
        flaky = pv.load_known_flaky(repo)
        self.assertEqual(flaky, {'TestA.test_two': '時間相依，偶發', 'TestZ.test_x': ''})
        fails = ['TestA.test_one', 'TestA.test_two', 'TestB.setUpClass']
        self.assertEqual(pv.new_failures(fails, ['TestB.setUpClass'], flaky), ['TestA.test_one'])
        self.assertEqual(pv.new_failures(fails, None, flaky), ['TestA.test_one', 'TestB.setUpClass'])

    def test_cache_key(self):
        k1 = pv.cache_key('abc', 'V1', ['b', 'a'])
        self.assertEqual(k1, pv.cache_key('abc', 'V1', ['a', 'b']))
        self.assertNotEqual(k1, pv.cache_key('abc', 'V2', ['a', 'b']))
        self.assertNotEqual(k1, pv.cache_key('abd', 'V1', ['a', 'b']))
        self.assertTrue(pv.cache_path(k1).startswith(os.path.join(self.kb, 'verify-cache')))

    def test_report_fields(self):
        rep = pv.new_report('V3', 'Mine')
        rep.update({'branch': 'feat/x', 'sha': 'abc', 'mods': ['m'], 'tests_total': 3, 'verdict': 'PASS',
                    'versions_before': {'m': '18.0.1.0.0'}, 'versions_after': {'m': '18.0.1.1.0'}})
        md, js = pv.write_report(rep, os.path.join(self.tmp, 'out'), '20261103-101010')
        self.assertTrue(md.endswith('20261103-101010-V3.md'))
        data = json.load(open(js, encoding='utf-8'))
        want = ['level', 'repo', 'branch', 'sha', 'base', 'mods', 'db', 'port', 'command', 'tests_total', 'failed',
                'errors', 'skipped', 'new_failures', 'migrations_ran', 'versions_before', 'versions_after',
                'overrides', 'log', 'duration', 'verdict']
        for k in want:
            self.assertIn(k, data)
        text = open(md, encoding='utf-8').read()
        for k in want:
            self.assertIn('| %s |' % k, text)

    def test_verdicts(self):
        rep = pv.new_report('V1', 'Mine')
        rep['tests_total'] = 5
        self.assertEqual(pv.decide_verdict(rep, ['m']), 'PASS')
        rep['new_failures'] = ['T.t']
        self.assertEqual(pv.decide_verdict(rep, ['m']), 'FAIL')
        rep = pv.new_report('V1', 'Mine')
        self.assertEqual(pv.decide_verdict(rep, ['m']), 'FAIL', '有 tests/ 卻 0 項＝不可當通過')
        rep['blocked_reasons'] = ['x']
        self.assertEqual(pv.decide_verdict(rep, ['m']), 'BLOCKED')
        rep = pv.new_report('V0', 'Mine')
        rep['v0_issues'] = [{'severity': 'warn'}]
        self.assertEqual(pv.decide_verdict(rep, ['m']), 'PASS')
        rep['v0_issues'] = [{'severity': 'error'}]
        self.assertEqual(pv.decide_verdict(rep, ['m']), 'FAIL')


# ---------------------------------------------------------------- port、庫名
class TestPortAndDbName(unittest.TestCase):
    def test_pick_port_skips_busy(self):
        busy = {8150, 8151}
        self.assertEqual(pv.pick_port(is_free=lambda p: p not in busy), 8152)
        self.assertIsNone(pv.pick_port(is_free=lambda p: False))

    def test_port_free_detects_listener(self):
        s = socket.socket()
        s.bind(('', 0))
        s.listen(1)
        try:
            self.assertFalse(pv.port_free(s.getsockname()[1]))
        finally:
            s.close()
        self.assertTrue(8150 <= (pv.pick_port() or 8150) <= 8199)

    def test_db_name(self):
        when = dt.datetime(2026, 11, 3, 9, 5)
        self.assertEqual(pv.make_db_name('Knowledge', 'feat/case-synth', 'V1', when), 'v_knowledge_case_synth_v1_0905')
        long = pv.make_db_name('A-Very-Long-Repository-Name-For-Testing', 'feature/an-extremely-long-branch-name-x',
                               'V3', when, suffix='b')
        self.assertLessEqual(len(long), 60)
        self.assertRegex(long, r'^v_[a-z0-9_]+_v3_0905_b$')
        for n in (long, pv.make_db_name('Ünï Côdé', 'HEAD', 'V0', when)):
            self.assertRegex(n, r'^[a-z0-9_]+$')
            self.assertNotIn('__', n)


# ---------------------------------------------------------------- TOML、snapshot
class TestTomlAndSnapshot(Sandbox):
    def test_toml_subset_matches_files(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for f in ('targets.toml', 'prod_overrides.toml'):
            data = pv.parse_toml_subset(open(os.path.join(here, f), encoding='utf-8').read())
            self.assertTrue(data)
        t = pv.parse_toml_subset(open(os.path.join(here, 'targets.toml'), encoding='utf-8').read())
        names = [x['name'] for x in t['target']]
        self.assertEqual(names, ['admin.corpaas.com', 'admin.dobtor.com', 'demo-accounting'])
        self.assertEqual(t['target'][0]['pause_crons'][0], 'dobtor_infrastructure.ir_cron_queue')
        o = pv.parse_toml_subset(open(os.path.join(here, 'prod_overrides.toml'), encoding='utf-8').read())
        self.assertEqual(o['override'][0]['repo'], 'website-user')

    def test_load_snapshot_dir_variants(self):
        d = os.path.join(self.tmp, 'snap')
        mkmod(os.path.join(d, 'PAAS'), 'p1')
        write(os.path.join(self.tmp, 'inst.txt'), 'p1, p2,\np3')
        s = pv.load_snapshot(snapshot_dir=d, installed=os.path.join(self.tmp, 'inst.txt'))
        self.assertEqual(s['src'], d)
        self.assertEqual(sorted(s['installed']), ['p1', 'p2', 'p3'])
        self.assertEqual(pv.snapshot_layers(s), [os.path.join(d, 'PAAS')])

    def test_snapshot_with_fake_ssh(self):
        """用假的 ssh／docker 在本機模擬（不連正式機）。"""
        src = os.path.join(self.tmp, 'remote_src')
        mkmod(os.path.join(src, 'PAAS'), 'p1')
        write(os.path.join(src, 'PAAS', 'p1', '__pycache__', 'x.pyc'), 'junk')
        fakebin = os.path.join(self.tmp, 'fakebin')
        write(os.path.join(fakebin, 'ssh'), '#!/bin/bash\n# 丟掉 -i key -o opt host，剩下的在本機跑\n'
              'while [ $# -gt 1 ]; do case "$1" in -i|-o) shift 2;; *) shift;; esac; done\nexec bash -c "$1"\n')
        write(os.path.join(fakebin, 'docker'), '#!/bin/bash\n'
              'echo \'{"installed": {"p1": "18.0.1.0.0", "base": "18.0.1.3"}, "addons_path": "/mnt/x"}\'\n')
        for f in ('ssh', 'docker'):
            os.chmod(os.path.join(fakebin, f), 0o755)
        targets = os.path.join(self.tmp, 'targets.toml')
        write(targets, '[[target]]\nname = "fake"\nssh_host = "root@nowhere"\nssh_key = "~/k"\n'
                       'container = "c"\ndb = "d"\nsources_path = "%s"\n' % src)
        old = dict(os.environ)
        os.environ.update(PT_VERIFY_TARGETS=targets, PT_VERIFY_SSH=os.path.join(fakebin, 'ssh'),
                          PATH=fakebin + os.pathsep + os.environ['PATH'])
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(pv.cmd_snapshot(SimpleNamespace(target='fake')), 0)
        finally:
            os.environ.clear()
            os.environ.update(old)
        day = dt.datetime.now().strftime('%Y%m%d')
        out = os.path.join(self.kb, 'prod', 'fake', day)
        self.assertTrue(os.path.isfile(os.path.join(out, 'src', 'PAAS', 'p1', '__manifest__.py')))
        self.assertFalse(os.path.exists(os.path.join(out, 'src', 'PAAS', 'p1', '__pycache__')))
        self.assertEqual(json.load(open(os.path.join(out, 'installed.json')))['installed']['p1'], '18.0.1.0.0')
        self.assertEqual(pv.latest_snapshot_dir('fake'), out)

    def test_snapshot_refuses_unconfirmed_target(self):
        targets = os.path.join(self.tmp, 'targets.toml')
        write(targets, '[[target]]\nname = "tbd"\nssh_host = "h"\ncontainer = "c"\ndb = "d"\nsources_path = ""\n')
        os.environ['PT_VERIFY_TARGETS'] = targets
        try:
            with self.assertRaises(SystemExit) as cm:
                pv.cmd_snapshot(SimpleNamespace(target='tbd'))
            self.assertIn('sources_path', str(cm.exception))
        finally:
            os.environ.pop('PT_VERIFY_TARGETS')


# ---------------------------------------------------------------- deploy-plan
class TestDeployPlan(Sandbox):
    def test_md5_lines_c_locale_order(self):
        g = os.path.join(self.tmp, 'grp')
        write(os.path.join(g, 'mod_b', 'z.py'), 'z')
        write(os.path.join(g, 'mod_b', 'A.py'), 'A')
        write(os.path.join(g, 'mod_b', '_x.py'), 'x')
        write(os.path.join(g, 'mod_a', 'b.py'), 'b')
        write(os.path.join(g, 'mod_b', '__pycache__', 'q.pyc'), 'q')
        lines = pv.md5_lines(g, ['mod_b', 'mod_a'])
        paths = sorted(x.split('  ', 1)[1] for x in lines)
        self.assertEqual(paths, ['mod_a/b.py', 'mod_b/A.py', 'mod_b/_x.py', 'mod_b/z.py'], '__pycache__ 不列')
        for x in lines:
            self.assertRegex(x, r'^[0-9a-f]{32}  mod_[ab]/\S+$')
        # 與 LC_ALL=C sort 結果一致
        r = subprocess.run(['sort'], input='\n'.join(reversed(lines)) + '\n', capture_output=True, text=True,
                           env=dict(os.environ, LC_ALL='C'))
        self.assertEqual(r.stdout.splitlines(), lines)

    def test_plan_groups_and_empty_exist(self):
        src = os.path.join(self.tmp, 'snap', 'src')
        mkmod(os.path.join(src, 'PAAS'), 'p_old')
        mkmod(os.path.join(src, 'ProductivityTools'), 'k_old')
        os.makedirs(os.path.join(src, 'Knowledge'))
        smap = {'p_old': os.path.join(src, 'PAAS', 'p_old'), 'k_old': os.path.join(src, 'ProductivityTools', 'k_old')}
        groups, err = pv.plan_groups(['p_old', 'k_new', 'k_old', 'p_new'], smap, src,
                                     {'k_new': 'Knowledge', 'p_new': 'PAAS', 'k_old': 'Knowledge', 'p_old': 'PAAS'})
        self.assertEqual(err, [])
        self.assertEqual(list(groups), ['Knowledge', 'PAAS', 'ProductivityTools'])
        self.assertEqual(groups['Knowledge'], {'mods': ['k_new'], 'exist': []})
        self.assertEqual(groups['PAAS'], {'mods': ['p_new', 'p_old'], 'exist': ['p_old']})
        self.assertEqual(groups['ProductivityTools'], {'mods': ['k_old'], 'exist': ['k_old']}, '已在正式機的模組放回原位')
        _g, err = pv.plan_groups(['x_new'], smap, src, {'x_new': 'NoSuchDir'})
        self.assertTrue(err and 'x_new' in err[0])

    def test_remote_script_runs_locally_with_empty_group(self):
        """產生的 remote.sh 在本機用假 docker 跑一遍：空清單分組不掃整個目錄、漂移比對、換碼、-u。"""
        host_src = os.path.join(self.tmp, 'host', 'sources')
        mkmod(os.path.join(host_src, 'PAAS'), 'p_old', extra={'a.py': 'old\n'})
        mkmod(os.path.join(host_src, 'PAAS'), 'p_other', extra={'a.py': 'other\n'})
        os.makedirs(os.path.join(host_src, 'Knowledge'))
        bk = os.path.join(self.tmp, 'bk')
        os.makedirs(bk)
        groups = {'Knowledge': {'mods': ['k_new'], 'exist': []}, 'PAAS': {'mods': ['p_old'], 'exist': ['p_old']}}
        t = {'sources_path': host_src, 'container': 'c', 'db': 'd', 'pause_crons': ['a.b'],
             'queue_busy_sql': '', 'kill_pattern': ''}
        with open(os.path.join(bk, 'remote.sh'), 'w') as f:
            f.write(pv.render_remote_script(t, groups, ['p_old'], [], 'test'))
        # 部署包與預期 md5
        stage = os.path.join(self.tmp, 'stage')
        mkmod(os.path.join(stage, '0'), 'k_new')
        mkmod(os.path.join(stage, '1'), 'p_old', extra={'a.py': 'new\n'})
        pv._tar_dir(os.path.join(stage, '0'), ['k_new'], os.path.join(bk, 'bundle_0.tgz'))
        pv._tar_dir(os.path.join(stage, '1'), ['p_old'], os.path.join(bk, 'bundle_1.tgz'))
        write(os.path.join(bk, 'expect_0.md5'), '')
        write(os.path.join(bk, 'expect_1.md5'), ''.join(x + '\n' for x in pv.md5_lines(os.path.join(host_src, 'PAAS'), ['p_old'])))
        fakebin = os.path.join(self.tmp, 'fakebin')
        calls = os.path.join(self.tmp, 'docker_calls')
        write(os.path.join(fakebin, 'docker'), '#!/bin/bash\necho "$*" >> %s\n'
              'case "$1" in exec) for a in "$@"; do case "$a" in --logfile=*) : > "%s/$(basename "${a#--logfile=}")";; esac; done\n'
              '  [ "$3" = cat ] && echo "INFO ok";;\nesac\nexit 0\n' % (calls, self.tmp))
        os.chmod(os.path.join(fakebin, 'docker'), 0o755)
        env = dict(os.environ, BK=bk, RESTART_WAIT='0', PATH=fakebin + os.pathsep + os.environ['PATH'])
        r = subprocess.run(['bash', os.path.join(bk, 'remote.sh')], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('drift: Knowledge 只有新模組，略過比對', r.stdout)
        self.assertIn('drift check OK', r.stdout)
        self.assertEqual(open(os.path.join(host_src, 'PAAS', 'p_old', 'a.py')).read(), 'new\n')
        self.assertEqual(open(os.path.join(host_src, 'PAAS', 'p_other', 'a.py')).read(), 'other\n', '其他模組不動')
        self.assertTrue(os.path.isfile(os.path.join(host_src, 'Knowledge', 'k_new', '__manifest__.py')))
        self.assertIn('-u p_old', open(calls).read())
        # now_1.md5 只含 p_old（不是整個 PAAS 目錄）
        self.assertNotIn('p_other', open(os.path.join(bk, 'now_1.md5')).read())
        self.assertFalse(os.path.exists(os.path.join(bk, 'now_0.md5')), '空清單分組不做 find')

    def test_remote_script_aborts_on_drift(self):
        host_src = os.path.join(self.tmp, 'host', 'sources')
        mkmod(os.path.join(host_src, 'PAAS'), 'p_old', extra={'a.py': 'changed on prod\n'})
        bk = os.path.join(self.tmp, 'bk')
        os.makedirs(bk)
        t = {'sources_path': host_src, 'container': 'c', 'db': 'd'}
        with open(os.path.join(bk, 'remote.sh'), 'w') as f:
            f.write(pv.render_remote_script(t, {'PAAS': {'mods': ['p_old'], 'exist': ['p_old']}}, ['p_old'], [], 't'))
        write(os.path.join(bk, 'expect_0.md5'), '00000000000000000000000000000000  p_old/a.py\n')
        r = subprocess.run(['bash', os.path.join(bk, 'remote.sh')], capture_output=True, text=True,
                           env=dict(os.environ, BK=bk))
        self.assertEqual(r.returncode, 2)
        self.assertIn('ABORT', r.stdout)
        self.assertEqual(open(os.path.join(host_src, 'PAAS', 'p_old', 'a.py')).read(), 'changed on prod\n')

    def test_deploy_plan_end_to_end_and_guards(self):
        # 本機 repo
        repo = os.path.join(self.gh, 'PAAS')
        mkmod(repo, 'p_old', extra={'a.py': 'new\n'})
        git(repo, 'init', '-q')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'x')
        # 快照
        snapdir = os.path.join(self.kb, 'prod', 'fake', dt.datetime.now().strftime('%Y%m%d'))
        mkmod(os.path.join(snapdir, 'src', 'PAAS'), 'p_old', extra={'a.py': 'old\n'})
        write(os.path.join(snapdir, 'installed.json'), json.dumps({'installed': {'p_old': '18.0.1.0.0'}}))
        targets = os.path.join(self.tmp, 'targets.toml')
        write(targets, '[[target]]\nname = "fake"\ndeploy_mode = "host"\nssh_host = "root@h"\nssh_key = "~/k"\n'
                       'container = "c"\ndb = "d"\nsources_path = "/opt/src"\n\n'
                       '[[target]]\nname = "cp"\ndeploy_mode = "control_panel"\ncontrol_panel_instance_id = 240\n'
                       'control_panel_database_id = 238\ndb = "x"\n')
        os.environ['PT_VERIFY_TARGETS'] = targets
        try:
            def plan(**kw):
                a = dict(target='fake', mods='p_old', repo=None, ref='HEAD', dest=None, install_new=False,
                         allow_dirty=False, label=None, snapshot_dir=None, installed=None,
                         no_refresh_snapshot=True)
                a.update(kw)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = pv.cmd_deploy_plan(SimpleNamespace(**a))
                return rc, buf.getvalue()
            rc, out = plan()
            self.assertEqual(rc, 0, out)
            last = out.strip().splitlines()[-1]
            self.assertTrue(last.startswith('! bash ') and last.endswith('/deploy.sh'), last)
            d = os.path.dirname(last[len('! bash '):])
            for f in ('bundle_0.tgz', 'expect_0.md5', 'remote.sh', 'deploy.sh', 'plan.json'):
                self.assertTrue(os.path.isfile(os.path.join(d, f)), f)
            self.assertIn('p_old/a.py', open(os.path.join(d, 'expect_0.md5')).read())
            self.assertEqual(subprocess.run(['bash', '-n', os.path.join(d, 'remote.sh')]).returncode, 0)
            # 新模組未安裝且沒加 --install-new → 沒有要升級的 → 拒絕
            mkmod(repo, 'p_new')
            git(repo, 'add', '-A')
            git(repo, 'commit', '-qm', 'y')
            rc, out = plan(mods='p_new')
            self.assertEqual(rc, 2)
            self.assertIn('沒有要升級', out)
            rc, out = plan(mods='p_new', install_new=True)
            self.assertEqual(rc, 0, out)
            # 空清單
            with self.assertRaises(SystemExit):
                plan(mods=' , ')
            # 未 commit 的變更擋下
            write(os.path.join(repo, 'p_old', 'a.py'), 'dirty\n')
            rc, out = plan()
            self.assertEqual(rc, 2)
            self.assertIn('未 commit', out)
            # control_panel：只印動作
            rc, out = plan(target='cp')
            self.assertEqual(rc, 0)
            self.assertIn('#240', out)
            self.assertIn('#238', out)
            self.assertNotIn('! bash', out)
        finally:
            os.environ.pop('PT_VERIFY_TARGETS')


    def test_deploy_plan_refreshes_snapshot_first(self):
        """預設先重抓快照（mock 掉 cmd_snapshot，不連線）；--snapshot-dir／--installed 不重抓；重抓失敗就停。"""
        repo = os.path.join(self.gh, 'PAAS')
        mkmod(repo, 'p_old', extra={'a.py': 'new\n'})
        git(repo, 'init', '-q')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'x')
        day = dt.datetime.now().strftime('%Y%m%d')
        old_snap = os.path.join(self.kb, 'prod', 'fake', '20200101')
        mkmod(os.path.join(old_snap, 'src', 'PAAS'), 'p_old', extra={'a.py': 'stale\n'})
        write(os.path.join(old_snap, 'installed.json'), json.dumps({'installed': {'p_old': '18.0.1.0.0'}}))
        targets = os.path.join(self.tmp, 'targets.toml')
        write(targets, '[[target]]\nname = "fake"\ndeploy_mode = "host"\nssh_host = "root@h"\nssh_key = "~/k"\n'
                       'container = "c"\ndb = "d"\nsources_path = "/opt/src"\n')
        calls = []

        def fake_snapshot(a):
            calls.append(a.target)
            out = os.path.join(self.kb, 'prod', a.target, day)
            mkmod(os.path.join(out, 'src', 'PAAS'), 'p_old', extra={'a.py': 'fresh\n'})
            write(os.path.join(out, 'installed.json'), json.dumps({'installed': {'p_old': '18.0.1.0.0'}}))
            return 0

        def boom(a):
            calls.append(a.target)
            raise SystemExit('下載原碼失敗（ssh 結束碼 255）')

        orig = pv.cmd_snapshot
        os.environ['PT_VERIFY_TARGETS'] = targets
        try:
            def plan(**kw):
                a = dict(target='fake', mods='p_old', repo=None, ref='HEAD', dest=None, install_new=False,
                         allow_dirty=False, label=None, snapshot_dir=None, installed=None, no_refresh_snapshot=False)
                a.update(kw)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = pv.cmd_deploy_plan(SimpleNamespace(**a))
                return rc, buf.getvalue()

            def plan_dir(out):
                return os.path.dirname(out.strip().splitlines()[-1][len('! bash '):])
            pv.cmd_snapshot = fake_snapshot
            # 預設：先重抓，用今天的新快照比對
            rc, out = plan()
            self.assertEqual(rc, 0, out)
            self.assertEqual(calls, ['fake'])
            d = plan_dir(out)
            self.assertEqual(json.load(open(os.path.join(d, 'plan.json')))['snapshot'],
                             os.path.join(self.kb, 'prod', 'fake', day))
            self.assertNotIn('不是今天的快照', out)
            # --snapshot-dir：不重抓
            rc, out = plan(snapshot_dir=old_snap)
            self.assertEqual(rc, 0, out)
            self.assertEqual(calls, ['fake'])
            self.assertIn('不是今天的快照', out)
            # --installed：不重抓
            rc, out = plan(installed=os.path.join(old_snap, 'installed.json'))
            self.assertEqual(rc, 0, out)
            self.assertEqual(calls, ['fake'])
            # --no-refresh-snapshot：不重抓，用最新既有快照
            shutil.rmtree(os.path.join(self.kb, 'prod', 'fake', day))
            rc, out = plan(no_refresh_snapshot=True)
            self.assertEqual(rc, 0, out)
            self.assertEqual(calls, ['fake'])
            self.assertEqual(json.load(open(os.path.join(plan_dir(out), 'plan.json')))['snapshot'], old_snap)
            self.assertIn('不是今天的快照', out)
            # 重抓失敗：明確停下，不退回舊快照
            pv.cmd_snapshot = boom
            with self.assertRaises(SystemExit) as cm:
                plan()
            self.assertIn('重抓快照失敗', str(cm.exception))
            self.assertIn('ssh 結束碼 255', str(cm.exception))
            self.assertEqual(calls, ['fake', 'fake'])
            # CLI 旗標
            ns = pv.build_parser().parse_args(['deploy-plan', 'fake', '--mods', 'p_old', '--no-refresh-snapshot'])
            self.assertTrue(ns.no_refresh_snapshot)
            self.assertFalse(pv.build_parser().parse_args(['deploy-plan', 'fake', '--mods', 'x']).no_refresh_snapshot)
        finally:
            pv.cmd_snapshot = orig
            os.environ.pop('PT_VERIFY_TARGETS')

# ---------------------------------------------------------------- post-check（本機假站台）
class TestPostCheck(Sandbox):
    def test_login_page_and_rpc_versions(self):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200 if self.path == '/web/login' else 404)
                self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                args = body['params']['args']
                res = 7 if body['params']['method'] == 'authenticate' else [
                    {'name': 'm1', 'state': 'installed', 'latest_version': '18.0.1.2.0'}]
                if body['params']['method'] == 'authenticate':
                    assert args[2] == 'sekret'
                out = json.dumps({'jsonrpc': '2.0', 'result': res}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(out)
        srv = http.server.HTTPServer(('127.0.0.1', 0), H)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        targets = os.path.join(self.tmp, 'targets.toml')
        write(targets, '[[target]]\nname = "local.test"\ndb = "d"\nurl = "http://127.0.0.1:%d"\n' % srv.server_port)
        os.environ['PT_VERIFY_TARGETS'] = targets
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = pv.cmd_post_check(SimpleNamespace(target='local.test', mods='m1'))
            self.assertEqual(rc, 0)
            self.assertIn('HTTP 200', buf.getvalue())
            self.assertIn('略過', buf.getvalue(), '缺金鑰要略過並標示')
            os.environ['PT_VERIFY_RPC_KEY_LOCAL_TEST'] = 'sekret'
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = pv.cmd_post_check(SimpleNamespace(target='local.test', mods='m1,m2'))
            self.assertIn('18.0.1.2.0', buf.getvalue())
            self.assertIn('m2', buf.getvalue())
            self.assertEqual(rc, 1, 'm2 不存在 → 非 0')
        finally:
            os.environ.pop('PT_VERIFY_TARGETS', None)
            os.environ.pop('PT_VERIFY_RPC_KEY_LOCAL_TEST', None)
            srv.shutdown()


# ---------------------------------------------------------------- CLI：V0 端到端（不啟動 Odoo）
class TestCliV0(Sandbox):
    def run_cli(self, *argv):
        import contextlib
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = pv.main(list(argv))
        return rc, out.getvalue().strip().splitlines()[-1]

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.gh, 'Mine')
        mkmod(self.repo, 'm_a', ['mail'])
        mkmod(self.repo, 'm_b', ['m_a'])
        git(self.repo, 'init', '-q')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'base')
        git(self.repo, 'branch', 'basebr')

    def test_v0_auto_mods_last_line_and_report(self):
        write(os.path.join(self.repo, 'm_a', 'models.py'), 'x = 1\n')
        rc, last = self.run_cli('run', self.repo, '--level', 'V0', '--base', 'basebr')
        self.assertEqual(rc, 0)
        path, verdict = last.rsplit(' ', 1)
        self.assertEqual(verdict, 'PASS')
        self.assertTrue(path.startswith(os.path.join(self.kb, 'verify-reports', 'Mine')))
        data = json.load(open(path[:-3] + '.json', encoding='utf-8'))
        self.assertEqual(data['mods'], ['m_a'], 'V0 只驗變動模組，不加反向相依')
        self.assertEqual(data['verdict'], 'PASS')

    def test_no_changes_is_blocked_not_pass(self):
        rc, last = self.run_cli('run', self.repo, '--level', 'V0', '--base', 'basebr')
        self.assertEqual((rc, last.rsplit(' ', 1)[1]), (2, 'BLOCKED'))

    def test_unknown_mod_blocked(self):
        rc, last = self.run_cli('run', self.repo, '--level', 'V0', '--mods', 'nope', '--base', 'basebr')
        self.assertEqual(last.rsplit(' ', 1)[1], 'BLOCKED')

    def test_v3_without_base_or_snapshot_blocked(self):
        write(os.path.join(self.repo, 'm_a', 'models.py'), 'x = 1\n')
        rc, last = self.run_cli('run', self.repo, '--level', 'V3', '--mods', 'm_a')
        self.assertEqual(last.rsplit(' ', 1)[1], 'BLOCKED')
        data = json.load(open(last.rsplit(' ', 1)[0][:-3] + '.json', encoding='utf-8'))
        self.assertIn('V3 需要基準', data['blocked_reasons'][0])
        rc, last = self.run_cli('run', self.repo, '--level', 'V4', '--mods', 'm_a')
        data = json.load(open(last.rsplit(' ', 1)[0][:-3] + '.json', encoding='utf-8'))
        self.assertIn('V4 需要正式機快照', data['blocked_reasons'][0])


if __name__ == '__main__':
    unittest.main()
