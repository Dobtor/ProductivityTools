"""Knowledge 自我優化第 4 期的主機端工具：源碼修補的驗證與推送、並版匯出、合併後標記。

由人（或指揮的代理）手動執行——**不是自動閘門**：不掛 cron、不掛 git hook、不接 CI（D-KN-008）。

用法（在 ProductivityTools 根目錄）：
  python3 tools/knowledge/opt_patch.py list
  python3 tools/knowledge/opt_patch.py generate [<提案編號>...] [--dry-run] [--no-verify] [--no-push] [--model M]
                                                [--max-turns N] [--timeout-min N]
  python3 tools/knowledge/opt_patch.py verify <提案編號> [--no-push] [--dry-run]
  python3 tools/knowledge/opt_patch.py push <提案編號>            （verify 用了 --no-push 之後再推）
  python3 tools/knowledge/opt_patch.py release <並版編號> [--no-verify] [--no-push] [--dry-run]
  python3 tools/knowledge/opt_patch.py merged <提案編號> [--force]
  python3 tools/knowledge/opt_patch.py merged release:<並版編號> [--force]

generate（D-KN-102，使用者 2026-11-09 決定先不開沙盒 Runner）：不指定提案＝所有可修補的第 3 層提案（只記錄、
        Runner 未就緒、修補失敗；專案知識跳過）。每筆：唯讀取備料（kb_patch_brief）→ 標「本機修補中」（Hub 不會同時送）
        → 從 origin/dev-18.0 開 worktree opt-<編號>／分支 opt/<編號> → 在 worktree 裡跑 claude -p --restricted 寫修補
        （只能動 worktree、Bash 只放行 py_compile／git diff／git status、限輪數與逾時、環境變數白名單）
        → 只收 dobtor_ 模組的改動、py_compile → commit → 寫回修補檔（待驗證）→ 接 verify 的 V1、V2、推 opt/ 分支。
        失敗一律寫回修補失敗與原因。--dry-run 只讀：提示詞存到 ~/Library/Caches/corpaas-kb/opt/<編號>/prompt.md。
verify：取回待驗證提案的修補檔 → 在 Knowledge 開 worktree（分支 opt/<提案編號>，從 origin/dev-18.0）→ git apply
        → commit → 改到的模組都要升版號 → pt-verify V1、V2（V2 帶 --target）→ 結果與報告路徑寫回提案 → 兩級都 PASS 且報告的 sha 等於 HEAD
        就推 opt/<提案編號> → 提案轉「待合併」。審查小組精簡版不在工具內，由人另外跑。
release：取回並版紀錄凍結的匯出內容 → 逐筆重查（已停用、刪除、退役、內容改過的拿掉，只少不多，D-KN-092）
        → 開 opt/release-<日期> → 寫進源碼並版表
        dobtor_corpaas_knowledge/services/rule_merged.json、核心版號最後一碼加一、docs/decisions.tsv 加一列
        → commit、存 diff → pt-verify V1、V2 → 寫回 → 通過就推 opt/release-<日期>。
merged：確認分支已併進 origin/dev-18.0、分支有升版號、正式機模組版本已到分支的版本，
        而且正式機快照（先跑 pt-verify snapshot，唯讀）裡該 commit 改動的檔案內容全部一致 → 提案轉「已並版」／並版紀錄檢查退役。
        （squash 合併時 commit 不會是祖先，人確認過可加 --force 跳過祖先檢查；正式機版本仍要到。）

★ 會寫正式機（admin.corpaas.com，rpc.rw，只限白名單方法 action_kb_patch_verified／action_kb_patch_pushed／
  action_kb_patch_merged／action_kb_release_exported／action_kb_release_check／action_kb_patch_local_start／
  action_kb_patch_local_result）。--dry-run 不寫、不推。
★ 只推 opt/ 開頭的分支（明確 refspec、不 --force）；不合併、不部署。
★ 不讀、不印任何金鑰：正式機連線由 rpc.py 從鑰匙圈取密碼，本工具不碰；不讀 settings.env 以外的設定。
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GH = os.environ.get('PT_VERIFY_GH', os.path.expanduser('~/Documents/GitHub'))
KNOWLEDGE = os.environ.get('OPT_KNOWLEDGE_REPO', os.path.join(GH, 'Knowledge'))
WORKTREES = os.environ.get('OPT_WORKTREES', os.path.join(GH, 'Knowledge-worktrees'))
PT_VERIFY = os.environ.get('OPT_PT_VERIFY', os.path.join(os.path.dirname(HERE), 'verify', 'pt-verify'))
SNAP_ROOT = os.environ.get('OPT_SNAP_ROOT', os.path.expanduser('~/Library/Caches/corpaas-kb/prod'))
CACHE = os.environ.get('OPT_CACHE', os.path.expanduser('~/Library/Caches/corpaas-kb/opt'))
TARGET = os.environ.get('OPT_TARGET', 'admin.corpaas.com')
BASE_REF = 'origin/dev-18.0'
CORE = 'dobtor_corpaas_knowledge'
MERGED_JSON = os.path.join(CORE, 'services', 'rule_merged.json')
DECISIONS = os.path.join('docs', 'decisions.tsv')
PROPOSAL = 'corpaas.knowledge.opt_proposal'
RELEASE = 'corpaas.knowledge.opt_release'
REPORT_LINE = re.compile(r'^(\S.*\.md) (PASS|FAIL|BLOCKED)$')
BRANCH_RE = re.compile(r'opt/[A-Za-z0-9][A-Za-z0-9._-]{0,80}')
OVERRIDE = 'corpaas.knowledge.rule_override'
MERGED_KEYS = ('hook', 'group', 'action', 'key', 'value', 'scope', 'package_id', 'db_uuid', 'package_name',
               'examples_pos', 'examples_neg', 'override_id', 'proposal_id', 'release_id', 'note')


class ToolError(Exception):
    pass


# ----------------------------------------------------------------------
# 外部依賴（測試換成假的）
# ----------------------------------------------------------------------
class Prod:
    """正式機連線：ro 唯讀；rw 只用 rpc.py 白名單裡的方法。dry_run 時 rw 只印不寫。"""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self._rpc = None

    def _mod(self):
        if self._rpc is None:
            sys.path.insert(0, HERE)
            import rpc  # noqa: E402 — 延後匯入：沒設定時 list 以外的說明也能看
            self._rpc = rpc
        return self._rpc

    def ro(self, model, method, *args, **kw):
        return self._mod().ro(model, method, *args, **kw)

    def rw(self, model, method, *args, **kw):
        if self.dry_run:
            print('  [dry-run] 不寫正式機：%s.%s %s' % (model, method, json.dumps(args[1:] if len(args) > 1 else [],
                                                                         ensure_ascii=False)[:300]))
            return None
        return self._mod().rw(model, method, *args, **kw)


class Shell:
    """執行外部指令（git、pt-verify）。回 (結束碼, 標準輸出)。"""

    def run(self, cmd, cwd=None, check=True, timeout=None):
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        if check and p.returncode != 0:
            raise ToolError('指令失敗（%s）：%s\n%s' % (p.returncode, ' '.join(cmd), (p.stderr or p.stdout)[-2000:]))
        return p.returncode, (p.stdout or '') + (p.stderr or '' if p.returncode else '')


# ----------------------------------------------------------------------
# git／pt-verify
# ----------------------------------------------------------------------
def valid_branch(name):
    return bool(BRANCH_RE.fullmatch(name or '')) and '..' not in name


def git(sh, repo, *args, check=True):
    return sh.run(['git', '-C', repo] + list(args), check=check)


def push_branch(sh, repo, branch, sha):
    """★ 只推 opt/ 開頭的分支：明確 refspec「<驗證過的 sha>:refs/heads/<分支>」（審查 G3：推的就是驗證的那個 commit，
    不是本機分支 ref 當下指到的東西）、不 --force、不推其他 ref。"""
    if not valid_branch(branch):
        raise ToolError('拒絕推送：只推 opt/ 開頭的分支（%s）' % branch)
    if not re.fullmatch(r'[0-9a-f]{7,64}', sha or ''):
        raise ToolError('拒絕推送：沒有驗證過的 commit sha（%s）' % (sha or '—'))
    git(sh, repo, 'push', 'origin', '%s:refs/heads/%s' % (sha, branch))


def open_worktree(sh, branch, path):
    if os.path.exists(path):
        raise ToolError('worktree 已存在：%s（先確認沒人在用，再 git -C %s worktree remove %s）' % (path, KNOWLEDGE, path))
    git(sh, KNOWLEDGE, 'fetch', 'origin')
    code, _out = git(sh, KNOWLEDGE, 'rev-parse', '--verify', '--quiet', 'refs/heads/%s' % branch, check=False)
    if code == 0:
        raise ToolError('本機已有分支 %s：先確認是否舊的嘗試（git -C %s branch -D %s）' % (branch, KNOWLEDGE, branch))
    git(sh, KNOWLEDGE, 'worktree', 'add', '--no-track', path, '-b', branch, BASE_REF)
    return path


def head_sha(sh, repo):
    return git(sh, repo, 'rev-parse', 'HEAD')[1].strip()


def run_verify(sh, repo, level, target=None):
    """pt-verify run：回 {'report', 'verdict', 'sha'}；最後一行是「<報告 .md> <PASS|FAIL|BLOCKED>」。"""
    cmd = [PT_VERIFY, 'run', repo, '--level', level]
    if target:
        cmd += ['--target', target]
    _code, out = sh.run(cmd, check=False)
    # ★ 審查 F9：失敗時輸出後面會接 stderr，報告行不一定是最後一行——從後往前找第一個報告行
    hit = None
    for line in reversed((out or '').splitlines()):
        hit = REPORT_LINE.match(line.strip())
        if hit:
            break
    if not hit:
        tail = [x for x in (out or '').strip().splitlines() if x.strip()][-1:] or ['']
        return {'report': '', 'verdict': 'BLOCKED', 'sha': '', 'note': 'pt-verify 沒有印出報告行：%s' % tail[0][:300]}
    report, verdict = hit.group(1), hit.group(2)
    sha = ''
    try:
        with open(report[:-3] + '.json', encoding='utf-8') as fh:
            sha = json.load(fh).get('sha') or ''
    except (OSError, ValueError):
        pass
    return {'report': report, 'verdict': verdict, 'sha': sha}


def verify_levels(sh, repo, head):
    """V1、V2（V2 帶正式機目標取整組）；報告的 sha 不等於 HEAD 一律當 FAIL。"""
    out = {}
    for lvl, target in (('V1', None), ('V2', TARGET)):
        r = run_verify(sh, repo, lvl, target)
        same = bool(r['sha']) and (head.startswith(r['sha']) or r['sha'].startswith(head))
        if r['verdict'] == 'PASS' and not same:
            r = dict(r, verdict='FAIL', note='報告的 sha（%s）不等於 HEAD（%s）' % (r['sha'] or '—', head))
        out[lvl.lower()] = r
        print('  %s %s %s' % (lvl, r['verdict'], r['report']))
        if r['verdict'] != 'PASS':
            break   # V1 沒過就不跑 V2（省時間）
    return out


def manifest_version(sh, repo, ref, mod):
    code, text = git(sh, repo, 'show', '%s:%s/__manifest__.py' % (ref, mod), check=False)
    if code != 0:
        return None
    m = re.search(r"['\"]version['\"]\s*:\s*['\"]([\d.]+)['\"]", text or '')
    return m.group(1) if m else None


def changed_modules(sh, repo, base, head):
    _c, out = git(sh, repo, 'diff', '--name-only', base, head)
    return sorted({x.split('/', 1)[0] for x in out.splitlines() if '/' in x and x.startswith('dobtor_')})


def version_bumps(sh, repo, base, head):
    """審查 F7：改到的每個模組版號都要比基準高（新模組不比）。回 ({模組: 新版號}, [問題])；沒有改到模組也是問題。"""
    mods = changed_modules(sh, repo, base, head)
    want, problems = {}, []
    if not mods:
        problems.append('沒有改到任何模組')
    for mod in mods:
        new = manifest_version(sh, repo, head, mod)
        if not new:
            continue   # 模組被刪掉或沒有 manifest
        old = manifest_version(sh, repo, base, mod)
        want[mod] = new
        if old and _ver(new) <= _ver(old):
            problems.append('%s 版號沒有升（%s → %s）' % (mod, old, new))
    if mods and not want:
        problems.append('改到的模組都沒有 manifest 版號')
    return want, problems


def _both_pass(res):
    return all((res.get(k) or {}).get('verdict') == 'PASS' for k in ('v1', 'v2'))


def _notes(res):
    return '；'.join('%s：%s' % (k.upper(), v['note']) for k, v in sorted(res.items()) if v.get('note'))


# ----------------------------------------------------------------------
# verify
# ----------------------------------------------------------------------
def cmd_verify(prod, sh, pid, push=True):
    recs = prod.ro(PROPOSAL, 'read', [pid], fields=['state', 'layer', 'name', 'patch_diff', 'patch_base_commit'])
    if not recs:
        raise ToolError('找不到提案 #%s' % pid)
    rec = recs[0]
    if rec['state'] != 'to_verify' or not rec.get('patch_diff'):
        raise ToolError('提案 #%s 不在待驗證或沒有修補檔（%s）' % (pid, rec['state']))
    branch = 'opt/%s' % int(pid)
    path = os.path.join(WORKTREES, 'opt-%s' % int(pid))
    os.makedirs(os.path.join(CACHE, str(pid)), exist_ok=True)
    diff_file = os.path.join(CACHE, str(pid), 'changes.diff')
    with open(diff_file, 'w', encoding='utf-8') as fh:
        fh.write(rec['patch_diff'] if rec['patch_diff'].endswith('\n') else rec['patch_diff'] + '\n')
    if os.path.isdir(path) and _generated_worktree(sh, path, branch, rec['patch_diff']):
        print('沿用 generate 留下的 worktree %s（%s，內容和提案的修補檔相同）' % (path, branch))
        return verify_and_push(prod, sh, pid, path, branch, push)
    open_worktree(sh, branch, path)
    print('worktree %s（%s，從 %s）' % (path, branch, BASE_REF))
    code, out = git(sh, path, 'apply', '--index', diff_file, check=False)
    if code != 0:
        code, out2 = git(sh, path, 'apply', '--index', '--3way', diff_file, check=False)
        if code != 0:
            res = {'v1': {'verdict': 'BLOCKED', 'report': '', 'sha': ''}, 'v2': {'verdict': 'BLOCKED', 'report': ''}}
            prod.rw(PROPOSAL, 'action_kb_patch_verified', [pid], {
                **res, 'note': 'git apply 失敗（%s，基準 %s）：%s' % (BASE_REF, rec.get('patch_base_commit') or '—',
                                                                (out + out2)[-800:])})
            print('git apply 失敗：已寫回（提案轉修補失敗）')
            return 'apply_failed'
    git(sh, path, 'commit', '-m', 'opt(#%s)：%s\n\nAI Hub 源碼修補（提案 #%s，Hub 基準 %s）。修補報告見提案。' % (
        pid, rec.get('name') or '', pid, rec.get('patch_base_commit') or '—'))
    return verify_and_push(prod, sh, pid, path, branch, push)


def verify_and_push(prod, sh, pid, path, branch, push=True):
    """worktree 已 commit 好修補（提案在待驗證）：版號檢查 → V1、V2 → 寫回 → 兩級都 PASS 且 sha＝HEAD 才推 opt/ 分支。
    verify（Hub 修補檔）與 generate（本機修補）共用。"""
    head = head_sha(sh, path)
    _want, problems = version_bumps(sh, path, BASE_REF, 'HEAD')
    if problems:
        prod.rw(PROPOSAL, 'action_kb_patch_verified', [pid], {
            'v1': {'verdict': 'FAIL', 'report': '', 'sha': head}, 'v2': {'verdict': 'BLOCKED', 'report': ''},
            'note': '修補沒有升版號（部署後無法確認已並版）：%s' % '；'.join(problems)})
        print('版號檢查沒過：%s——已寫回（提案轉修補失敗）' % '；'.join(problems))
        return 'failed'
    res = verify_levels(sh, path, head)
    payload = {'v1': res.get('v1') or {}, 'v2': res.get('v2') or {'verdict': 'BLOCKED', 'report': '',
                                                                   'note': 'V1 沒過，沒跑 V2'}, 'note': _notes(res)}
    prod.rw(PROPOSAL, 'action_kb_patch_verified', [pid], payload)
    if not _both_pass(payload):
        print('驗證沒有通過：已寫回（提案轉修補失敗）；worktree 留著給人看：%s' % path)
        return 'failed'
    if not push:
        print('V1、V2 通過；--no-push：沒有推分支，提案留在待驗證（之後可用 push %s 推）' % pid)
        return 'passed'
    if prod.dry_run:
        print('  [dry-run] 不推 %s' % branch)
        return 'passed'
    push_branch(sh, path, branch, head)
    prod.rw(PROPOSAL, 'action_kb_patch_pushed', [pid], {'branch': branch, 'commit': head})
    print('已推 %s（%s）：提案轉待合併。合併與部署由人決定。' % (branch, head[:12]))
    return 'pushed'


def _generated_worktree(sh, path, branch, patch_diff):
    """generate --no-verify 留下的 worktree：在 opt/<編號>、沒有未 commit 的改動、最後一個 commit 的 diff 就是提案的修補檔。"""
    if git(sh, path, 'rev-parse', '--abbrev-ref', 'HEAD', check=False)[1].strip() != branch:
        return False
    if git(sh, path, 'status', '--porcelain', check=False)[1].strip():
        return False
    code, diff = git(sh, path, 'diff', 'HEAD~1..HEAD', check=False)
    return code == 0 and bool(diff.strip()) and diff.strip() == (patch_diff or '').strip()


def cmd_push(prod, sh, pid):
    """審查 F13：verify 用了 --no-push（或推送失敗）之後再推：提案要在待驗證、V1 V2 都 PASS，
    worktree 的 HEAD 要等於寫回的驗證 commit（驗證後沒有再改過）。"""
    rec = (prod.ro(PROPOSAL, 'read', [pid], fields=['state', 'verify_v1_verdict', 'verify_v2_verdict',
                                                     'verify_sha']) or [None])[0]
    if not rec:
        raise ToolError('找不到提案 #%s' % pid)
    if rec['state'] != 'to_verify' or rec.get('verify_v1_verdict') != 'PASS' \
            or rec.get('verify_v2_verdict') != 'PASS' or not rec.get('verify_sha'):
        raise ToolError('提案 #%s 不在待驗證或 V1／V2 沒有都通過（%s）' % (pid, rec['state']))
    branch = 'opt/%s' % int(pid)
    path = os.path.join(WORKTREES, 'opt-%s' % int(pid))
    if not os.path.isdir(path):
        raise ToolError('找不到 worktree %s：請重新 verify' % path)
    head = head_sha(sh, path)
    if not (head.startswith(rec['verify_sha']) or rec['verify_sha'].startswith(head)):
        raise ToolError('worktree HEAD（%s）不等於驗證的 commit（%s）：驗證後改過，請重新 verify' % (
            head[:12], rec['verify_sha'][:12]))
    if prod.dry_run:
        print('  [dry-run] 不推 %s' % branch)
        return 'passed'
    push_branch(sh, path, branch, rec['verify_sha'])
    prod.rw(PROPOSAL, 'action_kb_patch_pushed', [pid], {'branch': branch, 'commit': rec['verify_sha']})
    print('已推 %s（%s）：提案轉待合併' % (branch, rec['verify_sha'][:12]))
    return 'pushed'


# ----------------------------------------------------------------------
# generate（D-KN-102：本機產生修補，不開沙盒 Runner）
# ----------------------------------------------------------------------
#: 可以本機修補的狀態（Knowledge patch_lib 的 PATCHABLE）
GEN_STATES = ('recorded', 'runner_wait', 'patch_failed')
PATCH_LIB = os.path.join(CORE, 'services', 'patch_lib.py')
CLAUDE = os.environ.get('OPT_CLAUDE', 'claude')
CLAUDE_TIMEOUT = int(os.environ.get('OPT_CLAUDE_TIMEOUT', 45 * 60))
CLAUDE_MAX_TURNS = int(os.environ.get('OPT_CLAUDE_MAX_TURNS', 80))
#: claude 子程序只拿這些環境變數（其他一律不帶：正式機密碼、各種金鑰、API key 都不會進去）
CLAUDE_ENV = ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR', 'SHELL', 'TERM',
              'CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_OAUTH_TOKEN')
CLAUDE_TOOLS = 'Read,Edit,Write,Glob,Grep,Bash'
#: Bash 只放行驗證會用到的指令（相對路徑）；--permission-prompts none：其他一律自動拒絕
CLAUDE_ALLOW = ('Bash(python3 -m py_compile *)', 'Bash(git diff)', 'Bash(git diff --stat)', 'Bash(git diff -- *)',
                'Bash(git status)', 'Bash(git status --short)')
#: 擋絕對路徑、家目錄、上層目錄、推送與改設定（deny 優先於 allow）
CLAUDE_DENY = ('Bash(* /*)', 'Bash(*~*)', 'Bash(*..*)', 'Bash(git push*)', 'Bash(git commit*)', 'Bash(git config*)',
               'Bash(git remote*)', 'WebFetch', 'WebSearch')
REPORT_NAME = 'report.md'
LOCAL_RULES = """

## 本機修補的規則（主機端 opt_patch.py generate；D-KN-102）
- 你的工作目錄是 Knowledge repo 的 worktree（分支 {branch}，基準 {base_ref} {base}）。上面說「工作目錄的改動會被收成
  changes.diff」：在這裡由主機端工具 commit、跑 pt-verify V1、V2，通過才推分支。你不要 git add／commit／push（也做不到）。
- 只能讀寫這個工作目錄；不要讀工作目錄以外的檔案，不要讀或印出任何金鑰、密碼、權杖、設定檔。
- 只改 dobtor_ 開頭的模組目錄；其他路徑的改動會讓這次修補整筆失敗。
- 能用的指令只有：python3 -m py_compile <相對路徑>、git diff、git diff -- <相對路徑>、git status（路徑一律相對）。
  完整的 Odoo 測試由主機端 pt-verify 跑。
- 一定要：改到的模組 __manifest__.py 版號最後一碼加一（沒升版號驗證一律不過），並補能重現缺陷的單元測試。
- report.md 寫在工作目錄根目錄（主機端會收走，不進 commit）。
"""


class Claude:
    """在 worktree 裡用無頭模式跑本機 Claude Code（測試換成假的）。

    安全邊界：--restricted（不讀使用者／專案的設定檔、檔案工具只能動工作目錄、拒絕 bypassPermissions）、
    --tools 只給檔案工具＋Bash、Bash 只放行 CLAUDE_ALLOW、--permission-prompts none（要問的一律拒絕）、
    --strict-mcp-config（不載 MCP）、不留 session、限輪數與逾時、環境變數白名單。"""

    def run(self, prompt, cwd, out_path, timeout=CLAUDE_TIMEOUT, max_turns=CLAUDE_MAX_TURNS, model=None):
        cmd = [CLAUDE, '-p', '--restricted', '--tools', CLAUDE_TOOLS, '--allowedTools', *CLAUDE_ALLOW,
               '--disallowedTools', *CLAUDE_DENY, '--permission-mode', 'acceptEdits', '--permission-prompts', 'none',
               '--strict-mcp-config', '--no-session-persistence', '--max-turns', str(int(max_turns)),
               '--output-format', 'json']
        if model:
            cmd += ['--model', model]
        env = {k: os.environ[k] for k in CLAUDE_ENV if os.environ.get(k)}
        try:
            p = subprocess.run(cmd, cwd=cwd, input=prompt, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'note': 'claude 超過 %s 分鐘沒做完（逾時中止）' % (timeout // 60)}
        except FileNotFoundError:
            return {'ok': False, 'note': '找不到 claude 指令（%s）' % CLAUDE}
        with open(out_path, 'w', encoding='utf-8') as fh:
            fh.write(p.stdout or '')
        try:
            res = json.loads(p.stdout or '{}')
        except ValueError:
            res = {}
        info = {'turns': res.get('num_turns'), 'cost_usd': res.get('total_cost_usd'),
                'duration_s': round((res.get('duration_ms') or 0) / 1000), 'subtype': res.get('subtype'),
                'denials': len(res.get('permission_denials') or [])}
        if p.returncode != 0 or res.get('is_error') or res.get('subtype') not in (None, 'success'):
            info.update(ok=False, note='claude 沒有正常結束（結束碼 %s、%s）：%s' % (
                p.returncode, res.get('subtype') or '—', ((res.get('result') or '') or (p.stderr or ''))[-500:]))
            return info
        info.update(ok=True, note='')
        return info


def load_patch_lib(sh):
    """Knowledge 的 patch_lib（純函式）：舊版正式機沒有 kb_patch_brief 時，唯讀組備料用。"""
    import types
    _c, src = git(sh, KNOWLEDGE, 'show', '%s:%s' % (BASE_REF, PATCH_LIB))
    mod = types.ModuleType('kb_patch_lib')
    exec(compile(src, PATCH_LIB, 'exec'), mod.__dict__)  # noqa: S102 — 自家 repo 的純函式模組
    return mod


def _m2o(v):
    return v[0] if isinstance(v, (list, tuple)) and v else (v or False)


def _fields_present(prod, model, names):
    try:
        have = prod.ro(model, 'fields_get', attributes=['type'])
    except Exception:  # noqa: BLE001 — 模型不存在等
        return None
    return [n for n in names if n in have]


def client_payload(prod, rec):
    """伺服器沒有 kb_patch_brief（還沒部署 18.0.3.37.1）時，用唯讀呼叫照 _kb_patch_payload 組同樣的備料。"""
    inc = {}
    if rec.get('incident_id'):
        inc = (prod.ro('corpaas.knowledge.opt_incident', 'read', [_m2o(rec['incident_id'])], fields=[
            'source', 'summary', 'hook', 'cause_message', 'cause_target', 'count', 'first_seen', 'last_seen',
            'detail', 'diagnose_note', 'res_model', 'res_id', 'gap_ids', 'gap_id']) or [{}])[0]
    gap_ids = list(inc.get('gap_ids') or [])
    if _m2o(inc.get('gap_id')) and _m2o(inc.get('gap_id')) not in gap_ids:
        gap_ids.append(_m2o(inc['gap_id']))
    gaps = prod.ro('corpaas.knowledge.gap_item', 'read', gap_ids[:15], fields=[
        'kind', 'state', 'root_cause', 'evidence', 'fix_note', 'attempts', 'res_model', 'res_id']) if gap_ids else []
    affected = []

    def one(model, rid, extra):
        fl = _fields_present(prod, model, ['state', 'error', 'error_message', 'last_error', 'log', 'note', 'method'])
        if fl is None:
            return None
        r = (prod.ro(model, 'read', [rid], fields=['display_name'] + fl) or [None])[0]
        if not r:
            return None
        item = {'model': model, 'id': rid, 'name': r.get('display_name')}
        item.update({f: str(r[f])[:1500] for f in fl if r.get(f) and not extra})
        item.update(extra)
        return item
    if inc.get('res_model') and inc.get('res_id'):
        it = one(inc['res_model'], inc['res_id'], {})
        if it:
            affected.append(it)
    for g in gaps:
        if g.get('res_model') and g.get('res_id'):
            it = one(g['res_model'], g['res_id'], {'via_gap': g['id']})
            if it:
                affected.append(it)
    texts = [rec.get('suggestion'), rec.get('reason'), rec.get('evidence'), inc.get('detail'), inc.get('summary')]
    texts += [g.get('fix_note') for g in gaps]
    return inc, gaps, affected, [t or '' for t in texts]


def fetch_brief(prod, sh, pid):
    """備料與提示詞（唯讀）。優先用伺服器的 kb_patch_brief（和送 Hub 同一套）；伺服器還沒有這個方法時：
    提案上存過的備料（送過 Hub 的）→ 沒有就用唯讀呼叫在本機組。回 {id, state, blocker, prompt, decisions, evidence, source}。"""
    try:
        got = prod.ro(PROPOSAL, 'kb_patch_brief', [pid])
        if got:
            return dict(got[0], source='server')
        raise ToolError('找不到提案 #%s' % pid)
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001
        if 'kb_patch_brief' not in str(e) or 'not exist' not in str(e):
            raise
    rec = (prod.ro(PROPOSAL, 'read', [pid], fields=[
        'name', 'state', 'layer', 'package_id', 'incident_id', 'suggestion', 'reason', 'evidence', 'content_json',
        'patch_prompt', 'patch_decisions']) or [None])[0]
    if not rec:
        raise ToolError('找不到提案 #%s' % pid)
    blocker = ''
    if rec['layer'] != '3':
        blocker = '不是第 3 層（源碼修補）提案'
    elif rec['state'] not in GEN_STATES:
        blocker = '目前不能修補（%s）' % rec['state']
    elif rec.get('package_id'):
        pk = prod.ro('infrastructure.solution.package', 'read', [_m2o(rec['package_id'])], fields=['knowledge_kind'])
        if pk and pk[0].get('knowledge_kind') == 'project':
            blocker = '專案知識（客戶的方案）的證據可能含客戶資料，不送修補'
    inc, gaps, affected, texts = client_payload(prod, rec)
    lib = load_patch_lib(sh)
    decisions = lib.decision_refs(inc.get('hook') or None, inc.get('source') or None, texts)
    out = {'id': pid, 'name': rec['name'], 'state': rec['state'], 'blocker': blocker, 'decisions': decisions,
           'evidence': {'incident': bool(inc), 'gaps': len(gaps), 'affected': len(affected)}}
    if rec.get('patch_prompt'):
        return dict(out, prompt=rec['patch_prompt'], source='stored', decisions=[
            d for d in (rec.get('patch_decisions') or '').split('、') if d] or decisions)
    payload = {
        'proposal': {'id': pid, 'layer': rec['layer'], 'suggestion': rec.get('suggestion') or '',
                     'reason': rec.get('reason') or '', 'evidence': rec.get('evidence') or '',
                     'ai_raw': (rec.get('content_json') or '')[:3000]},
        'incident': {'id': inc['id'], 'source': inc.get('source'), 'summary': inc.get('summary'),
                     'hook': inc.get('hook') or '', 'cause': inc.get('cause_message') or '',
                     'target': inc.get('cause_target') or '', 'count': inc.get('count'),
                     'first_seen': inc.get('first_seen'), 'last_seen': inc.get('last_seen'),
                     'detail': (inc.get('detail') or '')[:4000], 'diagnose': (inc.get('diagnose_note') or '')[:1500]}
        if inc else {},
        'gaps': [{'id': g['id'], 'kind': g.get('kind'), 'state': g.get('state'), 'root_cause': g.get('root_cause') or '',
                  'evidence': (g.get('evidence') or '')[:1500], 'history': (g.get('fix_note') or '')[-1500:],
                  'attempts': g.get('attempts')} for g in gaps],
        'affected': affected[:20], 'decisions': decisions,
        'module_versions': {m['name']: m['latest_version'] for m in prod.ro(
            'ir.module.module', 'search_read', [('name', 'like', 'dobtor_corpaas_knowledge%'),
                                                ('state', '=', 'installed')], fields=['name', 'latest_version'])},
    }
    return dict(out, prompt=lib.patch_prompt(payload), source='client')


def local_prompt(prompt, branch, base):
    return prompt + LOCAL_RULES.format(branch=branch, base_ref=BASE_REF, base=base[:12])


def _changed_paths(sh, path):
    """worktree 的改動（含未追蹤）：回 (要 commit 的路徑, 不允許的路徑)。快取檔與 report.md 不算。"""
    _c, out = git(sh, path, 'status', '--porcelain', '--untracked-files=all')
    keep, bad = [], []
    for line in out.splitlines():
        rel = line[3:].strip()
        if ' -> ' in rel:
            rel = rel.split(' -> ', 1)[1]
        rel = rel.strip('"')
        if not rel or rel == REPORT_NAME or '__pycache__/' in rel or rel.endswith(('.pyc', '.pyo')):
            continue
        (keep if rel.startswith('dobtor_') and '/' in rel else bad).append(rel)
    return keep, bad


def _py_compile(sh, path, files):
    bad = []
    for rel in files:
        if rel.endswith('.py') and os.path.exists(os.path.join(path, rel)):
            code, out = sh.run([sys.executable, '-m', 'py_compile', rel], cwd=path, check=False)
            if code != 0:
                bad.append('%s：%s' % (rel, (out or '').strip().splitlines()[-1:] or ['語法錯誤']))
    return bad


def gen_candidates(prod):
    return [r['id'] for r in prod.ro(PROPOSAL, 'search_read', [('layer', '=', '3'), ('state', 'in', GEN_STATES)],
                                     fields=['id'], order='id')]


def cmd_generate(prod, sh, claude, pid, verify=True, push=True, model=None, max_turns=CLAUDE_MAX_TURNS,
                 timeout=CLAUDE_TIMEOUT):
    """一筆：取備料 → 標本機修補中 → worktree opt-<編號>／opt/<編號> → claude -p 修 → commit → 寫回待驗證 → V1、V2 → 推。"""
    import socket
    cache = os.path.join(CACHE, str(pid))
    os.makedirs(cache, exist_ok=True)
    brief = fetch_brief(prod, sh, pid)
    branch = 'opt/%s' % int(pid)
    path = os.path.join(WORKTREES, 'opt-%s' % int(pid))
    ev = brief.get('evidence') or {}
    print('#%s %s（%s）備料來源 %s：事件 %s、缺口 %s、受影響記錄 %s、決策 %s；提示詞 %s 字' % (
        pid, brief.get('name') or '', brief.get('state'), brief['source'], '有' if ev.get('incident') else '沒有',
        ev.get('gaps', 0), ev.get('affected', 0), len(brief.get('decisions') or []), len(brief.get('prompt') or '')))
    if brief.get('blocker'):
        print('  跳過：%s' % brief['blocker'])
        return 'skipped'
    if prod.dry_run:
        _c, base = git(sh, KNOWLEDGE, 'rev-parse', BASE_REF, check=False)
        pfile = os.path.join(cache, 'prompt.md')
        with open(pfile, 'w', encoding='utf-8') as fh:
            fh.write(local_prompt(brief['prompt'], branch, (base or '').strip() or '—'))
        print('  [dry-run] 不標本機修補中、不開 worktree、不跑 claude；提示詞存在 %s' % pfile)
        return 'dry_run'
    # 開始前先確認 worktree／分支沒被占用（標了本機修補中才發現就白白轉失敗）
    if os.path.exists(path):
        raise ToolError('worktree 已存在：%s（先確認沒人在用，再 git -C %s worktree remove %s）' % (path, KNOWLEDGE, path))
    if git(sh, KNOWLEDGE, 'rev-parse', '--verify', '--quiet', 'refs/heads/%s' % branch, check=False)[0] == 0:
        raise ToolError('本機已有分支 %s：先確認是否舊的嘗試（git -C %s branch -D %s）' % (branch, KNOWLEDGE, branch))
    started = prod.rw(PROPOSAL, 'action_kb_patch_local_start', [pid], {'host': socket.gethostname()})
    prompt = (started or {}).get('prompt') or brief['prompt']

    def fail(note, **meta):
        print('  失敗：%s' % note)
        prod.rw(PROPOSAL, 'action_kb_patch_local_result', [pid], {'ok': False, 'note': note, 'meta': meta})
        return 'failed'
    try:
        open_worktree(sh, branch, path)
        base = head_sha(sh, path)
        print('  worktree %s（%s，基準 %s）；claude 執行中（上限 %s 輪、%s 分鐘）…' % (
            path, branch, base[:12], max_turns, timeout // 60))
        with open(os.path.join(cache, 'prompt.md'), 'w', encoding='utf-8') as fh:
            fh.write(local_prompt(prompt, branch, base))
        info = claude.run(local_prompt(prompt, branch, base), path, os.path.join(cache, 'claude.json'),
                          timeout=timeout, max_turns=max_turns, model=model)
        meta = {k: info.get(k) for k in ('turns', 'cost_usd', 'duration_s', 'subtype', 'denials') if k in info}
        meta.update(base_commit=base, mode='local', model=model or 'default')
        report = ''
        rpath = os.path.join(path, REPORT_NAME)
        if os.path.exists(rpath):
            with open(rpath, encoding='utf-8', errors='replace') as fh:
                report = fh.read()
            shutil.move(rpath, os.path.join(cache, REPORT_NAME))
        if not info.get('ok'):
            return fail(info.get('note') or 'claude 失敗', **meta)
        if head_sha(sh, path) != base:
            return fail('claude 動了 git 歷史（HEAD 不是基準 %s）' % base[:12], **meta)
        keep, bad = _changed_paths(sh, path)
        if bad:
            return fail('改到 dobtor_ 模組以外的路徑：%s' % '、'.join(bad[:10]), **meta)
        if not keep:
            return fail('claude 沒有改任何模組檔案', **meta)
        broken = _py_compile(sh, path, keep)
        if broken:
            return fail('py_compile 沒過：%s' % '；'.join(broken[:5]), **meta)
        git(sh, path, 'add', '-A', '--', *keep)
        git(sh, path, 'commit', '-m', 'opt(#%s)：%s\n\n本機源碼修補（opt_patch.py generate，D-KN-102；提案 #%s，基準 %s）。'
            '修補報告見提案。' % (pid, brief.get('name') or '', pid, base[:12]))
        _c, diff = git(sh, path, 'diff', '%s..HEAD' % base)
        with open(os.path.join(cache, 'changes.diff'), 'w', encoding='utf-8') as fh:
            fh.write(diff)
    except (ToolError, OSError, subprocess.SubprocessError) as e:
        return fail(str(e)[:1500] or e.__class__.__name__)
    state = prod.rw(PROPOSAL, 'action_kb_patch_local_result', [pid], {
        'ok': True, 'diff': diff, 'report': report, 'base_commit': base, 'meta': meta,
        'note': '%s，%s 輪、%s 秒' % (branch, meta.get('turns') or '—', meta.get('duration_s') or '—')})
    print('  已 commit（%s 個檔案）→ 提案 %s；修補檔 %s' % (len(keep), state, os.path.join(cache, 'changes.diff')))
    if not verify:
        print('  --no-verify：停在待驗證；之後跑 opt_patch.py verify %s（會沿用這個 worktree）' % pid)
        return 'generated'
    return verify_and_push(prod, sh, pid, path, branch, push)


def cmd_generate_all(prod, sh, claude, pids=None, **kw):
    pids = list(pids or []) or gen_candidates(prod)
    if not pids:
        print('沒有可修補的第 3 層提案（只記錄、Runner 未就緒、修補失敗）')
        return {}
    out = {}
    for pid in pids:
        try:
            out[pid] = cmd_generate(prod, sh, claude, pid, **kw)
        except ToolError as e:
            print('#%s 錯誤：%s' % (pid, e), file=sys.stderr)
            out[pid] = 'error'
    print('結果：%s' % '、'.join('#%s %s' % (k, v) for k, v in out.items()))
    return out


# ----------------------------------------------------------------------
# release
# ----------------------------------------------------------------------
def _norm(v):
    return v.strip() if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)


def _ident(m):
    return (m.get('hook'), m.get('group'), m.get('action'), (m.get('key') or '').strip(),
            _norm(m.get('value')) if m.get('action') == 'add' else '', m.get('scope') or 'global',
            int(m.get('package_id') or 0), m.get('db_uuid') or '')


def merge_rules(current, export):
    """匯出內容 → 並版表條目（方案範圍帶資料庫識別與方案 id，D-KN-090）；同一條不重複加。回 (新清單, 加了幾條)。"""
    rules = list(current.get('rules') or [])
    have = {_ident(m) for m in rules}
    added = 0
    for r in export.get('rules') or []:
        m = {k: r.get(k) for k in MERGED_KEYS if r.get(k) not in (None, '', [])}
        m['release_id'] = export.get('release_id')
        m.setdefault('scope', 'global')
        if m['action'] != 'add':
            m.pop('value', None)
        if m['scope'] == 'package':
            m['db_uuid'] = export.get('db_uuid') or ''
        else:
            for k in ('package_id', 'package_name', 'db_uuid'):
                m.pop(k, None)
        if _ident(m) in have:
            continue
        rules.append(m)
        have.add(_ident(m))
        added += 1
    return dict(current, rules=rules), added


def _ov_value(raw, frozen):
    if not isinstance(frozen, str):
        try:
            return json.loads(raw or 'null')
        except ValueError:
            return raw
    return raw or ''


def recheck_rules(prod, export):
    """D-KN-092（使用者決定 F8）：凍結的每條覆寫逐筆重查目前狀態——已刪除、已停用、已退役、內容改過的拿掉。
    凍結內容是上限：只會少不會多。回 (保留的 export, [{override_id, reason}])。"""
    rules = export.get('rules') or []
    ids = [r['override_id'] for r in rules if r.get('override_id')]
    cur = {o['id']: o for o in prod.ro(OVERRIDE, 'read', ids, fields=[
        'enabled', 'retired', 'hook', 'group', 'action', 'rule_key', 'value', 'scope', 'package_id'])} if ids else {}
    kept, dropped = [], []
    for r in rules:
        o = cur.get(r.get('override_id'))
        why = None
        if not o:
            why = '已刪除'
        elif o.get('retired'):
            why = '已退役'
        elif not o.get('enabled'):
            why = '已停用'
        else:
            pkg = (o.get('package_id') or [None])[0] if o.get('package_id') else None
            group = (o.get('group') or '').strip()
            same = (o.get('hook') == r.get('hook') and (not group or group == r.get('group'))
                    and o.get('action') == r.get('action') and (o.get('rule_key') or '').strip() == r.get('key')
                    and (o.get('scope') or 'global') == (r.get('scope') or 'global')
                    and (r.get('scope') != 'package' or pkg == r.get('package_id')))
            if same and r.get('action') == 'add':
                same = _norm(_ov_value(o.get('value'), r.get('value'))) == _norm(r.get('value'))
            if not same:
                why = '內容和凍結時不同'
        if why:
            dropped.append({'override_id': r.get('override_id'), 'reason': why})
        else:
            kept.append(r)
    # ★ 審查 G2：並進源碼的條目排在同範圍資料庫覆寫的最前面；同代碼還有沒並版的覆寫（重查拿掉的、凍結後新開的）
    #   時，並版會改變兩者的先後（參數後蓋前），判定跟著變——這種條目這次也不並，寫進說明。
    kept, dropped = _drop_order_conflicts(prod, kept, dropped)
    return dict(export, rules=kept), dropped


def _drop_order_conflicts(prod, kept, dropped):
    live = prod.ro(OVERRIDE, 'search_read', [('enabled', '=', True), ('retired', '=', False)],
                   fields=['id', 'hook', 'group', 'rule_key', 'scope', 'package_id'])
    while True:
        ids = {r.get('override_id') for r in kept}
        out, moved = [], False
        for r in kept:
            pkg = r.get('package_id') if r.get('scope') == 'package' else None
            clash = [o['id'] for o in live if o['id'] not in ids and o.get('hook') == r.get('hook')
                     and (not (o.get('group') or '').strip() or o['group'] == r.get('group'))
                     and (o.get('rule_key') or '').strip() == r.get('key')
                     and (o.get('scope') or 'global') == (r.get('scope') or 'global')
                     and ((o.get('package_id') or [None])[0] if o.get('package_id') else None) == pkg]
            if clash:
                dropped.append({'override_id': r.get('override_id'), 'reason': '同代碼還有未並版的覆寫 %s'
                                '（並進源碼會改變先後、判定跟著變）' % '、'.join('#%s' % c for c in clash)})
                moved = True
            else:
                out.append(r)
        kept = out
        if not moved:
            return kept, dropped


def bump_version(text):
    """__manifest__.py 的版號最後一碼加一。回 (新內容, 舊版, 新版)。"""
    m = re.search(r"(['\"]version['\"]\s*:\s*['\"])(\d+(?:\.\d+)+)(['\"])", text)
    if not m:
        raise ToolError('manifest 找不到版號')
    old = m.group(2)
    parts = old.split('.')
    parts[-1] = str(int(parts[-1]) + 1)
    new = '.'.join(parts)
    return text[:m.start(2)] + new + text[m.end(2):], old, new


def next_decision_id(tsv_text):
    nums = [int(x) for x in re.findall(r'^D-KN-(\d+)\t', tsv_text, re.M)]
    return 'D-KN-%03d' % ((max(nums) if nums else 0) + 1)


def decision_row(did, rel_id, export, branch, today):
    """並版時寫進 docs/decisions.tsv 的一列（11 欄；TSV 內不能有 tab／換行）。"""
    items = []
    props = sorted({r.get('proposal_id') for r in export.get('rules') or [] if r.get('proposal_id')})
    for r in export.get('rules') or []:
        scope = '方案 %s' % (r.get('package_name') or r.get('package_id')) if r.get('scope') == 'package' else '全站'
        items.append('%s／%s／%s %s（%s）' % (r.get('hook'), r.get('group'), r.get('action'), r.get('key'), scope))
    clean = lambda s: re.sub(r'[\t\r\n]+', ' ', s)  # noqa: E731
    cols = [did, today, 'dobtor_corpaas_knowledge（並版 #%s）' % rel_id,
            clean('並版紀錄 #%s：%s 條規則覆寫並進源碼並版表 services/rule_merged.json：%s；來源提案 %s。部署後對應覆寫自動退役'
                  % (rel_id, len(items), '；'.join(items), '、'.join('#%s' % p for p in props) or '—')),
            '設計書並版流程：生效中的覆寫定期並進源碼，資料庫保持乾淨%s' % (
                clean('；匯出前重查拿掉 %s（D-KN-092）' % '、'.join('#%s %s' % (d['override_id'], d['reason'])
                                                         for d in export['dropped']))
                if export.get('dropped') else ''), '覆寫一直留在資料庫（規則堆積）',
            '並進的規則造成誤判時（從並版表拿掉、升版）', '分支 %s；opt_release #%s' % (branch, rel_id), 'active', '',
            '待人合併確認（並版 #%s）' % rel_id]
    assert not any('\t' in c or '\n' in c for c in cols)
    return '\t'.join(cols)


def cmd_release(prod, sh, rid, verify=True, push=True, today=None):
    recs = prod.ro(RELEASE, 'read', [rid], fields=['state', 'name', 'export_json'])
    if not recs:
        raise ToolError('找不到並版紀錄 #%s' % rid)
    rec = recs[0]
    if rec['state'] not in ('draft', 'exported') or not rec.get('export_json'):
        raise ToolError('並版紀錄 #%s 不能匯出（%s）' % (rid, rec['state']))
    export = json.loads(rec['export_json'])
    export.setdefault('release_id', rid)
    export, dropped = recheck_rules(prod, export)
    export['dropped'] = dropped
    for d in dropped:
        print('  重查拿掉覆寫 #%s：%s' % (d['override_id'], d['reason']))
    if not export['rules']:
        prod.rw(RELEASE, 'action_kb_release_exported', [rid], {'dropped': dropped})
        print('重查後沒有可並版的覆寫：並版紀錄取消')
        return 'cancelled'
    today = today or datetime.date.today().isoformat()
    branch = 'opt/release-%s' % today.replace('-', '')
    path = os.path.join(WORKTREES, 'opt-release-%s' % today.replace('-', ''))
    if os.path.exists(path):
        branch, path = '%s-%s' % (branch, rid), '%s-%s' % (path, rid)
    open_worktree(sh, branch, path)
    jpath = os.path.join(path, MERGED_JSON)
    try:
        with open(jpath, encoding='utf-8') as fh:
            current = json.load(fh)
    except (OSError, ValueError):
        raise ToolError('%s 讀不到（基準分支還沒有第 4 期的並版表？）' % MERGED_JSON) from None
    merged, added = merge_rules(current, export)
    if not added:
        raise ToolError('匯出的覆寫都已經在並版表裡：不需要並版（可在並版紀錄按「檢查退役」）')
    with open(jpath, 'w', encoding='utf-8') as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    mpath = os.path.join(path, CORE, '__manifest__.py')
    with open(mpath, encoding='utf-8') as fh:
        text, old, new = bump_version(fh.read())
    with open(mpath, 'w', encoding='utf-8') as fh:
        fh.write(text)
    dpath = os.path.join(path, DECISIONS)
    with open(dpath, encoding='utf-8') as fh:
        tsv = fh.read()
    did = next_decision_id(tsv)
    with open(dpath, 'a', encoding='utf-8') as fh:
        fh.write(('' if tsv.endswith('\n') else '\n') + decision_row(did, rid, export, branch, today) + '\n')
    git(sh, path, 'add', MERGED_JSON, os.path.join(CORE, '__manifest__.py'), DECISIONS)
    git(sh, path, 'commit', '-m', 'opt(release #%s)：%s 條規則覆寫並進源碼並版表（%s，核心 %s → %s）' % (
        rid, added, did, old, new))
    head = head_sha(sh, path)
    os.makedirs(os.path.join(CACHE, 'release-%s' % rid), exist_ok=True)
    diff_path = os.path.join(CACHE, 'release-%s' % rid, 'release.diff')
    with open(diff_path, 'w', encoding='utf-8') as fh:
        fh.write(git(sh, path, 'diff', '%s...HEAD' % BASE_REF)[1])
    print('並版表加 %s 條、核心 %s → %s、決策 %s；修補檔 %s' % (added, old, new, did, diff_path))
    res = verify_levels(sh, path, head) if verify else {}
    pushed = False
    if verify and _both_pass(res) and push and not prod.dry_run:
        push_branch(sh, path, branch, head)
        pushed = True
    prod.rw(RELEASE, 'action_kb_release_exported', [rid], {
        'branch': branch, 'commit': head, 'diff_path': diff_path, 'v1': res.get('v1') or {},
        'v2': res.get('v2') or {}, 'pushed': pushed, 'dropped': dropped})
    print('已推 %s：待人合併、部署' % branch if pushed else '沒有推分支（驗證沒全過、--no-verify 或 --no-push）')
    return 'pushed' if pushed else 'exported'


# ----------------------------------------------------------------------
# merged
# ----------------------------------------------------------------------
def _ver(v):
    out = []
    for x in (v or '').split('.'):
        if not x.isdigit():
            break
        out.append(int(x))
    return tuple(out)


def take_snapshot(sh, snapshot_dir=None):
    """審查 G1：正式機實際部署的原碼樹。沒指定就先跑 pt-verify snapshot（唯讀），取最新一份的 src/。"""
    if snapshot_dir:
        src = os.path.join(snapshot_dir, 'src')
        return src if os.path.isdir(src) else snapshot_dir
    code, out = sh.run([PT_VERIFY, 'snapshot', TARGET], check=False)
    if code != 0:
        raise ToolError('pt-verify snapshot %s 失敗：%s' % (TARGET, (out or '')[-500:]))
    base = os.path.join(SNAP_ROOT, TARGET)
    days = sorted(d for d in (os.listdir(base) if os.path.isdir(base) else []) if os.path.isdir(os.path.join(base, d, 'src')))
    if not days:
        raise ToolError('找不到 %s 的快照原碼樹（%s）' % (TARGET, base))
    return os.path.join(base, days[-1], 'src')


def _prod_path(src, rel):
    """repo 內的相對路徑（<模組>/…）→ 快照裡的檔案路徑（模組在哪個子目錄就用哪個）；找不到模組回 None。"""
    mod = rel.split('/', 1)[0]
    for sub in sorted(os.listdir(src)):
        if os.path.isdir(os.path.join(src, sub, mod)):
            return os.path.join(src, sub, rel)
    return None


def deployed_mismatches(sh, src, commit):
    """該 commit 改動的模組檔案，和正式機快照逐檔比對內容；回不一致的清單（空＝全部一致）。"""
    _c, out = git(sh, KNOWLEDGE, 'diff', '--name-only', '%s^' % commit, commit)
    files = [x for x in out.splitlines() if '/' in x and x.startswith('dobtor_')]
    if not files:
        return ['沒有改到模組檔案']
    bad = []
    for rel in files:
        path = _prod_path(src, rel)
        if path is None:
            bad.append('%s：正式機沒有這個模組' % rel)
            continue
        code, text = git(sh, KNOWLEDGE, 'show', '%s:%s' % (commit, rel), check=False)
        if code != 0:   # 這個 commit 刪掉的檔案
            if os.path.exists(path):
                bad.append('%s：應已刪除，正式機還在' % rel)
            continue
        try:
            with open(path, encoding='utf-8', errors='replace', newline='') as fh:
                live = fh.read()
        except OSError:
            bad.append('%s：正式機沒有這個檔案' % rel)
            continue
        if live != text:
            bad.append('%s：內容和正式機不同' % rel)
    return bad


def cmd_merged(prod, sh, ref, force=False, snapshot_dir=None):
    if str(ref).startswith('release:'):
        rid = int(str(ref).split(':', 1)[1])
        rec = (prod.ro(RELEASE, 'read', [rid], fields=['state', 'branch', 'commit_sha']) or [None])[0]
        model, method, what = RELEASE, 'action_kb_release_check', '並版紀錄 #%s' % rid
        rec_id, commit, ok_state = rid, (rec or {}).get('commit_sha'), 'to_merge'
    else:
        pid = int(ref)
        rec = (prod.ro(PROPOSAL, 'read', [pid], fields=['state', 'patch_branch', 'patch_commit']) or [None])[0]
        model, method, what = PROPOSAL, 'action_kb_patch_merged', '提案 #%s' % pid
        rec_id, commit, ok_state = pid, (rec or {}).get('patch_commit'), 'to_merge'
    if not rec:
        raise ToolError('找不到%s' % what)
    if model == RELEASE and rec['state'] == 'merged':
        # 審查 F10：升級時已自動退役、轉已並版——不是錯誤
        print('%s 已經是已並版（升級時已自動退役）' % what)
        return 'merged'
    if rec['state'] != ok_state or not commit:
        raise ToolError('%s不在待合併（%s）或沒有分支 commit' % (what, rec['state']))
    git(sh, KNOWLEDGE, 'fetch', 'origin')
    code, _o = git(sh, KNOWLEDGE, 'merge-base', '--is-ancestor', commit, BASE_REF, check=False)
    if code != 0 and not force:
        print('%s 的 %s 還沒併進 %s（squash 合併的話確認後加 --force）' % (what, commit[:12], BASE_REF))
        return 'not_merged'
    # ★ 審查 F7：分支 commit 要真的升了改到的模組版號，否則「正式機版本已到」永遠成立、未部署就標已並版
    want, problems = version_bumps(sh, KNOWLEDGE, '%s^' % commit, commit)
    if problems or not want:
        print('%s 的 %s 沒有升版號，無法確認已部署：%s' % (what, commit[:12], '；'.join(problems) or '沒有模組'))
        return 'no_bump'
    have = {r['name']: r['latest_version'] for r in prod.ro(
        'ir.module.module', 'search_read', [('name', 'in', list(want))], fields=['name', 'latest_version'])} \
        if want else {}
    behind = ['%s 正式機 %s < %s' % (m, have.get(m) or '未安裝', v) for m, v in sorted(want.items())
              if _ver(have.get(m)) < _ver(v)]
    if behind:
        print('還沒部署：%s' % '；'.join(behind))
        return 'not_deployed'
    # ★ 審查 G1：版號相同不代表部署的是這個分支（兩分支可能升到同版號）——比對正式機實際的程式
    src = take_snapshot(sh, snapshot_dir)
    bad = deployed_mismatches(sh, src, commit)
    if bad:
        print('尚未部署（正式機的程式和 %s 不一致）：%s' % (commit[:12], '；'.join(bad[:10])))
        return 'not_deployed'
    version = '、'.join('%s %s' % (m, v) for m, v in sorted(want.items()))
    state = prod.rw(model, method, [rec_id], {'commit': commit, 'version': version}) \
        if method == 'action_kb_patch_merged' else prod.rw(model, method, [rec_id])
    print('%s：已確認合併與部署（%s）→ %s' % (what, version or '—', state))
    return 'merged'


# ----------------------------------------------------------------------
def cmd_list(prod):
    props = prod.ro(PROPOSAL, 'search_read', [('state', 'in', ('patching', 'patch_local', 'to_verify', 'to_merge',
                                                                  'runner_wait', 'patch_failed'))],
                    fields=['id', 'name', 'state', 'patch_note', 'patch_branch'], order='id')
    print('第 3 層源碼修補：')
    for p in props:
        print('  #%s %-12s %s %s' % (p['id'], p['state'], p['name'], (p.get('patch_note') or '')[:80]))
    rels = prod.ro(RELEASE, 'search_read', [('state', 'in', ('draft', 'exported', 'to_merge'))],
                   fields=['id', 'name', 'state', 'branch', 'note'], order='id')
    print('並版紀錄：')
    for r in rels:
        print('  #%s %-10s %s %s' % (r['id'], r['state'], r['name'], (r.get('note') or '')[:80]))
    return len(props) + len(rels)


def main(argv=None, prod=None, sh=None, claude=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list')
    v = sub.add_parser('verify')
    v.add_argument('proposal', type=int)
    v.add_argument('--no-push', action='store_true')
    v.add_argument('--dry-run', action='store_true')
    r = sub.add_parser('release')
    r.add_argument('release', type=int)
    r.add_argument('--no-verify', action='store_true')
    r.add_argument('--no-push', action='store_true')
    r.add_argument('--dry-run', action='store_true')
    g = sub.add_parser('generate', help='本機產生修補（D-KN-102）：不指定提案＝所有可修補的第 3 層提案')
    g.add_argument('proposals', type=int, nargs='*')
    g.add_argument('--dry-run', action='store_true', help='只讀：組備料與提示詞存到快取，不標狀態、不開 worktree、不跑 claude')
    g.add_argument('--no-verify', action='store_true', help='commit 後停在待驗證（之後 verify <提案> 會沿用 worktree）')
    g.add_argument('--no-push', action='store_true')
    g.add_argument('--model', help='claude 的模型（預設用 claude 自己的預設）')
    g.add_argument('--max-turns', type=int, default=CLAUDE_MAX_TURNS)
    g.add_argument('--timeout-min', type=int, default=CLAUDE_TIMEOUT // 60)
    pu = sub.add_parser('push')
    pu.add_argument('proposal', type=int)
    pu.add_argument('--dry-run', action='store_true')
    m = sub.add_parser('merged')
    m.add_argument('ref', help='<提案編號> 或 release:<並版編號>')
    m.add_argument('--force', action='store_true', help='squash 合併時跳過祖先檢查（正式機版本仍要到）')
    m.add_argument('--dry-run', action='store_true')
    m.add_argument('--snapshot-dir', help='用這份正式機快照（預設先跑 pt-verify snapshot 取最新）')
    a = ap.parse_args(argv)
    prod = prod or Prod(dry_run=getattr(a, 'dry_run', False))
    sh = sh or Shell()
    try:
        if a.cmd == 'list':
            cmd_list(prod)
            return 0
        if a.cmd == 'verify':
            res = cmd_verify(prod, sh, a.proposal, push=not a.no_push)
            return 0 if res in ('pushed', 'passed') else 1
        if a.cmd == 'release':
            res = cmd_release(prod, sh, a.release, verify=not a.no_verify, push=not a.no_push)
            return 0 if res == 'pushed' else 1
        if a.cmd == 'generate':
            res = cmd_generate_all(prod, sh, claude or Claude(), a.proposals, verify=not a.no_verify,
                                   push=not a.no_push, model=a.model, max_turns=a.max_turns,
                                   timeout=a.timeout_min * 60)
            ok = ('dry_run', 'skipped', 'pushed', 'passed', 'generated')
            return 0 if res and all(v in ok for v in res.values()) else 1
        if a.cmd == 'push':
            return 0 if cmd_push(prod, sh, a.proposal) == 'pushed' else 1
        if a.cmd == 'merged':
            return 0 if cmd_merged(prod, sh, a.ref, force=a.force, snapshot_dir=a.snapshot_dir) == 'merged' else 1
    except ToolError as e:
        print('錯誤：%s' % e, file=sys.stderr)
        return 2
    return 2


if __name__ == '__main__':
    sys.exit(main())
