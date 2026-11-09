"""opt_patch.py 單元測試：正式機連線、git、pt-verify 一律用假的——測試裡不會真的 apply 到 repo、不會跑驗證、不會推送。

執行：cd tools/knowledge && python3 -m unittest discover -s tests -v
"""
import json
import io
import os
import shutil
import sys
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import opt_patch as T  # noqa: E402


class FakeProd:
    def __init__(self, records=None, modules=None, dry_run=False):
        self.records = records or {}
        self.modules = modules or {}
        self.writes = []
        self.dry_run = dry_run

    def ro(self, model, method, *args, **kw):
        if method == 'read':
            return [self.records[(model, i)] for i in args[0] if (model, i) in self.records]
        if method == 'search_read' and model == 'ir.module.module':
            names = args[0][0][2]
            return [{'name': n, 'latest_version': self.modules[n]} for n in names if n in self.modules]
        if method == 'search_read' and model == T.OVERRIDE:
            return [dict(v) for (m, _i), v in sorted(self.records.items()) if m == T.OVERRIDE
                    and v.get('enabled') and not v.get('retired')]
        if method == 'search_read':
            return []
        raise AssertionError('不該呼叫 %s.%s' % (model, method))

    def rw(self, model, method, *args, **kw):
        assert method in WHITELIST, method
        self.writes.append((model, method, args))
        if self.dry_run:
            return None
        return 'ok'


class FakeShell:
    """記下每個指令；git apply／commit 等照設定回應；pt-verify 照 verdicts 回報告行。★ push 只記錄，不執行。"""

    def __init__(self, tmp, verdicts=('PASS', 'PASS'), apply_ok=True, sha='abc1234def', ancestor=True,
                 manifest_version='18.0.3.36.1', base_version='18.0.3.36.0', changed=None, stderr_tail=''):
        self.tmp, self.verdicts, self.apply_ok, self.sha = tmp, list(verdicts), apply_ok, sha
        self.ancestor, self.manifest_version, self.base_version = ancestor, manifest_version, base_version
        self.changed = changed or ['dobtor_corpaas_knowledge/models/x.py', 'docs/decisions.tsv']
        self.stderr_tail = stderr_tail
        self.files = {'dobtor_corpaas_knowledge/models/x.py': 'a = 2\n'}
        self.calls = []

    def run(self, cmd, cwd=None, check=True, timeout=None):
        self.calls.append(cmd)
        if cmd[0] == 'git':
            sub = cmd[3]
            if sub == 'worktree':
                path = cmd[cmd.index('--no-track') + 1]
                src = os.path.join(self.tmp, 'repo')
                shutil.copytree(src, path)
                return 0, ''
            if sub == 'rev-parse' and '--verify' in cmd:
                return 1, ''
            if sub == 'rev-parse':
                return 0, self.sha + '\n'
            if sub == 'apply':
                return (0, '') if self.apply_ok else (1, 'error: patch failed')
            if sub == 'merge-base':
                return (0, '') if self.ancestor else (1, '')
            if sub == 'diff' and '--name-only' in cmd:
                return 0, '\n'.join(self.changed) + '\n'
            if sub == 'show':
                ref, path = cmd[4].split(':', 1)
                if not path.endswith('__manifest__.py'):
                    return (0, self.files[path]) if path in self.files else (128, 'fatal: path does not exist')
                ver = self.base_version if (ref == T.BASE_REF or ref.endswith('^')) else self.manifest_version
                return 0, "{'name': 'x', 'version': '%s'}" % ver
            if sub == 'diff':
                return 0, 'diff --git a/x b/x\n'
            return 0, ''
        if cmd[0] == T.PT_VERIFY and cmd[1] == 'snapshot':
            return 0, '快照完成'
        if cmd[0] == T.PT_VERIFY:
            lvl = cmd[cmd.index('--level') + 1]
            verdict = self.verdicts.pop(0)
            rep = os.path.join(self.tmp, '%s.md' % lvl)
            with open(rep[:-3] + '.json', 'w') as fh:
                json.dump({'sha': self.sha, 'verdict': verdict}, fh)
            return (0 if verdict == 'PASS' else 1), 'log...\n%s %s\n%s' % (rep, verdict, self.stderr_tail)
        raise AssertionError('不認得的指令：%s' % cmd)

    def pushes(self):
        return [c for c in self.calls if c[0] == 'git' and c[3] == 'push']

    def levels(self):
        return [c[c.index('--level') + 1] for c in self.calls if c[0] == T.PT_VERIFY]


WHITELIST = {'action_kb_patch_verified', 'action_kb_patch_pushed', 'action_kb_patch_merged',
             'action_kb_release_exported', 'action_kb_release_check',
             'action_kb_patch_local_start', 'action_kb_patch_local_result'}


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        repo = os.path.join(self.tmp, 'repo')
        os.makedirs(os.path.join(repo, T.CORE, 'services'))
        os.makedirs(os.path.join(repo, 'docs'))
        with open(os.path.join(repo, T.MERGED_JSON), 'w') as fh:
            json.dump({'note': 'x', 'rules': []}, fh)
        with open(os.path.join(repo, T.CORE, '__manifest__.py'), 'w') as fh:
            fh.write("{\n    'name': 'k',\n    'version': '18.0.3.36.0',\n}\n")
        with open(os.path.join(repo, T.DECISIONS), 'w') as fh:
            fh.write('id\tdate\n D\nD-KN-088\t2026-11-09\tx\n')
        self.patches = [mock.patch.object(T, 'WORKTREES', os.path.join(self.tmp, 'wt')),
                        mock.patch.object(T, 'CACHE', os.path.join(self.tmp, 'cache')),
                        mock.patch.object(T, 'KNOWLEDGE', repo),
                        mock.patch.object(T, 'SNAP_ROOT', os.path.join(self.tmp, 'prod'))]
        self.snap = os.path.join(self.tmp, 'prod', T.TARGET, '20261109', 'src', 'ProductivityTools')
        self.prod_file('dobtor_corpaas_knowledge/models/x.py', 'a = 2\n')
        for p in self.patches:
            p.start()
        os.makedirs(os.path.join(self.tmp, 'wt'))

    def prod_file(self, rel, text):
        path = os.path.join(self.snap, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as fh:
            fh.write(text)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestVerify(Base):

    def _prod(self, state='to_verify'):
        return FakeProd({(T.PROPOSAL, 5): {'id': 5, 'state': state, 'layer': '3', 'name': '提案 #5',
                                           'patch_diff': 'diff --git a/x b/x', 'patch_base_commit': '242f56d'}})

    def test_happy_path_push_only_opt_branch(self):
        prod, sh = self._prod(), FakeShell(self.tmp)
        self.assertEqual(T.cmd_verify(prod, sh, 5, reviewed=True), 'pushed')
        self.assertEqual(sh.levels(), ['V1', 'V2'])
        v2 = [c for c in sh.calls if c[0] == T.PT_VERIFY][1]
        self.assertIn('--target', v2, 'V2 帶正式機目標取整組')
        add = [c for c in sh.calls if c[3] == 'worktree'][0]
        self.assertEqual(add[-3:], ['-b', 'opt/5', T.BASE_REF])
        self.assertEqual(sh.pushes(), [['git', '-C', os.path.join(self.tmp, 'wt', 'opt-5'), 'push', 'origin',
                                        'abc1234def:refs/heads/opt/5']])
        self.assertEqual([w[1] for w in prod.writes], ['action_kb_patch_verified', 'action_kb_patch_pushed'])
        payload = prod.writes[0][2][1]
        self.assertEqual((payload['v1']['verdict'], payload['v2']['verdict']), ('PASS', 'PASS'))
        self.assertTrue(payload['v1']['report'].endswith('V1.md'))
        self.assertEqual(prod.writes[1][2][1], {'branch': 'opt/5', 'commit': 'abc1234def'})
        commit = [c for c in sh.calls if c[3] == 'commit'][0]
        self.assertNotIn('Co-Authored-By', commit[-1])

    def test_v1_fail_no_v2_no_push(self):
        prod, sh = self._prod(), FakeShell(self.tmp, verdicts=['FAIL'])
        self.assertEqual(T.cmd_verify(prod, sh, 5, reviewed=True), 'failed')
        self.assertEqual(sh.levels(), ['V1'])
        self.assertEqual(sh.pushes(), [])
        self.assertEqual([w[1] for w in prod.writes], ['action_kb_patch_verified'])
        self.assertEqual(prod.writes[0][2][1]['v2']['verdict'], 'BLOCKED')

    def test_v2_fail_no_push(self):
        prod, sh = self._prod(), FakeShell(self.tmp, verdicts=['PASS', 'FAIL'])
        self.assertEqual(T.cmd_verify(prod, sh, 5, reviewed=True), 'failed')
        self.assertEqual(sh.pushes(), [])

    def test_sha_mismatch_is_fail(self):
        prod, sh = self._prod(), FakeShell(self.tmp)
        real = sh.run

        def run(cmd, **kw):
            code, out = real(cmd, **kw)
            if cmd[0] == T.PT_VERIFY:
                rep = out.strip().splitlines()[-1].rsplit(' ', 1)[0]
                with open(rep[:-3] + '.json', 'w') as fh:
                    json.dump({'sha': 'ffff000'}, fh)
            return code, out
        sh.run = run
        self.assertEqual(T.cmd_verify(prod, sh, 5, reviewed=True), 'failed')
        self.assertIn('不等於 HEAD', prod.writes[0][2][1]['note'])
        self.assertEqual(sh.pushes(), [])

    def test_apply_fail_blocked_writeback(self):
        prod, sh = self._prod(), FakeShell(self.tmp, apply_ok=False)
        self.assertEqual(T.cmd_verify(prod, sh, 5, reviewed=True), 'apply_failed')
        self.assertEqual(sh.levels(), [])
        self.assertEqual(sh.pushes(), [])
        self.assertIn('git apply 失敗', prod.writes[0][2][1]['note'])

    def test_no_push_and_dry_run(self):
        prod, sh = self._prod(), FakeShell(self.tmp)
        self.assertEqual(T.cmd_verify(prod, sh, 5, push=False, reviewed=True), 'passed')
        self.assertEqual(sh.pushes(), [])
        self.assertEqual([w[1] for w in prod.writes], ['action_kb_patch_verified'])
        shutil.rmtree(os.path.join(self.tmp, 'wt', 'opt-5'))
        prod, sh = FakeProd(self._prod().records, dry_run=True), FakeShell(self.tmp)
        self.assertEqual(T.cmd_verify(prod, sh, 5, reviewed=True), 'passed')
        self.assertEqual(sh.pushes(), [], 'dry-run 不推')

    def test_f9_fail_with_stderr_tail(self):
        """審查 F9：FAIL 時輸出後面接 stderr，仍要認出 FAIL 與報告路徑（不能記成 BLOCKED）。"""
        prod = self._prod()
        sh = FakeShell(self.tmp, verdicts=['FAIL'], stderr_tail='Traceback...\nsome stderr line\n')
        T.cmd_verify(prod, sh, 5, reviewed=True)
        v1 = prod.writes[0][2][1]['v1']
        self.assertEqual(v1['verdict'], 'FAIL')
        self.assertTrue(v1['report'].endswith('V1.md'))

    def test_f7_verify_requires_version_bump(self):
        """審查 F7：修補沒有升改到模組的版號 → 不跑驗證、寫回 FAIL、不推。"""
        prod, sh = self._prod(), FakeShell(self.tmp, manifest_version='18.0.3.36.0')
        self.assertEqual(T.cmd_verify(prod, sh, 5, reviewed=True), 'failed')
        self.assertEqual((sh.levels(), sh.pushes()), ([], []))
        self.assertIn('版號', prod.writes[0][2][1]['note'])
        self.assertEqual(prod.writes[0][2][1]['v1']['verdict'], 'FAIL')

    def test_f13_push_after_no_push(self):
        """審查 F13：--no-push 之後可用 push 子指令再推（HEAD 要等於驗證的 commit）。"""
        prod, sh = self._prod(), FakeShell(self.tmp)
        T.cmd_verify(prod, sh, 5, push=False, reviewed=True)
        rec = prod.records[(T.PROPOSAL, 5)]
        rec.update(verify_v1_verdict='PASS', verify_v2_verdict='PASS', verify_sha='abc1234def')
        self.assertEqual(T.cmd_push(prod, sh, 5), 'pushed')
        self.assertEqual(sh.pushes()[0][-1], 'abc1234def:refs/heads/opt/5')
        self.assertEqual(prod.writes[-1][1], 'action_kb_patch_pushed')
        rec['verify_sha'] = 'ffff999'
        with self.assertRaises(T.ToolError):
            T.cmd_push(prod, sh, 5)
        rec.update(verify_sha='abc1234def', verify_v2_verdict='FAIL')
        with self.assertRaises(T.ToolError):
            T.cmd_push(prod, sh, 5)
        self.assertEqual(len(sh.pushes()), 1)

    def test_wrong_state_refused(self):
        with self.assertRaises(T.ToolError):
            T.cmd_verify(self._prod('patching'), FakeShell(self.tmp), 5)

    def test_existing_worktree_refused(self):
        os.makedirs(os.path.join(self.tmp, 'wt', 'opt-5'))
        with self.assertRaises(T.ToolError):
            T.cmd_verify(self._prod(), FakeShell(self.tmp), 5, reviewed=True)

    def test_push_guard(self):
        sh = FakeShell(self.tmp)
        for bad in ('dev-18.0', 'main', 'opt/../dev-18.0', 'refs/heads/opt/1', 'opt/', 'feat/x'):
            with self.assertRaises(T.ToolError, msg=bad):
                T.push_branch(sh, '/r', bad, 'abc1234')
        with self.assertRaises(T.ToolError):
            T.push_branch(sh, '/r', 'opt/5', '')
        self.assertEqual(sh.pushes(), [])

    def test_g3_push_uses_verified_sha(self):
        """審查 G3：push 子指令推的是驗證過的 sha（refspec <verify_sha>:refs/heads/opt/N），不是本機分支 ref。"""
        prod, sh = self._prod(), FakeShell(self.tmp)
        T.cmd_verify(prod, sh, 5, push=False, reviewed=True)
        prod.records[(T.PROPOSAL, 5)].update(verify_v1_verdict='PASS', verify_v2_verdict='PASS',
                                             verify_sha='abc1234def')
        T.cmd_push(prod, sh, 5)
        self.assertEqual(sh.pushes()[-1][-1], 'abc1234def:refs/heads/opt/5')
        self.assertEqual(prod.writes[-1][2][1]['commit'], 'abc1234def')


class TestRelease(Base):

    EXPORT = {'release_id': 3, 'db_uuid': 'uuid-1', 'rules': [
        {'override_id': 1, 'hook': 'text.tech_label', 'group': 'map', 'action': 'add', 'key': 'lbl_waived',
         'value': {'value': 'waived', 'label': '已略過'}, 'scope': 'package', 'package_id': 19,
         'package_name': '財務會計', 'examples_pos': [], 'examples_neg': [], 'proposal_id': 7, 'note': ''},
        {'override_id': 2, 'hook': 'claim.negation_words', 'group': 'except', 'action': 'add', 'key': 'x',
         'value': '類別', 'scope': 'global', 'package_id': None, 'examples_pos': ['類別'], 'examples_neg': ['別']},
        {'override_id': 3, 'hook': 'claim.not_a_rule', 'group': 'screen', 'action': 'disable', 'key': 'screen_3',
         'value': None, 'scope': 'global'},
    ]}

    OVERRIDES = {
        1: {'id': 1, 'enabled': True, 'retired': False, 'hook': 'text.tech_label', 'group': 'map', 'action': 'add',
            'rule_key': 'lbl_waived', 'value': '{"label": "已略過", "value": "waived"}', 'scope': 'package',
            'package_id': [19, '財務會計']},
        2: {'id': 2, 'enabled': True, 'retired': False, 'hook': 'claim.negation_words', 'group': 'except',
            'action': 'add', 'rule_key': 'x', 'value': '類別', 'scope': 'global', 'package_id': False},
        3: {'id': 3, 'enabled': True, 'retired': False, 'hook': 'claim.not_a_rule', 'group': False,
            'action': 'disable', 'rule_key': 'screen_3', 'value': False, 'scope': 'global', 'package_id': False},
    }

    def _prod(self, overrides=None):
        recs = {(T.RELEASE, 3): {'id': 3, 'state': 'draft', 'name': '並版',
                                 'export_json': json.dumps(self.EXPORT, ensure_ascii=False)}}
        for k, v in (self.OVERRIDES if overrides is None else overrides).items():
            recs[(T.OVERRIDE, k)] = dict(v)
        return FakeProd(recs)

    def test_release_writes_table_version_decision_and_pushes(self):
        prod, sh = self._prod(), FakeShell(self.tmp)
        self.assertEqual(T.cmd_release(prod, sh, 3, today='2026-11-09'), 'pushed')
        wt = os.path.join(self.tmp, 'wt', 'opt-release-20261109')
        with open(os.path.join(wt, T.MERGED_JSON)) as fh:
            table = json.load(fh)
        self.assertEqual(len(table['rules']), 3)
        pkg = table['rules'][0]
        self.assertEqual((pkg['scope'], pkg['package_id'], pkg['db_uuid'], pkg['release_id']), ('package', 19, 'uuid-1', 3))
        self.assertNotIn('db_uuid', table['rules'][1], '全站條目不帶資料庫識別')
        self.assertNotIn('value', table['rules'][2], '停用不帶值')
        with open(os.path.join(wt, T.CORE, '__manifest__.py')) as fh:
            self.assertIn("'version': '18.0.3.36.1'", fh.read())
        with open(os.path.join(wt, T.DECISIONS)) as fh:
            last = fh.read().splitlines()[-1].split('\t')
        self.assertEqual((last[0], len(last), last[8]), ('D-KN-089', 11, 'active'))
        self.assertEqual(sh.pushes()[0][-1], 'abc1234def:refs/heads/opt/release-20261109')
        w = prod.writes[-1]
        self.assertEqual((w[1], w[2][1]['branch'], w[2][1]['pushed']), ('action_kb_release_exported',
                                                                         'opt/release-20261109', True))

    def test_f8_recheck_drops_disabled_deleted_changed(self):
        """D-KN-092（使用者決定 F8）：凍結後被停用、刪除或內容改過的覆寫從這次並版拿掉；只少不多。"""
        ovs = {k: dict(v) for k, v in self.OVERRIDES.items()}
        ovs[1]['enabled'] = False
        ovs[2]['value'] = '類別們'
        prod, sh = self._prod(ovs), FakeShell(self.tmp)
        T.cmd_release(prod, sh, 3, today='2026-11-09')
        wt = os.path.join(self.tmp, 'wt', 'opt-release-20261109')
        with open(os.path.join(wt, T.MERGED_JSON)) as fh:
            table = json.load(fh)
        self.assertEqual([r['key'] for r in table['rules']], ['screen_3'])
        dropped = prod.writes[-1][2][1]['dropped']
        self.assertEqual({d['override_id']: d['reason'] for d in dropped}, {1: '已停用', 2: '內容和凍結時不同'})
        with open(os.path.join(wt, T.DECISIONS)) as fh:
            self.assertIn('重查拿掉', fh.read().splitlines()[-1])
        # 全部拿掉（含刪除）：不開分支，寫回取消
        shutil.rmtree(os.path.join(self.tmp, 'wt'))
        os.makedirs(os.path.join(self.tmp, 'wt'))
        prod, sh = self._prod({}), FakeShell(self.tmp)
        self.assertEqual(T.cmd_release(prod, sh, 3, today='2026-11-09'), 'cancelled')
        self.assertEqual({d['reason'] for d in prod.writes[-1][2][1]['dropped']}, {'已刪除'})
        self.assertEqual(sh.calls, [], '沒開 worktree、沒推')

    def test_g2_same_key_unmerged_override_blocks(self):
        """審查 G2：參數後蓋前。全站 A＝0.3（順序 10）與 B＝0.5（順序 20）同代碼，原本結果是 0.5；若 B 凍結後改過
        內容被拿掉、A 照並，部署後 A 變成並版表條目排到最前，B 反而蓋過 A——先後跟著變。同代碼還有未並版覆寫時
        A 這次也不並、寫進說明；凍結後才開的同代碼覆寫也一樣擋。"""
        exp = {'release_id': 3, 'db_uuid': 'u', 'rules': [
            {'override_id': 11, 'hook': 'review.auto_approve', 'group': 'param', 'action': 'add',
             'key': 'minor_budget_ratio', 'value': 0.3, 'scope': 'global'},
            {'override_id': 12, 'hook': 'review.auto_approve', 'group': 'param', 'action': 'add',
             'key': 'minor_budget_ratio', 'value': 0.5, 'scope': 'global'},
            {'override_id': 13, 'hook': 'review.auto_approve', 'group': 'param', 'action': 'add',
             'key': 'block_auto_approve', 'value': False, 'scope': 'global'}]}
        base = {'enabled': True, 'retired': False, 'hook': 'review.auto_approve', 'group': 'param', 'action': 'add',
                'scope': 'global', 'package_id': False}
        ovs = {11: dict(base, id=11, rule_key='minor_budget_ratio', value='0.3'),
               12: dict(base, id=12, rule_key='minor_budget_ratio', value='0.7'),   # 凍結後改過
               13: dict(base, id=13, rule_key='block_auto_approve', value='false')}
        prod = FakeProd({(T.OVERRIDE, k): v for k, v in ovs.items()})
        kept, dropped = T.recheck_rules(prod, exp)
        self.assertEqual([r['override_id'] for r in kept['rules']], [13])
        why = {d['override_id']: d['reason'] for d in dropped}
        self.assertEqual(why[12], '內容和凍結時不同')
        self.assertIn('同代碼還有未並版的覆寫 #12', why[11])
        # 凍結後新開的同代碼覆寫（不在匯出裡）
        ovs[12]['value'] = '0.5'
        ovs[14] = dict(base, id=14, rule_key='block_auto_approve', value='true')
        prod = FakeProd({(T.OVERRIDE, k): v for k, v in ovs.items()})
        kept, dropped = T.recheck_rules(prod, exp)
        self.assertEqual([r['override_id'] for r in kept['rules']], [11, 12])
        self.assertIn('#14', dropped[0]['reason'])

    def test_recheck_same_content_kept(self):
        kept, dropped = T.recheck_rules(self._prod(), self.EXPORT)
        self.assertEqual((len(kept['rules']), dropped), (3, []))

    def test_merge_rules_dedupes(self):
        cur, n = T.merge_rules({'rules': []}, self.EXPORT)
        cur2, n2 = T.merge_rules(cur, self.EXPORT)
        self.assertEqual((n, n2, len(cur2['rules'])), (3, 0, 3))

    def test_release_no_verify_no_push(self):
        prod, sh = self._prod(), FakeShell(self.tmp)
        self.assertEqual(T.cmd_release(prod, sh, 3, verify=False, today='2026-11-09'), 'exported')
        self.assertEqual((sh.levels(), sh.pushes()), ([], []))
        self.assertFalse(prod.writes[-1][2][1]['pushed'])

    def test_bump_and_decision_id(self):
        self.assertEqual(T.bump_version("'version': '18.0.3.36.9',")[1:], ('18.0.3.36.9', '18.0.3.36.10'))
        self.assertEqual(T.next_decision_id('D-KN-007\tx\nD-KN-120\ty\n'), 'D-KN-121')


class TestMerged(Base):

    def _prod(self, prod_version):
        return FakeProd({(T.PROPOSAL, 5): {'id': 5, 'state': 'to_merge', 'patch_branch': 'opt/5',
                                           'patch_commit': 'abc1234'},
                         (T.RELEASE, 3): {'id': 3, 'state': 'to_merge', 'branch': 'opt/release-1',
                                          'commit_sha': 'r1'}},
                        modules={'dobtor_corpaas_knowledge': prod_version})

    def test_merged_and_deployed(self):
        prod, sh = self._prod('18.0.3.36.1'), FakeShell(self.tmp)
        self.assertEqual(T.cmd_merged(prod, sh, '5'), 'merged')
        self.assertEqual(prod.writes[0][1], 'action_kb_patch_merged')
        self.assertEqual(sh.pushes(), [])
        self.assertEqual(T.cmd_merged(prod, sh, 'release:3'), 'merged')
        self.assertEqual(prod.writes[1][1], 'action_kb_release_check')

    def test_f7_merged_requires_bump(self):
        """審查 F7：分支沒有升版號 → 無法確認部署，不標已並版。"""
        prod, sh = self._prod('18.0.3.36.1'), FakeShell(self.tmp, manifest_version='18.0.3.36.0')
        self.assertEqual(T.cmd_merged(prod, sh, '5'), 'no_bump')
        prod, sh = self._prod('18.0.3.36.1'), FakeShell(self.tmp, changed=['docs/decisions.tsv'])
        self.assertEqual(T.cmd_merged(prod, sh, '5'), 'no_bump')
        self.assertEqual(prod.writes, [])

    def test_g1_same_version_other_branch_deployed(self):
        """審查 G1：兩條分支升到同版號，正式機部署的是另一條 → 版號一樣但程式不同，不標已並版。"""
        prod, sh = self._prod('18.0.3.36.1'), FakeShell(self.tmp)
        sh.files['dobtor_corpaas_knowledge/models/x.py'] = 'a = 3  # 這條分支的修法\n'
        self.assertEqual(T.cmd_merged(prod, sh, '5'), 'not_deployed')
        self.assertEqual(prod.writes, [])
        self.assertIn([T.PT_VERIFY, 'snapshot', T.TARGET], sh.calls, '先跑 pt-verify snapshot')
        # 這條分支刪掉的檔案，正式機還在 → 也算沒部署
        sh = FakeShell(self.tmp, changed=['dobtor_corpaas_knowledge/models/x.py', 'dobtor_corpaas_knowledge/old.py'])
        self.prod_file('dobtor_corpaas_knowledge/old.py', 'x = 1\n')
        self.assertEqual(T.cmd_merged(prod, sh, '5'), 'not_deployed')
        # 正式機沒有這個模組
        sh = FakeShell(self.tmp, changed=['dobtor_corpaas_knowledge_marketing/a.py'])
        sh.files = {'dobtor_corpaas_knowledge_marketing/a.py': 'y\n'}
        prod.modules['dobtor_corpaas_knowledge_marketing'] = '18.0.3.36.1'
        self.assertEqual(T.cmd_merged(prod, sh, '5'), 'not_deployed')
        self.assertEqual(prod.writes, [])

    def test_f10_release_already_merged(self):
        prod = self._prod('18.0.3.36.1')
        prod.records[(T.RELEASE, 3)]['state'] = 'merged'
        self.assertEqual(T.cmd_merged(prod, FakeShell(self.tmp), 'release:3'), 'merged')
        self.assertEqual(prod.writes, [])

    def test_f12_full_version_string(self):
        prod = self._prod('18.0.3.36.1')
        prod.modules['dobtor_corpaas_knowledge_manual'] = '18.0.3.36.1'
        sh = FakeShell(self.tmp, changed=['dobtor_corpaas_knowledge/a.py', 'dobtor_corpaas_knowledge_manual/b.py'])
        sh.files = {'dobtor_corpaas_knowledge/a.py': 'a\n', 'dobtor_corpaas_knowledge_manual/b.py': 'b\n'}
        self.prod_file('dobtor_corpaas_knowledge/a.py', 'a\n')
        self.prod_file('dobtor_corpaas_knowledge_manual/b.py', 'b\n')
        T.cmd_merged(prod, sh, '5')
        ver = prod.writes[0][2][1]['version']
        self.assertEqual(ver, 'dobtor_corpaas_knowledge 18.0.3.36.1、dobtor_corpaas_knowledge_manual 18.0.3.36.1')

    def test_not_deployed_or_not_merged(self):
        prod, sh = self._prod('18.0.3.36.0'), FakeShell(self.tmp)
        self.assertEqual(T.cmd_merged(prod, sh, '5'), 'not_deployed')
        prod, sh = self._prod('18.0.3.36.1'), FakeShell(self.tmp, ancestor=False)
        self.assertEqual(T.cmd_merged(prod, sh, '5'), 'not_merged')
        self.assertEqual(prod.writes, [])
        self.assertEqual(T.cmd_merged(prod, sh, '5', force=True), 'merged', 'squash 合併：人確認後 --force')


class GenProd(FakeProd):
    """generate 用：kb_patch_brief、候選查詢、本機修補的寫回（含權杖）。"""

    def __init__(self, briefs=None, server_brief=True, candidates=(), start_error=None, **kw):
        super().__init__(**kw)
        self.briefs = briefs or {}
        self.server_brief = server_brief
        self.candidates = list(candidates)
        self.domains = []
        self.start_error = start_error

    def ro(self, model, method, *args, **kw):
        if method == 'kb_patch_brief':
            if not self.server_brief:
                raise RuntimeError("AttributeError: The method 'kb_patch_brief' does not exist on the model")
            return [self.briefs[i] for i in args[0] if i in self.briefs]
        if method == 'search_read' and model == T.PROPOSAL:
            self.domains.append(args[0])
            return [{'id': i} for i in self.candidates]
        return super().ro(model, method, *args, **kw)

    def rw(self, model, method, *args, **kw):
        if method == 'action_kb_patch_local_start' and self.start_error:
            raise self.start_error
        super().rw(model, method, *args, **kw)
        if self.dry_run:
            return None
        if method == 'action_kb_patch_local_start':
            return {'state': 'patch_local', 'prompt': '伺服器重組的備料 #%s' % args[0][0], 'decisions': ['D-KN-008'],
                    'token': 4}
        if method == 'action_kb_patch_local_result':
            return 'to_verify' if args[1].get('ok') else 'patch_failed'
        return 'ok'

    def methods(self):
        return [w[1] for w in self.writes]

    def result(self):
        return [w[2][1] for w in self.writes if w[1] == 'action_kb_patch_local_result'][-1]


class GenShell(FakeShell):
    """status 依路徑回應；worktree remove／branch -D／ls-remote 照設定；python 子程序只記錄。"""

    def __init__(self, tmp, status=None, pre_status='', has_branch=False, remote_has=False, **kw):
        super().__init__(tmp, **kw)
        self.status = status if status is not None else (
            ' M dobtor_corpaas_knowledge/models/x.py\n?? dobtor_corpaas_knowledge/tests/test_x.py\n'
            '?? report.md\n?? dobtor_corpaas_knowledge/__pycache__/x.cpython-39.pyc\n')
        self.pre_status, self.has_branch, self.remote_has = pre_status, has_branch, remote_has
        self.opened = False

    def run(self, cmd, cwd=None, check=True, timeout=None):
        if cmd[0] == sys.executable:
            self.calls.append(cmd)
            return 0, ''
        if cmd[0] == 'git':
            sub = cmd[3]
            if sub == 'status':
                self.calls.append(cmd)
                return 0, self.status if self.opened else self.pre_status
            if sub == 'worktree' and cmd[4] == 'remove':
                self.calls.append(cmd)
                shutil.rmtree(cmd[-1], ignore_errors=True)
                return 0, ''
            if sub == 'worktree':
                self.opened = True
            if sub == 'rev-parse' and '--verify' in cmd:
                self.calls.append(cmd)
                return (0, '') if self.has_branch else (1, '')
            if sub == 'branch':
                self.calls.append(cmd)
                self.has_branch = False
                return 0, ''
            if sub == 'ls-remote':
                self.calls.append(cmd)
                return 0, ('abc\trefs/heads/opt/5\n' if self.remote_has else '')
        return super().run(cmd, cwd=cwd, check=check, timeout=timeout)

    def git_sub(self, sub):
        return [c for c in self.calls if c[0] == 'git' and c[3] == sub]


class FakeClaude:
    """★ 不真的跑 claude：記下呼叫、在 worktree 寫幾個檔案。"""

    def __init__(self, ok=True, files=None, report='# 根因\n', raises=None):
        self.ok, self.report, self.raises = ok, report, raises
        self.files = files if files is not None else {'dobtor_corpaas_knowledge/models/x.py': 'a = 2\n',
                                                      'dobtor_corpaas_knowledge/tests/test_x.py': 'b = 1\n'}
        self.calls = []

    def run(self, prompt, cwd, out_path, timeout=None, max_turns=None, model=None):
        self.calls.append({'prompt': prompt, 'cwd': cwd, 'timeout': timeout, 'max_turns': max_turns, 'model': model})
        for rel, text in self.files.items():
            os.makedirs(os.path.dirname(os.path.join(cwd, rel)), exist_ok=True)
            with open(os.path.join(cwd, rel), 'w') as fh:
                fh.write(text)
        if self.report:
            with open(os.path.join(cwd, 'report.md'), 'w') as fh:
                fh.write(self.report)
        if self.raises:
            raise self.raises
        if not self.ok:
            return {'ok': False, 'note': 'claude 沒有正常結束（error_max_turns）', 'turns': 80}
        return {'ok': True, 'note': '', 'turns': 12, 'cost_usd': 1.5, 'duration_s': 600, 'subtype': 'success'}


class GenBase(Base):

    def _brief(self, pid=5, blocker=''):
        return {'id': pid, 'name': '提案 #%s' % pid, 'state': 'runner_wait', 'blocker': blocker, 'local_attempts': 0,
                'prompt': '修補指示 #%s' % pid, 'decisions': ['D-KN-008'],
                'evidence': {'incident': True, 'gaps': 1, 'affected': 2}}

    def _prod(self, **kw):
        prod = GenProd(briefs={5: self._brief()}, **kw)
        prod.records[(T.PROPOSAL, 5)] = {'id': 5, 'state': 'to_verify', 'layer': '3', 'name': '提案 #5',
                                         'patch_diff': 'diff --git a/x b/x', 'patch_base_commit': 'abc'}
        return prod

    def wt(self, pid=5):
        return os.path.join(self.tmp, 'wt', 'opt-%s' % pid)


class TestGenerate(GenBase):

    def test_generate_stops_before_running_ai_code(self):
        """D-KN-104（審查 A2）：產生修補、commit、寫回待驗證就停——不跑 pt-verify、不推。"""
        prod, sh, cl = self._prod(), GenShell(self.tmp), FakeClaude()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(T.cmd_generate(prod, sh, cl, 5), 'generated')
        self.assertEqual(prod.methods(), ['action_kb_patch_local_start', 'action_kb_patch_local_result'])
        self.assertEqual((sh.levels(), sh.pushes()), ([], []), '沒執行 AI 寫的程式、沒推')
        self.assertIn('verify 5 --reviewed', buf.getvalue())
        self.assertIn('還沒執行任何 AI 寫的程式', buf.getvalue())
        call = cl.calls[0]
        self.assertEqual(call['cwd'], self.wt(), 'claude 只在 worktree 裡跑')
        self.assertIn('伺服器重組的備料 #5', call['prompt'], '用開始時伺服器重組的備料')
        self.assertIn('分支 opt/5', call['prompt'])
        res = prod.result()
        self.assertTrue(res['ok'])
        self.assertEqual(res['token'], 4, '審查 A5：寫回帶開始時的權杖')
        self.assertEqual(res['report'], '# 根因\n', 'report.md 收走寫回')
        self.assertEqual(res['meta']['turns'], 12)
        add = sh.git_sub('add')[0]
        self.assertNotIn('report.md', add, 'report.md 不進 commit')
        self.assertFalse([x for x in add if 'pycache' in x])
        self.assertIn('dobtor_corpaas_knowledge/tests/test_x.py', add)
        self.assertFalse(os.path.exists(os.path.join(self.wt(), 'report.md')))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'cache', '5', 'report.md')))

    def test_claude_fail_writes_failed_with_report_and_cleans(self):
        prod, sh = self._prod(), GenShell(self.tmp)
        self.assertEqual(T.cmd_generate(prod, sh, FakeClaude(ok=False, report='# 和 D-KN-088 衝突'), 5), 'failed')
        self.assertEqual(prod.methods(), ['action_kb_patch_local_start', 'action_kb_patch_local_result'])
        res = prod.result()
        self.assertFalse(res['ok'])
        self.assertIn('error_max_turns', res['note'])
        self.assertEqual((res['token'], res['report']), (4, '# 和 D-KN-088 衝突'), '審查 A6：失敗也帶 report')
        self.assertEqual((sh.git_sub('commit'), sh.pushes(), sh.levels()), ([], [], []))
        # 審查 A4：清掉這次的 worktree 與分支
        self.assertFalse(os.path.exists(self.wt()))
        self.assertTrue(sh.git_sub('branch'))

    def test_changes_outside_modules_rejected(self):
        prod = self._prod()
        sh = GenShell(self.tmp, status=' M dobtor_corpaas_knowledge/models/x.py\n M docs/decisions.tsv\n'
                                       '?? .github/workflows/ci.yml\n')
        self.assertEqual(T.cmd_generate(prod, sh, FakeClaude(), 5), 'failed')
        self.assertIn('docs/decisions.tsv', prod.result()['note'])
        self.assertEqual((sh.git_sub('commit'), sh.pushes()), ([], []))

    def test_no_changes_rejected(self):
        prod, sh = self._prod(), GenShell(self.tmp, status='?? report.md\n')
        self.assertEqual(T.cmd_generate(prod, sh, FakeClaude(files={}), 5), 'failed')
        self.assertIn('沒有改任何模組檔案', prod.result()['note'])

    def test_dry_run_reads_only(self):
        prod, sh, cl = self._prod(dry_run=True), GenShell(self.tmp), FakeClaude()
        self.assertEqual(T.cmd_generate(prod, sh, cl, 5), 'dry_run')
        self.assertEqual((prod.writes, cl.calls, sh.git_sub('worktree')), ([], [], []))
        with open(os.path.join(self.tmp, 'cache', '5', 'prompt.md')) as fh:
            text = fh.read()
        self.assertIn('修補指示 #5', text)
        self.assertIn('分支 opt/5', text)

    def test_blocker_skipped(self):
        prod = GenProd(briefs={5: self._brief(blocker='目前不能修補（to_merge）')})
        self.assertEqual(T.cmd_generate(prod, GenShell(self.tmp), FakeClaude(), 5), 'skipped')
        self.assertEqual(prod.writes, [])

    def test_a3_interrupt_writes_failed_then_reraises(self):
        prod, sh = self._prod(), GenShell(self.tmp)
        with self.assertRaises(KeyboardInterrupt):
            T.cmd_generate(prod, sh, FakeClaude(raises=KeyboardInterrupt()), 5)
        res = prod.result()
        self.assertFalse(res['ok'])
        self.assertIn('中斷', res['note'])
        self.assertFalse(os.path.exists(self.wt()), '中斷也清掉 worktree')

    def test_a3_batch_continues_after_rpc_error(self):
        prod = GenProd(briefs={5: self._brief(5), 7: self._brief(7)}, candidates=[5, 7],
                       start_error=RuntimeError('RPC 連線中斷'))
        out = T.cmd_generate_all(prod, GenShell(self.tmp), FakeClaude())
        self.assertEqual(out, {5: 'error', 7: 'error'}, '每筆都試、不整批中止')

    def test_a4_retry_cleans_previous_attempt(self):
        os.makedirs(self.wt())
        prod, sh = self._prod(), GenShell(self.tmp, has_branch=True)
        self.assertEqual(T.cmd_generate(prod, sh, FakeClaude(), 5), 'generated')
        self.assertEqual(sh.git_sub('worktree')[0][4], 'remove', '先清掉上次留下的（乾淨、沒推過）')

    def test_a4_dirty_or_pushed_previous_refused_before_marking(self):
        os.makedirs(self.wt())
        prod, cl = self._prod(), FakeClaude()
        with self.assertRaises(T.ToolError):
            T.cmd_generate(prod, GenShell(self.tmp, pre_status=' M dobtor_x/a.py\n'), cl, 5)
        with self.assertRaises(T.ToolError):
            T.cmd_generate(prod, GenShell(self.tmp, remote_has=True), cl, 5)
        self.assertEqual((prod.writes, cl.calls), ([], []), '沒標本機修補中、沒跑 claude')
        self.assertTrue(os.path.isdir(self.wt()), '有人在看的不刪')

    def test_a5_timeout_capped_below_stale(self):
        prod, cl = self._prod(), FakeClaude()
        T.cmd_generate(prod, GenShell(self.tmp), cl, 5, timeout=5 * 3600)
        self.assertEqual(cl.calls[0]['timeout'], T.CLAUDE_TIMEOUT_MAX)
        self.assertLess(T.CLAUDE_TIMEOUT_MAX, 2 * 3600, '比伺服器的本機修補中斷時限（2 小時）短')

    def test_a8_candidates_filter(self):
        prod = GenProd(candidates=[])
        self.assertEqual(T.gen_candidates(prod), [])
        dom = prod.domains[0]
        for term in (('rejected_at', '=', False), ('patch_local_attempts', '<', T.GEN_MAX_ATTEMPTS),
                     ('incident_id.state', '=', 'open'), ('state', 'in', T.GEN_STATES)):
            self.assertIn(term, dom)

    def test_a10_old_server_and_no_candidates(self):
        with self.assertRaises(T.ToolError) as cm:
            T.fetch_brief(GenProd(server_brief=False), 5)
        self.assertIn('18.0.3.37.1', str(cm.exception))
        self.assertFalse(hasattr(T, 'client_payload'), '舊伺服器退回本機組備料的程式已刪')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(T.main(['generate'], prod=GenProd(candidates=[]), sh=GenShell(self.tmp),
                                    claude=FakeClaude()), 0, '沒有候選不是錯誤')


class TestReviewedGate(GenBase):
    """D-KN-104（審查 A2）：verify 沒有 --reviewed 只印 diff 摘要，不開 worktree、不跑 pt-verify、不寫正式機。"""

    def test_verify_without_reviewed_runs_nothing(self):
        prod, sh = self._prod(), GenShell(self.tmp)
        prod.records[(T.PROPOSAL, 5)]['patch_diff'] = ('diff --git a/dobtor_x/a.py b/dobtor_x/a.py\n--- a/dobtor_x/a.py\n'
                                                       '+++ b/dobtor_x/a.py\n@@ -1 +1,2 @@\n-a\n+b\n+c\n')
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(T.cmd_verify(prod, sh, 5), 'needs_review')
        self.assertEqual((prod.writes, sh.levels(), sh.git_sub('worktree'), sh.git_sub('apply')), ([], [], [], []))
        self.assertIn('dobtor_x/a.py（+2 −1）', buf.getvalue())
        self.assertIn('--reviewed', buf.getvalue())
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'cache', '5', 'changes.diff')), '存 diff 給人看')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(T.main(['verify', '5'], prod=prod, sh=sh), 1)
        self.assertEqual(sh.levels(), [])

    def test_verify_reviewed_runs(self):
        prod, sh = self._prod(), GenShell(self.tmp)
        self.assertEqual(T.cmd_verify(prod, sh, 5, reviewed=True), 'pushed')
        self.assertEqual(sh.levels(), ['V1', 'V2'])

    def test_diff_summary_flags_outside(self):
        out = '\n'.join(T.diff_summary('diff --git a/docs/x b/docs/x\n+a\n'))
        self.assertIn('dobtor_ 模組以外', out)

    def test_verify_reuses_generated_worktree(self):
        os.makedirs(self.wt())
        sh = GenShell(self.tmp, status='')
        sh.opened = True
        orig = sh.run

        def run(cmd, cwd=None, check=True, timeout=None):
            if cmd[0] == 'git' and cmd[3] == 'rev-parse' and '--abbrev-ref' in cmd:
                return 0, 'opt/5\n'
            if cmd[0] == 'git' and cmd[3] == 'diff' and 'HEAD~1..HEAD' in cmd:
                return 0, 'diff --git a/x b/x\n'
            return orig(cmd, cwd=cwd, check=check, timeout=timeout)
        sh.run = run
        self.assertEqual(T.cmd_verify(self._prod(), sh, 5, reviewed=True), 'pushed')
        self.assertEqual((sh.git_sub('apply'), [c for c in sh.git_sub('worktree') if c[4] == 'add']), ([], []),
                         '沿用、不重開不重套')


class TestA1NoCodeExecution(unittest.TestCase):
    """審查 A1：提示詞來自正式機（不受信任）——claude 不能執行任何程式；主機端語法檢查也不會執行 worktree 裡的東西。"""

    def test_claude_bash_has_no_python(self):
        for rule in T.CLAUDE_ALLOW:
            self.assertTrue(rule.startswith('Bash(git diff') or rule.startswith('Bash(git status'), rule)
            self.assertNotIn('python', rule)
        self.assertIn('Bash(python*)', T.CLAUDE_DENY)

    def test_host_compile_does_not_import_worktree_files(self):
        """真的跑一次（不是 mock）：worktree 根目錄放 py_compile.py／sitecustomize.py／compile.py，都不能被執行。"""
        wt = tempfile.mkdtemp()
        cache = tempfile.mkdtemp()
        marker = os.path.join(cache, 'PWNED')
        try:
            evil = 'open(%r, "w").write("x")\n' % marker
            for name in ('py_compile.py', 'sitecustomize.py', 'compile.py', 'usercustomize.py'):
                with open(os.path.join(wt, name), 'w') as fh:
                    fh.write(evil)
            os.makedirs(os.path.join(wt, 'dobtor_x'))
            with open(os.path.join(wt, 'dobtor_x', 'ok.py'), 'w') as fh:
                fh.write('import py_compile\na = 1\n')
            with open(os.path.join(wt, 'dobtor_x', 'bad.py'), 'w') as fh:
                fh.write('def f(:\n')
            with mock.patch.object(T, 'CACHE', cache), \
                    mock.patch.dict(os.environ, {'PYTHONPATH': wt, 'PYTHONSTARTUP': os.path.join(wt, 'py_compile.py')}):
                self.assertEqual(T._py_compile(T.Shell(), wt, ['dobtor_x/ok.py']), [])
                bad = T._py_compile(T.Shell(), wt, ['dobtor_x/ok.py', 'dobtor_x/bad.py'])
                # 對照組：舊做法（python3 -m py_compile，cwd 在 worktree）會執行 worktree 的 py_compile.py
                subprocess.run([sys.executable, '-m', 'py_compile', 'dobtor_x/ok.py'], cwd=wt, capture_output=True,
                               env={'PATH': os.environ.get('PATH', '')})
                hijacked = os.path.exists(marker)
                if hijacked:
                    os.remove(marker)
                self.assertEqual(T._py_compile(T.Shell(), wt, ['dobtor_x/ok.py']), [])
            self.assertTrue(bad and 'SyntaxError' in bad[0], bad)
            self.assertTrue(hijacked, '對照組：舊做法確實會被劫持（證明這個測試抓得到）')
            self.assertFalse(os.path.exists(marker), 'worktree 裡的 py_compile.py 等沒有被執行')
            self.assertFalse(os.path.exists(os.path.join(wt, 'dobtor_x', '__pycache__')), '只 compile、不寫快取')
        finally:
            shutil.rmtree(wt, ignore_errors=True)
            shutil.rmtree(cache, ignore_errors=True)


class TestClaudeCommand(unittest.TestCase):
    """★ 不真的跑 claude：只檢查組出來的指令與環境變數。"""

    def test_flags_and_env(self):
        out = {'num_turns': 5, 'total_cost_usd': 0.5, 'duration_ms': 3000, 'subtype': 'success', 'is_error': False}
        fake = mock.MagicMock(returncode=0, stdout=json.dumps(out), stderr='')
        env = {'PATH': '/bin', 'HOME': '/h', 'CORPAAS_RPC_PASSWORD': 'x', 'ANTHROPIC_API_KEY': 'y', 'GH_TOKEN': 'z'}
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(T.subprocess, 'run', return_value=fake) as run:
                info = T.Claude().run('提示', '/wt/opt-5', os.path.join(tmp, 'c.json'), timeout=60, max_turns=9)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertTrue(info['ok'])
        self.assertEqual((info['turns'], info['duration_s']), (5, 3))
        cmd, kw = run.call_args[0][0], run.call_args[1]
        for flag in ('-p', '--restricted', '--strict-mcp-config', '--no-session-persistence'):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index('--permission-prompts') + 1], 'none')
        self.assertEqual(cmd[cmd.index('--permission-mode') + 1], 'acceptEdits')
        self.assertEqual(cmd[cmd.index('--max-turns') + 1], '9')
        self.assertNotIn('bypassPermissions', cmd)
        self.assertNotIn('--dangerously-skip-permissions', cmd)
        self.assertIn('Bash(git push*)', cmd)
        self.assertFalse([c for c in cmd if 'python' in c and c.startswith('Bash(') and c in T.CLAUDE_ALLOW])
        self.assertEqual((kw['cwd'], kw['timeout'], kw['input']), ('/wt/opt-5', 60, '提示'))
        self.assertEqual(set(kw['env']), {'PATH', 'HOME'}, '金鑰、密碼、API key 不進 claude 的環境')

    def test_timeout_and_error(self):
        with mock.patch.object(T.subprocess, 'run', side_effect=T.subprocess.TimeoutExpired('claude', 60)):
            self.assertFalse(T.Claude().run('p', '/wt', '/dev/null', timeout=60)['ok'])
        bad = mock.MagicMock(returncode=1, stdout=json.dumps({'subtype': 'error_max_turns', 'is_error': True}),
                             stderr='')
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.object(T.subprocess, 'run', return_value=bad):
                info = T.Claude().run('p', '/wt', os.path.join(tmp, 'c.json'))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertFalse(info['ok'])
        self.assertIn('error_max_turns', info['note'])

class TestNoSecrets(unittest.TestCase):

    def test_tool_never_reads_keys(self):
        src = open(T.__file__, encoding='utf-8').read()
        for word in ('find-generic-password', 'CORPAAS_RPC_PASSWORD', 'hub_key', 'X-AI-Hub-Key', 'GITHUB_TOKEN'):
            self.assertNotIn(word, src)

    def test_rpc_whitelist_has_tool_methods(self):
        rpc_src = open(os.path.join(os.path.dirname(T.__file__), 'rpc.py'), encoding='utf-8').read()
        for m in WHITELIST:
            self.assertIn("'%s'" % m, rpc_src)


if __name__ == '__main__':
    unittest.main()
