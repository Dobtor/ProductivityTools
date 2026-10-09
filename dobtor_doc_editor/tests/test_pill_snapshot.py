"""藥丸管線測試 — 快照管線：展開重複列、條件、分組、流水、稅額彙總、pass 順序。
對應 models/render/snapshot.py。

這一批是從 test_pill_pipeline.py 拆出來的（原本 3921 行、43 個類別）。
按**被測的那一層**分，讓「某一層壞了」一眼看得出是哪一批紅。
共用的 _text / _pill helper 在 test_pill_helpers.py。
"""
from unittest.mock import patch
import json

from odoo.tests.common import TransactionCase, tagged

from .test_pill_helpers import _cell, _pill, _text


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestSnapshotAndFlatten(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({
            'name': '德博測試客戶',
            'comment': False,
        })

    def test_snapshot_writes_value_and_keeps_pill(self):
        """快照後仍是 label 且仍帶 extension——否則就失去可追溯與重新帶值的能力。"""
        tree = {'main': [_pill('客戶名稱', source='record', path='name')]}
        self.Mixin._snapshot_content_json(tree, self.partner)

        el = tree['main'][0]
        self.assertEqual(el['value'], '德博測試客戶')
        self.assertEqual(el['type'], 'label')
        self.assertEqual(el['extension']['dobtorField']['path'], 'name')

    def test_snapshot_empty_value_prints_blank(self):
        """決策三：空值印空白，不印底線、不擋匯出。

        keepEmpty=True 是必要的——規則 A 的自動收合會把「只含空藥丸的段落」
        整段移除，那時就沒有元素可以斷言。這則測的是求值結果，不是收合行為；
        收合另有 TestConditionalPrinting 覆蓋。
        """
        tree = {'main': [_pill('備註', source='record', path='comment',
                               keepEmpty=True)]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(tree['main'][0]['value'], '')

    def test_snapshot_static_source(self):
        tree = {'main': [_pill('固定', source='static', static='合約編號 A-001')]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(tree['main'][0]['value'], '合約編號 A-001')

    def test_snapshot_broken_expression_does_not_raise(self):
        """一個壞欄位不該讓整份文件產不出來。（keepEmpty 理由同上）"""
        tree = {'main': [_pill('壞的', source='record', path='no_such_field_here',
                               keepEmpty=True)]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(tree['main'][0]['value'], '')

    def test_snapshot_covers_table_cells(self):
        tree = {'main': [{
            'type': 'table',
            'trList': [{'tdList': [
                {'value': [_pill('客戶', source='record', path='name')]},
            ]}],
        }]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        cell = tree['main'][0]['trList'][0]['tdList'][0]['value'][0]
        self.assertEqual(cell['value'], '德博測試客戶')

    def test_flatten_strips_pill_chrome(self):
        """決策四：匯出只輸出值，網底不進正式文件。"""
        tree = {'main': [_pill('客戶名稱', source='record', path='name')]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.Mixin._flatten_content_json(tree)

        el = tree['main'][0]
        self.assertEqual(el['value'], '德博測試客戶')
        self.assertNotIn('label', el)
        self.assertNotIn('extension', el)
        self.assertNotEqual(el.get('type'), 'label')

    def test_flatten_does_not_evaluate(self):
        """攤平不求值——值應已由快照凍結，重新求值會違背凍結語意。"""
        tree = {'main': [_pill('客戶名稱', source='record', path='name')]}
        self.Mixin._flatten_content_json(tree)
        self.assertEqual(tree['main'][0]['value'], '客戶名稱')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRepeatRows(TransactionCase):
    """重複列（表格明細）——業務單據的核心需求：訂單明細、發票行。

    純量藥丸只能帶一個值，多筆必須有列複製機制。這批測試釘住的是
    「每一列對應各自的明細」——錯掉的話單據上每一行都是同一筆資料，
    而那種錯誤看起來像是資料本身有問題，很難追到渲染層。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.parent = self.env['res.partner'].create({'name': '買方公司'})
        # type='other'：預設的 'contact' 子聯絡人會繼承母公司地址，
        # 那會讓「每列值不同」的斷言變成假通過（三列都是母公司的城市）
        self.env['res.partner'].create([
            {'name': '品項A', 'city': '台北', 'parent_id': self.parent.id, 'type': 'other'},
            {'name': '品項B', 'city': '台中', 'parent_id': self.parent.id, 'type': 'other'},
            {'name': '品項C', 'city': '高雄', 'parent_id': self.parent.id, 'type': 'other'},
        ])

    def _cell(self, *els):
        return {'value': list(els), 'colspan': 1, 'rowspan': 1}

    def _tree(self, repeat_path='child_ids'):
        return {'main': [{
            'type': 'table',
            'trList': [
                {'tdList': [self._cell(_text('品項')), self._cell(_text('城市'))]},
                {'tdList': [
                    self._cell(
                        _pill('明細', source='repeat', path=repeat_path),
                        _pill('品名', source='line', path='name'),
                    ),
                    self._cell(_pill('城市', source='line', path='city')),
                ]},
            ],
        }]}

    def _rows(self, tree):
        return [
            ['|'.join(e.get('value', '') for e in c['value']) for c in row['tdList']]
            for row in tree['main'][0]['trList']
        ]

    def test_row_expands_once_per_line(self):
        tree = self._tree()
        self.assertEqual(self.Mixin._count_repeat_rows(tree), 1)
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(
            len(tree['main'][0]['trList']), 4, '表頭 1 + 明細 3',
        )

    def test_each_row_binds_to_its_own_line(self):
        """每列的值必須對應各自的明細——這是整個功能的重點。"""
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertEqual(rows[0], ['品項', '城市'], '表頭列不該被動')
        self.assertEqual(rows[1], ['品項A', '台北'])
        self.assertEqual(rows[2], ['品項B', '台中'])
        self.assertEqual(rows[3], ['品項C', '高雄'])

    def test_marker_pill_not_in_output(self):
        """標記藥丸是設計期的宣告，不是內容，不可出現在成品。"""
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.parent)
        left = [
            el for el in self.Mixin._iter_elements(tree)
            if (self.Mixin._element_field_meta(el) or {}).get('source') == 'repeat'
        ]
        self.assertFalse(left)

    def test_zero_lines_removes_the_row(self):
        """零筆明細整列移除——留一列空白會印出一條空表格列，看起來像資料掉了。"""
        empty = self.env['res.partner'].create({'name': '無明細'})
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, empty)
        self.assertEqual(len(tree['main'][0]['trList']), 1, '只剩表頭')

    def test_non_o2m_path_yields_no_rows(self):
        """重複來源指到純量欄位是設定錯誤——不該炸，但也不該產生列。"""
        tree = self._tree(repeat_path='name')
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(len(tree['main'][0]['trList']), 1)

    def test_bad_path_does_not_raise(self):
        tree = self._tree(repeat_path='no_such_field')
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(len(tree['main'][0]['trList']), 1)

    def test_line_pill_outside_repeat_row_keeps_label(self):
        """line 藥丸放在重複列之外＝設定錯誤，刻意保留標籤文字讓錯誤看得見。"""
        tree = {'main': [_pill('孤立明細欄位', source='line', path='name')]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(
            tree['main'][0]['value'], '孤立明細欄位',
            '不該變空白——變空白的話使用者找不到問題在哪',
        )

    def test_scalar_and_aggregate_still_work_alongside(self):
        """主記錄的純量藥丸與聚合表達式要能與重複列並存。

        聚合不需要另外設計——沙箱已支援 one2many 與 Jinja 的 sum/length。
        """
        tree = self._tree()
        tree['main'].insert(0, _pill('買方', source='record', path='name'))
        tree['main'].append(_pill(
            '筆數', source='expression', expression='object.child_ids|length',
        ))
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(tree['main'][0]['value'], '買方公司')
        self.assertEqual(tree['main'][-1]['value'], '3')

    def test_expanded_rows_survive_flatten_and_html(self):
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.parent)
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree)
        )
        self.assertEqual(html.count('<tr>'), 4)
        for name in ('品項A', '品項B', '品項C'):
            self.assertIn(name, html)
        self.assertNotIn('#e3f2fd', html, '藥丸網底不該進成品')


_NL = {'value': '\n'}


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestConditionalPrinting(TransactionCase):
    """條件式列印三種機制。

    對應真實 Odoo 報表的 t-if 分佈（銷售訂單 20 個實測）：
      一半是「欄位有值才印」→ 自動收合（零設定）
      值比較／複合邏輯      → source='condition'
      逐明細判斷           → repeat 的 filter
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.with_vat = self.env['res.partner'].create({
            'name': '有統編公司', 'vat': '12345678', 'city': '台北市',
        })
        self.no_vat = self.env['res.partner'].create({
            'name': '無統編公司', 'city': '台中市',
        })

    def _paras(self, tree):
        import re
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree)
        )
        return [
            re.sub(r'<[^>]+>', '', x)
            for x in re.findall(r'<p[^>]*>(.*?)</p>', html)
        ]

    # ─── ① 自動收合空段落（規則 A）────────────────────────────────────

    def _labelled_tree(self, **pill_kw):
        return {'main': [
            _text('客戶：'), _pill('名稱', source='record', path='name'), dict(_NL),
            _text('統一編號：'),
            _pill('統編', source='record', path='vat', **pill_kw), dict(_NL),
            _text('這段沒有藥丸'), dict(_NL),
        ]}

    def test_paragraph_with_value_is_kept(self):
        tree = self._labelled_tree()
        self.Mixin._snapshot_content_json(tree, self.with_vat)
        self.assertIn('統一編號：12345678', self._paras(tree))

    def test_empty_pill_collapses_whole_paragraph_including_label(self):
        """規則 A：標籤一起消失。

        否則沒統編的單據上會留一個孤零零的「統一編號：」——
        這是最常見的難看問題，也是當初選規則 A 的理由。
        """
        tree = self._labelled_tree()
        self.Mixin._snapshot_content_json(tree, self.no_vat)
        paras = self._paras(tree)
        self.assertNotIn('統一編號：', paras)
        self.assertFalse([p for p in paras if '統一編號' in p])

    def test_paragraph_without_pills_is_never_collapsed(self):
        """純靜態段落不受影響——收合只針對「含藥丸且全空」的段落。"""
        tree = self._labelled_tree()
        self.Mixin._snapshot_content_json(tree, self.no_vat)
        self.assertIn('這段沒有藥丸', self._paras(tree))

    def test_keep_empty_opts_out_of_collapse(self):
        """keepEmpty 是規則 A 的退出閥，給「重要靜態文字配可選藥丸」用。"""
        tree = self._labelled_tree(keepEmpty=True)
        self.Mixin._snapshot_content_json(tree, self.no_vat)
        self.assertIn('統一編號：', self._paras(tree))

    # ─── ② 明確條件 ──────────────────────────────────────────────────

    def _cond_tree(self, expression):
        return {'main': [
            _pill('條件', source='condition', expression=expression),
            _text('有條件的內容'), dict(_NL),
            _text('無條件的內容'), dict(_NL),
        ]}

    def test_paragraph_condition_true_keeps_and_strips_marker(self):
        tree = self._cond_tree('object.vat')
        self.Mixin._snapshot_content_json(tree, self.with_vat)
        paras = self._paras(tree)
        self.assertIn('有條件的內容', paras)
        # 不能直接找「條件」兩字——內容本身就有。改查標記藥丸的元素是否還在。
        left = [
            el for el in self.Mixin._iter_elements(tree)
            if (self.Mixin._element_field_meta(el) or {}).get('source') == 'condition'
        ]
        self.assertFalse(left, '標記藥丸不該留在成品')

    def test_paragraph_condition_false_removes_paragraph(self):
        tree = self._cond_tree('object.vat')
        self.Mixin._snapshot_content_json(tree, self.no_vat)
        paras = self._paras(tree)
        self.assertNotIn('有條件的內容', paras)
        self.assertIn('無條件的內容', paras)

    def test_value_comparison_condition(self):
        """涵蓋 t-if 裡的值比較類（partner_shipping_id == partner_invoice_id 之類）。"""
        tree = self._cond_tree("object.city == '台北市'")
        self.Mixin._snapshot_content_json(tree, self.with_vat)
        self.assertIn('有條件的內容', self._paras(tree))

        tree2 = self._cond_tree("object.city == '台北市'")
        self.Mixin._snapshot_content_json(tree2, self.no_vat)
        self.assertNotIn('有條件的內容', self._paras(tree2))

    def test_broken_condition_keeps_content(self):
        """條件寫壞時保留內容——寧可多印也不要靜默少印。

        少印的話使用者會以為是資料問題，幾乎追不到渲染層。
        """
        tree = self._cond_tree('object.no_such_field.nope')
        self.Mixin._snapshot_content_json(tree, self.with_vat)
        self.assertIn('有條件的內容', self._paras(tree))

    def test_row_condition(self):
        def tree(expr):
            return {'main': [{'type': 'table', 'trList': [
                {'tdList': [{'value': [_text('表頭')], 'colspan': 1, 'rowspan': 1}]},
                {'tdList': [{'value': [
                    _pill('條件', source='condition', expression=expr),
                    _text('有條件的列'),
                ], 'colspan': 1, 'rowspan': 1}]},
                {'tdList': [{'value': [_text('無條件的列')], 'colspan': 1, 'rowspan': 1}]},
            ]}]}
        t1 = tree('object.vat')
        self.Mixin._snapshot_content_json(t1, self.with_vat)
        self.assertEqual(len(t1['main'][0]['trList']), 3)

        t2 = tree('object.vat')
        self.Mixin._snapshot_content_json(t2, self.no_vat)
        self.assertEqual(len(t2['main'][0]['trList']), 2)

    # ─── ③ 明細篩選 ──────────────────────────────────────────────────

    def test_repeat_filter_drops_lines(self):
        """對應原生報表的 lines_to_report：section/note 行不該印成空白列。"""
        parent = env_parent = self.env['res.partner'].create({'name': '母公司'})
        self.env['res.partner'].create([
            {'name': '正常A', 'parent_id': parent.id, 'type': 'other'},
            {'name': '略過我', 'parent_id': parent.id, 'type': 'other',
             'comment': 'SKIP'},
            {'name': '正常B', 'parent_id': parent.id, 'type': 'other'},
        ])

        def tree(flt=None):
            meta = {'source': 'repeat', 'path': 'child_ids', 'labelText': '明細'}
            if flt:
                meta['filter'] = flt
            marker = {'type': 'label', 'value': '明細', 'label': {},
                      'extension': {'dobtorField': meta}}
            return {'main': [{'type': 'table', 'trList': [
                {'tdList': [{'value': [_text('品名')], 'colspan': 1, 'rowspan': 1}]},
                {'tdList': [{'value': [
                    marker, _pill('品名', source='line', path='name'),
                ], 'colspan': 1, 'rowspan': 1}]},
            ]}]}

        t_all = tree()
        self.Mixin._snapshot_content_json(t_all, parent)
        self.assertEqual(len(t_all['main'][0]['trList']), 4, '表頭 + 3 筆')

        t_flt = tree('not line.comment')
        self.Mixin._snapshot_content_json(t_flt, parent)
        self.assertEqual(len(t_flt['main'][0]['trList']), 3, '表頭 + 2 筆')
        names = [
            e.get('value', '')
            for row in t_flt['main'][0]['trList']
            for c in row['tdList'] for e in c['value']
        ]
        self.assertNotIn('略過我', names)

    def test_filter_can_use_object_as_well_as_line(self):
        """filter 裡 line 與 object 都指向當前明細，兩種寫法都接受。"""
        parent = self.env['res.partner'].create({'name': '母公司2'})
        self.env['res.partner'].create([
            {'name': '留下', 'parent_id': parent.id, 'type': 'other'},
            {'name': '濾掉', 'parent_id': parent.id, 'type': 'other',
             'comment': 'X'},
        ])
        meta = {'source': 'repeat', 'path': 'child_ids', 'labelText': '明細',
                'filter': 'not object.comment'}
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [{'value': [
                {'type': 'label', 'value': '明細', 'label': {},
                 'extension': {'dobtorField': meta}},
                _pill('品名', source='line', path='name'),
            ], 'colspan': 1, 'rowspan': 1}]},
        ]}]}
        self.Mixin._snapshot_content_json(tree, parent)
        self.assertEqual(len(tree['main'][0]['trList']), 1)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestConditionBlocks(TransactionCase):
    """條件區塊：無框線單格表格當容器。

    這批測試釘住的是「區塊邊界」。元素串列是扁平的，只有換行與表格列是可靠
    邊界；表格是原子結構，使用者刪就整個刪。所以區塊條件不需要新機制，
    但需要兩件配套：空表格要連著孤兒換行一起清掉、容器不可印框線。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({
            'name': '測試公司', 'vat': 'TW12345678',
        })

    def _block(self, inner, block='condition', **meta):
        return {
            'type': 'table',
            'extension': {'dobtorBlock': block},
            'trList': [{'tdList': [{
                'value': ([_pill('條件', source='condition', **meta)] if meta
                          else []) + list(inner),
                'colspan': 1, 'rowspan': 1,
            }]}],
        }

    def _html(self, tree):
        self.Mixin._snapshot_content_json(tree, self.partner)
        return self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree)
        )

    def test_false_condition_removes_whole_block(self):
        """條件為假時整塊（含多段內容）消失。"""
        tree = {'main': [
            _text('前'), _text('\n'),
            self._block(
                [_text('第一段'), _text('\n'), _text('第二段'), _text('\n')],
                expression='object.name == "不存在"',
            ),
            _text('\n'), _text('後'), _text('\n'),
        ]}
        html = self._html(tree)
        self.assertNotIn('第一段', html)
        self.assertNotIn('第二段', html)
        self.assertIn('前', html)
        self.assertIn('後', html)

    def test_false_condition_leaves_no_blank_paragraph(self):
        """移除後不可留下空段落——使用者看到「條件為假時多一行空白」完全追不到原因。"""
        tree = {'main': [
            _text('前'), _text('\n'),
            self._block([_text('內容'), _text('\n')],
                        expression='object.name == "不存在"'),
            _text('\n'), _text('後'), _text('\n'),
        ]}
        self.assertEqual(self._html(tree), '<p>前</p><p>後</p>')

    def test_true_condition_keeps_block_and_drops_marker(self):
        tree = {'main': [self._block(
            [_text('內容'), _text('\n')], expression='object.name',
        )]}
        html = self._html(tree)
        self.assertIn('內容', html)
        self.assertNotIn('條件', html, '標記藥丸是宣告不是內容')

    def test_block_table_carries_doc_block_class(self):
        """容器不是真表格，輸出時必須關掉框線——靠這個 class。"""
        tree = {'main': [self._block([_text('內容'), _text('\n')],
                                     expression='object.name')]}
        self.assertIn('class="doc-block"', self._html(tree))

    def test_plain_table_has_no_doc_block_class(self):
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [{'value': [_text('普通表格')],
                         'colspan': 1, 'rowspan': 1}]},
        ]}]}
        html = self._html(tree)
        self.assertIn('<table>', html)
        self.assertNotIn('doc-block', html)

    def test_nested_block_inside_table_cell_works(self):
        """巢狀：區塊放在表格儲存格裡也要生效（走訪器會下探）。"""
        inner = self._block([_text('該消失'), _text('\n')],
                            expression='object.name == "不存在"')
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [{'value': [_text('外層'), _text('\n'), inner],
                         'colspan': 1, 'rowspan': 1}]},
        ]}]}
        html = self._html(tree)
        self.assertIn('外層', html)
        self.assertNotIn('該消失', html)

    # ─── if / else 配對 ──────────────────────────────────────────────

    def _if_else(self, expression):
        """同一個表格的兩列共用 groupId——兩個分支因此不可能被分開。"""
        return {
            'type': 'table',
            'extension': {'dobtorBlock': 'condition'},
            'trList': [
                {'tdList': [{'value': [
                    _pill('若', source='condition', groupId='g1', role='if',
                          expression=expression),
                    _text('真分支'), _text('\n'),
                ], 'colspan': 1, 'rowspan': 1}]},
                {'tdList': [{'value': [
                    _pill('否則', source='condition', groupId='g1', role='else'),
                    _text('假分支'), _text('\n'),
                ], 'colspan': 1, 'rowspan': 1}]},
            ],
        }

    def test_if_true_prints_only_if_branch(self):
        html = self._html({'main': [self._if_else('object.vat')]})
        self.assertIn('真分支', html)
        self.assertNotIn('假分支', html)

    def test_if_false_prints_only_else_branch(self):
        html = self._html({'main': [self._if_else('not object.vat')]})
        self.assertIn('假分支', html)
        self.assertNotIn('真分支', html)

    def test_exactly_one_branch_always_survives(self):
        """互斥必須由程式保證。使用者維護兩份互補條件時，改一個忘了改另一個
        會變成兩段都印或都不印，而且不會報錯——那正是這個機制要消除的。"""
        for expression in ('object.vat', 'not object.vat'):
            tree = {'main': [self._if_else(expression)]}
            self.Mixin._snapshot_content_json(tree, self.partner)
            self.assertEqual(
                len(tree['main'][0]['trList']), 1,
                '不論條件真假，剛好留下一個分支：%s' % expression,
            )

    def test_orphan_else_prints(self):
        """配對的 if 被刪掉時，else 一律列印——與條件求值失敗同樣的策略：
        寧可多印也不要靜默少印。"""
        tree = {'main': [{
            'type': 'table',
            'extension': {'dobtorBlock': 'condition'},
            'trList': [{'tdList': [{'value': [
                _pill('否則', source='condition', groupId='gX', role='else'),
                _text('孤兒分支'), _text('\n'),
            ], 'colspan': 1, 'rowspan': 1}]}],
        }]}
        self.assertIn('孤兒分支', self._html(tree))

    def test_group_results_computed_before_any_removal(self):
        """列條件會移走 if 標記，段落裡的 else 必須還找得到配對。

        兩個 pass 共用同一份先算好的結果，順序因此不影響語意。
        """
        tree = {'main': [
            # if 在表格列裡
            {'type': 'table', 'trList': [{'tdList': [{'value': [
                _pill('若', source='condition', groupId='g9', role='if',
                      expression='not object.vat'),
                _text('列分支'),
            ], 'colspan': 1, 'rowspan': 1}]}]},
            # else 在段落裡
            _pill('否則', source='condition', groupId='g9', role='else'),
            _text('段落分支'), _text('\n'),
        ]}
        html = self._html(tree)
        self.assertNotIn('列分支', html, 'if 為假 → 該列不印')
        self.assertIn('段落分支', html, 'else 取反 → 該段要印')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRunningPills(TransactionCase):
    """流水藥丸：項次與逐列累計。

    這是唯一需要跨列狀態的藥丸。累加器的鍵是「藥丸在範本列中的位置」——
    位置若算錯（例如在過濾標記藥丸之後才算），每一列會共用或錯開累加器，
    印出來的數字看似合理卻是錯的。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.parent = self.env['res.partner'].create({'name': '母公司'})
        self.env['res.partner'].create([
            {'name': 'L1', 'parent_id': self.parent.id, 'type': 'other'},
            {'name': 'L2', 'parent_id': self.parent.id, 'type': 'other'},
            {'name': 'L3', 'parent_id': self.parent.id, 'type': 'other'},
        ])

    def _cell(self, *els):
        return {'value': list(els), 'colspan': 1, 'rowspan': 1}

    def _tree(self, **running):
        return {'main': [{'type': 'table', 'trList': [
            {'tdList': [
                self._cell(
                    _pill('明細', source='repeat', path='child_ids'),
                    _pill('項次', source='running', op='index', **running),
                ),
                self._cell(_pill('品名', source='line', path='name')),
            ]},
        ]}]}

    def _col(self, tree, idx):
        return [
            ''.join(e.get('value', '') for e in row['tdList'][idx]['value'])
            for row in tree['main'][0]['trList']
        ]

    def test_index_counts_from_one(self):
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(self._col(tree, 0), ['1', '2', '3'])

    def test_index_is_per_pill_not_shared(self):
        """同一列兩個項次藥丸各有自己的累加器，不可互相加成。"""
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [
                self._cell(
                    _pill('明細', source='repeat', path='child_ids'),
                    _pill('項次', source='running', op='index'),
                ),
                self._cell(_pill('項次2', source='running', op='index')),
            ]},
        ]}]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(self._col(tree, 0), ['1', '2', '3'])
        self.assertEqual(self._col(tree, 1), ['1', '2', '3'])

    def test_running_sum_accumulates(self):
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [
                self._cell(
                    _pill('明細', source='repeat', path='child_ids'),
                    _pill('累計', source='running', op='sum',
                          expression='1', numberFormat=',.0f'),
                ),
            ]},
        ]}]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(self._col(tree, 0), ['1', '2', '3'])

    def test_running_sum_ignores_non_numeric(self):
        """求值不出數字時當 0，不可讓整份文件產不出來。"""
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [
                self._cell(
                    _pill('明細', source='repeat', path='child_ids'),
                    _pill('累計', source='running', op='sum',
                          expression='line.name', numberFormat=',.0f'),
                ),
            ]},
        ]}]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(self._col(tree, 0), ['0', '0', '0'])

    def test_running_pill_outside_repeat_row_keeps_label(self):
        """放在重複列之外是設定錯誤——保留標籤文字讓錯誤在文件上看得見，
        而不是靜默變成空白。"""
        tree = {'main': [_pill('項次', source='running', op='index'),
                         _text('\n')]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual(tree['main'][0]['value'], '項次')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRepeatGrouping(TransactionCase):
    """分組重複：分組標題列 / 分組小計列。

    取代 QWeb 的累加器（current_subtotal = current_subtotal + …）。
    最容易踩的是求值順序：分隔列一定會被「排除非商品列」那種篩選濾掉，
    先篩就再也找不到分隔點——那會靜默退化成「只有一組」，小計看起來
    是個合理的數字，但其實是全單總計。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.parent = self.env['res.partner'].create({'name': '母公司'})
        # comment 當「這是分隔列」的旗標，city 當分組依據
        self.env['res.partner'].create([
            # 名稱刻意加數字前綴：child_ids 依 complete_name 排序而不是建立
            # 順序，中文名會排到 ASCII 之後——分隔列就跑到明細後面去，
            # 分組測試會以莫名其妙的方式失敗。
            {'name': '1 甲區', 'parent_id': self.parent.id, 'type': 'other',
             'comment': 'SECTION'},
            {'name': '2 A1', 'parent_id': self.parent.id, 'type': 'other',
             'city': '台北'},
            {'name': '3 A2', 'parent_id': self.parent.id, 'type': 'other',
             'city': '台中'},
            {'name': '4 乙區', 'parent_id': self.parent.id, 'type': 'other',
             'comment': 'SECTION'},
            {'name': '5 B1', 'parent_id': self.parent.id, 'type': 'other',
             'city': '台北'},
        ])

    def _cell(self, *els):
        return {'value': list(els), 'colspan': 1, 'rowspan': 1}

    def _tree(self, repeat_meta, with_header=True, with_footer=True):
        rows = []
        if with_header:
            rows.append({'tdList': [
                self._cell(_pill('〔標題〕', source='groupHeader',
                                 isMarker=True),
                           _pill('組名', source='group',
                                 expression='group.label')),
                self._cell(_text('')),
            ]})
        rows.append({'tdList': [
            self._cell(_pill('明細', source='repeat', **repeat_meta)),
            self._cell(_pill('品名', source='line', path='name')),
        ]})
        if with_footer:
            rows.append({'tdList': [
                self._cell(_pill('〔小計〕', source='groupFooter',
                                 isMarker=True)),
                self._cell(_pill('筆數', source='group',
                                 expression='group.lines|length')),
            ]})
        return {'main': [{'type': 'table', 'trList': rows}]}

    def _rows(self, tree):
        return [
            ['|'.join(e.get('value', '') for e in c['value'])
             for c in row['tdList']]
            for row in tree['main'][0]['trList']
        ]

    def test_marker_mode_splits_into_groups(self):
        tree = self._tree({
            'path': 'child_ids',
            'groupMode': 'marker',
            'groupSplitOn': 'line.comment',
        })
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        # 標題 甲區 / A1 / A2 / 小計2 / 標題 乙區 / B1 / 小計1
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[1][1], '2 A1')
        self.assertEqual(rows[2][1], '3 A2')
        self.assertEqual(rows[3][1], '2', '甲區兩筆')
        self.assertEqual(rows[5][1], '5 B1')
        self.assertEqual(rows[6][1], '1', '乙區一筆')

    def test_marker_mode_filter_applied_after_grouping(self):
        """分隔列會被篩選排除，所以分組必須先做。

        這則測試是整個分組功能最關鍵的一條：先篩再分組的話結果會變成
        「只有一組」，小計印出來是全單總計——數字看起來合理，錯得完全看不出來。
        """
        tree = self._tree({
            'path': 'child_ids',
            'filter': 'not line.comment',
            'groupMode': 'marker',
            'groupSplitOn': 'line.comment',
        })
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        names = [r[1] for r in rows]
        self.assertNotIn('1 甲區', names, '分隔列本身不該出現在明細裡')
        self.assertNotIn('4 乙區', names)
        self.assertEqual(
            [r[1] for r in rows if r[1] in ('1', '2')], ['2', '1'],
            '兩組小計分別是 2 筆與 1 筆，不是合併成一組 3 筆',
        )

    def test_marker_group_label_comes_from_split_line(self):
        tree = self._tree({
            'path': 'child_ids',
            'filter': 'not line.comment',
            'groupMode': 'marker',
            'groupSplitOn': 'line.comment',
        })
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertEqual(rows[0][0], '1 甲區')
        self.assertEqual(rows[4][0], '4 乙區')

    def test_field_mode_groups_by_value(self):
        tree = self._tree({
            'path': 'child_ids',
            'filter': 'not line.comment',
            'groupMode': 'field',
            'groupBy': 'city',
        })
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        # 台北組（A1, B1）＋ 台中組（A2）
        self.assertEqual(rows[0][0], '台北')
        self.assertEqual([rows[1][1], rows[2][1]], ['2 A1', '5 B1'])
        self.assertEqual(rows[3][1], '2')
        self.assertEqual(rows[4][0], '台中')

    def test_no_grouping_makes_footer_a_grand_total(self):
        """沒設定分組時整批明細視為一組——小計列因此變成總計列。

        刻意的：使用者放了小計列卻沒設分組時，印出總計是他會期待的，
        比「什麼都不印」好。
        """
        tree = self._tree({'path': 'child_ids', 'filter': 'not line.comment'})
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertEqual(rows[-1][1], '3', '三筆明細全算一組')

    def test_group_subtotal_expression_sees_group_lines(self):
        tree = self._tree({
            'path': 'child_ids',
            'filter': 'not line.comment',
            'groupMode': 'marker',
            'groupSplitOn': 'line.comment',
        }, with_header=False)
        # 把小計的表達式換成「組內品名串接」，證明 group.lines 是真的 recordset 清單
        footer = tree['main'][0]['trList'][-1]['tdList'][1]['value'][0]
        footer['extension']['dobtorField']['expression'] = (
            "group.lines|map(attribute='name')|join('+')"
        )
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertIn('2 A1+3 A2', [r[1] for r in rows])
        self.assertIn('5 B1', [r[1] for r in rows])

    def test_group_marker_pills_not_in_output(self):
        tree = self._tree({
            'path': 'child_ids',
            'groupMode': 'marker',
            'groupSplitOn': 'line.comment',
        })
        self.Mixin._snapshot_content_json(tree, self.parent)
        flat = json.dumps(self._rows(tree), ensure_ascii=False)
        self.assertNotIn('〔標題〕', flat)
        self.assertNotIn('〔小計〕', flat)

    def test_running_reset_on_group(self):
        """每組重新起算：resetOn='group' 的累加器在組界歸零。"""
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [
                self._cell(
                    _pill('明細', source='repeat', path='child_ids',
                          filter='not line.comment', groupMode='marker',
                          groupSplitOn='line.comment'),
                    _pill('項次', source='running', op='index',
                          resetOn='group'),
                ),
            ]},
        ]}]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual([r[0] for r in self._rows(tree)], ['1', '2', '1'])

    def test_running_without_reset_runs_across_groups(self):
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [
                self._cell(
                    _pill('明細', source='repeat', path='child_ids',
                          filter='not line.comment', groupMode='marker',
                          groupSplitOn='line.comment'),
                    _pill('項次', source='running', op='index'),
                ),
            ]},
        ]}]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertEqual([r[0] for r in self._rows(tree)], ['1', '2', '3'])

    def test_broken_split_expression_degrades_to_single_group(self):
        """分隔判斷式壞掉時退化成不分組，而不是把每一筆都當分隔列。

        若沿用 _eval_condition 的「失敗當真」，一個壞掉的判斷式會印出 N 個
        空組——比不分組難看得多，所以這裡用 _try_eval_condition。
        """
        tree = self._tree({
            'path': 'child_ids',
            'filter': 'not line.comment',
            'groupMode': 'marker',
            'groupSplitOn': 'line.這個欄位不存在.x',
        }, with_header=False)
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertEqual(rows[-1][1], '3', '全部併成一組')

    def test_group_mode_without_criteria_is_no_grouping(self):
        """設了模式卻沒設依據＝不分組（而不是當掉或產生怪結果）。"""
        meta = {'source': 'repeat', 'path': 'child_ids', 'groupMode': 'marker'}
        self.assertEqual(self.Mixin._repeat_group_mode(meta), '')
        meta['groupSplitOn'] = 'line.comment'
        self.assertEqual(self.Mixin._repeat_group_mode(meta), 'marker')

    def test_empty_group_is_dropped(self):
        """空組不印：印一個標題配 0 筆小計只會讓人以為資料掉了。"""
        # 只有分隔列、沒有商品列
        lonely = self.env['res.partner'].create({'name': '空的母公司'})
        self.env['res.partner'].create({
            'name': '只有章節', 'parent_id': lonely.id, 'type': 'other',
            'comment': 'SECTION',
        })
        tree = self._tree({
            'path': 'child_ids',
            'filter': 'not line.comment',
            'groupMode': 'marker',
            'groupSplitOn': 'line.comment',
        })
        self.Mixin._snapshot_content_json(tree, lonely)
        # 整個表格的列都沒了 → 由 _drop_empty_tables 收尾
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree)
        )
        self.assertEqual(html, '')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestTaxTotalsBlock(TransactionCase):
    """稅額彙總內建區塊。

    對應原生報表的 t-call="sale.document_tax_totals"。做成內建區塊的理由是
    tax_totals 的結構每個 Odoo 版本都在改（amount_by_group 在 18 已消失）；
    這批測試釘住的是「結構變了要在這裡壞，不是在客戶的範本裡靜默印空白」。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '買方'})

    def _cell(self, *els):
        return {'value': list(els), 'colspan': 1, 'rowspan': 1}

    def _tree(self, path='tax_totals'):
        def val(part, field, label):
            return _pill(label, source='taxTotals', part=part, field=field,
                         path=path)
        return {'main': [{
            'type': 'table',
            'extension': {'dobtorBlock': 'taxTotals'},
            'trList': [
                {'tdList': [self._cell(val('untaxed', 'label', '稅前小計')),
                            self._cell(val('untaxed', 'amount', '金額'))]},
                {'tdList': [self._cell(val('groups', 'label', '稅別')),
                            self._cell(val('groups', 'amount', '稅額'))]},
                {'tdList': [self._cell(_text('總計')),
                            self._cell(val('total', 'amount', '總計金額'))]},
            ],
        }]}

    def _rows(self, tree):
        return [
            ['|'.join(e.get('value', '') for e in c['value'])
             for c in row['tdList']]
            for row in tree['main'][0]['trList']
        ]

    def test_missing_source_yields_blanks_not_crash(self):
        """欄位不存在（非銷售單據）時不可讓整份文件產不出來。

        小計列與稅別列都是「有幾筆資料就幾列」（原生也是 t-foreach），
        所以沒有 tax_totals 時兩列都不出現，只剩總計那一列印 0。
        小計列原本固定印一列，資料沒有時會留一條空白列。
        """
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.partner)
        rows = self._rows(tree)
        self.assertEqual(len(rows), 1, '沒有資料 → 小計列與稅別列都不印')
        self.assertEqual(rows[0][0], '總計')

    def test_fill_tax_row_formats_numbers(self):
        """金額套千分位；名稱原樣輸出。"""
        row = {'tdList': [
            self._cell(_pill('稅別', source='taxTotals', part='groups',
                             field='label')),
            self._cell(_pill('稅額', source='taxTotals', part='groups',
                             field='amount')),
        ]}
        # values 的形狀是 {'document': …, 'company': …}——雙幣別發票要能同時
        # 印兩種幣別，所以每個藥丸自己依 currencyMode 取
        self.Mixin._fill_tax_row(
            row,
            {'document': {'label': '營業稅 5%', 'amount': 1234.5},
             'company': {'label': '營業稅 5%', 'amount': 40000.0}},
            '2026-01-01 00:00:00',
        )
        self.assertEqual(row['tdList'][0]['value'][0]['value'], '營業稅 5%')
        self.assertEqual(row['tdList'][1]['value'][0]['value'], '1,234.50')

    def test_company_currency_mode_reads_other_bucket(self):
        """對應原生發票的 document_tax_totals_company_currency_template。"""
        row = {'tdList': [self._cell(
            _pill('稅額', source='taxTotals', part='groups', field='amount',
                  currencyMode='company', numberFormat=',.0f'),
        )]}
        self.Mixin._fill_tax_row(
            row,
            {'document': {'amount': 1234.5}, 'company': {'amount': 40000.0}},
            '2026-01-01 00:00:00',
        )
        self.assertEqual(row['tdList'][0]['value'][0]['value'], '40,000')

    def test_fill_tax_row_custom_format(self):
        row = {'tdList': [self._cell(
            _pill('稅額', source='taxTotals', part='total', field='amount',
                  numberFormat=',.0f'),
        )]}
        # 刻意不用 .5：Python 的 format 走 banker's rounding，1234.5 → '1,234'，
        # 那會讓這則測試在驗「自訂格式」之外還意外驗到捨入規則。
        self.Mixin._fill_tax_row(
            row, {'document': {'amount': 1234.6}}, '2026-01-01 00:00:00',
        )
        self.assertEqual(row['tdList'][0]['value'][0]['value'], '1,235')

    def test_marker_pill_not_in_output(self):
        row = {'tdList': [self._cell(
            _pill('〔總計〕', source='taxTotals', part='total', isMarker=True),
            _text('總計'),
        )]}
        self.Mixin._fill_tax_row(
            row, {'document': {'amount': 1.0}}, '2026-01-01 00:00:00',
        )
        values = [e.get('value') for e in row['tdList'][0]['value']]
        self.assertEqual(values, ['總計'])

    def test_groups_row_clones_per_tax_group(self):
        """稅別列依稅別數複製。用假資料直接驗展開，不綁 sale 模組。"""
        tree = self._tree(path='nonexistent')
        table = tree['main'][0]
        # 直接餵一份結構進去（繞過 _traverse_path），證明複製邏輯本身正確
        def _fake(_self, record, meta):
            return {
                'currency_id': self.env.company.currency_id.id,
                'subtotals': [{
                    'name': '稅前小計', 'base_amount_currency': 700.0,
                    'tax_groups': [
                        {'group_name': '營業稅 5%', 'tax_amount_currency': 35.0,
                         'base_amount_currency': 700.0},
                        {'group_name': '其他稅', 'tax_amount_currency': 10.0,
                         'base_amount_currency': 200.0},
                    ],
                }],
                'total_amount_currency': 745.0,
                'base_amount_currency': 700.0,
            }

        with patch.object(type(self.Mixin), '_tax_totals_data', _fake):
            self.Mixin._expand_tax_totals_rows(tree, self.partner)
        rows = self._rows(tree)
        self.assertEqual(len(rows), 4, '小計 1 + 稅別 2 + 總計 1')
        # 金額預設走幣別格式（帶符號），不是純數字——稅額彙總一定是金額，
        # 預設值應該直接可用。要純數字請在藥丸上填 numberFormat。
        from odoo.tools.misc import format_amount
        cur = self.env.company.currency_id
        self.assertEqual(rows[0], ['稅前小計', format_amount(self.env, 700.0, cur)])
        self.assertEqual(rows[1], ['營業稅 5%', format_amount(self.env, 35.0, cur)])
        self.assertEqual(rows[2], ['其他稅', format_amount(self.env, 10.0, cur)])
        self.assertEqual(rows[3], ['總計', format_amount(self.env, 745.0, cur)])
        self.assertIs(table, tree['main'][0])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestColumnConditions(TransactionCase):
    """B：欄條件 —— 對應原生報表的折扣欄（th 與每一列的 td 共用一個 t-if）。

    欄與列是對稱的兩件事，但欄多了一個 colgroup 要同步：忘了同步的話
    canvas-editor 的欄寬會跟實際格數對不上，整張表看起來歪掉，而且在
    HTML／PDF 上還看不出來——只有回到編輯器才發現。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({
            'name': '買方', 'vat': 'TW11112222',
        })

    def _cell(self, *els, **kw):
        return dict({'value': list(els), 'colspan': 1, 'rowspan': 1}, **kw)

    def _tree(self, expression, colspan_row=False):
        rows = [
            {'tdList': [
                self._cell(_text('品名')),
                self._cell(_text('數量')),
                self._cell(_text('折扣'),
                           _pill('欄條件', source='column',
                                 expression=expression)),
                self._cell(_text('金額')),
            ]},
            {'tdList': [
                self._cell(_text('A')), self._cell(_text('1')),
                self._cell(_text('10%')), self._cell(_text('90')),
            ]},
        ]
        if colspan_row:
            # 小計列：前三欄合併成一格
            rows.append({'tdList': [
                self._cell(_text('小計'), colspan=3),
                self._cell(_text('90')),
            ]})
        return {'main': [{
            'type': 'table',
            'colgroup': [{'width': 100}, {'width': 60}, {'width': 60},
                         {'width': 80}],
            'trList': rows,
        }]}

    def _rows(self, tree):
        return [
            ['|'.join(e.get('value', '') for e in c['value'])
             for c in row['tdList']]
            for row in tree['main'][0]['trList']
        ]

    def test_false_condition_removes_column_everywhere(self):
        tree = self._tree('object.name == "不存在"')
        self.Mixin._snapshot_content_json(tree, self.partner)
        rows = self._rows(tree)
        self.assertEqual(rows[0], ['品名', '數量', '金額'], '表頭也要少一欄')
        self.assertEqual(rows[1], ['A', '1', '90'])

    def test_true_condition_keeps_column_and_strips_marker(self):
        tree = self._tree('object.vat')
        self.Mixin._snapshot_content_json(tree, self.partner)
        rows = self._rows(tree)
        self.assertEqual(rows[0], ['品名', '數量', '折扣', '金額'])
        self.assertNotIn('欄條件', rows[0][2], '標記藥丸是宣告不是內容')

    def test_colgroup_is_kept_in_sync(self):
        """colgroup 沒跟著刪，編輯器裡的欄寬就跟實際格數對不上。"""
        tree = self._tree('object.name == "不存在"')
        self.Mixin._snapshot_content_json(tree, self.partner)
        cg = tree['main'][0]['colgroup']
        self.assertEqual(len(cg), 3)

    def test_removed_width_goes_to_last_column(self):
        """表格總寬要維持不變，否則刪一欄整張表就縮一截。"""
        tree = self._tree('object.name == "不存在"')
        before = sum(c['width'] for c in tree['main'][0]['colgroup'])
        self.Mixin._snapshot_content_json(tree, self.partner)
        after = sum(c['width'] for c in tree['main'][0]['colgroup'])
        self.assertEqual(before, after)

    def test_colspan_cell_is_narrowed_not_deleted(self):
        """跨欄的格子整格刪掉會讓該列少一欄，表格對不齊——要改 colspan。"""
        tree = self._tree('object.name == "不存在"', colspan_row=True)
        self.Mixin._snapshot_content_json(tree, self.partner)
        subtotal = tree['main'][0]['trList'][2]
        self.assertEqual(len(subtotal['tdList']), 2, '格數不變')
        self.assertEqual(subtotal['tdList'][0]['colspan'], 2, '3 → 2')

    def test_column_condition_evaluated_against_main_record(self):
        """整欄要不要印是一次決定的事，用主記錄求值而不是逐筆明細。"""
        tree = self._tree(
            "object.child_ids|selectattr('comment')|list|length > 0"
        )
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(len(self._rows(tree)[0]), 3, '沒有子聯絡人 → 條件為假')

    def test_all_columns_removed_drops_table(self):
        """每一列的格子都被刪空時整個表格要消失，不可留下一個空段落。"""
        tree = {'main': [
            _text('前'), _text('\n'),
            {'type': 'table',
             'colgroup': [{'width': 100}],
             'trList': [{'tdList': [{
                 'value': [_text('只有這一欄'),
                           _pill('欄條件', source='column',
                                 expression='object.name == "不存在"')],
                 'colspan': 1, 'rowspan': 1}]}]},
            _text('\n'), _text('後'), _text('\n'),
        ]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree)
        )
        self.assertEqual(html, '<p>前</p><p>後</p>')

    def test_runs_after_row_conditions(self):
        """欄一定排在列之後。

        列條件的標記可能就放在某一欄裡——先刪欄會讓那個列條件無聲消失，
        該不印的列就印出來了。
        """
        tree = {'main': [{
            'type': 'table',
            'colgroup': [{'width': 100}, {'width': 100}],
            'trList': [
                {'tdList': [
                    {'value': [_text('表頭'),
                               _pill('欄條件', source='column',
                                     expression='object.name == "不存在"')],
                     'colspan': 1, 'rowspan': 1},
                    {'value': [_text('留著')], 'colspan': 1, 'rowspan': 1},
                ]},
                {'tdList': [
                    # 列條件標記放在「即將被刪掉的那一欄」裡
                    {'value': [_pill('列條件', source='condition',
                                     expression='object.name == "不存在"')],
                     'colspan': 1, 'rowspan': 1},
                    {'value': [_text('該消失的列')], 'colspan': 1, 'rowspan': 1},
                ]},
            ],
        }]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        flat = json.dumps(self._rows(tree), ensure_ascii=False)
        self.assertNotIn('該消失的列', flat, '列條件要先生效')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRowVariants(TransactionCase):
    """C：列型分派 —— 對應原生報表迴圈裡的 t-if / t-elif / t-else。

    重點是**保持交錯順序**。兩條獨立的重複列做不到：那會印成
    「所有商品」然後「所有備註」，而單據上的備註必須緊跟在它註解的那一行後面。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.parent = self.env['res.partner'].create({'name': '母公司'})
        # comment 當「這是備註列」的旗標；名稱加數字前綴固定 child_ids 的排序
        self.env['res.partner'].create([
            {'name': '1 商品A', 'parent_id': self.parent.id, 'type': 'other',
             'city': '台北'},
            {'name': '2 備註甲', 'parent_id': self.parent.id, 'type': 'other',
             'comment': 'NOTE'},
            {'name': '3 商品B', 'parent_id': self.parent.id, 'type': 'other',
             'city': '台中'},
        ])

    def _cell(self, *els, **kw):
        return dict({'value': list(els), 'colspan': 1, 'rowspan': 1}, **kw)

    def _tree(self, note_filter="line.comment"):
        """主要列（商品）在前、備註列型在後——使用者加列型時的自然順序。"""
        return {'main': [{'type': 'table', 'trList': [
            {'tdList': [
                self._cell(_pill('明細', source='repeat', path='child_ids',
                                 repeatId='rp1'),
                           _pill('品名', source='line', path='name')),
                self._cell(_pill('城市', source='line', path='city')),
            ]},
            {'tdList': [
                self._cell(_pill('列型', source='repeat', path='child_ids',
                                 repeatId='rp1', rowFilter=note_filter),
                           _text('備註：'),
                           _pill('內容', source='line', path='name'),
                           colspan=2),
            ]},
        ]}]}

    def _rows(self, tree):
        return [
            ['|'.join(e.get('value', '') for e in c['value'])
             for c in row['tdList']]
            for row in tree['main'][0]['trList']
        ]

    def test_variants_preserve_interleaved_order(self):
        """這則是整個功能的重點：備註必須留在原本的位置。"""
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], ['1 商品A', '台北'])
        self.assertEqual(rows[1], ['備註：|2 備註甲'], '備註用備註列型')
        self.assertEqual(rows[2], ['3 商品B', '台中'])

    def test_note_variant_keeps_its_own_layout(self):
        """備註列用自己的版面（合併欄），不是商品列的兩欄。"""
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.parent)
        note_row = tree['main'][0]['trList'][1]
        self.assertEqual(len(note_row['tdList']), 1)
        self.assertEqual(note_row['tdList'][0]['colspan'], 2)

    def test_variant_with_condition_wins_over_blank_one(self):
        """有條件的列型優先，不必把它搬到主要列上面去。

        若用單純的「第一個符合就勝出」（留空＝一律符合），主要列會吃掉
        所有明細，新加的列型永遠不生效——而「加了設定卻沒反應」是最難
        自己看出來的一種錯。
        """
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.parent)
        self.assertIn('備註：', json.dumps(self._rows(tree), ensure_ascii=False))

    def test_blank_variant_is_the_else_branch(self):
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertEqual(rows[0], ['1 商品A', '台北'], '沒有條件的列型接住其餘')

    def test_broken_row_filter_falls_through_to_else(self):
        """壞掉的列型條件不該攔截明細——否則一個寫壞的條件會把所有明細
        都吃進那個列型，而且不會報錯。"""
        tree = self._tree(note_filter='line.這個欄位不存在.x')
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(len(row), 2, '全部落到商品列型')

    def test_no_variant_matches_uses_first(self):
        """所有列型都有條件且都不成立時用第一個——寧可多印，不要靜默漏印。"""
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [
                self._cell(_pill('明細', source='repeat', path='child_ids',
                                 repeatId='rp1', rowFilter='False'),
                           _pill('品名', source='line', path='name')),
            ]},
            {'tdList': [
                self._cell(_pill('列型', source='repeat', path='child_ids',
                                 repeatId='rp1', rowFilter='False'),
                           _text('第二型'),
                           _pill('品名', source='line', path='name')),
            ]},
        ]}]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertEqual(len(rows), 3, '三筆明細都印出來')
        self.assertNotIn('第二型', rows[0][0])

    def test_settings_come_from_the_first_variant(self):
        """來源／篩選／分組取最上面那一列——否則哪個生效取決於列的先後，
        而那種不確定性在範本裡完全看不出來。"""
        tree = self._tree()
        primary = (tree['main'][0]['trList'][0]['tdList'][0]['value'][0]
                   ['extension']['dobtorField'])
        primary['filter'] = 'not line.comment'
        # 第二個列型設一個會衝突的篩選，應該被忽略
        variant = (tree['main'][0]['trList'][1]['tdList'][0]['value'][0]
                   ['extension']['dobtorField'])
        variant['filter'] = 'line.comment'
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        self.assertEqual(len(rows), 2, '主要列的篩選濾掉備註那一筆')
        self.assertNotIn('備註', json.dumps(rows, ensure_ascii=False))

    def test_running_counters_are_independent_per_variant(self):
        """商品列的項次不該被備註列的流水藥丸影響，而兩者在各自版面裡的
        位置很可能剛好相同。"""
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [
                self._cell(_pill('明細', source='repeat', path='child_ids',
                                 repeatId='rp1'),
                           _pill('項次', source='running', op='index')),
            ]},
            {'tdList': [
                self._cell(_pill('列型', source='repeat', path='child_ids',
                                 repeatId='rp1', rowFilter='line.comment'),
                           _pill('備註序', source='running', op='index')),
            ]},
        ]}]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        vals = [r[0] for r in self._rows(tree)]
        # 商品 1、備註 1（自己的計數器）、商品 2
        self.assertEqual(vals, ['1', '1', '2'])

    def test_variants_combine_with_grouping(self):
        """列型與分組並存：章節由分組標題列接手，備註仍走自己的列型。"""
        self.env['res.partner'].create({
            'name': '0 甲區', 'parent_id': self.parent.id, 'type': 'other',
            'ref': 'SECTION',
        })
        tree = self._tree()
        primary = (tree['main'][0]['trList'][0]['tdList'][0]['value'][0]
                   ['extension']['dobtorField'])
        primary.update({
            'groupMode': 'marker',
            'groupSplitOn': "line.ref == 'SECTION'",
        })
        tree['main'][0]['trList'].insert(0, {'tdList': [
            self._cell(_pill('〔標題〕', source='groupHeader', isMarker=True,
                             repeatId='rp1'),
                       _pill('組名', source='group',
                             expression='group.label')),
            self._cell(_text('')),
        ]})
        self.Mixin._snapshot_content_json(tree, self.parent)
        rows = self._rows(tree)
        flat = json.dumps(rows, ensure_ascii=False)
        self.assertIn('0 甲區', flat, '章節 → 分組標題列')
        self.assertIn('備註：', flat, '備註 → 備註列型')
        self.assertIn('1 商品A', flat)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestLineRowConditions(TransactionCase):
    """重複列裡的條件標記要逐筆求值。

    這是列條件管線的一個盲點：_apply_row_conditions 跑在展開之後，但它求值時
    只有 object 可用（_condition_marker_result 不帶 line），所以同一個條件在
    每一列都得到同一個答案——要嘛整批留、要嘛整批刪。而原生報表裡
    「<tr t-if="line.xxx">」很常見（發票的付款列就是），那種一定得逐筆判斷。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '母公司'})
        # child_ids 依 complete_name 排序，所以名稱前面加序號才會是建立順序
        self.env['res.partner'].create([
            {'name': '1 有電話', 'parent_id': self.partner.id,
             'phone': '0212345678'},
            {'name': '2 沒電話', 'parent_id': self.partner.id},
            {'name': '3 有電話', 'parent_id': self.partner.id,
             'phone': '0287654321'},
        ])

    def _tree(self, expression):
        return {'header': [], 'footer': [], 'main': [
            {'type': 'table', 'value': '', 'colgroup': [{'width': 400}],
             'trList': [{'tdList': [_cell(
                 _pill('明細', source='repeat', path='child_ids',
                       repeatId='rp1'),
                 _pill('列條件', source='condition', expression=expression),
                 _pill('名稱', source='line', path='name'),
             )]}]},
            _text('\n'),
        ]}

    def _row_texts(self, tree):
        table = tree['main'][0]
        out = []
        for row in table['trList']:
            txt = ''.join(
                (el.get('value') or '') for cell in row['tdList']
                for el in cell['value'] if (el.get('value') or '') != '\n'
            )
            out.append(txt)
        return out

    def test_condition_filters_per_line(self):
        tree = self.Mixin._snapshot_content_json(
            self._tree('line.phone'), self.partner)
        self.assertEqual(self._row_texts(tree), ['1 有電話', '3 有電話'])

    def test_marker_is_stripped_from_kept_rows(self):
        """留下來的列要清掉標記藥丸，否則文件上會印出「列條件」四個字。

        而且不清的話，後面那一關會用「只有 object」的環境再判一次——
        帶 line 的條件在那裡求值失敗就當成真，條件從此靜默失效。
        """
        tree = self.Mixin._snapshot_content_json(
            self._tree('line.phone'), self.partner)
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree))
        self.assertNotIn('列條件', html)

    def test_condition_that_raises_prints_everything(self):
        """求值丟例外時寧可多印——少印會被當成資料問題，追不到渲染層。

        用 line.sudo()（沙箱會丟 SecurityError）而不是不存在的欄位：
        Jinja 對不存在的屬性回 Undefined，那在 if 裡就只是 falsy，
        不是求值失敗——那條路的語意是「條件為假」，列本來就該被刪掉。
        """
        tree = self.Mixin._snapshot_content_json(
            self._tree('line.sudo()'), self.partner)
        self.assertEqual(len(self._row_texts(tree)), 3)

    def test_unknown_field_is_falsy_not_an_error(self):
        """不存在的欄位＝條件為假（Jinja 的 Undefined），列會被刪掉。

        釘住這一條是因為它跟上面那則看起來像同一件事，實際語意相反。
        """
        tree = self.Mixin._snapshot_content_json(
            self._tree('line.no_such_field'), self.partner)
        self.assertEqual(tree['main'], [],
                         '整張表格沒有列了，連表格一起清掉')

    def test_group_paired_markers_are_left_to_the_later_pass(self):
        """若／否則的另一半在別的列上，展開階段看不到，不可在這裡判。"""
        tree = {'header': [], 'footer': [], 'main': [
            {'type': 'table', 'value': '', 'colgroup': [{'width': 400}],
             'trList': [{'tdList': [_cell(
                 _pill('明細', source='repeat', path='child_ids',
                       repeatId='rp1'),
                 _pill('若', source='condition', groupId='g1', role='if',
                       expression='line.phone'),
                 _pill('名稱', source='line', path='name'),
             )]}]},
            _text('\n'),
        ]}
        snapped = self.Mixin._snapshot_content_json(tree, self.partner)
        # groupId 的那一顆不該被展開階段吃掉：此處三列全留，交給列條件那一關
        self.assertEqual(len(snapped['main'][0]['trList']), 3)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestListRepeatSource(TransactionCase):
    """重複來源可以是「回傳 list 的計算欄位」，不只 recordset。

    發票的 payment_term_details（分期明細）就是 list of dict。原本只收
    recordset，結果整段不印而且沒有任何訊息——最難追的一種壞法。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '清單來源'})

    def test_list_of_dict_source_expands(self):
        rows = [{'label': '第一期', 'amount': 500.0},
                {'label': '第二期', 'amount': 300.0}]
        tree = {'header': [], 'footer': [], 'main': [
            {'type': 'table', 'value': '', 'colgroup': [{'width': 400}],
             'trList': [{'tdList': [_cell(
                 _pill('明細', source='repeat', path='fake_terms',
                       repeatId='rp1'),
                 _pill('期別', source='line', expression="line.get('label')"),
             )]}]},
            _text('\n'),
        ]}
        original = type(self.Mixin)._traverse_path

        def _fake(mixin_self, record, path):
            if path == 'fake_terms':
                return rows
            return original(mixin_self, record, path)

        self.patch(type(self.Mixin), '_traverse_path', _fake)
        snapped = self.Mixin._snapshot_content_json(tree, self.partner)
        texts = [
            ''.join((el.get('value') or '') for cell in row['tdList']
                    for el in cell['value'] if (el.get('value') or '') != '\n')
            for row in snapped['main'][0]['trList']
        ]
        self.assertEqual(texts, ['第一期', '第二期'])

    def test_scalar_source_still_rejected(self):
        """純量欄位設成重複來源是設定錯誤——Char 欄位逐字展開更難懂。"""
        lines = self.Mixin._resolve_repeat_records(
            self.partner, {'source': 'repeat', 'path': 'name'})
        self.assertEqual(lines, [])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestNestedTableSurvivesCollapse(TransactionCase):
    """段落收合不可以連帶刪掉同段落裡的表格。

    段落邊界只認 value == '\\n'，而表格元素的 value 是空字串，所以表格會被
    算進同一段。實測到的後果：發票的分期清單被旁邊求值為空的「提前付款折扣」
    藥丸連帶整段刪掉——頁面上那一區整塊消失，沒有任何訊息。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '收合測試'})

    def test_table_in_the_same_span_is_kept(self):
        inner = {'type': 'table', 'value': '', 'colgroup': [{'width': 300}],
                 'trList': [{'tdList': [_cell(_text('區塊內的字'))]}]}
        tree = {'header': [], 'footer': [], 'main': [
            # comment 是空的 → 這顆藥丸求值為空
            _pill('備註', source='record', path='comment'),
            inner,
            _text('\n'),
        ]}
        snapped = self.Mixin._snapshot_content_json(tree, self.partner)
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(snapped))
        self.assertIn('區塊內的字', html)

    def test_plain_empty_paragraph_still_collapses(self):
        """規則 A 本身不可被上面那個例外削弱。"""
        tree = {'header': [], 'footer': [], 'main': [
            _text('客戶統編：'),
            _pill('統編', source='record', path='vat'),
            _text('\n'),
            _text('保留這段'),
            _text('\n'),
        ]}
        snapped = self.Mixin._snapshot_content_json(tree, self.partner)
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(snapped))
        self.assertNotIn('客戶統編', html)
        self.assertIn('保留這段', html)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRepeatRowNestedBlocks(TransactionCase):
    """重複列裡的巢狀表格（轉換器把「列內的條件」做成條件區塊）。

    不往巢狀表格裡走的話，區塊內的 line 藥丸不會被求值，最後把標籤文字
    原樣印進單據——實測在出貨單的包裝說明欄印出「aggregated_lines__c8」
    這種變數名。而區塊的條件若交給後面那一關，那裡只有 object，
    帶 line 的條件求值失敗就當成真，條件靜默失效。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.parent = self.env['res.partner'].create({'name': '巢狀母公司'})
        self.env['res.partner'].create([
            {'name': '1 有電話', 'parent_id': self.parent.id,
             'phone': '02-1111'},
            {'name': '2 沒電話', 'parent_id': self.parent.id},
        ])

    def _tree(self, block_condition=''):
        inner_cell = [_pill('名稱', source='line', path='name')]
        if block_condition:
            inner_cell.insert(0, _pill('條件', source='condition',
                                       expression=block_condition))
        block = {'type': 'table', 'value': '',
                 'extension': {'dobtorBlock': 'condition'},
                 'colgroup': [{'width': 200}],
                 'trList': [{'tdList': [_cell(*inner_cell)]}]}
        return {'header': [], 'footer': [], 'main': [
            {'type': 'table', 'value': '', 'colgroup': [{'width': 400}],
             'trList': [{'tdList': [_cell(
                 _pill('明細', source='repeat', path='child_ids',
                       repeatId='rp1'),
                 block,
             )]}]},
            _text('\n'),
        ]}

    def _html(self, tree):
        snapped = self.Mixin._snapshot_content_json(tree, self.parent)
        return self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(snapped))

    def test_line_pill_inside_a_nested_block_is_evaluated(self):
        html = self._html(self._tree())
        self.assertIn('1 有電話', html)
        self.assertIn('2 沒電話', html)
        self.assertNotIn('名稱', html, '標籤文字不可以印進文件')

    def test_condition_inside_a_nested_block_is_per_line(self):
        html = self._html(self._tree(block_condition='line.phone'))
        self.assertIn('1 有電話', html)
        self.assertNotIn('2 沒電話', html, '條件要逐筆判斷')
        self.assertNotIn('條件', html)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestLoopContext(TransactionCase):
    """迴圈位置變數（loop_index / loop_first / loop_last / loop_size）。

    原生報表的「章節小計」靠它：
        lines[line_index+1].display_type == 'line_section'
    沒有這組變數的話那個條件求值失敗 → 策略是當真 → 每一列後面都印一次小計。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.parent = self.env['res.partner'].create({'name': '迴圈母公司'})
        self.env['res.partner'].create([
            {'name': '1 甲', 'parent_id': self.parent.id},
            {'name': '2 乙', 'parent_id': self.parent.id},
            {'name': '3 丙', 'parent_id': self.parent.id},
        ])

    def _rows(self, condition):
        tree = {'header': [], 'footer': [], 'main': [
            {'type': 'table', 'value': '', 'colgroup': [{'width': 400}],
             'trList': [{'tdList': [_cell(
                 _pill('明細', source='repeat', path='child_ids',
                       repeatId='rp1'),
                 _pill('列條件', source='condition', expression=condition),
                 _pill('名稱', source='line', path='name'),
             )]}]},
            _text('\n'),
        ]}
        snapped = self.Mixin._snapshot_content_json(tree, self.parent)
        out = []
        for row in snapped['main'][0]['trList'] if snapped['main'] else []:
            out.append(''.join(
                (el.get('value') or '') for cell in row['tdList']
                for el in cell['value'] if (el.get('value') or '') != '\n'))
        return out

    def test_loop_last_keeps_only_the_last_row(self):
        self.assertEqual(self._rows('loop_last'), ['3 丙'])

    def test_loop_first_keeps_only_the_first_row(self):
        self.assertEqual(self._rows('loop_first'), ['1 甲'])

    def test_loop_index_is_zero_based_like_qweb(self):
        self.assertEqual(self._rows('loop_index == 1'), ['2 乙'])

    def test_loop_size_is_the_line_count(self):
        self.assertEqual(len(self._rows('loop_size == 3')), 3)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestDictRepeatSource(TransactionCase):
    """重複來源是 dict（計算欄位回傳的彙總資料）。

    出貨單的彙總明細是 _get_aggregated_product_quantities() 回傳的 dict，
    範本寫 aggregated_lines[key]['name'] 取值——也就是真正要重複的是「值」。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': 'dict 來源'})

    def test_dict_source_iterates_values(self):
        rows = {'k1': {'name': '甲品', 'qty': 2},
                'k2': {'name': '乙品', 'qty': 5}}
        original = type(self.Mixin)._traverse_path

        def _fake(mixin_self, record, path):
            if path == 'fake_agg':
                return rows
            return original(mixin_self, record, path)

        self.patch(type(self.Mixin), '_traverse_path', _fake)
        lines = self.Mixin._resolve_repeat_records(
            self.partner, {'source': 'repeat', 'path': 'fake_agg'})
        self.assertEqual([ln['name'] for ln in lines], ['甲品', '乙品'])

    def test_dict_source_via_expression(self):
        """sourceExpression 那條路也要一樣（_eval_collection）。"""
        lines = self.Mixin._eval_collection(
            "{'a': {'name': '丙品'}}", self.partner)
        self.assertEqual(lines, [{'name': '丙品'}])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestTaxTotalsRowsRepeat(TransactionCase):
    """小計列依 tax_totals['subtotals'] 複製、現金捨入列沒設定就不印。

    原生是 for subtotal in tax_totals['subtotals']——多個稅基時（含稅與
    未稅混用）會有好幾列小計，而我們原本只取 subtotals[0]。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '彙總列'})

    def _tree(self):
        def val(part, field, label):
            return _pill(label, source='taxTotals', part=part, field=field)
        return {'header': [], 'footer': [], 'main': [{
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'taxTotals'},
            'colgroup': [{'width': 200}, {'width': 200}],
            'trList': [
                {'tdList': [_cell(val('untaxed', 'label', '小計')),
                            _cell(val('untaxed', 'amount', '金額'))]},
                {'tdList': [_cell(val('rounding', 'label', '捨入')),
                            _cell(val('rounding', 'amount', '捨入金額'))]},
                {'tdList': [_cell(_text('總計')),
                            _cell(val('total', 'amount', '總計金額'))]},
            ],
        }, _text('\n')]}

    def _rows(self, data):
        original = type(self.Mixin)._tax_totals_data
        self.patch(type(self.Mixin), '_tax_totals_data',
                   lambda mixin, record, meta: data)
        tree = self._tree()
        self.Mixin._expand_tax_totals_rows(tree, self.partner)
        self.patch(type(self.Mixin), '_tax_totals_data', original)
        return [[''.join(e.get('value') or '' for e in cell['value']).strip()
                 for cell in row['tdList']]
                for row in tree['main'][0]['trList']]

    def test_two_subtotals_give_two_rows(self):
        rows = self._rows({
            'subtotals': [
                {'name': '未稅金額', 'base_amount_currency': 100.0},
                {'name': '含稅金額', 'base_amount_currency': 50.0},
            ],
            'total_amount_currency': 150.0,
        })
        self.assertEqual([r[0] for r in rows], ['未稅金額', '含稅金額', '總計'])

    def test_rounding_row_appears_only_when_configured(self):
        without = self._rows({'subtotals': [], 'total_amount_currency': 1.0})
        self.assertEqual([r[0] for r in without], ['總計'])
        with_rounding = self._rows({
            'subtotals': [],
            'cash_rounding_base_amount_currency': -0.03,
            'total_amount_currency': 1.0,
        })
        self.assertEqual(len(with_rounding), 2, '有設定就要印那一列')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestConditionalFormat(TransactionCase):
    """條件式格式：條件成立就把這一列（或這一段）變粗體／改色／改對齊。

    原生用 t-att-class 做這件事（章節列粗體、備註列斜體），而範本原本只吃
    得懂靜態 class。設計與條件標記對稱——標記放哪裡就決定作用範圍——
    但失敗策略相反：條件算不出來時**不套用**，因為格式套錯（整份變粗體）
    比沒套上難追得多。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.parent = self.env['res.partner'].create({'name': '格式母公司'})
        self.env['res.partner'].create([
            {'name': '1 有電話', 'parent_id': self.parent.id,
             'phone': '02-1'},
            {'name': '2 沒電話', 'parent_id': self.parent.id},
        ])

    def _repeat_tree(self, expression, **style):
        return {'header': [], 'footer': [], 'main': [
            {'type': 'table', 'value': '', 'colgroup': [{'width': 400}],
             'trList': [{'tdList': [_cell(
                 _pill('明細', source='repeat', path='child_ids',
                       repeatId='rp1'),
                 _pill('條件格式', source='format', expression=expression,
                       **style),
                 _pill('名稱', source='line', path='name'),
             )]}]},
            _text('\n'),
        ]}

    def _rows(self, tree):
        snapped = self.Mixin._snapshot_content_json(tree, self.parent)
        out = []
        for row in snapped['main'][0]['trList']:
            texts, bolds = [], []
            for cell in row['tdList']:
                for el in cell['value']:
                    if (el.get('value') or '') != '\n':
                        texts.append(el.get('value'))
                        bolds.append(bool(el.get('bold')))
            out.append((''.join(texts), any(bolds)))
        return out

    def test_applies_per_line_in_a_repeat_row(self):
        rows = self._rows(self._repeat_tree('line.phone', bold=True))
        self.assertEqual(rows, [('1 有電話', True), ('2 沒電話', False)])

    def test_marker_is_removed(self):
        tree = self._repeat_tree('line.phone', bold=True)
        snapped = self.Mixin._snapshot_content_json(tree, self.parent)
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(snapped))
        self.assertNotIn('條件格式', html)

    def test_broken_condition_does_not_apply(self):
        """條件算不出來時不套用——與條件標記的「寧可多印」刻意相反。"""
        rows = self._rows(self._repeat_tree('line.sudo()', bold=True))
        self.assertEqual([b for _t, b in rows], [False, False])

    def test_empty_condition_always_applies(self):
        rows = self._rows(self._repeat_tree('', bold=True))
        self.assertEqual([b for _t, b in rows], [True, True])

    def test_paragraph_scope_outside_a_table(self):
        tree = {'header': [], 'footer': [], 'main': [
            _pill('條件格式', source='format', expression='object.name',
                  bold=True),
            _text('這一段要粗體'),
            _text('\n'),
            _text('這一段不要'),
            _text('\n'),
        ]}
        snapped = self.Mixin._snapshot_content_json(tree, self.parent)
        elements = snapped['main']
        bolded = [el.get('value') for el in elements if el.get('bold')]
        self.assertEqual(bolded, ['這一段要粗體'])

    def test_align_sets_paragraph_alignment(self):
        tree = {'header': [], 'footer': [], 'main': [
            _pill('條件格式', source='format', expression='', align='right'),
            _text('靠右'),
            _text('\n'),
        ]}
        snapped = self.Mixin._snapshot_content_json(tree, self.parent)
        nl = [el for el in snapped['main'] if (el.get('value') or '') == '\n']
        self.assertEqual(nl[0].get('rowFlex'), 'right')

    def test_table_inside_the_span_is_not_restyled(self):
        """同段落裡的表格是獨立區塊，它的格子各自處理，不該被整段套用。"""
        inner = {'type': 'table', 'value': '', 'colgroup': [{'width': 100}],
                 'trList': [{'tdList': [_cell(_text('格子'))]}]}
        tree = {'header': [], 'footer': [], 'main': [
            _pill('條件格式', source='format', expression='', bold=True),
            inner,
            _text('\n'),
        ]}
        self.Mixin._snapshot_content_json(tree, self.parent)
        cell_el = tree['main'][0]['trList'][0]['tdList'][0]['value'][0]
        self.assertFalse(cell_el.get('bold'))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestMarkersNeverPrint(TransactionCase):
    """標記藥丸（條件／格式／重複／分組）絕對不可以印進文件。

    它們是設計期的宣告，不是內容。正常路徑上各自那一關會把它們吃掉，
    但 only_pending=True 的匯出路徑**不跑**那些關卡（它只補值），
    所以使用者在「已快照過的文件」裡插一個標記再匯出時，攤平會把標記的
    標籤文字當成內容印出來——單據上就多一個「條件格式」四個字。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '標記測試'})

    def _html_after_export_path(self, pill):
        tree = {'header': [], 'footer': [], 'main': [
            pill, _text('正常內容'), _text('\n'),
        ]}
        # 匯出路徑：只補還沒凍結過的值，不跑條件／重複／格式那幾關
        self.Mixin._snapshot_content_json(tree, self.partner, only_pending=True)
        return self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree))

    def test_condition_marker_does_not_print(self):
        html = self._html_after_export_path(
            _pill('條件', source='condition', expression='object.name'))
        self.assertIn('正常內容', html)
        self.assertNotIn('條件', html)

    def test_format_marker_does_not_print(self):
        html = self._html_after_export_path(
            _pill('條件格式', source='format', expression='object.name',
                  bold=True))
        self.assertIn('正常內容', html)
        self.assertNotIn('條件格式', html)

    def test_repeat_marker_does_not_print(self):
        html = self._html_after_export_path(
            _pill('明細 × child_ids', source='repeat', path='child_ids',
                  repeatId='rp1'))
        self.assertIn('正常內容', html)
        self.assertNotIn('明細', html)

    def test_group_markers_do_not_print(self):
        for source in ('groupHeader', 'groupFooter'):
            html = self._html_after_export_path(
                _pill('〔分組標題〕', source=source, isMarker=True,
                      repeatId='rp1'))
            self.assertNotIn('分組', html, '%s 的標記印出來了' % source)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestSnapshotPassOrder(TransactionCase):
    """快照管線的 pass 順序本身。

    467 則測試驗的都是「每一關的行為」，沒有一則驗「順序」——而
    _snapshot_content_json 的註解自稱「順序有意義，不可對調」。
    少了這一則，把欄條件搬到列條件前面不會有任何測試變紅，
    症狀是某張單據的列條件無聲消失（那個標記剛好放在被刪掉的欄裡）。

    這則測試刻意同時釘住「順序」與「註解」：順序寫在 EXPECTED 裡，
    而註解裡的那份清單是權威——兩邊不一致時，是提醒去看註解有沒有漏寫。
    """

    # 依 _snapshot_content_json 註解裡的 1 → 5
    EXPECTED = [
        '_expand_repeat_rows',          # 1
        '_expand_tax_totals_rows',      # 1.5
        '_condition_group_results',     # 2 的前置（兩關共用同一份結果）
        '_apply_row_conditions',        # 2
        '_apply_column_conditions',     # 3（一定排在列之後）
        '_apply_paragraph_conditions',  # 3
        '_apply_format_markers',        # 3.6
        '_drop_empty_tables',           # 3.5
        '_collapse_empty_paragraphs',   # 5（4 是下方的求值迴圈，不是方法）
    ]

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '順序測試'})

    def _record_order(self, tree):
        calls = []
        klass = type(self.Mixin)
        for name in self.EXPECTED:
            original = getattr(klass, name)

            def make(name, original):
                def wrapper(mixin_self, *args, **kwargs):
                    calls.append(name)
                    return original(mixin_self, *args, **kwargs)
                return wrapper

            self.patch(klass, name, make(name, original))
        self.Mixin._snapshot_content_json(tree, self.partner)
        return calls

    def _tree(self):
        return {'header': [], 'footer': [], 'main': [
            {'type': 'table', 'value': '', 'colgroup': [{'width': 300}],
             'trList': [{'tdList': [_cell(
                 _pill('明細', source='repeat', path='child_ids',
                       repeatId='rp1'),
                 _pill('名稱', source='line', path='name'),
             )]}]},
            _text('\n'),
            _pill('條件', source='condition', expression='object.name'),
            _text('有條件的一段'),
            _text('\n'),
        ]}

    def test_passes_run_in_the_documented_order(self):
        self.assertEqual(self._record_order(self._tree()), self.EXPECTED)

    def test_every_pass_actually_runs(self):
        """少跑一關比順序錯更嚴重：那一關的功能整個靜默失效。"""
        calls = self._record_order(self._tree())
        self.assertEqual(sorted(set(calls)), sorted(set(self.EXPECTED)))

    def test_export_path_skips_the_structural_passes(self):
        """only_pending=True 是匯出時補值用的，不可以再動結構。

        那時版面已經定案（條件算過、重複展開過），再跑一次會把已經填好的
        列又當成模板複製一遍。
        """
        calls = []
        klass = type(self.Mixin)
        for name in self.EXPECTED:
            original = getattr(klass, name)

            def make(name, original):
                def wrapper(mixin_self, *args, **kwargs):
                    calls.append(name)
                    return original(mixin_self, *args, **kwargs)
                return wrapper

            self.patch(klass, name, make(name, original))
        self.Mixin._snapshot_content_json(
            self._tree(), self.partner, only_pending=True)
        self.assertEqual(calls, [], '匯出路徑不該跑結構關卡：%s' % calls)

    def test_the_comment_block_lists_every_pass(self):
        """註解是權威，所以它必須提到每一關的名字。

        加了新的 pass 卻沒更新那段註解，就是「順序約束只存在於某人腦袋裡」
        的開始——實測發生過一次（條件式格式）。
        """
        import inspect
        source = inspect.getsource(
            type(self.Mixin)._snapshot_content_json)
        head = source[:source.index('env_j = self._get_sandbox_env')]
        comment = '\n'.join(line for line in head.split('\n')
                            if line.strip().startswith('#'))
        for name in self.EXPECTED:
            if name == '_condition_group_results':
                continue  # 它是前置計算，註解裡以「if/else 群組」描述
            self.assertIn(
                name, comment,
                '%s 沒有寫進 _snapshot_content_json 的順序註解' % name)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestPageScopeMarker(TransactionCase):
    """頁面範圍標記：這一段只在首頁／續頁／奇數頁／偶數頁出現。

    對應 LibreOffice Writer 頁首的「首頁相同」與「左右頁相同」。做法不同：
    那兩個是版面設定，這裡是標記——我們的頁首頁尾是一份 HTML，wkhtmltopdf
    每頁重載一次並在網址帶 page 參數，所以「哪一段要出現」只能在那一刻決定。
    後端不知道這一頁是第幾頁。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '頁面範圍測試'})

    def _html(self, *elements):
        tree = {'main': list(elements)}
        self.Mixin._snapshot_content_json(tree, self.partner)
        return self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree))

    def test_marker_becomes_a_paragraph_class(self):
        html = self._html(
            _pill('只在首頁', source='pageScope', scope='first', isMarker=True),
            _text('信紙'), _text('\n'))
        self.assertIn('class="doc-page-first"', html)
        self.assertIn('信紙', html)

    def test_marker_never_prints_its_own_label(self):
        """標記是宣告不是內容。印出「只在首頁」四個字就是缺陷。"""
        html = self._html(
            _pill('只在首頁', source='pageScope', scope='first', isMarker=True),
            _text('信紙'), _text('\n'))
        self.assertNotIn('只在首頁', html)

    def test_each_scope_gets_its_own_class(self):
        for scope in ('first', 'rest', 'odd', 'even'):
            html = self._html(
                _pill('X', source='pageScope', scope=scope, isMarker=True),
                _text('內容'), _text('\n'))
            self.assertIn('class="doc-page-%s"' % scope, html)

    def test_unknown_scope_is_dropped_not_guessed(self):
        html = self._html(
            _pill('X', source='pageScope', scope='somewhere', isMarker=True),
            _text('內容'), _text('\n'))
        self.assertNotIn('doc-page-', html)
        self.assertIn('內容', html)

    def test_scope_does_not_leak_to_the_next_paragraph(self):
        """每沖一段就要清掉，否則後面每一段都繼承同一個範圍。"""
        html = self._html(
            _pill('X', source='pageScope', scope='first', isMarker=True),
            _text('第一段'), _text('\n'),
            _text('第二段'), _text('\n'))
        self.assertEqual(html.count('doc-page-first'), 1)
        self.assertIn('<p>第二段</p>', html)

    def test_scope_coexists_with_alignment(self):
        html = self._html(
            _pill('X', source='pageScope', scope='even', isMarker=True),
            _text('靠右'), _text('\n', rowFlex='right'))
        self.assertIn('doc-page-even', html)
        self.assertIn('text-align:right', html)
