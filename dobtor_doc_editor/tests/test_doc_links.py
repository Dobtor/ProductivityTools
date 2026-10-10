# -*- coding: utf-8 -*-
r"""文件裡的連結與路徑還成立嗎——階段 6 的守衛（2026-10-09 全檔案稽核）。

量到的 4 處會害人的（不是 4 處筆誤）：

  CONTRIBUTING.md            四處把規矩**外包**給另一個 repo 的檔案
                             （`/mnt/d/work/odoo18-docker/CLAUDE.md`、
                             `/home/chichi/.claude/CLAUDE.md`），而那些路徑
                             位於已不存在的開發機。使用者的規則是
                             「模組不要追蹤／指使別的 repo，**寫規則不寫對方
                             檔名清單**」——這四處正是反例。
  docs/onboarding_prompt.md  叫新人先讀 `docs/progress_snapshot.md` 與
                             `docs/autonomous_roadmap.md`，而那兩個檔案
                             **在 git 歷史上從來不存在**（`git log --all`
                             各 0 個提交），還叫人 `cd` 到已不存在的機器。
  docs/github_workflow.md    「如兩處衝突，以 plan file 為準」——而那份
                             plan file 不在 repo 內，等於把權威指向讀不到的東西。
  docs/qweb_converter_coverage.md  說某個決定由 `tests/test_pill_pipeline.py`
                             釘住，而那支檔案後來被拆成 test_pill_*.py 六支。

☠️ 這一支守的是**會害人的那一類**，不是所有死連結。歷史日誌
（`SPRINT_AUDIT_CONSOLIDATED.md`）提到當時存在的檔案是正常的；
「附註：對應 plan 的 W5-6 段」這種史料歸屬也不該被當成缺陷。
判準寫寬會變噪音，然後被人加例外清單繞過去——`scan_absolute_promises.py`
的檔頭講的是同一件事。
"""
import os
import re

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(MODULE_ROOT)

#: 歷史日誌：它記錄當時的狀態，提到已消失的檔案是它的工作
HISTORY_DOCS = {'SPRINT_AUDIT_CONSOLIDATED.md'}

#: 已不存在的開發機留下的路徑前綴
DEAD_MACHINE = ('/mnt/d/', '/home/chichi/', 'D:\\')

#: markdown 連結
LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)\s]+)\)')


def _docs():
    for base, _dirs, files in os.walk(MODULE_ROOT):
        if 'node_modules' in base:
            continue
        for f in files:
            if f.endswith('.md') and f not in HISTORY_DOCS:
                yield os.path.join(base, f)


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


from odoo.tests.common import TransactionCase, tagged  # noqa: E402


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestDocLinks(TransactionCase):
    """文件的連結與它所指的東西。"""

    def test_there_are_docs_to_check(self):
        """先確認真的撈到文件——撈不到的話底下每一則都會空轉過關。"""
        n = len(list(_docs()))
        self.assertGreaterEqual(
            n, 10, '只撈到 %d 支 .md，_docs() 可能壞了' % n)

    def test_no_markdown_link_points_at_a_dead_machine(self):
        """不可以有**可點的連結**指向已不存在的開發機。

        純文字的史料註記（「外部計畫檔，位於已不存在的開發機」）是允許的
        ——它明說了讀不到，不會害人去追。會害人的是看起來可以點的連結。
        """
        bad = []
        for doc in sorted(_docs()):
            for label, target in LINK_RE.findall(_read(doc)):
                if target.startswith(DEAD_MACHINE):
                    bad.append('%s → [%s](%s)'
                               % (os.path.relpath(doc, MODULE_ROOT), label, target))
        self.assertFalse(
            bad,
            '下列連結指向已不存在的開發機（讀的人會撲空）：\n  %s\n'
            '史料請寫成純文字註記，不要寫成可點的連結。' % '\n  '.join(bad))

    def test_no_doc_outsources_rules_to_another_repo(self):
        """不可以把規矩外包給另一個 repo 的檔案。

        使用者的規則：「模組不要追蹤／指使別的 repo——**寫規則不寫對方檔名
        清單**」。需要別的專案的規範時，把規矩寫進來。
        """
        patterns = ('odoo18-docker/CLAUDE.md', '.claude/CLAUDE.md')
        bad = []
        for doc in sorted(_docs()):
            text = _read(doc)
            for label, target in LINK_RE.findall(text):
                if any(pat in target for pat in patterns):
                    bad.append('%s → [%s](%s)'
                               % (os.path.relpath(doc, MODULE_ROOT), label, target))
        self.assertFalse(
            bad,
            '下列連結把規矩指向另一個 repo 的檔案：\n  %s\n'
            '把規矩寫進本模組，不要寫成對方的檔名。' % '\n  '.join(bad))

    def test_relative_doc_links_resolve(self):
        """文件之間的相對連結要解析得到。

        只檢查 `.md` 的相對連結——那是讀者會點的。外部 URL、`#anchor`、
        以及指向程式碼的連結不在此列（程式碼路徑由
        `scan_absolute_promises.py` 之外的機制與 code review 顧）。
        """
        broken = []
        for doc in sorted(_docs()):
            d = os.path.dirname(doc)
            for label, target in LINK_RE.findall(_read(doc)):
                if target.startswith(('http', '#', 'mailto:')) or '://' in target:
                    continue
                path = target.split('#')[0]
                if not path.endswith('.md'):
                    continue
                if path.startswith('/'):
                    broken.append('%s → %s（絕對路徑，不可攜）'
                                  % (os.path.relpath(doc, MODULE_ROOT), target))
                    continue
                if not os.path.exists(os.path.normpath(os.path.join(d, path))):
                    broken.append('%s → %s'
                                  % (os.path.relpath(doc, MODULE_ROOT), target))
        self.assertFalse(
            broken,
            '下列文件間的相對連結解析不到：\n  %s' % '\n  '.join(broken))

    def test_onboarding_docs_do_not_point_at_files_that_never_existed(self):
        """onboarding 文件不可以叫人去讀不存在的檔案。

        ☠️ `docs/progress_snapshot.md` 與 `docs/autonomous_roadmap.md`
        **在 git 歷史上從來不存在**（實測 `git log --all` 各 0 個提交），
        而 onboarding_prompt.md 把它們列為「先讀，最準」的狀態檔。
        保留那份檔案是因為它記錄了當時的決策，但它必須明說自己過期。
        """
        never_existed = ('docs/progress_snapshot.md', 'docs/autonomous_roadmap.md')
        for name in ('docs/onboarding_prompt.md', 'docs/onboarding_sop.md'):
            path = os.path.join(MODULE_ROOT, name)
            if not os.path.exists(path):
                continue
            text = _read(path)
            mentioned = [n for n in never_existed if n in text]
            if not mentioned:
                continue
            # 提到了就必須在檔頭明說自己過期
            self.assertIn(
                '已經過期', text[:2000],
                '%s 提到了從未存在的 %s，但檔頭沒有標明自己過期'
                '——照抄的人會撲空。' % (name, mentioned))

    #: 治理文件（回答「完成了嗎／還有什麼沒查／符合需求嗎／下一步做什麼／
    #: 部署會送多少東西下去」）——這幾份是給人**現在**讀的，
    #: 不被 INDEX 列到就等於不存在。
    GOVERNANCE_DOCS = (
        'DONE_CRITERIA.md',
        'AUDIT_LENSES.md',
        'REQUIREMENTS_CONFORMANCE.md',
        'OPTIMIZATION_RECOMMENDATIONS.md',
        'DEPLOYMENT_FOOTPRINT.md',
    )

    def test_governance_docs_are_listed_in_the_index(self):
        """每一份治理文件都要被 `docs/INDEX.md` 列到。

        ☠️ 它們寫完的當下**一份都沒有進 INDEX**——那正是本次稽核一路在修的
        「存在但沒人找得到」。文件的價值取決於有人讀得到它，而 INDEX 是唯一
        的入口。
        """
        index_path = os.path.join(MODULE_ROOT, 'docs', 'INDEX.md')
        self.assertTrue(os.path.exists(index_path), '缺 docs/INDEX.md')
        index = _read(index_path)
        missing = []
        for name in self.GOVERNANCE_DOCS:
            path = os.path.join(MODULE_ROOT, 'docs', name)
            if not os.path.exists(path):
                missing.append('%s 不存在' % name)
            elif name not in index:
                missing.append('%s 存在但 INDEX.md 沒列它' % name)
        self.assertFalse(
            missing,
            '治理文件的入口有缺口：\n  %s' % '\n  '.join(missing))
