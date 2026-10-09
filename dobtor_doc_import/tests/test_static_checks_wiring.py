# -*- coding: utf-8 -*-
r"""本機靜態檢查**自己**的健康——Makefile 的接線守門員。

☠️ 為什麼需要這一支（2026-10-09 稽核，一次抓到三個）：

1. `ci-xml` 原本寫 `find … -exec xmllint --noout {} \;`。**find 的退出碼不受
   -exec 的結果影響，恆為 0** ——壞掉的 XML 會把 parser error 印出來，然後
   make 說過關。實測：放一支壞 XML 進 views/，`ci-xml` 與 `ci-all` 都回 0。
2. `dobtor_doc_import` 的 `ci-python` scope 照抄核心、含 `models`，但拆模組
   （ADR-033）時 models/ 整個留在核心。flake8 每次都 `E902 FileNotFoundError`
   而退出 1，`make ci-all` 從拆完到現在**沒有一次能過**。
3. 同一個模組的 `ci-all` 裡**完全沒有 XML 檢查**——核心有、拆的時候沒帶過來。

三個的共同點，和本模組反覆出現的那個失效模式是同一個：
**檢查存在，但它的判決到不了任何人眼前。** 第 1 個是判決被丟棄，
第 2 個是檢查自己死了，第 3 個是檢查根本沒接上。

這些 Makefile target 是**手動**跑的（ADR-028 撤掉了 CI），所以「壞掉而沒人
發現」的時間窗沒有上限。把它們的接線綁到**有人會跑的那一組測試**上，
壞掉的當下就會紅。

這支只讀 Makefile 的文字，不執行它——執行 flake8 / xmllint 需要 host 或容器
的工具鏈，而測試跑在容器裡、不該依賴那個。
"""
import os
import re

from odoo.tests.common import TransactionCase, tagged

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _makefile():
    with open(os.path.join(MODULE_ROOT, 'Makefile'), encoding='utf-8') as fh:
        return fh.read()


def _target_body(text, target):
    """抽出一個 target 的 recipe（到下一個 target 或空行區塊結束為止）。"""
    lines = text.split('\n')
    out = []
    started = False
    for line in lines:
        if not started:
            if re.match(r'^%s\s*:' % re.escape(target), line):
                started = True
                out.append(line)
            continue
        # recipe 行以 tab 開頭；非 tab 且非空 → 這個 target 結束了
        if line.startswith('\t') or line.strip() == '':
            out.append(line)
            continue
        break
    return '\n'.join(out)


def _flake8_scope(text):
    """從 ci-python 的 FLAKE 變數抽出被掃的目錄清單。"""
    m = re.search(r'FLAKE="([^"]+)"', text)
    if not m:
        return None
    # 旗標之後、不以 - 開頭的那些 token 就是路徑
    return [t for t in m.group(1).split() if not t.startswith('-')]


@tagged('post_install', '-at_install', 'dobtor_doc_import')
class TestStaticChecksWiring(TransactionCase):
    """Makefile 的靜態檢查接線。"""

    def test_flake8_scope_dirs_all_exist(self):
        """ci-python 掃的每個目錄都要真的存在。

        這是缺陷 2 的直接守衛：scope 指到不存在的目錄 → flake8 回 E902 →
        **整個 ci-all 失敗**，於是 flake8 等於沒在檢查任何東西。
        """
        scope = _flake8_scope(_makefile())
        self.assertIsNotNone(scope, 'ci-python 的 FLAKE="…" 抽不出來，Makefile 格式變了')
        missing = [d for d in scope if not os.path.isdir(os.path.join(MODULE_ROOT, d))]
        self.assertFalse(
            missing,
            'Makefile 的 ci-python 要掃 %s，但這些目錄不存在：%s。\n'
            'flake8 遇到不存在的路徑會回 E902 並退出 1 → make ci-all 必定失敗 →'
            '等於完全沒在檢查。目錄搬家或改名時要同步改 Makefile 的 FLAKE。'
            % (scope, missing),
        )

    def test_flake8_scope_covers_every_python_package(self):
        """模組裡每個含 .py 的頂層目錄都要在 scope 內（除了明列的例外）。

        缺陷 2 的另一半：`tools/` 有三支 fixture 產生器，從來沒被掃過。
        """
        # static/ 底下是前端資源（TS/JS），security/ 只有 csv，都沒有 .py
        IGNORE = {'static', 'security', 'i18n', 'migrations', 'node_modules',
                  '__pycache__', 'docs', 'data', 'views', 'report'}
        scope = set(_flake8_scope(_makefile()) or [])
        uncovered = []
        for name in sorted(os.listdir(MODULE_ROOT)):
            path = os.path.join(MODULE_ROOT, name)
            if not os.path.isdir(path) or name in IGNORE or name.startswith('.'):
                continue
            if name in scope:
                continue
            has_py = any(
                f.endswith('.py')
                for _root, _dirs, files in os.walk(path) for f in files
            )
            if has_py:
                uncovered.append(name)
        self.assertFalse(
            uncovered,
            '這些目錄有 .py 但不在 ci-python 的 scope 裡：%s。\n'
            '要嘛加進 Makefile 的 FLAKE，要嘛加進本測試的 IGNORE 並寫明原因。'
            % uncovered,
        )

    def test_ci_xml_verdict_is_not_discarded(self):
        r"""ci-xml 不可以用 `find -exec … \;` 那個形式。

        缺陷 1 的回歸守衛。`find` 的退出碼**不受** `-exec` 執行結果影響，
        所以那個寫法會把 xmllint 的判決丟掉：錯誤訊息印出來、make 回 0。
        正確寫法是走 pipeline（`-print0 | xargs -0 xmllint`），xargs 的
        退出碼會傳出來。
        """
        body = _target_body(_makefile(), 'ci-xml')
        self.assertTrue(body, 'Makefile 找不到 ci-xml target')
        # 只看 recipe 行（以 tab 開頭），註解行裡會提到舊寫法當教材
        recipe = '\n'.join(
            line for line in body.split('\n')
            if line.startswith('\t') and not line.lstrip('\t').startswith('#')
        )
        self.assertNotIn(
            '-exec', recipe,
            'ci-xml 的 recipe 又用了 find -exec——那個形式 find 恆回 0，'
            'xmllint 的判決會被丟棄（2026-10-09 實測：壞 XML 時 ci-all 回 0）。'
            '改用 `-print0 | xargs -0 xmllint --noout`。',
        )
        self.assertIn(
            'xargs', recipe,
            'ci-xml 的 recipe 沒有走 pipeline，判決可能傳不出來。',
        )

    def test_ci_all_wires_in_every_check_target(self):
        """ci-all 要把所有 ci-* 檢查 target 都接進去。

        缺陷 3 的守衛：匯入模組寫了檢查卻沒接進 ci-all，等於沒寫。
        """
        text = _makefile()
        declared = set(re.findall(r'^(ci-[a-z0-9-]+)\s*:', text, re.M)) - {'ci-all'}
        m = re.search(r'^ci-all\s*:([^#\n]*)', text, re.M)
        self.assertTrue(m, 'Makefile 找不到 ci-all target')
        wired = set(m.group(1).split())
        orphan = sorted(declared - wired)
        self.assertFalse(
            orphan,
            '這些檢查 target 沒有被 ci-all 接進去：%s。\n'
            '寫了檢查卻不接線，和沒寫是同一件事。' % orphan,
        )
