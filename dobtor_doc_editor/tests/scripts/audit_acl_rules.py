#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""尺：ACL／record rule 逐 model 對照（`make audit` 的一部分）。

☠️ 2026-10-09 這把尺量到**兩個真的跨公司讀取漏洞**：

  1. `rule_doc_document_manager_all` 的 domain 是 `[(1, '=', 1)]`，而 Odoo 的
     **非 global rule 之間是 OR**——它把 `rule_doc_document_company` 的公司
     範圍整條 OR 掉了，manager 讀得到所有公司的文件內容。
  2. `doc.template.field` / `.option` / `.signer` 有 ACL 但**完全沒有 record
     rule**，而母體 `doc.template` 有公司隔離。Odoo 不會讓子記錄自動繼承
     母體的 rule。

它們都不是「少打一個字」，是**看表格看不出來**的：要把 ACL、rule、
model 的父子關係三者並排才看得見。這支腳本做的就是並排。

它**不判定**，只攤開。判讀需要人——`doc.output` 的 `RU` 看起來像漏的，
查過之後是刻意的（見 `models/doc_output.py` 的 docstring）。

用法：python3 tests/scripts/audit_acl_rules.py [模組…]
"""
import ast
import csv
import io
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_MODULES = ('dobtor_doc_editor', 'dobtor_doc_import')


def own_models(root):
    """AST 找出 `_name = '...'` 的 model（含 Abstract/Transient 標記）。"""
    out = {}
    for sub in ('models', 'wizards'):
        base = os.path.join(root, sub)
        for dirpath, _d, files in os.walk(base) if os.path.isdir(base) else ():
            for f in sorted(files):
                if not f.endswith('.py'):
                    continue
                with open(os.path.join(dirpath, f), encoding='utf-8') as fh:
                    tree = ast.parse(fh.read())
                for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                    bases = [getattr(b, 'attr', getattr(b, 'id', '')) or ''
                             for b in cls.bases]
                    kind = ('AbstractModel' if any('AbstractModel' in b for b in bases)
                            else 'TransientModel' if any('TransientModel' in b for b in bases)
                            else 'Model')
                    for st in cls.body:
                        if not isinstance(st, ast.Assign):
                            continue
                        for t in st.targets:
                            if (getattr(t, 'id', None) == '_name'
                                    and isinstance(st.value, ast.Constant)):
                                out[st.value.value] = (f, kind)
    return out


def acl_rows(root):
    path = os.path.join(root, 'security', 'ir.model.access.csv')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as fh:
        return list(csv.DictReader(io.StringIO(fh.read())))


def perms(row):
    return ''.join(c for c, k in zip('RWCU', ('perm_read', 'perm_write',
                                              'perm_create', 'perm_unlink'))
                   if (row.get(k) or '0').strip() in ('1', 'True', 'true'))


def rules(root):
    """從 XML 抽出 ir.rule（含 domain、groups、global）。"""
    out = []
    for dirpath, _d, files in os.walk(root):
        if 'node_modules' in dirpath:
            continue
        for f in sorted(files):
            if not f.endswith('.xml'):
                continue
            with open(os.path.join(dirpath, f), encoding='utf-8',
                      errors='ignore') as fh:
                txt = fh.read()
            for m in re.finditer(
                    r'<record\b([^>]*model="ir\.rule"[^>]*)>(.*?)</record>',
                    txt, re.S):
                attrs, blk = m.group(1), m.group(2)
                rid = (re.search(r'id="([^"]+)"', attrs) or [None, '?'])[1]
                model = (re.search(r'name="model_id"\s+ref="([^"]+)"', blk)
                         or [None, '?'])[1]
                dom = (re.search(r'name="domain_force">(.*?)</field>', blk, re.S)
                       or [None, '(無)'])[1]
                groups = re.search(r'name="groups"[^>]*eval="([^"]*)"', blk)
                out.append({
                    'id': rid, 'model': model,
                    'domain': ' '.join(dom.split()),
                    'groups': ' '.join((groups.group(1) if groups else
                                        '(無→global)').split()),
                })
    return out


def main():
    modules = sys.argv[1:] or list(DEFAULT_MODULES)
    for mod in modules:
        root = os.path.join(REPO_ROOT, mod)
        models = own_models(root)
        acl = acl_rows(root)
        rl = rules(root)
        print('\n════ %s ════' % mod)
        print('  自有 model %d / ACL %d 列 / record rule %d 條'
              % (len(models), len(acl), len(rl)))
        by_model = {}
        for row in acl:
            by_model.setdefault(row['model_id:id'].strip(), []).append(row)
        rules_by_model = {}
        for r in rl:
            rules_by_model.setdefault(r['model'], []).append(r)
        print('\n  ── model × ACL × rule ──')
        for name, (fn, kind) in sorted(models.items()):
            key = 'model_' + name.replace('.', '_')
            a = [k for k in by_model if key in k]
            rr = [k for k in rules_by_model if key in k]
            flag = ''
            if kind == 'Model' and not a:
                flag = '  ✗ 沒有 ACL'
            elif kind == 'Model' and a and not rr:
                flag = '  ⚠ 有 ACL 但沒有 record rule（子記錄不會繼承母體的 rule）'
            print('  %-34s %-14s ACL=%s rule=%s (%s)%s'
                  % (name, kind, 'Y' if a else 'N', 'Y' if rr else 'N', fn, flag))
        if rl:
            print('\n  ── record rule 的 domain 與 groups ──')
            print('  ☠️ 非 global rule 之間是 **OR**：任一條寬的會把其他條的範圍 OR 掉。')
            for r in sorted(rl, key=lambda x: (x['model'], x['id'])):
                wide = '  ← **這條是全開，會 OR 掉同 model 其他 rule 的範圍**' \
                    if "(1, '=', 1)" in r['domain'] else ''
                print('  %-46s %s' % (r['id'], r['model'].replace('model_', '')))
                print('      groups=%s' % r['groups'][:80])
                print('      domain=%s%s' % (r['domain'][:110], wide))
    print('\n☠️ 這是尺，不是閘門——它攤開事實，判讀需要人。')
    print('   刻意的形狀（如 doc.output 的 RU）由 tests/test_acl_shapes.py 釘住；')
    print('   公司隔離由 tests/test_acl_company_isolation.py 實際建資料去讀。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
