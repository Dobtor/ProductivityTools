# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMultiSheetSave(TransactionCase):
    """save_mindmap_data 必須寫進呼叫端指定的分頁。

    這組測試釘死一個資料遺失的迴歸：save_mindmap_data 過去固定寫
    sheet_ids[0]，而編輯器在切換分頁「之前」會先存檔目前畫面 —— 於是從
    第二張切回第一張時，會把第二張的畫面寫進第一張，第一張的內容就被清空，
    而第二張的編輯從頭到尾沒有被存下來過。
    """

    def setUp(self):
        super().setUp()
        self.Workbook = self.env['xmind.workbook']
        self.Sheet = self.env['xmind.sheet']
        self.Topic = self.env['xmind.topic']

    def _data(self, root_title, child_titles=()):
        """最小的 jsMind node_tree 載荷。"""
        return {
            'meta': {'name': root_title, 'version': '1.0'},
            'format': 'node_tree',
            'data': {
                'id': 'root',
                'topic': root_title,
                'expanded': True,
                'data': {},
                'children': [
                    {'id': 'n%d' % i, 'topic': t, 'expanded': True, 'data': {}, 'children': []}
                    for i, t in enumerate(child_titles)
                ],
            },
        }

    def _titles(self, sheet):
        return set(sheet.topic_ids.mapped('title'))

    def _make(self):
        wb = self.Workbook.create({'name': 'WB'})
        s1 = self.Sheet.create({'workbook_id': wb.id, 'name': 'Sheet 1', 'sequence': 10})
        s2 = self.Sheet.create({'workbook_id': wb.id, 'name': 'Sheet 2', 'sequence': 20})
        return wb, s1, s2

    def test_01_save_targets_given_sheet(self):
        wb, s1, s2 = self._make()
        wb.save_mindmap_data(self._data('Root1', ['A', 'B']), sheet_id=s1.id)
        wb.save_mindmap_data(self._data('Root2', ['X']), sheet_id=s2.id)

        self.assertIn('A', self._titles(s1))
        self.assertIn('B', self._titles(s1))
        self.assertIn('X', self._titles(s2))
        self.assertNotIn('X', self._titles(s1), '第二張的內容不該落到第一張')
        self.assertNotIn('A', self._titles(s2))

    def test_02_switching_back_does_not_wipe_first_sheet(self):
        """重現原始情境：Sheet1 有內容 → 切到 Sheet2（空）→ 切回 Sheet1。

        切換前的那次存檔帶的是「當下畫面」，也就是 Sheet2 的空白內容，
        但目標分頁必須是 Sheet2 而不是 Sheet1。
        """
        wb, s1, s2 = self._make()
        wb.save_mindmap_data(self._data('Root1', ['Keep me']), sheet_id=s1.id)

        # 切到 Sheet2：存目前畫面（Sheet1）→ 寫 s1
        wb.save_mindmap_data(self._data('Root1', ['Keep me']), sheet_id=s1.id)
        # 切回 Sheet1：存目前畫面（Sheet2 的空白）→ 必須寫 s2
        wb.save_mindmap_data(self._data('Sheet 2'), sheet_id=s2.id)

        self.assertIn('Keep me', self._titles(s1), 'Sheet 1 的內容不可被清空')
        self.assertNotIn('Keep me', self._titles(s2))

    def test_03_rejects_sheet_from_another_workbook(self):
        wb, s1, _s2 = self._make()
        other = self.Workbook.create({'name': 'Other'})
        foreign = self.Sheet.create({'workbook_id': other.id, 'name': 'Foreign'})
        with self.assertRaises(UserError):
            wb.save_mindmap_data(self._data('X'), sheet_id=foreign.id)

    def test_04_falls_back_to_first_sheet_without_sheet_id(self):
        """舊呼叫端（xmind.revision 還原、既有測試）不傳 sheet_id 時仍走第一張。"""
        wb, s1, s2 = self._make()
        wb.save_mindmap_data(self._data('Root1', ['Legacy']))
        self.assertIn('Legacy', self._titles(s1))
        self.assertNotIn('Legacy', self._titles(s2))

    def test_05_creates_a_sheet_when_workbook_has_none(self):
        wb = self.Workbook.create({'name': 'Empty WB'})
        self.assertFalse(wb.sheet_ids)
        wb.save_mindmap_data(self._data('Root', ['Only']))
        self.assertEqual(len(wb.sheet_ids), 1)
        self.assertIn('Only', self._titles(wb.sheet_ids))

    def test_06_first_sheet_is_the_same_on_both_paths(self):
        """編輯器初次載入走 get_mindmap_data（sheet_ids[0]），分頁列走
        sorted('sequence')；兩者的「第一張」必須是同一張，否則畫面顯示 A
        卻把存檔寫進 B。"""
        wb, s1, s2 = self._make()
        # 故意讓 id 序與 sequence 序相反
        s1.sequence = 20
        s2.sequence = 10
        wb.invalidate_recordset(['sheet_ids'])
        self.assertEqual(wb.sheet_ids[0], wb.sheet_ids.sorted('sequence')[0])

    # ----- 版本快照必須綁定分頁 -----

    def test_07_revision_records_its_sheet(self):
        wb, s1, s2 = self._make()
        wb.save_mindmap_data(self._data('Root1', ['A']), sheet_id=s1.id)
        wb.save_mindmap_data(self._data('Root2', ['X']), sheet_id=s2.id)

        revs = self.env['xmind.revision'].search(
            [('workbook_id', '=', wb.id)], order='id asc')
        self.assertEqual(len(revs), 2)
        self.assertEqual(revs[0].sheet_id, s1)
        self.assertEqual(revs[1].sheet_id, s2)

    def test_08_restore_writes_back_to_its_own_sheet(self):
        """還原 Sheet2 的版本不可覆蓋 Sheet1（與存檔同一類的資料遺失）。"""
        wb, s1, s2 = self._make()
        wb.save_mindmap_data(self._data('Root1', ['Keep me']), sheet_id=s1.id)
        wb.save_mindmap_data(self._data('Root2', ['X']), sheet_id=s2.id)
        # 再動一次 Sheet2，讓它有第二個版本可還原
        wb.save_mindmap_data(self._data('Root2', ['Y']), sheet_id=s2.id)

        rev_s2 = self.env['xmind.revision'].search(
            [('workbook_id', '=', wb.id), ('sheet_id', '=', s2.id)], order='id asc')[0]
        rev_s2.action_restore()

        self.assertIn('Keep me', self._titles(s1), 'Sheet 1 不可被還原動作覆蓋')
        self.assertIn('X', self._titles(s2), 'Sheet 2 應回到該版本')

    def test_09_legacy_revision_without_sheet_falls_back(self):
        """加上 sheet_id 之前建立的舊版本仍應可還原（寫回第一張）。"""
        wb, s1, _s2 = self._make()
        wb.save_mindmap_data(self._data('Root1', ['A']), sheet_id=s1.id)
        rev = self.env['xmind.revision'].search(
            [('workbook_id', '=', wb.id)], limit=1)
        rev.sheet_id = False          # 模擬舊資料
        rev.action_restore()
        self.assertIn('A', self._titles(s1))

    def test_10_revision_pruning_is_per_sheet(self):
        """每張分頁各自保留 50 版 —— 依工作簿修剪會讓忙碌的分頁擠掉另一張的歷史。"""
        wb, s1, s2 = self._make()
        for i in range(3):
            wb.save_mindmap_data(self._data('R1', ['A%d' % i]), sheet_id=s1.id)
        for i in range(3):
            wb.save_mindmap_data(self._data('R2', ['B%d' % i]), sheet_id=s2.id)
        Rev = self.env['xmind.revision']
        self.assertEqual(
            Rev.search_count([('workbook_id', '=', wb.id), ('sheet_id', '=', s1.id)]), 3)
        self.assertEqual(
            Rev.search_count([('workbook_id', '=', wb.id), ('sheet_id', '=', s2.id)]), 3)
