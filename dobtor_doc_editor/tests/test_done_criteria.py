# -*- coding: utf-8 -*-
r"""完工判準不准漂移——`docs/DONE_CRITERIA.md` 對 `run_done_check.sh`。

☠️ 為什麼需要這一支：這整套設計的價值在於「完成」有一份**有限、可機器判定**
的清單。那份清單一旦跟實際執行的腳本脫鉤，就退化成本模組一整天抓到的兩種形狀
之一：

  - 文件多一條、腳本沒實作 → 「宣告了但沒人執行」
  - 腳本多一條、文件沒寫    → 「有個檢查沒人知道它為什麼存在」

兩種都踩過（ADR-028 的 workflow、`tools/dist/visual_regression_pipeline.iife.js`
沒有 build script、`_assert_session_alive` 量錯東西）。所以兩邊的 ID 集合必須
**完全相等**，由這一支強制。

這支只讀檔案文字，不執行 `make done`——跑它需要 docker 容器，而測試跑在容器
裡、不該要求容器裡還有容器。
"""
import os
import re

from odoo.tests.common import TransactionCase, tagged

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(MODULE_ROOT, 'docs', 'DONE_CRITERIA.md')
SCRIPT = os.path.join(MODULE_ROOT, 'tests', 'scripts', 'run_done_check.sh')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _doc_ids():
    """判準表的第一欄：`| `id` | 判準 | 理由 |`。"""
    ids = []
    for line in _read(DOC).split('\n'):
        m = re.match(r'^\|\s*`([a-z0-9-]+)`\s*\|', line)
        if m:
            ids.append(m.group(1))
    return ids


def _script_ids():
    """腳本裡每條判準都以 `if skipped <id>;` 開頭——那是它的註冊點。"""
    return re.findall(r'^if skipped ([a-z0-9-]+);', _read(SCRIPT), re.M)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestDoneCriteria(TransactionCase):
    """判準清單與執行它的腳本必須對得上。"""

    def test_doc_and_script_exist(self):
        """先確認兩個檔案都在——不在的話底下每一則都會空轉過關。"""
        self.assertTrue(os.path.exists(DOC), '找不到 %s' % DOC)
        self.assertTrue(os.path.exists(SCRIPT), '找不到 %s' % SCRIPT)

    def test_doc_lists_some_criteria(self):
        """判準表抽得出東西——抽不到就代表表格格式變了，這支變成空檢查。"""
        ids = _doc_ids()
        self.assertGreaterEqual(
            len(ids), 5,
            'docs/DONE_CRITERIA.md 的判準表只抽到 %d 條（%s）。'
            '表格格式若改了，請同步改本測試的 _doc_ids()——'
            '不要讓它靜默地抽到 0 條然後過關。' % (len(ids), ids))

    def test_script_registers_some_criteria(self):
        """腳本的註冊點抽得出東西。"""
        ids = _script_ids()
        self.assertGreaterEqual(
            len(ids), 5,
            'run_done_check.sh 只抽到 %d 個 `if skipped <id>;` 註冊點（%s）。'
            '腳本若改了寫法，請同步改本測試的 _script_ids()。' % (len(ids), ids))

    def test_doc_and_script_cover_the_same_ids(self):
        """兩邊的 ID 集合必須**完全相等**。"""
        doc, script = set(_doc_ids()), set(_script_ids())
        only_doc = sorted(doc - script)
        only_script = sorted(script - doc)
        self.assertFalse(
            only_doc,
            'docs/DONE_CRITERIA.md 寫了但 run_done_check.sh 沒實作：%s\n'
            '——那是「宣告了但沒人執行」，本模組踩過的形狀。' % only_doc)
        self.assertFalse(
            only_script,
            'run_done_check.sh 實作了但 docs/DONE_CRITERIA.md 沒寫：%s\n'
            '——那是「有個檢查沒人知道它為什麼存在」，另一種形狀。' % only_script)

    def test_no_duplicate_ids(self):
        """同一個 ID 不可以出現兩次（表格複製貼上很容易發生）。"""
        for name, ids in (('文件', _doc_ids()), ('腳本', _script_ids())):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            self.assertFalse(dupes, '%s裡有重複的判準 ID：%s' % (name, dupes))

    def test_every_criterion_has_a_reason(self):
        """判準表每一列的「為什麼它在清單裡」不可以空白。

        ☠️ 跟 bundle_reachability.test.ts 的 `why` 同一個道理：沒有理由的判準，
        下一個人只能猜它能不能刪。
        """
        thin = []
        for line in _read(DOC).split('\n'):
            m = re.match(r'^\|\s*`([a-z0-9-]+)`\s*\|([^|]*)\|([^|]*)\|', line)
            if m and len(m.group(3).strip()) < 8:
                thin.append(m.group(1))
        self.assertFalse(thin, '這些判準沒寫「為什麼它在清單裡」：%s' % thin)

    def test_script_distinguishes_env_failure_from_pass(self):
        """腳本必須把「環境不具備」與「通過」分開（退出碼 2 vs 0）。

        ☠️ 這是今天抓到兩次的洞（VR 的兩道閘門、我自己的量測迴圈）：
        沒量到東西卻回 0。這一則守住 run_done_check.sh 不要變成第三次。
        """
        body = _read(SCRIPT)
        self.assertIn(
            'exit 2', body,
            'run_done_check.sh 沒有任何 `exit 2`——那代表它沒有把'
            '「環境不具備」與「通過」分開。')
        self.assertIn(
            '${#PASS[@]} -eq 0', body,
            'run_done_check.sh 沒有「一條判準都沒跑成」的檢查——'
            '那種情況下它會回 0，跟全部通過分不出來。')
