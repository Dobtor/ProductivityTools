# -*- coding: utf-8 -*-
r"""每支 .py 都接得上線——階段 2 的守衛（2026-10-09 全檔案深度稽核）。

Odoo 的載入方式讓「漏 import」變成一種**靜默**的失效：
`models/__init__.py` 漏掉一支 → 那個 model 不存在，而錯誤會出現在很遠的
地方（視圖找不到欄位、ACL 指到不存在的 model）。`tests/__init__.py` 漏掉一支
→ **那批測試從來不執行，而測試報告一片綠**。

☠️ 判準有**兩條，不是一條**。我第一版把它們混在一起，於是把三支完全正常的
共用輔助模組報成缺陷：

    tests/session_probe.py        SessionAliveMixin，被 4 支核心 + 2 支匯入測試 import
    tests/test_pill_helpers.py    沒有類別，被 5 支同層測試 import
    models/qweb/constants.py      沒有類別，被 5 支同層模組 import

它們都**不該**出現在 `__init__.py` 裡（session_probe 的檔頭就寫明了原因：
它沒有測試類別，放進去會讓「有類別卻沒 import」那條檢查要為它開例外）。

所以兩條判準是：

  A. 每支 .py 都要有**某個** importer（`__init__.py` 或同層檔案）。
     沒有任何 importer 才是真的死檔。
  B. **定義了需要註冊的類別**的檔案，必須在 `__init__.py` 裡。
     需要註冊＝Odoo model／controller／測試類別。輔助模組不在此列。

B 才是會害人的那一條：測試類別沒被 import ＝ 那批測試永遠不執行。
"""
import ast
import os

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 這些套件由 `__init__.py` 決定載入什麼
PACKAGES = ('models', 'models/render', 'models/qweb', 'controllers',
            'wizards', 'tests')

#: 類別基底名稱出現這些字樣，就是「需要註冊」
REGISTRABLE_BASES = (
    'Model', 'AbstractModel', 'TransientModel',    # Odoo models
    'Controller',                                   # Odoo controllers
    'TransactionCase', 'HttpCase', 'SavepointCase', 'BaseCase', 'TestCase',
)


def _parse(path):
    with open(path, encoding='utf-8') as fh:
        return ast.parse(fh.read())


def _init_imports(pkg_dir):
    """AST 解析 `from . import x` / `from .x import y`。

    ☠️ 不能字串切割——中文註解會被當模組名，本模組踩過。
    """
    init = os.path.join(pkg_dir, '__init__.py')
    if not os.path.exists(init):
        return None
    names = set()
    for node in ast.walk(_parse(init)):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module is None:
                names |= {a.name for a in node.names}
            else:
                names.add(node.module.split('.')[0])
    return names


def _registrable_classes(path):
    """檔案裡定義了哪些「需要註冊」的類別。"""
    out = []
    for node in _parse(path).body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [getattr(b, 'attr', None) or getattr(b, 'id', '') or ''
                 for b in node.bases]
        if any(any(k in b for k in REGISTRABLE_BASES) for b in bases):
            out.append(node.name)
    return out


def _modules_of(pkg_dir):
    return sorted(f[:-3] for f in os.listdir(pkg_dir)
                  if f.endswith('.py') and f != '__init__.py')


def _sibling_importers(pkg_dir, stem):
    """同層哪些檔案 import 了 stem（用 AST，不是 grep）。"""
    out = []
    for f in sorted(os.listdir(pkg_dir)):
        if not f.endswith('.py') or f == '%s.py' % stem:
            continue
        for node in ast.walk(_parse(os.path.join(pkg_dir, f))):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                if node.module == stem or (
                        node.module is None
                        and stem in {a.name for a in node.names}):
                    out.append(f)
                    break
    return out


from odoo.tests.common import TransactionCase, tagged  # noqa: E402


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestPythonPackageWiring(TransactionCase):
    """兩條判準，分開驗。"""

    def test_every_package_has_an_init(self):
        """沒有 `__init__.py` 的套件整個載不進去。"""
        missing = [p for p in PACKAGES
                   if os.path.isdir(os.path.join(MODULE_ROOT, p))
                   and not os.path.exists(
                       os.path.join(MODULE_ROOT, p, '__init__.py'))]
        self.assertFalse(missing, '這些套件缺 __init__.py：%s' % missing)

    def test_init_does_not_import_missing_modules(self):
        """`__init__.py` 不可以 import 不存在的模組（ImportError 擋住整個模組）。"""
        phantom = []
        for pkg in PACKAGES:
            d = os.path.join(MODULE_ROOT, pkg)
            if not os.path.isdir(d):
                continue
            names = _init_imports(d) or set()
            have = set(_modules_of(d)) | {
                x for x in os.listdir(d)
                if os.path.isdir(os.path.join(d, x))
                and os.path.exists(os.path.join(d, x, '__init__.py'))}
            phantom += ['%s/%s' % (pkg, n) for n in sorted(names - have)]
        self.assertFalse(
            phantom, '__init__.py import 了不存在的模組：%s' % phantom)

    def test_every_module_has_an_importer(self):
        """判準 A：每支 .py 都要有某個 importer（init 或同層）。

        沒有任何 importer ＝ 真的死檔。
        """
        orphans = []
        for pkg in PACKAGES:
            d = os.path.join(MODULE_ROOT, pkg)
            if not os.path.isdir(d):
                continue
            names = _init_imports(d) or set()
            for stem in _modules_of(d):
                if stem in names:
                    continue
                if _sibling_importers(d, stem):
                    continue
                orphans.append('%s/%s.py' % (pkg, stem))
        self.assertFalse(
            orphans,
            '下列 .py 沒有任何 importer（__init__.py 沒收、同層也沒 import）'
            '——它們是死檔：\n  %s' % '\n  '.join(orphans))

    def test_files_defining_registrable_classes_are_in_init(self):
        """判準 B：定義 model／controller／測試類別的檔案必須在 `__init__.py`。

        ☠️ 這是會害人的那一條：測試類別沒被 import ＝ **那批測試永遠不執行，
        而測試報告一片綠**。model 沒被 import ＝ model 不存在，而錯誤出現在
        很遠的地方（視圖找不到欄位、ACL 指到不存在的 model）。
        """
        unregistered = []
        for pkg in PACKAGES:
            d = os.path.join(MODULE_ROOT, pkg)
            if not os.path.isdir(d):
                continue
            names = _init_imports(d) or set()
            for stem in _modules_of(d):
                if stem in names:
                    continue
                classes = _registrable_classes(os.path.join(d, '%s.py' % stem))
                if classes:
                    unregistered.append(
                        '%s/%s.py 定義了 %s 但不在 __init__.py 裡'
                        % (pkg, stem, classes))
        self.assertFalse(
            unregistered,
            '下列檔案定義了需要註冊的類別卻沒被 __init__.py 收：\n  %s'
            % '\n  '.join(unregistered))
