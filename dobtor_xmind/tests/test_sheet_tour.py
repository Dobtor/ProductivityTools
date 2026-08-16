# -*- coding: utf-8 -*-
"""多分頁切換的端到端測試（見 static/tests/tours/mindmap_sheet_tour.js）。

分頁在這裡用 ORM 先建好，不從 UI 建：``onAddSheet`` 用的是瀏覽器原生
``prompt()``，tour 停在原生對話框上就過不去了。

tour 跑完之後再回頭斷言資料庫 —— 這才是真正的回歸點：切分頁會先存檔，
只要 ``save_mindmap_data`` 又把 sheet 寫死回 ``sheet_ids[0]``，分頁 A 的
主題就會被分頁 B 的覆蓋，而畫面上不一定看得出來。
"""
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestSheetSwitchTour(HttpCase):

    def test_sheet_switch_tour(self):
        # xmind.workbook.create() 不會自動帶分頁，兩張都在這裡明確建立，
        # 順序由 sequence 決定（xmind.sheet._order = 'sequence, id'）。
        workbook = self.env['xmind.workbook'].create({'name': 'Tour Workbook'})
        sheet_a = self.env['xmind.sheet'].create({
            'name': 'Sheet A', 'workbook_id': workbook.id, 'sequence': 1,
        })
        self.env['xmind.topic'].create({
            'title': 'Alpha Root', 'sheet_id': sheet_a.id,
        })
        sheet_b = self.env['xmind.sheet'].create({
            'name': 'Sheet B', 'workbook_id': workbook.id, 'sequence': 2,
        })
        self.env['xmind.topic'].create({
            'title': 'Beta Root', 'sheet_id': sheet_b.id,
        })

        # 直接落在該筆的表單上：action 預設檢視是 kanban，繞清單點進去
        # 反而多一層不必要的脆弱性。
        self.start_tour(
            f'/odoo/action-dobtor_xmind.action_xmind_workbook/{workbook.id}',
            'dobtor_xmind_sheet_switch_tour',
            login='admin',
        )

        # tour 期間發生過 A→B→A 兩次切換，每次切換前都存了檔。
        # 兩張分頁的根主題都必須還在自己的分頁上。
        self.assertEqual(
            sheet_a.topic_ids.filtered(lambda t: not t.parent_id).mapped('name'),
            ['Alpha Root'],
            "分頁 A 的內容被別張分頁的畫布覆蓋了",
        )
        self.assertEqual(
            sheet_b.topic_ids.filtered(lambda t: not t.parent_id).mapped('name'),
            ['Beta Root'],
            "分頁 B 的內容被別張分頁的畫布覆蓋了",
        )
        # 存檔不可以把主題搬到別張分頁去（跨分頁污染）。
        self.assertFalse(
            sheet_a.topic_ids.filtered(lambda t: t.name == 'Beta Root'),
            "分頁 B 的主題跑到分頁 A 了",
        )
        self.assertFalse(
            sheet_b.topic_ids.filtered(lambda t: t.name == 'Alpha Root'),
            "分頁 A 的主題跑到分頁 B 了",
        )
