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
