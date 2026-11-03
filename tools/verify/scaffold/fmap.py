"""產生 feature-map 本體：模組 → 表單（模型）狀態列／表頭按鈕 → 呼叫該按鈕的測試類別 → 知識案例。"""
import os, re, sys, ast, glob, json, collections
repo = sys.argv[1]
cases_path = sys.argv[2] if len(sys.argv) > 2 else None
cases = json.load(open(cases_path))['cases'] if cases_path else []
mods = sorted(d for d in os.listdir(repo) if os.path.isfile(os.path.join(repo, d, '__manifest__.py')))
local = set(mods)
stats = collections.Counter()

def test_classes(p):
    out = []  # (file, cls, body, imported)
    tdir = os.path.join(p, 'tests')
    init = open(os.path.join(tdir, '__init__.py'), encoding='utf-8').read() if os.path.isfile(os.path.join(tdir, '__init__.py')) else ''
    for f in sorted(glob.glob(os.path.join(tdir, '**', '*.py'), recursive=True)):
        base = os.path.splitext(os.path.basename(f))[0]
        if base == '__init__':
            continue
        src = open(f, encoding='utf-8').read()
        imported = bool(re.search(r'\b%s\b' % re.escape(base), init)) or os.path.dirname(f) != tdir
        spans = [(m.start(), m.group(1)) for m in re.finditer(r'^class (\w+)\(', src, re.M)]
        for i, (s, c) in enumerate(spans):
            e = spans[i + 1][0] if i + 1 < len(spans) else len(src)
            body = src[s:e]
            if not re.search(r'^\s+def test_', body, re.M):
                continue  # 基底類別（沒有 test_ 方法）不列
            out.append((base, c, body, imported))
    return out

def forms(p):
    res = []  # (model, statusbar list, buttons list)
    for f in sorted(glob.glob(os.path.join(p, '**', '*.xml'), recursive=True)):
        t = open(f, encoding='utf-8', errors='ignore').read()
        for rec in re.findall(r'<record[^>]*model="ir.ui.view"[^>]*>(.*?)</record>', t, re.S):
            hs = re.findall(r'<header>(.*?)</header>', rec, re.S)
            if not hs:
                continue
            mm = re.search(r'<field name="model">([\w.]+)</field>', rec)
            model = mm.group(1) if mm else '?'
            sb, btn = [], []
            for h in hs:
                for m in re.finditer(r'<field name="(\w+)"[^>]*widget="statusbar"[^>]*', h):
                    sv = re.search(r'statusbar_visible="([^"]*)"', m.group(0))
                    sb.append('%s（%s）' % (m.group(1), sv.group(1).replace(',', '→') if sv else '全部狀態'))
                for b in re.finditer(r'<button\b[^>]*>', h):
                    tag = b.group(0)
                    if 'type="object"' not in tag:
                        continue
                    n = re.search(r'name="(\w+)"', tag)
                    if n and n.group(1) not in btn:
                        btn.append(n.group(1))
            if sb or btn:
                res.append((model, sb, btn))
    # 合併同模型
    merged = collections.OrderedDict()
    for model, sb, btn in res:
        a = merged.setdefault(model, ([], []))
        for x in sb:
            if x not in a[0]: a[0].append(x)
        for x in btn:
            if x not in a[1]: a[1].append(x)
    return merged

print('| 模組 | 版號 | 本 repo 相依 | 測試類別數 | 對到按鈕的類別 |')
print('|---|---|---|---|---|')
rows = []
body = []
for m in mods:
    p = os.path.join(repo, m)
    man = ast.literal_eval(open(os.path.join(p, '__manifest__.py'), encoding='utf-8').read())
    deps = [d for d in man.get('depends', []) if d in local]
    tcs = test_classes(p)
    fm = forms(p)
    mcases = [c for c in cases if c.get('module') == m]
    used_cls, used_cases = set(), set()
    out = ['## `%s`（%s）' % (m, man.get('name')), '', '%s' % (man.get('summary') or '').strip(), '']
    if deps or man.get('auto_install'):
        out.append('- 本 repo 相依：%s%s' % (', '.join('`%s`' % d for d in deps) or '無', '；auto_install' if man.get('auto_install') else ''))
    if fm:
        out += ['', '| 表單（模型） | 狀態列 | 主要按鈕 → 測試類別 | 知識案例 |', '|---|---|---|---|']
        for model, (sb, btn) in fm.items():
            parts, cparts = [], []
            for b in btn:
                cl = sorted({c for (_f, c, bd, _i) in tcs if re.search(r'\b%s\(' % re.escape(b), bd)})
                used_cls.update(cl)
                parts.append('`%s` → %s' % (b, ', '.join(cl) if cl else '（無測試直接呼叫）'))
                for c in mcases:
                    gm = {g.get('ref'): g.get('model') for g in c.get('given', [])}
                    if any(w.get('method') == b and gm.get(w.get('ref'), model) == model for w in c.get('when', [])) and c['code'] not in used_cases:
                        cparts.append('`%s`' % c['code']); used_cases.add(c['code'])
            out.append('| `%s` | %s | %s | %s |' % (model, '<br>'.join(sb) or '—', '<br>'.join(parts) or '—', ' '.join(cparts) or '—'))
    byfile = collections.OrderedDict()
    for f, c, _b, imp in tcs:
        byfile.setdefault(f, []).append(c + ('' if imp else '（⚠ 未在 tests/__init__ 匯入，不會執行）'))
    if byfile:
        out += ['', '測試類別（依檔案）：', '']
        for f, cl in byfile.items():
            fc = [c['code'] for c in mcases if ('/tests/%s.py' % f) in c.get('source_ref', '')]
            out.append('- `tests/%s.py`：%s%s' % (f, ', '.join(cl), ('；案例：' + ' '.join('`%s`' % x for x in fc)) if fc else ''))
            used_cases.update(fc)
    else:
        out += ['', '測試類別：**無 tests/**', '']
    left = [c for c in mcases if c['code'] not in used_cases]
    if left:
        out.append('- 其他案例（來源不是測試檔）：' + ' '.join('`%s`（%s）' % (c['code'], c.get('source_ref', '')[:50]) for c in left))
        used_cases.update(c['code'] for c in left)
    out.append('')
    body += out
    stats['mods'] += 1; stats['classes'] += len(tcs); stats['mapped'] += len(used_cls); stats['cases'] += len(used_cases)
    print('| `%s` | %s | %s | %d | %d |' % (m, man.get('version'), ', '.join(deps) or '—', len(tcs), len(used_cls)))
print()
print('\n'.join(body))
sys.stderr.write('STATS %s\n' % dict(stats))
