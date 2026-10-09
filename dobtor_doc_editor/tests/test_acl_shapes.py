# -*- coding: utf-8 -*-
r"""刻意的 ACL 形狀要被釘住——否則會被「順手補齊」。

☠️ Odoo 的 `security/ir.model.access.csv` **不支援註解行**，所以「為什麼這個
model 的權限長這樣」沒有地方可寫。結果是：看起來缺了一格的權限，下一個人會
當成漏的補上去。

2026-10-09 的全檔案稽核就在 `doc.output` 上停過：manager 是
`perm_read` ＋ `perm_unlink`，**沒有** write／create。看起來像漏的。
查過之後是刻意的——紀錄由 `_record_output()` 以 sudo 建立，給人工 create
權限會讓「輸出紀錄」失去意義（它要忠實反映實際印過什麼）。

所以這一支把「刻意的形狀」變成會紅的事實。要改 ACL 必須先改這裡，
而改這裡會逼人去讀 model 的 docstring 看原因。

**這不是把所有 ACL 都鎖死**——只釘那些「看起來像漏的、但其實是決定」的。
全部鎖死會變成每次改權限都要改測試的噪音。
"""
import csv
import io
import os

from odoo.tests.common import TransactionCase, tagged

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACL_PATH = os.path.join(MODULE_ROOT, 'security', 'ir.model.access.csv')

#: model_id:id → {group 短名: 'RWCU' 的子集}
#: 只列「看起來像漏的、但其實是決定」的那些。
INTENTIONAL_SHAPES = {
    'model_doc_output': {
        # 系統紀錄：以 sudo 建立，人工不可 create/write（見 doc_output.py docstring）
        'group_doc_editor': 'R',
        'group_doc_manager': 'RU',      # 可刪（清錯誤／過期），不可寫不可建
        'group_doc_portal': 'R',
    },
    'model_doc_editor_export_log': {
        # 2026-10-09 稽核收緊：原本任何人（含 portal）都讀得到全部公司的匯出紀錄
        'base.group_user': '',          # 連 read 都不給
        'group_doc_manager': 'RWCU',
        'group_doc_portal': '',
    },
    'model_doc_editor_perf_metric': {
        # 遙測：使用者只能建自己的（配 rule_..._self_create），不給 read
        'base.group_user': 'WC',
        'group_doc_manager': 'RWCU',
        'group_doc_portal': 'WC',
    },
}


def _acl_rows():
    with open(ACL_PATH, encoding='utf-8') as fh:
        return list(csv.DictReader(io.StringIO(fh.read())))


def _perms(row):
    return ''.join(
        c for c, key in zip('RWCU', ('perm_read', 'perm_write',
                                     'perm_create', 'perm_unlink'))
        if (row.get(key) or '0').strip() in ('1', 'True', 'true'))


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'security')
class TestAclShapes(TransactionCase):
    """刻意的 ACL 形狀。"""

    def test_acl_file_parses(self):
        """先確認讀得到——讀不到的話底下那則會空轉過關。"""
        rows = _acl_rows()
        self.assertGreater(len(rows), 20, '只讀到 %d 列 ACL' % len(rows))

    def test_intentional_shapes_are_unchanged(self):
        """被釘住的形狀不可以被「順手補齊」。"""
        actual = {}
        for row in _acl_rows():
            model = row['model_id:id'].strip()
            group = (row.get('group_id:id') or '').strip()
            short = group.split('.')[-1] if group.startswith('dobtor_doc_editor.') \
                else group
            actual.setdefault(model, {})[short] = _perms(row)
        problems = []
        for model, wanted in INTENTIONAL_SHAPES.items():
            got = actual.get(model)
            if got is None:
                problems.append('%s 在 ACL 裡找不到了' % model)
                continue
            for group, perms in wanted.items():
                if group not in got:
                    problems.append('%s 少了 %s 那一列' % (model, group))
                elif got[group] != perms:
                    problems.append(
                        '%s / %s 的權限從 %r 變成 %r'
                        % (model, group, perms, got[group]))
        self.assertFalse(
            problems,
            '下列 ACL 的形狀是刻意的，被改了：\n  %s\n'
            '——改之前請讀對應 model 的 docstring（CSV 不支援註解，'
            '所以理由寫在那裡），確認你知道為什麼它原本長那樣。'
            % '\n  '.join(problems))
