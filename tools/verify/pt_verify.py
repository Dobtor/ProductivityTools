#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pt-verify：Odoo 18 模組本機驗證工具包（V0～V4）、正式機快照、部署計畫、部署後檢查。

用法見同目錄 README.md。只用 Python 標準庫，3.9 以上可跑（3.11+ 用 tomllib，否則用內建的小型 TOML 解析）。
★ 不做任何自動閘門：不掛 git hook、不接 CI；何時跑、跑哪一級由人決定。
★ 不寫正式機：snapshot 只讀（tar 原碼＋唯讀交易查已安裝模組）；deploy-plan 只產生腳本，由使用者用 `!` 執行；
  post-check 只讀。
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from types import SimpleNamespace

LEVELS = ('V0', 'V1', 'V2', 'V3', 'V4')
SERIES = '18.0'
HERE = os.path.dirname(os.path.realpath(__file__))
MOD_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')
PORT_RANGE = (8150, 8199)


# ---------------------------------------------------------------- 路徑（可用環境變數改，單元測試用）
def _p(env, default):
    return os.path.abspath(os.path.expanduser(os.environ.get(env) or default))


def gh_root():
    return _p('PT_VERIFY_GH', '~/Documents/GitHub')


def odoo_root():
    return _p('PT_VERIFY_ODOO', '~/Desktop/Claude/odoo-18.0')


def kb_home():
    return _p('PT_VERIFY_KB_HOME', '~/Library/Caches/corpaas-kb')


def venv_python():
    return os.path.join(kb_home(), 'venv', 'bin', 'python')


def core_addons_dirs():
    """Odoo 18 內建 addons＋venv site-packages 的 odoo/addons（存在才列）。"""
    dirs = [os.path.join(odoo_root(), 'odoo', 'addons'), os.path.join(odoo_root(), 'addons')]
    dirs += sorted(glob.glob(os.path.join(kb_home(), 'venv', 'lib', 'python3*', 'site-packages', 'odoo', 'addons')))
    return [d for d in dirs if os.path.isdir(d)]


def targets_file():
    return _p('PT_VERIFY_TARGETS', os.path.join(HERE, 'targets.toml'))


def overrides_file():
    return _p('PT_VERIFY_OVERRIDES', os.path.join(HERE, 'prod_overrides.toml'))


class Blocked(Exception):
    """無法驗證（缺相依、缺基準、環境不全）：verdict=BLOCKED。"""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- TOML
def load_toml(path):
    with open(path, 'rb') as f:
        text = f.read().decode('utf-8')
    try:
        import tomllib  # noqa: PLC0415  (3.11+)
        return tomllib.loads(text)
    except ImportError:
        return parse_toml_subset(text)


def _strip_comment(line):
    out, q = [], None
    for ch in line:
        if q:
            if ch == q:
                q = None
        elif ch in '"\'':
            q = ch
        elif ch == '#':
            break
        out.append(ch)
    return ''.join(out)


def _split_top(s):
    parts, buf, q, depth = [], [], None, 0
    for ch in s:
        if q:
            buf.append(ch)
            if ch == q and (len(buf) < 2 or buf[-2] != '\\' or q == "'"):
                q = None
            continue
        if ch in '"\'':
            q = ch
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(''.join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if ''.join(buf).strip():
        parts.append(''.join(buf).strip())
    return parts


def _toml_value(v):
    v = v.strip()
    if v.startswith('"'):
        return json.loads(v)
    if v.startswith("'"):
        return v[1:-1]
    if v.startswith('['):
        return [_toml_value(x) for x in _split_top(v[1:-1])]
    if v in ('true', 'false'):
        return v == 'true'
    if re.match(r'^[+-]?\d+$', v):
        return int(v)
    raise ValueError('不支援的 TOML 值：%r' % v)


def parse_toml_subset(text):
    """Python 3.9 備援：支援註解、[table]、[[array]]、字串／整數／布林／陣列（可跨行）。"""
    root, cur, pending = {}, None, ''
    cur = root
    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if pending:
            pending += ' ' + line
            if pending.count('[') > pending.count(']'):
                continue
            line, pending = pending, ''
        if not line:
            continue
        if line.startswith('[['):
            name = line[2:-2].strip().strip('"')
            root.setdefault(name, []).append({})
            cur = root[name][-1]
        elif line.startswith('['):
            name = line[1:-1].strip().strip('"')
            cur = root.setdefault(name, {})
        else:
            k, _sep, v = line.partition('=')
            v = v.strip()
            if v.startswith('[') and v.count('[') > v.count(']'):
                pending = line
                continue
            cur[k.strip().strip('"')] = _toml_value(v)
    return root


# ---------------------------------------------------------------- manifest／版本
def read_manifest(mod_dir):
    try:
        with open(os.path.join(mod_dir, '__manifest__.py'), encoding='utf-8') as f:
            return ast.literal_eval(f.read())
    except Exception:  # noqa: BLE001
        return None


def is_module(d):
    return os.path.isfile(os.path.join(d, '__manifest__.py'))


def list_modules(addons_dir):
    out = {}
    try:
        entries = sorted(os.scandir(addons_dir), key=lambda e: e.name)
    except OSError:
        return out
    for e in entries:
        if e.is_dir() and not e.name.startswith('.') and is_module(e.path):
            out[e.name] = e.path
    return out


def adjust_version(v, series=SERIES):
    """同 Odoo 的 adjust_version：沒有 18.0. 前綴就補上。"""
    v = str(v or '').strip()
    if v == series or not v.startswith(series + '.'):
        v = '%s.%s' % (series, v) if v else series
    return v


def vparse(v):
    return tuple(int(x) if x.isdigit() else 0 for x in adjust_version(v).split('.'))


def manifest_series(v):
    """'14.0.1.0.0'／'18.0.1.0' → 14／18；'1.0'、'0.1' 這種沒帶系列的回 None。"""
    m = re.match(r'^(\d+)\.0\.', str(v or ''))
    return int(m.group(1)) if m and int(m.group(1)) >= 7 else None


# ---------------------------------------------------------------- 工作區模組索引
def _is_odoo_source(p):
    return os.path.isfile(os.path.join(p, 'odoo-bin'))


def _is_worktree_checkout(p):
    return os.path.isfile(os.path.join(p, '.git'))


def _has_modules(p):
    try:
        return any(e.is_dir() and is_module(e.path) for e in os.scandir(p))
    except OSError:
        return False


def scan_repo_dirs(root, exclude=(), skip_worktrees=True):
    """root 下的 addons 目錄：第一層（repo）或第二層（如 OCA/<repo>）。

    排除：隱藏目錄、*-worktrees、Odoo 原碼樹（有 odoo-bin）、git worktree 檢出（.git 是檔案）、exclude 指定的路徑。
    """
    excl = {os.path.realpath(x) for x in exclude}
    out = []

    def ok(p, name):
        if name.startswith('.') or name.endswith('-worktrees') or name in ('__pycache__', 'node_modules'):
            return False
        if os.path.realpath(p) in excl or _is_odoo_source(p):
            return False
        if skip_worktrees and _is_worktree_checkout(p):
            return False
        return True

    try:
        top = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return out
    for e in top:
        if not e.is_dir() or not ok(e.path, e.name) or is_module(e.path):
            continue
        if _has_modules(e.path):
            out.append((e.path, 1))
            continue
        try:
            subs = sorted(os.scandir(e.path), key=lambda s: s.name)
        except OSError:
            continue
        for s in subs:
            if s.is_dir() and ok(s.path, s.name) and not is_module(s.path) and _has_modules(s.path):
                out.append((s.path, 2))
    return out


class ModuleIndex:
    """~/Documents/GitHub（或 PT_VERIFY_GH）下所有 repo 的模組：name → 候選清單。"""

    def __init__(self, root=None, exclude=()):
        self.root = root or gh_root()
        self.repos = scan_repo_dirs(self.root, exclude)
        self.mods = {}
        for repo, depth in self.repos:
            for name, path in list_modules(repo).items():
                man = read_manifest(path) or {}
                self.mods.setdefault(name, []).append({
                    'name': name, 'path': path, 'repo': repo, 'depth': depth,
                    'version': man.get('version'), 'installable': man.get('installable', True) is not False,
                    'series': manifest_series(man.get('version')),
                })

    def choose(self, name, prefer_repos=()):
        """回 (候選, 說明)。

        優先序：可安裝且系列 18（或沒標系列）→ 已經被選用的 repo（同一套相依盡量來自同一批 repo）
        → manifest 版號較高 → 第一層 repo → repo 名字母序。
        """
        cands = [c for c in self.mods.get(name, []) if c['installable'] and c['series'] in (None, 18)]
        if not cands:
            others = self.mods.get(name, [])
            if others:
                return None, '模組 %s 只在不相容的位置：%s' % (
                    name, '；'.join('%s（version %s%s）' % (c['repo'], c['version'], '' if c['installable'] else '，installable=False')
                                   for c in others))
            return None, None
        prefer = set(prefer_repos)
        cands.sort(key=lambda c: (c['series'] != 18, c['repo'] not in prefer,
                                  tuple(-x for x in vparse(c['version'])), c['depth'],
                                  os.path.basename(c['repo']).lower()))
        note = None
        if len(cands) > 1:
            note = '模組 %s 在多個 repo：%s；採用 %s' % (name, '、'.join(c['repo'] for c in cands), cands[0]['repo'])
        return cands[0], note

    def ambiguous(self, name):
        return len([c for c in self.mods.get(name, []) if c['installable'] and c['series'] in (None, 18)]) > 1


def resolve_addons(mods, first=(), layers=(), index=None, core=None, include_all_layers=False):
    """從 mods 的 manifest depends 遞迴推導 addons 路徑。

    first：排最前面的目錄（受測 repo／worktree）；layers：其次優先的目錄（覆寫、正式機快照 repo）；
    core：Odoo 內建（預設 core_addons_dirs()）；index：工作區 ModuleIndex（找不到才用）。
    回 dict(addons, resolved{name: (path, dir, source)}, blocked[], notes[])。
    """
    core = core_addons_dirs() if core is None else list(core)
    pri = [d for d in list(first) + list(layers) if d]
    maps = {d: list_modules(d) for d in pri}
    core_map = {}
    for d in core:
        for n, p in list_modules(d).items():
            core_map.setdefault(n, (p, d))
    resolved, blocked, notes, parent = {}, [], [], {}
    seen, deferred = set(), set()
    queue = list(mods)
    while queue:
        m = queue.pop(0)
        if m in seen:
            continue
        seen.add(m)
        loc = None
        for d in pri:
            if m in maps[d]:
                loc = (maps[d][m], d, 'first' if d in first else 'layer')
                break
        if loc is None and m in core_map:
            resolved[m] = (core_map[m][0], core_map[m][1], 'core')
            continue
        if loc is None and index is not None:
            if index.ambiguous(m) and queue and m not in deferred:
                # 多個 repo 都有：先處理其他模組，看哪些 repo 已被選用再決定
                deferred.add(m)
                seen.discard(m)
                queue.append(m)
                continue
            cand, note = index.choose(m, prefer_repos={v[1] for v in resolved.values() if v[2] == 'workspace'})
            if note:
                notes.append(note)
            if cand:
                loc = (cand['path'], cand['repo'], 'workspace')
        if loc is None:
            who = ('（%s 依賴它）' % parent[m]) if parent.get(m) else '（受測模組）'
            blocked.append('找不到模組 %s%s：受測 repo、Odoo 內建、%s 下都沒有可用的 18.0 版本'
                           % (m, who, index.root if index else '工作區'))
            continue
        resolved[m] = loc
        man = read_manifest(loc[0]) or {}
        if man.get('installable', True) is False:
            blocked.append('模組 %s 標為 installable=False（%s）' % (m, loc[0]))
        for dep in man.get('depends', []) or []:
            if dep not in seen:
                parent.setdefault(dep, m)
                queue.append(dep)
    addons = []

    def add(d):
        if d not in addons:
            addons.append(d)
    for d in first:
        if d:
            add(d)
    used = {loc[1] for loc in resolved.values()}
    for d in layers:
        if d and (include_all_layers or d in used):
            add(d)
    for d in core:
        add(d)
    for m in sorted(resolved, key=lambda n: list(resolved).index(n)):
        if resolved[m][2] == 'workspace':
            add(resolved[m][1])
    # 遮蔽檢查：addons 路徑上第一個出現的同名模組必須就是推導選中的那份；可以的話把選中的目錄往前挪
    def shadows():
        out = []
        for m, (_path, d, src) in resolved.items():
            if src == 'core':
                continue
            for a in addons:
                if os.path.isfile(os.path.join(a, m, '__manifest__.py')):
                    if os.path.realpath(a) != os.path.realpath(d):
                        out.append((m, d, a))
                    break
        return out
    fixed = list(first) + list(core)
    for _i in range(len(addons) * 2):
        sh = [x for x in shadows() if x[1] not in fixed and x[2] not in fixed]
        if not sh:
            break
        _m, d, a = sh[0]
        addons.remove(d)
        addons.insert(addons.index(a), d)
    for m, d, a in shadows():
        notes.append('⚠ 遮蔽：模組 %s 推導用 %s，但 addons 路徑上 %s 排在前面' % (m, d, a))
    return {'addons': addons, 'resolved': resolved, 'blocked': blocked, 'notes': notes}


def reverse_deps(mods, universe):
    """universe：{name: 模組目錄}；回傳 mods 在 universe 內的（遞移）反向相依（不含 mods 本身）。"""
    deps = {n: set((read_manifest(p) or {}).get('depends', []) or []) for n, p in universe.items()}
    out, frontier = set(), set(mods)
    while frontier:
        nxt = {n for n, d in deps.items() if d & frontier and n not in out and n not in mods}
        out |= nxt
        frontier = nxt
    return out


# ---------------------------------------------------------------- git
def git(repo, *args, check=True):
    r = subprocess.run(['git', '-C', repo] + list(args), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Blocked('git %s 失敗：%s' % (' '.join(args), r.stderr.strip()[:300]))
    return r.stdout


def repo_info(path):
    path = os.path.realpath(path)
    sha = git(path, 'rev-parse', 'HEAD').strip()
    branch = git(path, 'rev-parse', '--abbrev-ref', 'HEAD').strip()
    # ★ 不用 --path-format=absolute：git < 2.31（本機 /usr/local/bin/git 是 2.19）不認得，會把它原樣印出、
    #   回傳 0，main_repo 變成垃圾路徑 → V0-2 沒排除主 repo，同一模組自己跟自己撞名。
    common = git(path, 'rev-parse', '--git-common-dir').strip()
    common = os.path.realpath(common if os.path.isabs(common) else os.path.join(path, common))
    main = os.path.dirname(common) if os.path.basename(common) == '.git' else path
    return {'path': path, 'sha': sha, 'branch': branch, 'main_repo': main, 'name': os.path.basename(main),
            'dirty': bool(git(path, 'status', '--porcelain', check=False).strip())}


def default_base_ref(repo):
    for ref in ('origin/HEAD', 'origin/dev-18.0', '@{upstream}'):
        r = subprocess.run(['git', '-C', repo, 'rev-parse', '--verify', '--quiet', ref + '^{commit}'],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return ref
    return None


def changed_modules_git(repo, diff_sha):
    names = git(repo, 'diff', '--name-only', diff_sha, '--').splitlines()
    names += git(repo, 'ls-files', '--others', '--exclude-standard').splitlines()
    out = set()
    for n in names:
        top = n.split('/')[0]
        if top and is_module(os.path.join(repo, top)):
            out.add(top)
    return sorted(out)


def tree_digest(path):
    """{相對路徑: md5}；排除 __pycache__、.pyc、.git、符號連結（與遠端 find -type f 一致）。"""
    out = {}
    for d, dirs, files in os.walk(path):
        dirs[:] = sorted(x for x in dirs if x not in ('__pycache__', '.git'))
        for f in files:
            p = os.path.join(d, f)
            if f.endswith('.pyc') or os.path.islink(p):
                continue
            with open(p, 'rb') as fh:
                out[os.path.relpath(p, path)] = hashlib.md5(fh.read()).hexdigest()
    return out


def archive_tree(repo, sha, dest):
    os.makedirs(dest, exist_ok=True)
    p1 = subprocess.Popen(['git', '-C', repo, 'archive', '--format=tar', sha], stdout=subprocess.PIPE)
    p2 = subprocess.run(['tar', '-x', '-C', dest], stdin=p1.stdout, capture_output=True)
    p1.stdout.close()
    if p1.wait() != 0 or p2.returncode != 0:
        raise Blocked('git archive %s 失敗：%s' % (sha, p2.stderr.decode(errors='replace')[:300]))
    return dest


# ---------------------------------------------------------------- V0 靜態檢查
NAME_ASSIGN_RE = re.compile(r'''^\s*_name\s*=\s*['"]([\w.]+)['"]''')


def _py_files(mod_dir):
    for d, dirs, files in os.walk(mod_dir):
        dirs[:] = [x for x in dirs if x not in ('__pycache__', 'node_modules', 'static')]
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(d, f)


def _xml_files(mod_dir):
    for d, dirs, files in os.walk(mod_dir):
        dirs[:] = [x for x in dirs if x not in ('__pycache__', 'node_modules', 'static', 'i18n')]
        for f in files:
            if f.endswith('.xml'):
                yield os.path.join(d, f)


def model_classes(py_path):
    """檔案內的模型類別：[(name, inherit[], kind)]；kind＝Model／TransientModel／AbstractModel／?。"""
    try:
        with open(py_path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
    except Exception:  # noqa: BLE001
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        name, inherit = None, []
        for st in node.body:
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                key = st.targets[0].id
                try:
                    val = ast.literal_eval(st.value)
                except Exception:  # noqa: BLE001
                    continue
                if key == '_name' and isinstance(val, str):
                    name = val
                elif key == '_inherit':
                    inherit = [val] if isinstance(val, str) else list(val or [])
        if not name:
            continue
        kind = '?'
        for b in node.bases:
            attr = b.attr if isinstance(b, ast.Attribute) else (b.id if isinstance(b, ast.Name) else '')
            if attr in ('Model', 'TransientModel', 'AbstractModel'):
                kind = attr
        out.append((name, inherit, kind))
    return out


def module_model_names(mod_dir):
    names = set()
    for py in _py_files(mod_dir):
        for name, _inh, _k in model_classes(py):
            names.add(name)
    return names


def module_xmlids(mod_dir):
    """模組自己定義的 xmlid（XML 的 id 屬性、CSV 的 id 欄、模型自動產生的 model_*）。"""
    ids = set()
    for x in _xml_files(mod_dir):
        try:
            root = ET.parse(x).getroot()
        except ET.ParseError:
            continue
        for el in root.iter():
            i = el.get('id')
            if i and el.tag in ('record', 'template', 'menuitem', 'report', 'act_window', 'asset'):
                ids.add(i.split('.', 1)[1] if '.' in i and i.split('.', 1)[0] == os.path.basename(mod_dir) else i)
    for d, _dirs, files in os.walk(mod_dir):
        for f in files:
            if f.endswith('.csv'):
                try:
                    with open(os.path.join(d, f), encoding='utf-8') as fh:
                        rows = fh.read().splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                if rows and rows[0].split(',')[0].strip().strip('"') == 'id':
                    for r in rows[1:]:
                        v = r.split(',')[0].strip().strip('"')
                        if v:
                            ids.add(v)
    for n in module_model_names(mod_dir):
        ids.add('model_' + n.replace('.', '_'))
    return ids


REF_EVAL_RE = re.compile(r'''ref\(\s*['"]([\w.]+)['"]\s*\)''')
AUTO_PREFIXES = ('field_', 'selection__', 'module_category_', 'module_')


def check_xml_refs(repo, mods, repo_mods):
    issues, cache = [], {}

    def defined(m):
        if m not in cache:
            cache[m] = module_xmlids(repo_mods[m])
        return cache[m]
    for m in mods:
        for x in _xml_files(repo_mods[m]):
            rel = os.path.relpath(x, repo)
            try:
                root = ET.parse(x).getroot()
            except ET.ParseError as e:
                issues.append({'rule': 'V0-4 xml', 'module': m, 'file': rel, 'msg': 'XML 解析失敗：%s' % e})
                continue
            for el in root.iter():
                refs = []
                for attr in ('ref', 'inherit_id'):
                    if el.get(attr):
                        refs.append((attr, el.get(attr)))
                for attr in ('eval',):
                    for r in REF_EVAL_RE.findall(el.get(attr) or ''):
                        refs.append(('eval ref()', r))
                for attr, r in refs:
                    tm, name = r.split('.', 1) if '.' in r else (m, r)
                    if tm not in repo_mods:
                        continue  # 只檢查本模組或本 repo 模組的參照
                    if name.startswith(AUTO_PREFIXES):
                        continue
                    if name not in defined(tm):
                        issues.append({'rule': 'V0-4 xmlid', 'module': m, 'file': rel,
                                       'msg': '%s="%s" 指向 %s 裡不存在的 xmlid' % (attr, r, tm)})
    return issues


def new_model_names(repo, diff_sha, mods, repo_mods):
    """diff 新增行（含未追蹤檔）裡的 _name，且確實是「新模型」（_name 不在 _inherit、基準版本 repo 內沒有）。"""
    added = {}
    if diff_sha:
        cur = None
        for line in git(repo, 'diff', '-U0', diff_sha, '--', '*.py').splitlines():
            if line.startswith('+++ '):
                cur = line[6:] if line.startswith('+++ b/') else None
            elif line.startswith('+') and cur:
                mm = NAME_ASSIGN_RE.match(line[1:])
                if mm:
                    added.setdefault(mm.group(1), set()).add(cur)
        for f in git(repo, 'ls-files', '--others', '--exclude-standard', '--', '*.py').splitlines():
            try:
                with open(os.path.join(repo, f), encoding='utf-8') as fh:
                    for ln in fh:
                        mm = NAME_ASSIGN_RE.match(ln)
                        if mm:
                            added.setdefault(mm.group(1), set()).add(f)
            except (OSError, UnicodeDecodeError):
                pass
    out = []
    for name, files in sorted(added.items()):
        for f in sorted(files):
            mod = f.split('/')[0]
            if mod not in mods or mod not in repo_mods:
                continue
            for cname, inherit, kind in model_classes(os.path.join(repo, f)):
                if cname == name and name not in inherit:
                    # 基準版本的本 repo 已有同名 _name＝搬家，不算新增
                    pat = r'''_name\s*=\s*['"]%s['"]''' % re.escape(name)
                    r = subprocess.run(['git', '-C', repo, 'grep', '-q', '-E', pat, diff_sha, '--', '*.py'],
                                       capture_output=True)
                    if r.returncode != 0:
                        out.append({'name': name, 'module': mod, 'file': f, 'kind': kind})
    return out


def search_model_elsewhere(names, exclude):
    """在工作區所有 repo（排除自己、worktrees、其他版本 Odoo 原碼樹）＋Odoo 18 內建找已存在的 _name。"""
    if not names:
        return {}
    excl = {os.path.realpath(x) for x in exclude}
    dirs = []
    try:
        for e in sorted(os.scandir(gh_root()), key=lambda e: e.name):
            if (e.is_dir() and not e.name.startswith('.') and not e.name.endswith('-worktrees')
                    and os.path.realpath(e.path) not in excl and not _is_odoo_source(e.path)
                    and not _is_worktree_checkout(e.path)):
                dirs.append(e.path)
    except OSError:
        pass
    dirs += [d for d in (os.path.join(odoo_root(), 'addons'), os.path.join(odoo_root(), 'odoo', 'addons')) if os.path.isdir(d)]
    if not dirs:
        return {}
    pat = r'''_name\s*=\s*['"](%s)['"]''' % '|'.join(re.escape(n) for n in names)
    cmd = ['grep', '-rlE', '--include=*.py', '--exclude-dir=.git', '--exclude-dir=node_modules',
           '--exclude-dir=*-worktrees', '--exclude-dir=__pycache__', '--exclude-dir=tests', pat] + dirs
    r = subprocess.run(cmd, capture_output=True, text=True)
    found = {}
    rx = re.compile(pat)
    for f in r.stdout.splitlines():
        if any(os.path.realpath(f).startswith(x + os.sep) for x in excl):
            continue
        try:
            with open(f, encoding='utf-8', errors='replace') as fh:
                for mm in rx.finditer(fh.read()):
                    found.setdefault(mm.group(1), []).append(f)
        except OSError:
            pass
    return found


def access_csv_models(mod_dir):
    ids = set()
    for d, _dirs, files in os.walk(mod_dir):
        for f in files:
            if f.endswith('.csv'):
                try:
                    with open(os.path.join(d, f), encoding='utf-8') as fh:
                        rows = fh.read().splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                if not rows:
                    continue
                head = [h.strip().strip('"') for h in rows[0].split(',')]
                if 'model_id:id' not in head:
                    continue
                k = head.index('model_id:id')
                for r in rows[1:]:
                    cols = r.split(',')
                    if len(cols) > k:
                        ids.add(cols[k].strip().strip('"').split('.')[-1])
    return ids


def v0_checks(repo, mods, diff_sha, exclude_repos=()):
    """回 issues[]：{rule, module, file, msg, severity(error/warn)}。"""
    repo_mods = list_modules(repo)
    issues = []
    # (5) Python 語法
    for m in mods:
        for py in _py_files(repo_mods[m]):
            try:
                with open(py, encoding='utf-8') as f:
                    ast.parse(f.read(), filename=py)
            except SyntaxError as e:
                issues.append({'rule': 'V0-5 語法', 'module': m, 'file': os.path.relpath(py, repo),
                               'msg': 'SyntaxError 第 %s 行：%s' % (e.lineno, e.msg)})
            except UnicodeDecodeError as e:
                issues.append({'rule': 'V0-5 語法', 'module': m, 'file': os.path.relpath(py, repo), 'msg': str(e)})
    # (1) 新的 migrations/<版號>/ 與 manifest 版號
    for m in mods:
        man = read_manifest(repo_mods[m])
        if man is None:
            issues.append({'rule': 'V0-1 manifest', 'module': m, 'file': m + '/__manifest__.py', 'msg': 'manifest 無法解析'})
            continue
        ver = man.get('version', '')
        base_ver = None
        if diff_sha:
            r = subprocess.run(['git', '-C', repo, 'show', '%s:%s/__manifest__.py' % (diff_sha, m)],
                               capture_output=True, text=True)
            if r.returncode == 0:
                try:
                    base_ver = ast.literal_eval(r.stdout).get('version')
                except Exception:  # noqa: BLE001
                    base_ver = None
        mig = os.path.join(repo_mods[m], 'migrations')
        if not os.path.isdir(mig):
            continue
        for vd in sorted(os.listdir(mig)):
            if not os.path.isdir(os.path.join(mig, vd)) or vd == 'tests':
                continue
            if diff_sha:
                r = subprocess.run(['git', '-C', repo, 'cat-file', '-e', '%s:%s/migrations/%s' % (diff_sha, m, vd)],
                                   capture_output=True)
                if r.returncode == 0:
                    continue  # 基準就有，不是新的
            if vparse(vd) > vparse(ver):
                issues.append({'rule': 'V0-1 migration', 'module': m, 'file': '%s/migrations/%s' % (m, vd),
                               'msg': '新增 migrations/%s，但 manifest 版號只有 %s（升級時不會跑）' % (vd, ver)})
            elif base_ver and vparse(vd) <= vparse(base_ver):
                issues.append({'rule': 'V0-1 migration', 'module': m, 'file': '%s/migrations/%s' % (m, vd),
                               'severity': 'warn',
                               'msg': 'migrations/%s 不高於基準版號 %s：從基準升級時不會執行' % (vd, base_ver)})
    # (2)(3) 新模型
    news = new_model_names(repo, diff_sha, set(mods), repo_mods) if diff_sha else []
    elsewhere = search_model_elsewhere(sorted({n['name'] for n in news}), exclude_repos)
    for n in news:
        if n['name'] in elsewhere:
            issues.append({'rule': 'V0-2 _name 重複', 'module': n['module'], 'file': n['file'],
                           'msg': '新增的 _name = %r 已存在於：%s' % (n['name'], '、'.join(sorted(set(elsewhere[n['name']]))[:5]))})
        if n['kind'] in ('Model', 'TransientModel'):
            want = 'model_' + n['name'].replace('.', '_')
            if want not in access_csv_models(repo_mods[n['module']]):
                issues.append({'rule': 'V0-3 存取權限', 'module': n['module'], 'file': n['file'],
                               'msg': '新模型 %s 在 ir.model.access.csv 沒有 %s 列' % (n['name'], want)})
    # (4) XML 參照
    issues += check_xml_refs(repo, mods, repo_mods)
    for i in issues:
        i.setdefault('severity', 'error')
    return issues


# ---------------------------------------------------------------- 資料庫／port／Odoo 執行
def make_db_name(repo, branch, level, when=None, suffix=''):
    def norm(s):
        return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', (s or '').lower())).strip('_')
    when = when or dt.datetime.now()
    r, b = norm(repo) or 'repo', norm((branch or 'head').split('/')[-1]) or 'head'
    tail = '%s_%s%s' % (norm(level), when.strftime('%H%M'), norm(suffix) and '_' + norm(suffix))
    budget = 60 - len('v__') - len(tail) - 1
    if len(r) + len(b) > budget:
        rb = max(budget // 2, budget - len(b))
        r = r[:rb].strip('_')
        b = b[:budget - len(r)].strip('_')
    name = '_'.join(x for x in ('v', r, b, tail) if x)
    return re.sub(r'_+', '_', name)[:60].strip('_')


def port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('', port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port(lo=PORT_RANGE[0], hi=PORT_RANGE[1], is_free=port_free):
    for p in range(lo, hi + 1):
        if is_free(p):
            return p
    return None


_PG_SCRIPT = r'''
import json, sys, psycopg2
a = json.load(sys.stdin)
cn = psycopg2.connect(host=a["host"], dbname=a["db"], user=a["user"], password=a["password"])
cn.autocommit = True
cur = cn.cursor()
cur.execute(a["sql"], a.get("params"))
print(json.dumps(cur.fetchall() if cur.description else [], default=str))
'''


class Pg:
    """本機 pgserver（~/Library/Caches/corpaas-kb/pgdata）；查詢走 venv 的 psycopg2。"""

    def __init__(self):
        self.user = os.environ.get('PT_VERIFY_DB_USER', 'odoo')
        self.password = os.environ.get('PT_VERIFY_DB_PASSWORD', 'odoo')
        self.host = None

    def start(self):
        code = ("import pgserver,sys; s=pgserver.get_server(sys.argv[1], cleanup_mode=None); "
                "print(s.get_uri().split('host=')[1])")
        r = subprocess.run([venv_python(), '-c', code, os.path.join(kb_home(), 'pgdata')], capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            raise Blocked('pgserver 起不來：%s' % (r.stderr.strip()[-400:] or r.stdout))
        self.host = r.stdout.strip().splitlines()[-1].strip()
        with open(os.path.join(kb_home(), 'pg_host'), 'w') as f:
            f.write(self.host)
        return self.host

    def q(self, sql, params=None, db='postgres'):
        r = subprocess.run([venv_python(), '-c', _PG_SCRIPT], capture_output=True, text=True,
                           input=json.dumps({'host': self.host, 'db': db, 'user': self.user, 'password': self.password,
                                             'sql': sql, 'params': params}))
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-400:])
        return json.loads(r.stdout or '[]')

    def exists(self, db):
        return bool(self.q('select 1 from pg_database where datname=%s', [db]))

    def drop(self, db):
        self.q('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % db.replace('"', ''))
        fs = os.path.join(kb_home(), 'data', 'filestore', db)
        if os.path.isdir(fs):
            shutil.rmtree(fs, ignore_errors=True)

    def module_states(self, db, names):
        if not names:
            return {}
        rows = self.q('select name, state, latest_version from ir_module_module where name = any(%s)', [list(names)], db=db)
        return {r[0]: {'state': r[1], 'version': r[2]} for r in rows}


def odoo_cmd(db, addons, port, pg, install=(), update=(), test_mods=(), log_level='test'):
    cmd = [venv_python(), os.path.join(odoo_root(), 'odoo-bin'), '-d', db,
           '--data-dir', os.path.join(kb_home(), 'data'), '--db_host', pg.host or '',
           '--db_user', pg.user, '--db_password', pg.password, '--addons-path', ','.join(addons)]
    if install:
        cmd += ['-i', ','.join(sorted(install))]
    if update:
        cmd += ['-u', ','.join(sorted(update))]
    if test_mods:
        cmd += ['--test-enable', '--test-tags', ','.join('/' + m for m in sorted(test_mods))]
    cmd += ['--without-demo=all', '--workers=0', '--max-cron-threads=0', '--http-port', str(port),
            '--stop-after-init', '--log-level', log_level]
    return cmd


def show_cmd(cmd):
    """指令字串（--db_password 的值遮掉）。"""
    out = list(cmd)
    for i, c in enumerate(out[:-1]):
        if c == '--db_password':
            out[i + 1] = '***'
    return ' '.join(shlex.quote(c) for c in out)


def run_odoo(cmd, log_path, timeout_min):
    log('▶ %s\n  log：%s' % (' '.join(cmd[2:6]) + ' …', log_path))
    with open(log_path, 'w') as lf:
        try:
            env = dict(os.environ)
            # corpaas-kb/bin 放 cloc 等外部相依（github_connector 的 external_dependencies）
            env['PATH'] = os.path.join(kb_home(), 'bin') + os.pathsep + env.get('PATH', '')
            r = subprocess.run(cmd, cwd=odoo_root(), stdout=lf, stderr=subprocess.STDOUT, env=env,
                               timeout=timeout_min * 60)
            return r.returncode
        except subprocess.TimeoutExpired:
            lf.write('\nPT-VERIFY: TIMEOUT after %s min\n' % timeout_min)
            return 124


RESULT_RE = re.compile(r'odoo\.tests\.result: (\d+) failed, (\d+) error\(s\) of (\d+) tests')
LINE_RE = re.compile(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \d+ (\w+) (\S+) ([\w.]+): (.*)$')
TESTFAIL_RE = re.compile(r'^(FAIL|ERROR): (.+?)\s*$')
SKIP_RE = re.compile(r'^skipped (\w+\.\w+)')
MIG_RE = re.compile(r'module (\w+): Running migration \[([^\]]*)\] ([\w-]+)')
LOAD_FAIL_PATTERNS = ('Failed to load registry', 'invalid module names, ignored', 'Some modules are not loaded',
                      'Some modules have inconsistent states', 'PT-VERIFY: TIMEOUT')
# 升級時新版 manifest 多了相依，Odoo 會先記 INFO「Unmet dependencies」再把新相依裝上：不算錯，但要提醒（部署要一起帶）
UNMET_RE = re.compile(r'module (\w+): Unmet dependencies: (.+?)\s*$')


def failure_name(text):
    m = re.match(r'^setUpClass \((?:[\w.]+\.)?(\w+)\)', text)
    if m:
        return '%s.setUpClass' % m.group(1)
    m = re.match(r'^(\w+)\.(\w+)', text)
    if m:
        return '%s.%s' % (m.group(1), m.group(2))
    return text[:160]


def parse_log(path):
    res = {'tests_total': 0, 'failed': 0, 'errors': 0, 'skipped': 0, 'failures': [], 'migrations_ran': [],
           'log_errors': [], 'load_errors': [], 'result_seen': False, 'unmet': []}
    skipped, failures = set(), []
    try:
        fh = open(path, encoding='utf-8', errors='replace')
    except OSError:
        res['load_errors'].append('log 不存在：%s' % path)
        return res
    with fh:
        for line in fh:
            line = line.rstrip('\n')
            m = RESULT_RE.search(line)
            if m:
                res['failed'], res['errors'], res['tests_total'] = int(m.group(1)), int(m.group(2)), int(m.group(3))
                res['result_seen'] = True
            m = UNMET_RE.search(line)
            if m:
                u = '%s 需要 %s' % (m.group(1), m.group(2))
                if u not in res['unmet']:
                    res['unmet'].append(u)
            m = MIG_RE.search(line)
            if m:
                res['migrations_ran'].append('%s %s %s' % (m.group(1), m.group(2), m.group(3)))
            for p in LOAD_FAIL_PATTERNS:
                if p in line:
                    res['load_errors'].append(line[:300])
            lm = LINE_RE.match(line)
            if not lm:
                continue
            level, logger, msg = lm.group(1), lm.group(3), lm.group(4)
            sm = SKIP_RE.match(msg)
            if sm:
                skipped.add(sm.group(1))
            if level not in ('ERROR', 'CRITICAL'):
                continue
            tm = TESTFAIL_RE.match(msg)
            if tm:
                n = failure_name(tm.group(2))
                if n not in failures:
                    failures.append(n)
                continue
            if logger.startswith('odoo.tests.result') or logger.startswith('odoo.tests.stats'):
                continue
            if level == 'CRITICAL':
                res['load_errors'].append(line[:300])
            if len(res['log_errors']) < 30:
                res['log_errors'].append('%s %s: %s' % (level, logger, msg[:200]))
    res['skipped'] = len(skipped)
    res['failures'] = failures
    res['load_errors'] = list(dict.fromkeys(res['load_errors']))[:20]
    return res


# ---------------------------------------------------------------- 快照、覆寫、已知不穩定
def load_targets():
    data = load_toml(targets_file())
    return {t['name']: t for t in data.get('target', [])}


def get_target(name):
    ts = load_targets()
    if name not in ts:
        raise SystemExit('未知的目標 %s；targets.toml 裡有：%s' % (name, '、'.join(ts)))
    return ts[name]


def load_overrides(target):
    path = overrides_file()
    if not os.path.isfile(path):
        return []
    return [o for o in load_toml(path).get('override', []) if o.get('target') == target]


def read_installed(path):
    """installed.json（{installed:{name:ver}} 或 {name:ver} 或 [name]）或文字檔（逗號／換行分隔）。"""
    with open(path, encoding='utf-8') as f:
        text = f.read()
    if path.endswith('.json'):
        data = json.loads(text)
        data = data.get('installed', data) if isinstance(data, dict) else data
        return dict(data) if isinstance(data, dict) else {n: None for n in data}
    return {n.strip(): None for n in re.split(r'[,\s]+', text) if n.strip()}


def latest_snapshot_dir(target):
    base = os.path.join(kb_home(), 'prod', target)
    days = sorted(d for d in os.listdir(base) if re.match(r'^\d{8}$', d)) if os.path.isdir(base) else []
    return os.path.join(base, days[-1]) if days else None


def load_snapshot(target=None, snapshot_dir=None, installed=None):
    d = snapshot_dir or (latest_snapshot_dir(target) if target else None)
    if not d:
        return None
    d = os.path.abspath(os.path.expanduser(d))
    src = os.path.join(d, 'src') if os.path.isdir(os.path.join(d, 'src')) else d
    inst_path = installed or next((p for p in (os.path.join(d, 'installed.json'), os.path.join(d, 'installed.txt'))
                                   if os.path.isfile(p)), None)
    inst = read_installed(inst_path) if inst_path else None
    return {'dir': d, 'src': src, 'installed': inst, 'installed_file': inst_path, 'target': target,
            'date': os.path.basename(d) if re.match(r'^\d{8}$', os.path.basename(d)) else None}


def snapshot_layers(snap):
    return [p for p, _d in scan_repo_dirs(snap['src'], skip_worktrees=False)]


def snapshot_module_map(snap):
    out = {}
    for layer in snapshot_layers(snap):
        for n, p in list_modules(layer).items():
            out.setdefault(n, p)
    return out


def load_known_flaky(repo):
    path = os.path.join(repo, '.claude', 'skills', 'verify', 'known_flaky.txt')
    out = {}
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(None, 1)
                out[parts[0]] = parts[1].strip() if len(parts) > 1 else ''
    return out


def new_failures(failures, baseline, flaky):
    base = set(baseline or ())
    return [f for f in failures if f not in base and f not in flaky]


def cache_key(base_sha, level, mods, extra=''):
    raw = '%s|%s|%s|%s' % (base_sha, level, ','.join(sorted(mods)), extra)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def cache_path(key):
    return os.path.join(kb_home(), 'verify-cache', key + '.json')


# ---------------------------------------------------------------- 報告
REPORT_FIELDS = ('level', 'repo', 'branch', 'sha', 'base', 'mods', 'db', 'port', 'command', 'tests_total', 'failed',
                 'errors', 'skipped', 'new_failures', 'migrations_ran', 'versions_before', 'versions_after',
                 'overrides', 'log', 'duration', 'verdict')


def new_report(level, repo):
    r = {k: None for k in REPORT_FIELDS}
    r.update({'level': level, 'repo': repo, 'tests_total': 0, 'failed': 0, 'errors': 0, 'skipped': 0,
              'new_failures': [], 'migrations_ran': [], 'versions_before': {}, 'versions_after': {}, 'overrides': [],
              'mods': [], 'verdict': None, 'notes': [], 'blocked_reasons': [], 'v0_issues': [], 'failures': [],
              'baseline_failures': None, 'known_flaky_hit': [], 'load_errors': [], 'log_errors': [],
              'logs': [], 'addons_path': [], 'install': [], 'invocation': ' '.join(shlex.quote(a) for a in sys.argv)})
    return r


def decide_verdict(rep, test_mods_with_tests=()):
    if rep['blocked_reasons']:
        return 'BLOCKED'
    reasons = []
    if any(i.get('severity') == 'error' for i in rep['v0_issues']):
        reasons.append('V0 靜態檢查有錯')
    if rep['new_failures']:
        reasons.append('新增失敗 %d 項' % len(rep['new_failures']))
    if rep['load_errors']:
        reasons.append('載入／安裝錯誤')
    if rep['level'] != 'V0' and test_mods_with_tests and not rep['tests_total']:
        reasons.append('有 tests/ 的模組卻沒跑到任何測試')
    rep['fail_reasons'] = reasons
    return 'FAIL' if reasons else 'PASS'


def write_report(rep, out_dir, stamp):
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, '%s-%s' % (stamp, rep['level']))
    n = 2
    while os.path.exists(base + '.json'):
        base = os.path.join(out_dir, '%s-%s-%d' % (stamp, rep['level'], n))
        n += 1
    with open(base + '.json', 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=2, default=str)
    L = ['# pt-verify %s：%s（%s）' % (rep['level'], rep['verdict'], rep['repo']), '']
    L += ['| 欄位 | 值 |', '|---|---|']
    for k in REPORT_FIELDS:
        v = rep.get(k)
        if isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False) if v else '—'
        L.append('| %s | %s |' % (k, str(v if v not in (None, '') else '—').replace('|', '\\|').replace('\n', ' ')))
    for title, key in (('不通過原因', 'fail_reasons'), ('BLOCKED 原因', 'blocked_reasons'), ('說明', 'notes'),
                       ('全部失敗', 'failures'), ('已知不穩定（略過）', 'known_flaky_hit'), ('載入錯誤', 'load_errors'),
                       ('非測試的 ERROR log（僅供參考，不影響判定）', 'log_errors'), ('安裝模組', 'install'),
                       ('addons 路徑', 'addons_path'), ('所有 log', 'logs')):
        if rep.get(key):
            L += ['', '## ' + title, ''] + ['- %s' % x for x in rep[key]]
    if rep.get('v0_issues'):
        L += ['', '## V0 靜態檢查', '', '| 規則 | 嚴重度 | 模組 | 檔案 | 說明 |', '|---|---|---|---|---|']
        L += ['| %s | %s | %s | %s | %s |' % (i['rule'], i['severity'], i['module'], i['file'], i['msg'].replace('|', '\\|'))
              for i in rep['v0_issues']]
    with open(base + '.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    return base + '.md', base + '.json'


# ---------------------------------------------------------------- run
class Runner:
    def __init__(self, args):
        self.args = args
        self.level = args.level.upper()
        if self.level not in LEVELS:
            raise SystemExit('--level 要是 %s' % '/'.join(LEVELS))
        self.started = time.time()
        self.stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
        self.tmp_dirs, self.dbs = [], []
        self.pg = None
        self.rep = None

    # -- 準備
    def prepare(self):
        a = self.args
        repo = os.path.realpath(os.path.expanduser(a.repo))
        if not os.path.isdir(repo):
            raise SystemExit('找不到 repo：%s' % repo)
        self.info = info = repo_info(repo)
        rep = self.rep = new_report(self.level, info['name'])
        self.out_dir = os.path.join(kb_home(), 'verify-reports', info['name'])
        rep.update({'branch': info['branch'], 'sha': info['sha'], 'repo_path': repo})
        if info['dirty']:
            rep['notes'].append('工作目錄有未 commit 的變更：驗證的是工作目錄現況（sha 只代表 HEAD）')
        self.repo = repo
        self.repo_mods = list_modules(repo)
        # 目標／快照
        base = a.base
        self.target = a.target or (base[5:] if base and base.startswith('prod:') else None)
        self.snap = load_snapshot(self.target, a.snapshot_dir, a.installed)
        if self.snap:
            rep['notes'].append('快照：%s（已安裝清單 %s 個，%s）' % (
                self.snap['src'], len(self.snap['installed'] or {}), self.snap['installed_file'] or '無已安裝清單'))
        elif self.target:
            rep['notes'].append('目標 %s 沒有快照（先跑 pt-verify snapshot %s）' % (self.target, self.target))
        # 基準
        self.base_kind, self.base_sha, self.diff_sha = None, None, None
        if base is None:
            if self.level in ('V3', 'V4'):
                base = 'prod:' + self.target if self.target else None
            else:
                base = default_base_ref(repo)
                if base:
                    rep['notes'].append('--base 省略：用 %s' % base)
        if base and base.startswith('prod:'):
            self.base_kind = 'prod'
            if not self.snap:
                raise Blocked('--base %s 需要快照：先跑 pt-verify snapshot %s，或給 --snapshot-dir' % (base, base[5:]))
            rep['base'] = '%s（快照 %s）' % (base, self.snap['date'] or self.snap['dir'])
        elif base:
            self.base_kind = 'git'
            self.base_sha = git(repo, 'rev-parse', base + '^{commit}').strip()
            self.diff_sha = git(repo, 'merge-base', 'HEAD', self.base_sha).strip()
            rep['base'] = '%s（%s；merge-base %s）' % (base, self.base_sha[:10], self.diff_sha[:10])
        if self.level == 'V3' and not self.base_kind:
            raise Blocked('V3 需要基準：給 --base <git-ref>，或 --base prod:<目標>／--target（取正式機快照）')
        if self.level == 'V4' and not (self.snap and self.snap['installed']):
            raise Blocked('V4 需要正式機快照與已安裝清單：pt-verify snapshot <目標>，或 --snapshot-dir＋--installed')
        self.index = ModuleIndex(exclude=[repo, info['main_repo']])
        # 受測模組
        if a.mods:
            mods = [m.strip() for m in a.mods.split(',') if m.strip()]
            bad = [m for m in mods if m not in self.repo_mods]
            if bad:
                raise Blocked('--mods 裡 %s 不在受測 repo %s' % ('、'.join(bad), repo))
            rep['notes'].append('受測模組：--mods 指定')
        else:
            if self.base_kind == 'git':
                mods = changed_modules_git(repo, self.diff_sha)
                how = '與 %s 的 merge-base 比較有變動' % base
            elif self.base_kind == 'prod':
                smap = snapshot_module_map(self.snap)
                mods = sorted(m for m, p in self.repo_mods.items()
                              if m not in smap or tree_digest(p) != tree_digest(smap[m]))
                how = '與正式機快照比較有變動（或正式機沒有）'
            else:
                raise Blocked('沒有 --mods 也沒有可用的基準（--base）可比較變動')
            rep['notes'].append('受測模組：%s → %s' % (how, '、'.join(mods) or '（無）'))
            if self.level != 'V0' and mods:
                rd = sorted(reverse_deps(set(mods), self.repo_mods))
                if rd:
                    rep['notes'].append('加上本 repo 內的反向相依：%s' % '、'.join(rd))
                mods = sorted(set(mods) | set(rd))
        if not mods:
            raise Blocked('沒有可驗證的模組（與基準無差異）；要驗證請用 --mods 指定')
        self.mods = sorted(mods)
        rep['mods'] = self.mods
        # 安裝集合（V2 起加正式機整組）
        install = set(self.mods)
        if self.level in ('V2', 'V3') and self.snap and self.snap['installed']:
            grp = sorted(set(self.snap['installed']) & set(self.repo_mods))
            rep['notes'].append('V2 整組：正式機已安裝 ∩ 受測 repo = %s' % ('、'.join(grp) or '（無）'))
            install |= set(grp)
        elif self.level in ('V2', 'V3'):
            rep['notes'].append('沒有快照的已安裝清單：整組＝受測模組本身')
        self.install = sorted(install)

    # -- Odoo
    def ensure_pg(self):
        if self.pg is None:
            if not os.path.isfile(os.path.join(odoo_root(), 'odoo-bin')):
                raise Blocked('找不到 Odoo 18 原碼：%s' % odoo_root())
            if not os.path.isfile(venv_python()):
                raise Blocked('找不到 venv：%s' % venv_python())
            self.pg = Pg()
            self.pg.start()
            self.port = pick_port()
            if not self.port:
                raise Blocked('8150–8199 沒有空的 port')
        return self.pg

    def new_db(self, suffix=''):
        name = make_db_name(self.info['name'], self.info['branch'], self.level, suffix=suffix)
        n, i = name, 2
        while self.pg.exists(n):
            n = (name[:57] + '_%d' % i)
            i += 1
        self.dbs.append(n)
        return n

    def resolve(self, mods, first=(), layers=(), include_all_layers=False):
        r = resolve_addons(mods, first=first, layers=layers, index=self.index, include_all_layers=include_all_layers)
        for n in r['notes']:
            if n not in self.rep['notes']:
                self.rep['notes'].append(n)
        if r['blocked']:
            raise Blocked('；'.join(r['blocked']))
        return r

    def step(self, name, db, addons, install=(), update=(), test_mods=()):
        cmd = odoo_cmd(db, addons, self.port, self.pg, install=install, update=update, test_mods=test_mods,
                       log_level='test' if test_mods else 'info')
        lp = os.path.join(self.out_dir, '%s-%s-%s.log' % (self.stamp, self.level, name))
        os.makedirs(self.out_dir, exist_ok=True)
        rc = run_odoo(cmd, lp, self.args.timeout)
        res = parse_log(lp)
        res.update({'rc': rc, 'log': lp, 'command': show_cmd(cmd)})
        self.rep['logs'].append(lp)
        for u in res['unmet']:
            n = '相依變動（%s）：%s——升級過程中 Odoo 會補裝；部署時這些相依要已在正式機或一起帶' % (name, u)
            if n not in self.rep['notes']:
                self.rep['notes'].append(n)
        if rc != 0 and not res['failures'] and not res['load_errors']:
            res['load_errors'].append('odoo-bin 結束碼 %s（log 沒有測試失敗）：%s' % (rc, lp))
        want = set(install) | set(update)
        if want:
            try:
                states = self.pg.module_states(db, want)
            except RuntimeError as e:
                states = {}
                res['load_errors'].append('讀不到模組狀態：%s' % e)
            res['states'] = states
            bad = sorted(m for m in want if states.get(m, {}).get('state') != 'installed')
            if bad:
                res['load_errors'].append('沒有成功安裝／升級：%s' % '、'.join(
                    '%s(%s)' % (m, states.get(m, {}).get('state', '不存在')) for m in bad))
        return res

    def pipeline(self, new_root, db_suffix=''):
        """跑一次指定等級（不含差集）。new_root＝新版受測模組目錄；None＝不換碼（V4 基準）。"""
        self.ensure_pg()
        lvl = self.level
        db = self.new_db(db_suffix)
        tag = 'base' if db_suffix else ''
        out = {'db': db, 'versions_before': {}, 'versions_after': {}, 'migrations_ran': []}
        new_mods = list_modules(new_root) if new_root else {}
        if lvl in ('V1', 'V2'):
            inst = sorted(m for m in self.install if m in new_mods)
            tests = sorted(m for m in self.mods if m in new_mods)
            r = self.resolve(inst, first=[new_root])
            self.rep['addons_path'] = r['addons']
            res = self.step(tag + 'test', db, r['addons'], install=inst, test_mods=tests)
            out['versions_after'] = {m: s['version'] for m, s in res.get('states', {}).items()}
        elif lvl == 'V3':
            base_root = self.base_root()
            base_mods = list_modules(base_root)
            base_inst = sorted(m for m in self.install if m in base_mods)
            if not base_inst:
                raise Blocked('基準版本沒有任何受測模組，V3 無從升級（全新模組請跑 V1/V2）')
            rb = self.resolve(base_inst, first=[base_root])
            rb_res = self.step(tag + 'base', db, rb['addons'], install=base_inst)
            if rb_res['load_errors']:
                raise Blocked('基準版本安裝失敗（%s）：%s' % (rb_res['log'], rb_res['load_errors'][0]))
            out['versions_before'] = {m: s['version'] for m, s in rb_res.get('states', {}).items()}
            upd = base_inst
            ins = sorted(m for m in self.install if m not in base_mods and m in new_mods)
            tests = sorted(m for m in self.mods if m in new_mods)
            rn = self.resolve(sorted(set(upd) | set(ins)), first=[new_root])
            self.rep['addons_path'] = rn['addons']
            res = self.step(tag + 'upgrade', db, rn['addons'], install=ins, update=upd, test_mods=tests)
            out['versions_after'] = {m: s['version'] for m, s in res.get('states', {}).items()}
        elif lvl == 'V4':
            layers = self.v4_layers()
            smap = {}
            for layer in layers:
                for n, p in list_modules(layer).items():
                    smap.setdefault(n, p)
            universe = dict(smap)
            universe.update(self.repo_mods)
            inst = self.snap['installed'] or {}
            relevant = set(self.mods) | reverse_deps(set(self.mods), universe)
            base_inst = sorted(m for m in relevant if m in inst and m in smap)
            if not base_inst:
                raise Blocked('正式機已安裝清單和相關模組沒有交集（%s）' % '、'.join(sorted(relevant)))
            self.rep['notes'].append('V4 基準安裝＝正式機已安裝 ∩ 相關模組：%s' % '、'.join(base_inst))
            rb = self.resolve(base_inst, layers=layers, include_all_layers=True)
            rb_res = self.step(tag + 'prodbase', db, rb['addons'], install=base_inst)
            if rb_res['load_errors']:
                raise Blocked('正式機原碼樹安裝基準失敗（%s）：%s' % (rb_res['log'], rb_res['load_errors'][0]))
            out['versions_before'] = {m: s['version'] for m, s in rb_res.get('states', {}).items()}
            replaced = set(new_mods) if new_root else set(self.repo_mods)
            upd = sorted(m for m in base_inst if m in replaced)
            ins = sorted(m for m in self.mods if m not in base_inst and (m in new_mods or m in smap))
            tests = sorted(self.mods)
            rn = self.resolve(sorted(set(upd) | set(ins)), first=[new_root] if new_root else [], layers=layers,
                              include_all_layers=True)
            ws = sorted(m for m, v in rn['resolved'].items() if v[2] == 'workspace')
            if ws:
                n = '⚠ 正式機原碼樹沒有、改取自本機工作區的相依：%s（部署時要一起帶，否則正式機升級會失敗）' % '、'.join(
                    '%s（%s）' % (m, rn['resolved'][m][1]) for m in ws)
                if n not in self.rep['notes']:
                    self.rep['notes'].append(n)
            self.rep['addons_path'] = rn['addons']
            res = self.step(tag + 'upgrade', db, rn['addons'], install=ins, update=upd, test_mods=tests)
            out['versions_after'] = {m: s['version'] for m, s in res.get('states', {}).items()}
        else:
            raise AssertionError(lvl)
        out.update({k: res[k] for k in ('tests_total', 'failed', 'errors', 'skipped', 'failures', 'load_errors',
                                         'log_errors', 'log', 'command')})
        out['migrations_ran'] = res['migrations_ran']
        out['install'] = sorted(set(res.get('states', {})))
        return out

    def base_root(self):
        if getattr(self, '_base_root', None):
            return self._base_root
        tmp = tempfile.mkdtemp(prefix='base-', dir=self._tmp_parent())
        self.tmp_dirs.append(tmp)
        if self.base_kind == 'git':
            archive_tree(self.repo, self.base_sha, tmp)
        elif self.base_kind == 'prod':
            smap = snapshot_module_map(self.snap)
            for m in self.repo_mods:
                if m in smap:
                    os.symlink(smap[m], os.path.join(tmp, m))
        else:
            raise Blocked('V3 需要基準：給 --base <git-ref> 或 --base prod:<目標>／--target（取正式機快照）')
        self._base_root = tmp
        return tmp

    def _tmp_parent(self):
        p = os.path.join(kb_home(), 'verify-tmp')
        os.makedirs(p, exist_ok=True)
        return p

    def v4_layers(self):
        if getattr(self, '_layers', None) is not None:
            return self._layers
        if not self.snap:
            raise Blocked('V4 需要正式機快照：pt-verify snapshot <目標>，或 --snapshot-dir')
        if not self.snap['installed']:
            raise Blocked('V4 需要快照的已安裝清單（installed.json，或 --installed 檔案）')
        if not self.target:
            self.rep['notes'].append('沒有 --target：不套用 prod_overrides.toml')
        ovs = load_overrides(self.target) if self.target else []
        repl = {}
        for o in ovs:
            path = os.path.abspath(os.path.expanduser(o['replace_with']))
            entry = {k: o.get(k) for k in ('repo', 'replace_with', 'branch', 'reason', 'registered', 'revoke_when')}
            if not os.path.isdir(path):
                entry['status'] = '未套用：本機路徑不存在'
            else:
                if o.get('branch'):
                    cur = git(path, 'rev-parse', '--abbrev-ref', 'HEAD', check=False).strip()
                    entry['actual_branch'] = cur
                    if cur != o['branch']:
                        self.rep['notes'].append('⚠ 覆寫 %s 要求分支 %s，本機目前是 %s' % (o['repo'], o['branch'], cur))
                entry['status'] = '已套用'
                repl[o['repo']] = path
            self.rep['overrides'].append(entry)
        layers = []
        for layer in snapshot_layers(self.snap):
            rel = os.path.relpath(layer, self.snap['src'])
            layers.append(repl.get(rel, repl.get(os.path.basename(layer), layer)))
        self._layers = layers
        return layers

    # -- 主流程
    def run(self):
        a = self.args
        try:
            self.prepare()
            rep = self.rep
            ex = [self.repo, self.info['main_repo']]
            rep['v0_issues'] = v0_checks(self.repo, self.mods, self.diff_sha, exclude_repos=ex)
            if not self.diff_sha:
                rep['notes'].append('沒有 git 基準：V0 規則 (1) 只比 manifest 版號、(2)(3) 新模型檢查略過')
            if self.level != 'V0':
                res = self.pipeline(self.repo)
                for k in ('tests_total', 'failed', 'errors', 'skipped', 'failures', 'load_errors', 'log_errors', 'log',
                          'command', 'db', 'migrations_ran', 'versions_before', 'versions_after', 'install'):
                    rep[k] = res[k]
                rep['port'] = self.port
                flaky = load_known_flaky(self.repo)
                rep['known_flaky_hit'] = ['%s（%s）' % (f, flaky[f]) for f in res['failures'] if f in flaky]
                cand = [f for f in res['failures'] if f not in flaky]
                if cand:
                    rep['baseline_failures'] = self.baseline()
                    if rep['baseline_failures'] is None:
                        rep['notes'].append('沒有基準結果可比：全部失敗都算新增')
                rep['new_failures'] = new_failures(res['failures'], rep['baseline_failures'], flaky)
            else:
                rep['command'] = 'V0 靜態檢查（不啟動 Odoo）'
            rep['verdict'] = decide_verdict(rep, [m for m in self.mods if os.path.isdir(os.path.join(self.repo_mods[m], 'tests'))])
        except Blocked as e:
            if self.rep is None:
                self.rep = new_report(self.level, os.path.basename(os.path.realpath(a.repo)))
                self.out_dir = os.path.join(kb_home(), 'verify-reports', self.rep['repo'])
            self.rep['blocked_reasons'].append(str(e))
            self.rep['verdict'] = 'BLOCKED'
        finally:
            self.cleanup()
        rep = self.rep
        rep['duration'] = '%.0fs' % (time.time() - self.started)
        md, js = write_report(rep, self.out_dir, self.stamp)
        self.print_summary(md, js)
        return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[rep['verdict']]

    def baseline(self):
        """基準版本同等級的失敗清單（以 base sha＋等級＋mods 快取）。"""
        if self.base_kind == 'git':
            key_sha = self.base_sha
        elif self.base_kind == 'prod' or self.level == 'V4':
            key_sha = 'prod:%s:%s' % (self.target, self.snap['dir'] if self.snap else '')
        else:
            return None
        key = cache_key(key_sha, self.level, self.mods, ','.join(self.install))
        cp = cache_path(key)
        if os.path.isfile(cp) and not self.args.no_cache:
            with open(cp, encoding='utf-8') as f:
                data = json.load(f)
            self.rep['notes'].append('基準結果取自快取：%s' % cp)
            return data['failures']
        log('◆ 有失敗，跑基準版本同等級比對…')
        saved_addons = self.rep['addons_path']
        try:
            if self.level == 'V4':
                res = self.pipeline(None, db_suffix='b')
            else:
                res = self.pipeline(self.base_root(), db_suffix='b')
        except Blocked as e:
            self.rep['notes'].append('基準版本跑不起來：%s' % e)
            return None
        finally:
            self.rep['addons_path'] = saved_addons
        if res['load_errors']:
            self.rep['notes'].append('基準版本有載入錯誤，不寫快取：%s' % res['load_errors'][0])
            return res['failures']
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        with open(cp, 'w', encoding='utf-8') as f:
            json.dump({'failures': res['failures'], 'tests_total': res['tests_total'], 'log': res['log'],
                       'created': dt.datetime.now().isoformat(timespec='seconds')}, f, ensure_ascii=False, indent=2)
        self.rep['notes'].append('基準結果（%s 項，失敗 %d）：%s' % (res['tests_total'], len(res['failures']), res['log']))
        return res['failures']

    def cleanup(self):
        if self.pg is not None and not self.args.keep_db:
            for db in self.dbs:
                try:
                    self.pg.drop(db)
                except Exception as e:  # noqa: BLE001
                    log('drop %s 失敗：%s' % (db, e))
        elif self.dbs and self.rep is not None:
            self.rep['notes'].append('--keep-db：保留資料庫 %s' % '、'.join(self.dbs))
        for d in self.tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)

    def print_summary(self, md, js):
        rep = self.rep
        if rep['blocked_reasons']:
            log('BLOCKED：' + '；'.join(rep['blocked_reasons']))
        for i in rep['v0_issues']:
            log('[%s] %s %s：%s' % (i['severity'], i['rule'], i['file'], i['msg']))
        if self.level != 'V0' and not rep['blocked_reasons']:
            log('測試 %s 項：failed %s、errors %s、skipped %s；新增失敗 %d' % (
                rep['tests_total'], rep['failed'], rep['errors'], rep['skipped'], len(rep['new_failures'])))
            for f in rep['new_failures']:
                log('  ✗ ' + f)
            for e in rep['load_errors'][:5]:
                log('  ! ' + e)
        print('%s %s' % (md, rep['verdict']))


# ---------------------------------------------------------------- snapshot
_SNAPSHOT_PY = r'''
import configparser, json, os, psycopg2
c = configparser.ConfigParser(); c.read(os.environ.get("PTV_CONF", "/etc/odoo/odoo.conf")); o = c["options"]
h = o.get("db_host"); h = None if h in (None, "", "False") else h
p = o.get("db_port"); p = None if p in (None, "", "False") else p
cn = psycopg2.connect(host=h, port=p or 5432, user=o.get("db_user"), password=o.get("db_password"), dbname=os.environ["PTV_DB"])
cn.set_session(readonly=True)
cur = cn.cursor()
cur.execute("select name, latest_version from ir_module_module where state = 'installed' order by name")
print(json.dumps({"installed": dict(cur.fetchall()), "addons_path": o.get("addons_path")}))
cn.rollback(); cn.close()
'''


def ssh_base(t):
    ssh = shlex.split(os.environ.get('PT_VERIFY_SSH', 'ssh'))
    key = os.path.expanduser(t.get('ssh_key') or '')
    return ssh + (['-i', key] if key else []) + ['-o', 'BatchMode=yes', t['ssh_host']]


def _safe_extract(tf, dest):
    dest_real = os.path.realpath(dest)
    for m in tf:
        p = os.path.realpath(os.path.join(dest, m.name))
        if not (p == dest_real or p.startswith(dest_real + os.sep)) or m.isdev():
            raise SystemExit('快照壓縮檔含不安全路徑：%s' % m.name)
        if m.issym() or m.islnk():
            lt = os.path.realpath(os.path.join(os.path.dirname(p), m.linkname))
            if not lt.startswith(dest_real + os.sep):
                continue  # 指到樹外的連結不展開
        if hasattr(tarfile, 'data_filter'):
            tf.extract(m, dest, filter='tar')  # 3.12+：路徑已自行檢查，保留權限
        else:
            tf.extract(m, dest)


def cmd_snapshot(args):
    t = get_target(args.target)
    missing = [k for k in ('ssh_host', 'sources_path', 'container', 'db') if not t.get(k)]
    if missing:
        raise SystemExit('目標 %s 的 %s 尚未設定（targets.toml 標「待確認」）；確認後再跑' % (t['name'], '、'.join(missing)))
    day = dt.datetime.now().strftime('%Y%m%d')
    out = os.path.join(kb_home(), 'prod', t['name'], day)
    tmp = out + '.tmp'
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.join(tmp, 'src'))
    remote_tar = 'cd %s && tar czf - --exclude=__pycache__ --exclude=.git .' % shlex.quote(t['sources_path'])
    cmd = ssh_base(t) + [remote_tar]
    log('▶ 下載原碼：%s' % ' '.join(shlex.quote(c) for c in cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    with tarfile.open(fileobj=p.stdout, mode='r|gz') as tf:
        _safe_extract(tf, os.path.join(tmp, 'src'))
    if p.wait() != 0:
        raise SystemExit('下載原碼失敗（ssh 結束碼 %s）' % p.returncode)
    q = 'docker exec -e PTV_DB=%s %s python3 -c %s' % (shlex.quote(t['db']), shlex.quote(t['container']),
                                                        shlex.quote(_SNAPSHOT_PY))
    r = subprocess.run(ssh_base(t) + [q], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('讀取已安裝模組失敗：%s' % r.stderr.strip()[-400:])
    data = json.loads(r.stdout.strip().splitlines()[-1])
    with open(os.path.join(tmp, 'installed.json'), 'w', encoding='utf-8') as f:
        json.dump({'installed': data['installed']}, f, ensure_ascii=False, indent=1, sort_keys=True)
    meta = {'target': t['name'], 'ssh_host': t['ssh_host'], 'sources_path': t['sources_path'], 'db': t['db'],
            'taken_at': dt.datetime.now().isoformat(timespec='seconds'), 'addons_path': data.get('addons_path'),
            'installed_count': len(data['installed'])}
    with open(os.path.join(tmp, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.rename(tmp, out)
    layers = scan_repo_dirs(os.path.join(out, 'src'), skip_worktrees=False)
    print('快照完成：%s（repo %d 個、已安裝模組 %d 個）' % (out, len(layers), len(data['installed'])))
    return 0


# ---------------------------------------------------------------- deploy-plan
def md5_lines(group_dir, mods):
    """`md5  路徑`（格式同 md5sum），整行以位元組序排序＝與遠端 `LC_ALL=C sort` 結果完全相同。"""
    lines = []
    for m in mods:
        for rel, h in tree_digest(os.path.join(group_dir, m)).items():
            lines.append('%s  %s/%s' % (h, m, rel))
    return sorted(lines, key=lambda x: x.encode())


def plan_groups(mods, snap_map, src_root, local_repo_names, dest=None):
    """部署分組：正式機原碼子目錄 → 模組清單。回 (groups{dir: {'mods':[], 'exist':[]}}, errors[])。

    已在快照的模組放回原位；新模組放 dest（--dest）或本機 repo 同名子目錄（快照內必須存在）。
    """
    groups, errors = {}, []
    for m in mods:
        if m in snap_map:
            g = os.path.relpath(os.path.dirname(snap_map[m]), src_root)
            groups.setdefault(g, {'mods': [], 'exist': []})
            groups[g]['mods'].append(m)
            groups[g]['exist'].append(m)
        else:
            g = (dest or {}).get(m) or local_repo_names.get(m)
            if not g or not os.path.isdir(os.path.join(src_root, g)):
                errors.append('新模組 %s：不知道放正式機哪個子目錄（用 --dest %s=<子目錄>）' % (m, m))
                continue
            groups.setdefault(g, {'mods': [], 'exist': []})['mods'].append(m)
    for g in groups.values():
        g['mods'].sort()
        g['exist'].sort()
    return dict(sorted(groups.items(), key=lambda kv: kv[0].encode())), errors


def render_remote_script(t, groups, upgrade, install, label):
    with open(os.path.join(HERE, 'deploy_remote.sh'), encoding='utf-8') as f:
        tpl = f.read()
    q = shlex.quote
    pause = ','.join("'%s'" % x for x in t.get('pause_crons', []) if re.match(r'^[\w.]+$', x))
    cfg = [
        'S=%s' % q(t['sources_path']), 'C=%s' % q(t['container']), 'DB=%s' % q(t['db']),
        'LABEL=%s' % q(label),
        'GROUP_DIRS=(%s)' % ' '.join(q(g) for g in groups),
        'GROUP_MODS=(%s)' % ' '.join(q(' '.join(v['mods'])) for v in groups.values()),
        'GROUP_EXIST=(%s)' % ' '.join(q(' '.join(v['exist'])) for v in groups.values()),
        'UPG=%s' % q(','.join(upgrade)), 'INS=%s' % q(','.join(install)),
        'PAUSE_XIDS=%s' % q(pause),
        'QUEUE_BUSY_SQL=%s' % q(t.get('queue_busy_sql', '')),
        'KILL_PATTERN=%s' % q(t.get('kill_pattern', '')),
        'ODOO_CONF=%s' % q(t.get('odoo_conf', '/etc/odoo/odoo.conf')),
        'CONTAINER_LOG_DIR=%s' % q(t.get('container_log_dir', '/var/lib/odoo')),
    ]
    return tpl.replace('# @@CONFIG@@', '\n'.join(cfg))


def _tar_dir(src_dir, mods, out_path):
    with tarfile.open(out_path, 'w:gz') as tf:
        for m in mods:
            tf.add(os.path.join(src_dir, m), arcname=m,
                   filter=lambda ti: None if '__pycache__' in ti.name or ti.name.endswith('.pyc') else ti)


def refresh_snapshot(target):
    """deploy-plan 比對漂移前先重抓快照（同 `pt-verify snapshot`，唯讀）；失敗就停，不退回舊快照。"""
    log('▶ 部署前先重抓 %s 的快照（不想重抓加 --no-refresh-snapshot，或用 --snapshot-dir 指定）' % target)
    try:
        cmd_snapshot(SimpleNamespace(target=target))
    except SystemExit as e:
        raise SystemExit('重抓快照失敗，部署計畫未產生（不會退回舊快照）：%s\n'
                         '離線時可加 --no-refresh-snapshot 改用最新的既有快照' % e)
    except Exception as e:  # tar／json／網路等非預期錯誤也要明確停下
        raise SystemExit('重抓快照失敗，部署計畫未產生（不會退回舊快照）：%s: %s\n'
                         '離線時可加 --no-refresh-snapshot 改用最新的既有快照' % (type(e).__name__, e))


def cmd_deploy_plan(args):
    t = get_target(args.target)
    mods = sorted({m.strip() for m in args.mods.split(',') if m.strip()})
    if not mods:
        raise SystemExit('--mods 不能是空的')
    bad = [m for m in mods if not MOD_NAME_RE.match(m)]
    if bad:
        raise SystemExit('模組名稱不合法：%s' % bad)
    if t.get('deploy_mode') == 'control_panel':
        print('目標 %s 由 CorPaaS 控制台部署（不產腳本）。請在控制台依序操作：' % t['name'])
        print('  1. 實例 #%s 的「實例模組」(instance_module)：對下列模組**各自**按「下載新版」'
              '（同 repo 多模組要每個模組各自按，漏一個＝import 失敗整站 500）：' % t.get('control_panel_instance_id', '?'))
        for m in mods:
            print('       - %s' % m)
        print('  2. 資料庫 #%s（%s）的「資料庫模組」(database_module)：對 %s 按「更新」'
              % (t.get('control_panel_database_id', '?'), t.get('db', '?'), ','.join(mods)))
        print('  3. 完成後跑：pt-verify post-check %s --mods %s' % (t['name'], ','.join(mods)))
        return 0
    for k in ('ssh_host', 'sources_path', 'container', 'db'):
        if not t.get(k):
            raise SystemExit('目標 %s 的 %s 尚未設定（待確認）' % (t['name'], k))
    if not (args.snapshot_dir or args.installed or getattr(args, 'no_refresh_snapshot', False)):
        refresh_snapshot(t['name'])
    snap = load_snapshot(t['name'], args.snapshot_dir, args.installed)
    if not snap:
        raise SystemExit('目標 %s 沒有快照：先跑 pt-verify snapshot %s' % (t['name'], t['name']))
    # 本機來源
    local = {}
    if args.repo:
        for rp in args.repo.split(','):
            rp = os.path.realpath(os.path.expanduser(rp))
            for n, p in list_modules(rp).items():
                local.setdefault(n, (rp, p))
    idx = None
    for m in mods:
        if m not in local:
            idx = idx or ModuleIndex()
            c, _note = idx.choose(m)
            if c:
                local[m] = (c['repo'], c['path'])
    missing = [m for m in mods if m not in local]
    if missing:
        raise SystemExit('本機找不到模組：%s（用 --repo 指定）' % '、'.join(missing))
    errors = []
    for m in mods:
        rp = local[m][0]
        dirty = git(rp, 'status', '--porcelain', '--', m, check=False).strip()
        if dirty and not args.allow_dirty:
            errors.append('%s 在 %s 有未 commit 的變更（部署包取 %s；確定要部署 commit 版本就加 --allow-dirty）' % (m, rp, args.ref))
    smap = snapshot_module_map(snap)
    names = {m: repo_info(local[m][0])['name'] for m in mods}
    dest = dict(x.split('=', 1) for x in (args.dest or '').split(',') if '=' in x)
    groups, gerr = plan_groups(mods, smap, snap['src'], names, dest)
    errors += gerr
    inst = snap['installed']
    if inst is None:
        upgrade, newmods = mods, []
        print('⚠ 快照沒有已安裝清單：全部當升級（-u）')
    else:
        upgrade = [m for m in mods if m in inst]
        newmods = [m for m in mods if m not in inst]
    install = newmods if args.install_new else []
    if newmods and not args.install_new:
        print('⚠ 正式機未安裝：%s——只換碼不安裝（要安裝加 --install-new）' % '、'.join(newmods))
    if not upgrade and not install:
        errors.append('沒有要升級／安裝的模組')
    if errors:
        for e in errors:
            print('✗ ' + e)
        return 2
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    out = os.path.join(kb_home(), 'deploy', t['name'], stamp)
    n = 2
    while os.path.exists(out):
        out = os.path.join(kb_home(), 'deploy', t['name'], '%s-%d' % (stamp, n))
        n += 1
    os.makedirs(out)
    stage = os.path.join(out, 'new')
    for i, (g, v) in enumerate(groups.items()):
        gdir = os.path.join(stage, str(i))
        os.makedirs(gdir)
        for m in v['mods']:
            rp = local[m][0]
            rel = os.path.relpath(local[m][1], rp)
            p1 = subprocess.Popen(['git', '-C', rp, 'archive', '--format=tar', args.ref, '--', rel], stdout=subprocess.PIPE)
            with tarfile.open(fileobj=p1.stdout, mode='r|') as tf:
                _safe_extract(tf, os.path.join(stage, 'tmp'))
            if p1.wait() != 0:
                raise SystemExit('git archive %s %s 失敗' % (args.ref, rel))
            shutil.move(os.path.join(stage, 'tmp', rel), os.path.join(gdir, m))
            shutil.rmtree(os.path.join(stage, 'tmp'), ignore_errors=True)
        _tar_dir(gdir, v['mods'], os.path.join(out, 'bundle_%d.tgz' % i))
        lines = md5_lines(os.path.join(snap['src'], g), v['exist']) if v['exist'] else []
        with open(os.path.join(out, 'expect_%d.md5' % i), 'w', encoding='utf-8') as f:
            f.write(''.join(x + '\n' for x in lines))
    label = re.sub(r'[^a-z0-9-]+', '-', (args.label or mods[0]).lower()).strip('-')[:40]
    with open(os.path.join(out, 'remote.sh'), 'w', encoding='utf-8') as f:
        f.write(render_remote_script(t, groups, upgrade, install, label))
    key = os.path.expanduser(t.get('ssh_key', ''))
    q = shlex.quote
    local_sh = '\n'.join([
        '#!/bin/bash',
        '# pt-verify deploy-plan 產生：上傳部署包到 %s 並執行 remote.sh（由使用者用 ! 執行）' % t['name'],
        'set -e',
        'D=$(cd "$(dirname "$0")" && pwd)',
        'H=%s; K=%s' % (q(t['ssh_host']), q(key)),
        'BK=/root/deploy-backup-$(date +%%Y%%m%%d-%%H%%M%%S)-%s' % label,
        'ssh -i "$K" "$H" "mkdir -p $BK"',
        'scp -q -i "$K" "$D"/bundle_*.tgz "$D"/expect_*.md5 "$D"/remote.sh "$H:$BK/"',
        'ssh -i "$K" "$H" "BK=$BK bash $BK/remote.sh"',
        ''])
    with open(os.path.join(out, 'deploy.sh'), 'w', encoding='utf-8') as f:
        f.write(local_sh)
    os.chmod(os.path.join(out, 'deploy.sh'), 0o755)
    plan = {'target': t['name'], 'snapshot': snap['dir'], 'ref': args.ref, 'groups': groups, 'upgrade': upgrade,
            'install': install, 'not_installed': newmods, 'created': stamp,
            'sources': {m: local[m][0] for m in mods}}
    with open(os.path.join(out, 'plan.json'), 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print('部署計畫：%s' % out)
    print('  快照：%s%s' % (snap['dir'], '' if snap['date'] == dt.datetime.now().strftime('%Y%m%d')
                                        else '（⚠ 不是今天的快照；建議先重跑 snapshot）'))
    for g, v in groups.items():
        print('  %s/%s：%s（既有 %d、新 %d）' % (t['sources_path'], g, ' '.join(v['mods']), len(v['exist']),
                                          len(v['mods']) - len(v['exist'])))
    print('  -u %s%s' % (','.join(upgrade) or '（無）', ('；-i ' + ','.join(install)) if install else ''))
    print('確認無誤後由你執行（本工具不會自行部署）：')
    print('! bash %s' % os.path.join(out, 'deploy.sh'))
    return 0


# ---------------------------------------------------------------- post-check
def _jsonrpc(url, service, method, *args):
    body = {'jsonrpc': '2.0', 'method': 'call', 'params': {'service': service, 'method': method, 'args': list(args)}}
    req = urllib.request.Request(url.rstrip('/') + '/jsonrpc', json.dumps(body).encode(),
                                 {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    res = json.load(urllib.request.urlopen(req, timeout=60))
    if 'error' in res:
        d = res['error'].get('data') or {}
        raise RuntimeError(d.get('message') or res['error'])
    return res.get('result')


def http_status(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        return 'ERR %s' % e


def env_key_name(target):
    return 'PT_VERIFY_RPC_KEY_' + re.sub(r'\W+', '_', target).upper()


def cmd_post_check(args):
    t = get_target(args.target)
    mods = [m.strip() for m in (args.mods or '').split(',') if m.strip()]
    url = (t.get('url') or '').rstrip('/')
    if not url:
        print('目標 %s 沒有設定 url（待確認）' % t['name'])
        return 2
    st = http_status(url + '/web/login')
    print('登入頁 %s/web/login：HTTP %s' % (url, st))
    keyname = env_key_name(t['name'])
    key = os.environ.get(keyname)
    login = os.environ.get(keyname.replace('_KEY_', '_LOGIN_')) or t.get('rpc_login') or 'admin'
    rc = 0 if st == 200 else 1
    if not key:
        print('版本讀取：略過（缺環境變數 %s；要讀版本請 export %s=<API 金鑰>，登入帳號 %s）' % (keyname, keyname, login))
    elif mods:
        try:
            uid = _jsonrpc(url, 'common', 'authenticate', t['db'], login, key, {})
            if not uid:
                raise RuntimeError('金鑰驗證失敗')
            rows = _jsonrpc(url, 'object', 'execute_kw', t['db'], uid, key, 'ir.module.module', 'search_read',
                            [[['name', 'in', mods]]], {'fields': ['name', 'state', 'latest_version']})
            got = {r['name']: r for r in rows}
            for m in mods:
                r = got.get(m)
                print('  %-45s %s %s' % (m, r['state'] if r else '不存在', r['latest_version'] if r else ''))
                if not r or r['state'] != 'installed':
                    rc = 1
        except Exception as e:  # noqa: BLE001
            print('版本讀取失敗：%s' % e)
            rc = 1
    if t.get('deploy_mode') == 'control_panel':
        print('（控制台部署：也可在 CorPaaS 控制台資料庫 #%s 的模組頁確認版本）' % t.get('control_panel_database_id', '?'))
    return rc


# ---------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(prog='pt-verify', description='Odoo 18 模組本機驗證（V0～V4）、快照、部署計畫、部署後檢查')
    sp = ap.add_subparsers(dest='cmd', required=True)
    r = sp.add_parser('run', help='驗證一個 repo（或 worktree）')
    r.add_argument('repo')
    r.add_argument('--level', required=True, help='V0|V1|V2|V3|V4')
    r.add_argument('--mods', help='逗號分隔；省略＝與 --base 比較有變動的模組（V1 起加反向相依）')
    r.add_argument('--base', help='<git-ref> 或 prod:<目標>；V0～V2 省略＝origin/HEAD，V3/V4 省略＝正式機快照')
    r.add_argument('--target', help='正式機目標名（targets.toml）：取快照、套用 prod_overrides.toml')
    r.add_argument('--snapshot-dir', help='直接指定快照目錄（含 src/ 與 installed.json，或本身就是原碼樹）')
    r.add_argument('--installed', help='已安裝模組清單檔（.json 或逗號／換行分隔的 .txt）')
    r.add_argument('--keep-db', action='store_true', help='結束不 drop 資料庫')
    r.add_argument('--no-cache', action='store_true', help='基準結果不用快取，重跑')
    r.add_argument('--timeout', type=int, default=90, help='每次 odoo-bin 的上限（分鐘）')
    s = sp.add_parser('snapshot', help='（唯讀）下載正式機原碼樹與已安裝模組清單')
    s.add_argument('target')
    d = sp.add_parser('deploy-plan', help='產生部署包與遠端腳本（不執行）')
    d.add_argument('target')
    d.add_argument('--mods', required=True)
    d.add_argument('--repo', help='本機來源 repo（逗號分隔）；省略＝在工作區找')
    d.add_argument('--ref', default='HEAD', help='打包哪個 commit（預設 HEAD）')
    d.add_argument('--dest', help='新模組放正式機哪個子目錄：mod=子目錄,…')
    d.add_argument('--install-new', action='store_true', help='正式機未安裝的模組也 -i 安裝')
    d.add_argument('--allow-dirty', action='store_true')
    d.add_argument('--label')
    d.add_argument('--snapshot-dir', help='指定快照目錄（不重抓）')
    d.add_argument('--installed', help='已安裝模組清單檔（不重抓）')
    d.add_argument('--no-refresh-snapshot', action='store_true',
                   help='不先重抓快照，改用最新的既有快照（例如離線時）')
    p = sp.add_parser('post-check', help='（唯讀）部署後檢查登入頁與模組版本')
    p.add_argument('target')
    p.add_argument('--mods', default='')
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == 'run':
        return Runner(args).run()
    if args.cmd == 'snapshot':
        return cmd_snapshot(args)
    if args.cmd == 'deploy-plan':
        return cmd_deploy_plan(args)
    if args.cmd == 'post-check':
        return cmd_post_check(args)
    return 2


if __name__ == '__main__':
    sys.exit(main())
