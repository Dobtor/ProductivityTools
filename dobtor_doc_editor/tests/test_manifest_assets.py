"""manifest 的 assets / data 完整性——核心自己的守門員。

☠️ 為什麼需要這一支：拆模組（2026-10-09）之前，這件事是由
`dobtor_doc_import/tests/unit/manifest_assets_hygiene.test.ts`（vitest）守的。
拆完之後**整條 TS 工具鏈都在匯入模組**，核心沒有 vitest 了——而核心才是有 28 支
出貨 JS 的那一個。那個守門員如果不補回來，就變成「守著只有一支 asset 的模組，
而真正會漏的那個模組沒人守」。

這裡用 Python 重寫，因為它不需要 node：
  1. manifest 的 `assets` 每一條都要解析得到檔案
  2. manifest 的 `data` 每一條都要存在
  3. `static/src/components/` 與 `static/src/core/` 底下每支 `.js` / `.xml` /
     `.css` 都要被 assets **主動引用**（被註解掉的不算），或在例外清單裡

第 3 條擋的失效模式是**靜默的**：少掛一支 JS 不會報錯，那支就是不執行；
而 OWL 會把隨之而來的渲染錯誤吞成一塊空白面板。
"""
import ast
import glob
import os
import re

from odoo.tests.common import TransactionCase, tagged

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_NAME = 'dobtor_doc_editor'

# 例外：刻意不在 assets 裡，但允許留在源樹。加例外請寫清楚原因。
ALLOW_NOT_IN_ASSETS = {
    # ☠️ 這份清單目前是**空的**，而且那是好事。
    #
    #    2026-10-09 之前它有 15 條：HTML/Wysiwyg 時代的舊資源，manifest 裡以
    #    註解列著並標「保留備查」（無條件、無期限）。全檔案稽核量到一件事:
    #    **它們唯一的引用者就是這份宣告它們沒用的清單**——讓它們活著的東西
    #    就是宣告它們死了的那份清單。2,788 行、每次稽核都要重新判讀一遍。
    #
    #    已刪除（git 歷史保留全部內容；「保留備查」在有 git 的前提下是弱理由
    #    ——git 就是備查）。
    #
    #    加新例外時請寫清楚原因**與移除條件**。沒有移除條件的例外，
    #    最後都會變成上面那 15 條。
}


def _manifest():
    path = os.path.join(MODULE_ROOT, '__manifest__.py')
    with open(path, encoding='utf-8') as fh:
        return ast.literal_eval(fh.read()), fh


def _active_asset_paths():
    """manifest 裡**主動引用**的 asset 路徑（跳過註解行）。"""
    path = os.path.join(MODULE_ROOT, '__manifest__.py')
    with open(path, encoding='utf-8') as fh:
        out = set()
        for line in fh:
            if line.lstrip().startswith('#'):
                continue
            for m in re.finditer(r"""['"]%s/([^'"]+)['"]""" % MODULE_NAME, line):
                out.add(m.group(1))
    return out


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestManifestAssets(TransactionCase):

    def test_every_asset_entry_resolves_to_a_file(self):
        man = ast.literal_eval(
            open(os.path.join(MODULE_ROOT, '__manifest__.py'), encoding='utf-8').read())
        bad = []
        for bundle, paths in (man.get('assets') or {}).items():
            for p in paths:
                if not isinstance(p, str):
                    continue
                rel = p.split('/', 1)[1] if p.startswith(MODULE_NAME + '/') else p
                if not glob.glob(os.path.join(MODULE_ROOT, rel)):
                    bad.append('%s → %s' % (bundle, p))
        self.assertFalse(bad, 'assets 解析不到檔案（少一支＝那支不執行、不報錯）：%s' % bad)

    def test_every_data_entry_exists(self):
        man = ast.literal_eval(
            open(os.path.join(MODULE_ROOT, '__manifest__.py'), encoding='utf-8').read())
        missing = [d for d in man.get('data', [])
                   if not os.path.exists(os.path.join(MODULE_ROOT, d))]
        self.assertFalse(missing, 'manifest data 指向不存在的檔案（安裝會 ParseError）：%s' % missing)

    def test_every_shipped_js_is_referenced(self):
        """`components/` 與 `core/` 底下的 .js/.xml/.css 都要被 assets 引用。"""
        active = _active_asset_paths()
        orphans = []
        for sub in ('static/src/components', 'static/src/core', 'static/src/css'):
            base = os.path.join(MODULE_ROOT, sub)
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if not f.endswith(('.js', '.xml', '.css')):
                        continue
                    rel = os.path.relpath(os.path.join(root, f), MODULE_ROOT)
                    if rel in ALLOW_NOT_IN_ASSETS or rel in active:
                        continue
                    if f.endswith('.test.js') or f == 'test_harness.js':
                        continue
                    orphans.append(rel)
        self.assertFalse(
            orphans,
            '下列檔案沒被 manifest assets 主動引用——加進 assets，或放進 '
            'ALLOW_NOT_IN_ASSETS 並寫明原因：\n  ' + '\n  '.join(sorted(orphans)))


#: `import … from "./x"` / `"../x"` / `"@dobtor_doc_editor/x"`（只看本模組自己的）
_IMPORT_RE = re.compile(
    r'''^\s*import\s[^;]*?from\s+["']((?:\.{1,2}/|@dobtor_doc_editor/)[^"']+)["']''',
    re.M)


def _resolve_import(importer_rel, spec):
    """把 import 的字串解成模組內相對路徑（含 .js）。"""
    if spec.startswith('@dobtor_doc_editor/'):
        rel = os.path.join('static', 'src', spec[len('@dobtor_doc_editor/'):])
    else:
        rel = os.path.normpath(os.path.join(os.path.dirname(importer_rel), spec))
    return rel if rel.endswith('.js') else rel + '.js'


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestAssetBundleClosure(TransactionCase):
    """每個 bundle 裡的 JS 所 import 的本模組檔案，必須在**同一個** bundle 裡。

    ☠️ 2026-10-12：doc_field_picker.js 只列在 web.assets_backend，而編輯器的
    五支 mixin 都在模組頂層 import 它。後台沒事；前台（Portal 的
    /my/documents/<id>）整條編輯器模組「unmet dependencies」，Portal 協作者打開
    文件永遠停在「載入文件編輯器…」。那個頁面的 JS 在那之前從沒在測試裡執行過，
    而 Odoo 18 沒有跨 bundle 的相依機制——**少一支就是整條斷掉，而且只在那個
    bundle 斷**。這一則不用瀏覽器就能抓到（tour 只在有 Chrome 時才跑）。
    """

    def _bundles(self):
        return {
            name: [e for e in entries if isinstance(e, str)]
            for name, entries in _manifest()[0].get('assets', {}).items()
        }

    def test_bundles_are_found(self):
        """先確認抽得到兩個 bundle——抽不到的話下一則會空轉過關。"""
        b = self._bundles()
        for name in ('web.assets_backend', 'web.assets_frontend'):
            self.assertIn(name, b, '找不到 %s' % name)
            self.assertTrue(
                [e for e in b[name] if e.endswith('.js')],
                '%s 裡一支 .js 都沒有——_bundles() 可能壞了' % name)

    def test_every_own_import_is_in_the_same_bundle(self):
        missing = []
        for name, entries in self._bundles().items():
            listed = set()
            for e in entries:
                rel = e.split('/', 1)[1] if e.startswith('dobtor_doc_editor/') else None
                if rel:
                    listed.update(
                        os.path.relpath(p, MODULE_ROOT)
                        for p in glob.glob(os.path.join(MODULE_ROOT, rel)))
            for importer in sorted(p for p in listed if p.endswith('.js')):
                with open(os.path.join(MODULE_ROOT, importer), encoding='utf-8') as fh:
                    src = fh.read()
                for spec in _IMPORT_RE.findall(src):
                    target = _resolve_import(importer, spec)
                    if target not in listed:
                        missing.append('%s：%s import 了 %s，但它不在這個 bundle'
                                       % (name, importer, target))
        self.assertFalse(
            missing,
            'bundle 不閉合（Odoo 18 沒有跨 bundle 相依，少一支整條就載不起來）：\n  %s'
            % '\n  '.join(missing))
