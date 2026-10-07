"""Phase 3-4（藥丸改版）：快照 / 攤平 / 元素樹轉 HTML。

這些測試釘住的是「靜默錯誤」——本改版最大的風險不是崩潰，而是
匯出一份看起來正常、值卻是錯的或空的文件。因此每則測試都對應一個
具體的靜默失效情境，而不只是覆蓋率。
"""
import json
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


def _text(value, **kw):
    return dict({'value': value}, **kw)


def _pill(label_text, **meta):
    payload = {'labelText': label_text}
    payload.update(meta)
    return {
        'type': 'label',
        'value': label_text,
        'label': {'backgroundColor': '#e3f2fd', 'color': '#1976d2'},
        'extension': {'dobtorField': payload},
    }


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestElementWalker(TransactionCase):
    """走訪器必須走到三個區域與表格巢狀——漏一個就是一批變數不帶值。"""

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']

    def _tree(self):
        return {
            'header': [_pill('頁首變數', source='record', path='name')],
            'main': [
                _text('本文 '),
                _pill('內文變數', source='record', path='name'),
                {
                    'type': 'table',
                    'trList': [{
                        'tdList': [
                            {'value': [_pill('表格變數', source='record', path='name')]},
                        ],
                    }],
                },
            ],
            'footer': [_pill('頁尾變數', source='record', path='name')],
        }

    def test_walker_reaches_all_zones_and_tables(self):
        labels = [
            el['value'] for el in self.Mixin._iter_elements(self._tree())
            if el.get('type') == 'label'
        ]
        self.assertEqual(
            sorted(labels),
            sorted(['頁首變數', '內文變數', '表格變數', '頁尾變數']),
            '走訪器漏掉區域或表格 → 那些變數永遠不會被帶值',
        )

    def test_walker_accepts_bare_list(self):
        """少數舊資料把 content_json 存成單純的元素陣列。"""
        elements = list(self.Mixin._iter_elements([_pill('X', source='record', path='name')]))
        self.assertEqual(len(elements), 1)


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
class TestContentJsonToHtml(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']

    def test_paragraph_split_on_newline(self):
        tree = {'main': [_text('第一段'), _text('\n'), _text('第二段')]}
        html = self.Mixin._content_json_to_html(tree)
        self.assertEqual(html.count('<p'), 2)
        self.assertIn('第一段', html)
        self.assertIn('第二段', html)

    def test_inline_styles_preserved(self):
        tree = {'main': [_text('粗體', bold=True, color='#ff0000')]}
        html = self.Mixin._content_json_to_html(tree)
        self.assertIn('font-weight:bold', html)
        self.assertIn('color:#ff0000', html)

    def test_font_size_unit_is_px_not_pt(self):
        """canvas-editor 的 element.size 單位是 px（lib 組 font 字串時用 `${size}px`）。

        寫成 pt 的話匯出的每段文字都會大 33%，而且完全無錯誤訊息——
        這是實際發生過的缺陷，原本的樣式測試只驗粗體與顏色所以抓不到。
        """
        tree = {'main': [_text('十六級字', size=16)]}
        html = self.Mixin._content_json_to_html(tree)
        self.assertIn('font-size:16px', html)
        self.assertNotIn('font-size:16pt', html)

    def test_table_rendered(self):
        tree = {'main': [{
            'type': 'table',
            'trList': [{'tdList': [{'value': [_text('儲存格')]}]}],
        }]}
        html = self.Mixin._content_json_to_html(tree)
        self.assertIn('<table>', html)
        self.assertIn('儲存格', html)

    def test_html_is_escaped(self):
        """使用者輸入的角括號不可原樣輸出，否則匯出的 HTML 會被撐破。"""
        tree = {'main': [_text('<script>alert(1)</script>')]}
        html = self.Mixin._content_json_to_html(tree)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_row_flex_alignment(self):
        tree = {'main': [_text('置中'), _text('\n', rowFlex='center')]}
        html = self.Mixin._content_json_to_html(tree)
        self.assertIn('text-align:center', html)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestExportBodySource(TransactionCase):
    """匯出必須以 content_json 為權威——否則藥丸的值進不了 PDF。"""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': '匯出測試客戶'})
        model = self.env['ir.model']._get('res.partner')
        self.doc = self.env['doc.document'].create({
            'name': '匯出測試',
            'model_id': model.id,
            'res_id': self.partner.id,
            'content_html': '<p>這是舊的 HTML 備份</p>',
            'content_json': json.dumps({
                'main': [_text('客戶：'), _pill('客戶名稱', source='record', path='name')],
            }),
        })

    def test_export_prefers_content_json(self):
        html = self.doc._export_body_html(self.partner)
        self.assertIn('匯出測試客戶', html)
        self.assertNotIn('舊的 HTML 備份', html)

    def test_export_falls_back_to_html_without_json(self):
        self.doc.content_json = False
        html = self.doc._export_body_html(self.partner)
        self.assertIn('舊的 HTML 備份', html)

    def test_snapshot_freezes_and_does_not_re_evaluate(self):
        """決策一：快照後改來源記錄，文件內容不變。"""
        self.doc._apply_value_snapshot()
        self.assertTrue(self.doc.snapshot_date)
        self.assertEqual(self.doc.snapshot_res_id, self.partner.id)

        self.partner.name = '改名後的客戶'
        html = self.doc._export_body_html(self.partner)
        self.assertIn('匯出測試客戶', html)
        self.assertNotIn('改名後的客戶', html)

    def test_refresh_values_picks_up_change(self):
        self.doc._apply_value_snapshot()
        self.partner.name = '改名後的客戶'
        self.doc.action_refresh_values()
        html = self.doc._export_body_html(self.partner)
        self.assertIn('改名後的客戶', html)

    def test_snapshot_updates_content_html_too(self):
        """伺服器端快照必須一併更新 content_html，否則舊匯出鏈讀到舊值。"""
        self.doc._apply_value_snapshot()
        self.assertIn('匯出測試客戶', self.doc.content_html)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestSandboxConvergence(TransactionCase):
    """補遺五：ORM 提權黑名單必須在每一條求值路徑上生效。"""

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '沙箱測試'})

    def test_snapshot_blocks_orm_escalation(self):
        """{{ object.env[...] }} 這類提權在快照路徑上必須失效（結果為空）。"""
        tree = {'main': [_pill(
            '提權', source='expression',
            expression="object.env['res.users'].sudo().browse(1).login",
            keepEmpty=True,   # 規則 A 的收合會移除整段，見 test_snapshot_empty_value_prints_blank
        )]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(tree['main'][0]['value'], '')

    def test_sandbox_env_is_hardened_class(self):
        env_j = self.Mixin._get_sandbox_env(self.partner)
        self.assertFalse(env_j.is_safe_attribute(self.partner, 'sudo', None))
        self.assertFalse(env_j.is_safe_attribute(self.partner, 'env', None))


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
        """欄位不存在（非銷售單據）時印空白，不可讓整份文件產不出來。"""
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.partner)
        rows = self._rows(tree)
        self.assertEqual(len(rows), 2, '沒有稅別資料 → 稅別列整列不印')
        self.assertEqual(rows[0], ['', ''])
        self.assertEqual(rows[1][0], '總計')

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
class TestMoneyFormatting(TransactionCase):
    """A：format_money —— 對應原生報表的 monetary widget。

    這批測試釘住的是「數字對、格式錯」：金額印成 1000.0 而不是帶幣別符號、
    或小數位跟幣別設定不一致。那種錯誤在單據上會被當成系統算錯。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '買方'})
        self.currency = self.env.company.currency_id

    def _render(self, expression, record=None, **extra):
        env_j = self.Mixin._get_sandbox_env(record or self.partner)
        return env_j.from_string('{{ %s }}' % expression).render(
            object=record or self.partner, user=self.env.user, **extra,
        )

    def test_delegates_to_odoo_formatter(self):
        """刻意委派給 odoo.tools.format_amount，不自己實作格式化。

        幣別符號位置、語系的千分位與小數點、currency.round 都在那支裡；
        自己重做一份就是等著跟 Odoo 的行為漂移。
        """
        from odoo.tools.misc import format_amount
        self.assertEqual(
            self._render('format_money(1234.5)'),
            format_amount(self.env, 1234.5, self.currency),
        )

    def test_symbol_is_present(self):
        """沒有幣別符號就只是個數字——這則測試擋的是「悄悄退化成純數字」。"""
        out = self._render('format_money(1234.5)')
        self.assertIn(self.currency.symbol, out)

    def test_decimal_places_follow_currency(self):
        """小數位依幣別設定，不是固定兩位。"""
        jpy = self.env['res.currency'].create({
            'name': 'TZZ', 'symbol': '¤', 'decimal_places': 0,
            'rounding': 1.0,
        })
        out = self._render('format_money(1234.5)').replace(' ', ' ')
        self.assertIn('.', out, '公司幣別預設兩位小數')
        out0 = self._render('format_money(1234.5, cur)', cur=jpy).replace(' ', ' ')
        self.assertNotIn('.', out0, 'decimal_places=0 不該有小數點')
        self.assertIn('¤', out0)

    def test_undefined_currency_arg_does_not_crash(self):
        """幣別參數打錯字時退回記錄身上的幣別，不可讓整份文件產不出來。

        Jinja 的 Undefined 在屬性存取時就會 raise，所以 _coerce_currency
        必須整段包 try——這則測試擋的就是那個。
        """
        out = self._render('format_money(1234.5, currrency)')
        self.assertIn(self.currency.symbol, out)

    def test_true_is_not_treated_as_currency_id(self):
        """True 是 int 的子類別，會被 browse(1) 當成某個幣別。"""
        self.assertEqual(
            self.Mixin._resolve_currency(self.partner, True),
            self.Mixin._resolve_currency(self.partner),
        )

    def test_currency_accepts_id(self):
        """tax_totals 給的是 currency_id（整數），不是 recordset。"""
        cur = self.Mixin._resolve_currency(self.partner, self.currency.id)
        self.assertEqual(cur, self.currency)

    def test_empty_value_is_empty_string(self):
        for expression in ('format_money(False)', 'format_money(None)',
                           "format_money('')"):
            self.assertEqual(self._render(expression), '')

    def test_non_numeric_passes_through(self):
        """求值出非數字時原樣回傳，不可讓整份文件產不出來。"""
        self.assertEqual(self._render("format_money('abc')"), 'abc')

    def test_resolve_currency_falls_back_to_company(self):
        """記錄身上沒有 currency_id 時退到公司幣別，而不是回空。"""
        self.assertTrue(self.Mixin._resolve_currency(self.partner))

    def test_running_sum_as_money(self):
        """累計金額欄跟其他金額欄必須同一套格式。"""
        from odoo.tools.misc import format_amount
        parent = self.env['res.partner'].create({'name': '母公司'})
        self.env['res.partner'].create([
            {'name': 'A1', 'parent_id': parent.id, 'type': 'other'},
            {'name': 'A2', 'parent_id': parent.id, 'type': 'other'},
        ])
        tree = {'main': [{'type': 'table', 'trList': [
            {'tdList': [{'value': [
                _pill('明細', source='repeat', path='child_ids'),
                _pill('累計', source='running', op='sum', expression='1',
                      asMoney=True),
            ], 'colspan': 1, 'rowspan': 1}]},
        ]}]}
        self.Mixin._snapshot_content_json(tree, parent)
        vals = [
            ''.join(e.get('value', '') for e in row['tdList'][0]['value'])
            for row in tree['main'][0]['trList']
        ]
        self.assertEqual(vals, [
            format_amount(self.env, 1.0, self.currency),
            format_amount(self.env, 2.0, self.currency),
        ])


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
class TestFieldListCoverage(TransactionCase):
    """欄位清單的型別白名單。

    這批測試擋的是一種特別難發現的壞法：功能在後端跑得動、測試也綠，但
    使用者在 UI 上找不到入口。one2many 不在白名單時，左欄「明細（一對多）」
    那一組永遠不渲染——整個重複列功能（連帶分組、列型、流水藥丸）都點不到。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']

    def _types(self, model='res.partner'):
        fields = self.Mixin.get_available_fields(model, max_depth=1)
        return {f['type'] for f in fields}

    def test_x2many_fields_are_listed(self):
        """重複列的 UI 入口靠這個。"""
        types = self._types()
        self.assertIn('one2many', types)

    def test_binary_fields_are_listed(self):
        """圖片藥丸（客戶簽名、公司 logo）的來源。"""
        self.assertIn('binary', self._types())

    def test_relation_is_exposed_for_x2many(self):
        """沒有 relation 就載不到明細欄位清單。"""
        fields = self.Mixin.get_available_fields('res.partner', max_depth=1)
        child = next(f for f in fields if f['name'] == 'child_ids')
        self.assertEqual(child['relation'], 'res.partner')

    def test_x2many_does_not_recurse(self):
        """一對多不展開子欄位——在這裡展開會讓 payload 爆掉。"""
        fields = self.Mixin.get_available_fields('res.partner', max_depth=2)
        child = next(f for f in fields if f['name'] == 'child_ids')
        self.assertNotIn('sub_fields', child)

    def test_many2one_still_recurses(self):
        fields = self.Mixin.get_available_fields('res.partner', max_depth=2)
        m2o = [f for f in fields if f['type'] == 'many2one' and f.get('sub_fields')]
        self.assertTrue(m2o, 'many2one 仍要展開子欄位')

    def test_scalar_list_matches_frontend_constant(self):
        """後端 _SCALAR_TTYPES 必須與前端 SCALAR_FIELD_TYPES 同步。

        前端靠它把 one2many / binary 從「主記錄欄位」的純量清單裡濾掉。
        兩邊不一致時，使用者會在純量清單裡看到 one2many，拖進去只印出
        recordset 的 repr——看起來像系統壞了。
        """
        import os
        import re
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(
            here, 'static', 'src', 'components', 'doc_editor', 'doc_editor.js',
        )
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        block = re.search(
            r'SCALAR_FIELD_TYPES\s*=\s*\[(.*?)\]', src, re.S,
        )
        self.assertIsNotNone(block, '前端找不到 SCALAR_FIELD_TYPES')
        front = set(re.findall(r'"([a-z0-9_]+)"', block.group(1)))
        self.assertEqual(front, set(self.Mixin._SCALAR_TTYPES))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestFormatAddress(TransactionCase):
    """format_address —— 對應原生的 t-options widget="contact"。"""

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({
            'name': '測試公司', 'street': '信義路五段 7 號',
            'city': '台北市', 'zip': '110',
        })

    def _render(self, expression, record=None, **extra):
        env_j = self.Mixin._get_sandbox_env(record or self.partner)
        return env_j.from_string('{{ %s }}' % expression).render(
            object=record or self.partner, user=self.env.user, **extra,
        )

    def test_delegates_to_display_address(self):
        """委派給 res.partner._display_address()——那支就是 Odoo 自己用的，
        依國家的地址格式排欄位。自己拼 street/city/zip 換個國家就排錯。"""
        self.assertEqual(
            self._render('format_address(object)'),
            self.partner._display_address(),
        )

    def test_with_name_prepends_display_name(self):
        """原生 contact widget 的 fields 預設含 "name"，_display_address 不含。

        收件人區塊少了名字就只是一串地址，所以轉換器會依原範本的 fields
        設定決定要不要帶——預設不帶，既有範本的版面不變。
        """
        plain = self._render('format_address(object)')
        named = self._render('format_address(object, with_name=True)')
        self.assertNotIn('測試公司', plain)
        self.assertTrue(named.startswith('測試公司'))
        self.assertIn(plain, named)

    def test_multiline_address_becomes_br_in_html(self):
        """多行地址不可塌成一行——在 HTML 裡只是少了換行，很難看出來。"""
        tree = {'main': [
            _pill('地址', source='expression',
                  expression='format_address(object)'),
            _text('\n'),
        ]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree)
        )
        self.assertIn('<br/>', html)
        self.assertIn('信義路五段 7 號', html)

    def test_without_company_flag(self):
        """without_company 影響的是「公司名稱那一行」，不是 parent_id。

        _display_address 只在 company_name 有值時才會把公司名排進地址裡，
        所以測試資料必須設 company_name，否則兩種結果相同、測不到東西。
        """
        holder = self.env['res.partner'].create({
            'name': '聯絡人', 'company_name': '某某股份有限公司',
            'street': '松仁路 1 號', 'city': '台北市',
        })
        full = self._render('format_address(object)', record=holder)
        bare = self._render('format_address(object, True)', record=holder)
        self.assertIn('某某股份有限公司', full)
        self.assertNotIn('某某股份有限公司', bare)

    def test_empty_partner_is_empty_string(self):
        self.assertEqual(self._render('format_address(False)'), '')
        empty = self.env['res.partner'].browse()
        self.assertEqual(
            self._render('format_address(p)', p=empty), '',
        )

    def test_non_partner_falls_back_to_display_name(self):
        """不是 partner 時退回 display_name，不可讓整份文件產不出來。"""
        company = self.env.company
        out = self._render('format_address(c)', c=company)
        self.assertTrue(out)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestImagePill(TransactionCase):
    """圖片藥丸 —— 對應原生的 image_data_uri(doc.signature)。

    客戶簽名每張單據都不同，所以不能像公司 logo 那樣貼死一張圖。
    這批測試釘住的是「攤平成真正的 image 元素」：若只是把 data URI 當文字，
    單據上會印出一長串 base64，而且不會報錯。
    """

    # 1x1 透明 PNG
    PNG = (
        b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
        b'YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
    )

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({
            'name': '有圖的客戶', 'image_1920': self.PNG,
        })
        self.blank = self.env['res.partner'].create({'name': '沒圖的客戶'})

    def _tree(self, path='image_1920', **meta):
        return {'main': [
            _pill('圖', source='image', path=path, **meta),
            _text('\n'),
        ]}

    def _html(self, tree, record):
        self.Mixin._snapshot_content_json(tree, record)
        return self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree)
        )

    def test_renders_as_img_not_text(self):
        html = self._html(self._tree(), self.partner)
        self.assertIn('<img src="data:image/png;base64,', html)
        self.assertNotIn('<p>data:', html, 'data URI 不可被當成文字印出來')

    def test_data_uri_detects_mime_type(self):
        """委派給 odoo.tools.image.image_data_uri——它會從 magic word 認型別。"""
        uri = self.Mixin._image_data_uri(self.partner, {'path': 'image_1920'})
        self.assertTrue(uri.startswith('data:image/png;base64,'))

    def test_empty_field_prints_nothing(self):
        """欄位空的就什麼都不印，不留下殘骸。"""
        tree = self._tree()
        # keepEmpty 擋掉自動收合，才測得到「圖片藥丸本身」的行為
        tree['main'][0]['extension']['dobtorField']['keepEmpty'] = True
        html = self._html(tree, self.blank)
        self.assertNotIn('<img', html)
        self.assertNotIn('data:', html)

    def test_width_height_carried_to_img(self):
        html = self._html(self._tree(width=120, height=40), self.partner)
        self.assertIn('width="120"', html)
        self.assertIn('height="40"', html)

    def test_relational_path_works(self):
        """company_id.logo 這種跨關聯的路徑要能取到。"""
        uri = self.Mixin._image_data_uri(
            self.env.company.partner_id, {'path': 'company_id.logo'},
        )
        self.assertTrue(uri == '' or uri.startswith('data:image/'))

    def test_broken_payload_returns_empty(self):
        """不是圖片的來源 → 空字串。

        odoo.tools.image.image_data_uri() 不驗證內容，認不出型別就一律當 png
        ——把文字欄位誤設成圖片來源時，它會回 'data:image/png;base64,壞圖'，
        在單據上印出一張破圖而且完全不報錯。所以要先比對 magic word。
        """
        bad = self.env['res.partner'].create({'name': '壞圖'})
        self.assertEqual(
            self.Mixin._image_data_uri(bad, {'path': 'name'}), '',
        )

    def test_existing_data_uri_passes_through(self):
        """欄位本身就存著 data URI（字串）時原樣使用，不要再包一層。"""
        uri = 'data:image/gif;base64,R0lGODlhAQABAAAAACw='
        holder = self.env['res.partner'].create({'name': '字串圖', 'ref': uri})
        self.assertEqual(
            self.Mixin._image_data_uri(holder, {'path': 'ref'}), uri,
        )

    def test_image_pill_skipped_by_scalar_pass_rules(self):
        """圖片藥丸走自己的求值分支，不可被當成一般純量去 render 表達式
        ——binary 經過 Jinja 會變成 "b'iVBOR…'" 的 repr。"""
        tree = self._tree()
        self.Mixin._snapshot_content_json(tree, self.partner)
        value = tree['main'][0]['value']
        self.assertFalse(value.startswith("b'"))
        self.assertTrue(value.startswith('data:image/'))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestPagePill(TransactionCase):
    """頁碼藥丸。

    Odoo 的 wkhtmltopdf 管線會把抽出來的 div.footer 包進 web.minimal_layout
    （subst=True，見 ir_actions_report.py:441），那支範本裡的 JS 會填滿所有
    class="page" / "topage" 的元素。所以模組只要輸出對的 span 即可。
    這批測試釘住的就是「輸出對的 span」，因為替換的那一端不在我們手上。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '客戶'})

    def _html(self, part, zone='footer'):
        tree = {zone: [
            _text('第 '), _pill('頁碼', source='page', part=part),
            _text(' 頁'), _text('\n'),
        ]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        return self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree), zone=zone,
        )

    def test_page_number_emits_span_page(self):
        self.assertIn('<span class="page"></span>', self._html('number'))

    def test_page_count_emits_span_topage(self):
        self.assertIn('<span class="topage"></span>', self._html('count'))

    def test_surrounding_text_is_kept(self):
        html = self._html('number')
        self.assertIn('第 ', html)
        self.assertIn(' 頁', html)

    def test_label_text_is_not_printed(self):
        """藥丸的標籤文字（「頁碼」）是設計期的顯示，不可印進成品。"""
        self.assertNotIn('頁碼', self._html('number'))

    def test_not_evaluated_as_scalar(self):
        """頁碼沒有值可求——被當成純量會變成空字串，連 span 都生不出來。"""
        tree = {'footer': [_pill('頁碼', source='page', part='number')]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(tree['footer'][0]['value'], '頁碼',
                         '求值那一輪要跳過它，標籤文字保持不動')

    def test_flatten_marks_page_kind(self):
        tree = {'footer': [
            _pill('頁碼', source='page', part='number'),
            _pill('總頁數', source='page', part='count'),
        ]}
        self.Mixin._flatten_content_json(tree)
        kinds = [el.get('pageKind') for el in tree['footer']]
        types = [el.get('type') for el in tree['footer']]
        self.assertEqual(kinds, ['number', 'count'])
        self.assertEqual(types, ['pageField', 'pageField'])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestHtmlPill(TransactionCase):
    """Html 欄位藥丸。

    不做這個的話，條款、公司資訊、頁尾文字會在單據上印出字面的 <p>、<strong>
    ——而且完全不報錯。external_layout 的外框幾乎全是 Html 欄位。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({
            'name': '客戶',
            'comment': '<p>一般<strong>條款</strong></p><p>第二段</p>',
        })

    def _html(self, tree, record=None):
        self.Mixin._snapshot_content_json(tree, record or self.partner)
        return self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree)
        )

    def test_markup_is_kept_not_escaped(self):
        tree = {'main': [_pill('條款', source='html', path='comment'),
                         _text('\n')]}
        html = self._html(tree)
        self.assertIn('<strong>條款</strong>', html)
        self.assertNotIn('&lt;strong&gt;', html)

    def test_scalar_pill_on_html_field_escapes(self):
        """對照組：同一個欄位用純量藥丸就會逸出——這正是要避免的那個結果。"""
        tree = {'main': [_pill('條款', source='record', path='comment'),
                         _text('\n')]}
        self.assertIn('&lt;strong&gt;', self._html(tree))

    def test_emitted_as_block_not_nested_in_paragraph(self):
        """區塊級輸出：塞進 <p> 裡會變成 <p><p>…</p></p> 的非法嵌套。"""
        tree = {'main': [
            _text('前言'),
            _pill('條款', source='html', path='comment'),
            _text('\n'),
        ]}
        html = self._html(tree)
        self.assertIn('<p>前言</p>', html)
        self.assertNotIn('<p><p>', html)

    def test_script_is_sanitized(self):
        """值最後進 PDF（wkhtmltopdf 會執行 JS）與後台編輯器，必須消毒。"""
        evil = self.env['res.partner'].create({
            'name': '壞東西',
            'comment': '<p>ok</p><script>alert(1)</script>',
        })
        tree = {'main': [_pill('條款', source='html', path='comment'),
                         _text('\n')]}
        html = self._html(tree, evil)
        self.assertIn('ok', html)
        self.assertNotIn('<script', html)

    def test_empty_html_shell_counts_as_empty(self):
        """'<p><br></p>' 這類空殼算沒有內容。

        原樣輸出的話，自動收合空段落會判斷成「有值」，單據上就多一段
        看不見的空白——而那在 HTML 裡完全看不出來。
        """
        blank = self.env['res.partner'].create({
            'name': '空條款', 'comment': '<p><br></p>',
        })
        self.assertEqual(
            self.Mixin._html_field_value(blank, {'path': 'comment'}), '',
        )
        self.assertFalse(self.Mixin._html_has_content('<p> </p>'))
        self.assertTrue(self.Mixin._html_has_content('<p>x</p>'))
        self.assertTrue(self.Mixin._html_has_content('<img src="x"/>'))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRenderLanguage(TransactionCase):
    """渲染語言必須套用到「記錄」，不只是 data-oe-lang。

    少了這一步是個靜默錯誤：綁定上設了 zh_TW，HTML 屬性會寫 zh_TW，但商品
    名稱、selection 標籤、付款條件全部印成操作者的語言。
    單據上絕大部分文字是「值」，所以這一項影響面最大。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']

    def test_explicit_lang_wins(self):
        partner = self.env['res.partner'].create({'name': 'A', 'lang': 'en_US'})
        mixin = self.Mixin.with_context(doc_render_lang='fr_FR')
        self.assertEqual(mixin._render_lang(partner), 'fr_FR')

    def test_partner_lang_is_used_when_not_explicit(self):
        """與原生報表一致：sale 的範本第 5 行就是
        doc.with_context(lang=doc.partner_id.lang)。"""
        partner = self.env['res.partner'].create({'name': 'A', 'lang': 'en_US'})
        order_like = self.env['res.partner'].create({
            'name': 'B', 'parent_id': partner.id, 'type': 'other',
        })
        # res.partner 沒有 partner_id 欄位，所以退回 context
        self.assertEqual(
            self.Mixin._render_lang(order_like),
            self.env.context.get('lang'),
        )

    def test_record_in_lang_switches_context(self):
        partner = self.env['res.partner'].create({'name': 'A'})
        switched = self.Mixin._record_in_lang(partner, 'en_US')
        self.assertEqual(switched.env.context.get('lang'), 'en_US')

    def test_record_in_lang_is_noop_for_same_lang(self):
        partner = self.env['res.partner'].create({'name': 'A'})
        same = self.Mixin._record_in_lang(
            partner, self.env.context.get('lang'),
        )
        self.assertIs(same, partner)

    def test_record_in_lang_tolerates_none(self):
        self.assertIsNone(self.Mixin._record_in_lang(None))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestI18nPill(TransactionCase):
    """i18n 靜態文字藥丸。"""

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '客戶'})

    def _value(self, texts, lang=None):
        record = self.partner
        if lang:
            record = record.with_context(lang=lang)
        return self.Mixin._i18n_text(record, {'texts': texts,
                                              'labelText': '標籤'})

    def test_picks_current_language(self):
        self.assertEqual(
            self._value({'en_US': 'Quotation', 'zh_TW': '報價單'}, 'en_US'),
            'Quotation',
        )

    def test_falls_back_to_en_us(self):
        self.assertEqual(
            self._value({'en_US': 'Quotation'}, 'zh_TW'), 'Quotation',
        )

    def test_falls_back_to_any_value(self):
        self.assertEqual(self._value({'ja_JP': '見積書'}, 'zh_TW'), '見積書')

    def test_falls_back_to_label_never_blank(self):
        """空白在單據上看起來像資料掉了，而未翻譯的字串至少讀得懂。"""
        self.assertEqual(self._value({}, 'zh_TW'), '標籤')

    def test_short_lang_code_matches(self):
        """zh_TW 找不到時也試 zh——翻譯表常只填兩字母碼。"""
        self.assertEqual(self._value({'zh': '報價單'}, 'zh_TW'), '報價單')

    def test_rendered_in_document(self):
        tree = {'main': [
            _pill('標題', source='i18n',
                  texts={'en_US': 'Quotation', 'zh_TW': '報價單'}),
            _text('\n'),
        ]}
        self.Mixin._snapshot_content_json(
            tree, self.partner.with_context(lang='en_US'),
        )
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree)
        )
        self.assertIn('Quotation', html)
        self.assertNotIn('報價單', html)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestI18nTools(TransactionCase):
    """抽取靜態文字與 CSV 匯入匯出。

    沒有這兩個工具 i18n 藥丸不會被用起來：沒人會回頭把一張做好的中文範本
    裡幾十段文字一個一個改成藥丸。
    """

    def setUp(self):
        super().setUp()
        self.template = self.env['doc.template'].create({
            'name': 'i18n 範本',
            'content_json': json.dumps({'main': [
                _text('報價單'), _text('\n'),
                _text('客戶：'),
                _pill('客戶名', source='record', path='name'),
                _text('\n'),
                _text('報價單'), _text('\n'),
            ]}, ensure_ascii=False),
        })

    def _tree(self):
        return json.loads(self.template.content_json)

    def test_extract_groups_by_text_with_counts(self):
        texts = self.template.extract_static_texts()
        table = {t['text']: t['count'] for t in texts}
        self.assertEqual(table.get('報價單'), 2, '同一段文字只列一筆、附次數')
        self.assertEqual(table.get('客戶：'), 1)

    def test_extract_does_not_cross_pill_boundary(self):
        """藥丸與換行都是 run 的邊界。

        跨越它們合併會把兩段不相干的文字黏成一個翻譯字串，譯者拿到的就是
        一句不知所云的話。
        """
        texts = [t['text'] for t in self.template.extract_static_texts()]
        self.assertIn('客戶：', texts)
        for text in texts:
            self.assertNotIn('\n', text)
        self.assertNotIn('客戶：報價單', texts)

    def test_convert_replaces_runs_with_pills(self):
        result = self.template.convert_texts_to_i18n(['報價單'], lang='zh_TW')
        self.assertEqual(result['converted'], 2, '兩處都要換')
        entries = self.template.i18n_entries()
        self.assertEqual(len(entries), 1, '同一段文字只會有一個 key')
        self.assertEqual(entries[0]['texts'], {'zh_TW': '報價單'})

    def test_convert_keeps_font_style(self):
        """轉成藥丸不該順手改掉字級與顏色。"""
        self.template.content_json = json.dumps({'main': [
            dict(_text('粗體標題'), bold=True, size=24), _text('\n'),
        ]}, ensure_ascii=False)
        self.template.convert_texts_to_i18n(['粗體標題'], lang='zh_TW')
        pill = self._tree()['main'][0]
        self.assertEqual(pill['type'], 'label')
        self.assertTrue(pill.get('bold'))
        self.assertEqual(pill.get('size'), 24)

    def test_convert_ignores_unselected(self):
        self.template.convert_texts_to_i18n(['報價單'], lang='zh_TW')
        remaining = [t['text'] for t in self.template.extract_static_texts()]
        self.assertIn('客戶：', remaining, '沒勾的不該被動')

    def test_csv_round_trip(self):
        self.template.convert_texts_to_i18n(['報價單'], lang='zh_TW')
        key = self.template.i18n_entries()[0]['key']

        exported = self.template.export_i18n_csv(langs=['zh_TW', 'en_US'])
        self.assertEqual(exported.split('\r\n')[0].split(','),
                         ['key', 'zh_TW', 'en_US'])
        self.assertIn(key, exported)

        result = self.template.import_i18n_csv(
            'key,zh_TW,en_US\n%s,報價單,Quotation\n' % key
        )
        # updated 計 key 數（對齊譯者手上 CSV 的列數）、pills 計實際改到的藥丸。
        # 「報價單」在範本裡出現兩次，所以一列 CSV 會改到兩個藥丸。
        self.assertEqual(result['updated'], 1)
        self.assertEqual(result['pills'], 2)
        self.assertEqual(result['unknown'], [])
        self.assertEqual(
            self.template.i18n_entries()[0]['texts'],
            {'zh_TW': '報價單', 'en_US': 'Quotation'},
        )

    def test_import_reports_unknown_keys(self):
        """靜默忽略的話，譯者改錯一個 key，使用者只會看到「翻譯沒進去」
        而查不出原因。"""
        self.template.convert_texts_to_i18n(['報價單'], lang='zh_TW')
        result = self.template.import_i18n_csv(
            'key,en_US\n不存在的鍵,Nope\n'
        )
        self.assertEqual(result['updated'], 0)
        self.assertEqual(result['unknown'], ['不存在的鍵'])

    def test_import_empty_is_safe(self):
        self.assertEqual(
            self.template.import_i18n_csv(''),
            {'updated': 0, 'pills': 0, 'unknown': []},
        )

    def test_export_includes_langs_present_in_template(self):
        """範本裡出現過但尚未安裝的語言也要匯出，否則那些翻譯會在一次
        匯出匯入後消失。"""
        self.template.convert_texts_to_i18n(['報價單'], lang='zh_TW')
        tree = self._tree()
        for el in tree['main']:
            meta = (el.get('extension') or {}).get('dobtorField') or {}
            if meta.get('source') == 'i18n':
                meta['texts']['ja_JP'] = '見積書'
        self.template.content_json = json.dumps(tree, ensure_ascii=False)
        header = self.template.export_i18n_csv().split('\n')[0]
        self.assertIn('ja_JP', header)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestLayoutTemplate(TransactionCase):
    """外框範本：頁首頁尾與紙張設定由外框決定。"""

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.layout = self.env['doc.template'].create({
            'name': '測試外框', 'role': 'layout',
            'margin_top': 150, 'header_spacing': 12, 'footer_spacing': 9,
            'content_json': json.dumps({
                'header': [_text('外框頁首'), _text('\n')],
                'main': [_text('外框本文不該被輸出'), _text('\n')],
                'footer': [_text('外框頁尾'), _text('\n')],
            }, ensure_ascii=False),
        })
        self.content = self.env['doc.template'].create({
            'name': '測試內容', 'role': 'content',
            'layout_id': self.layout.id,
            'margin_top': 96,
            'model_id': self.env['ir.model']._get('res.partner').id,
            'content_json': json.dumps({
                'header': [_text('內容範本自己的頁首'), _text('\n')],
                'main': [_text('本文'), _text('\n')],
            }, ensure_ascii=False),
        })

    def test_frame_template_resolves(self):
        self.assertEqual(self.content.frame_template(), self.layout)
        self.assertEqual(self.layout.frame_template(), self.layout)

    def test_no_layout_is_self(self):
        plain = self.env['doc.template'].create({'name': '無外框'})
        self.assertEqual(plain.frame_template(), plain)

    def test_layout_cannot_have_layout(self):
        with self.assertRaises(ValidationError):
            self.layout.layout_id = self.layout.copy({'role': 'layout'}).id

    def test_non_layout_cannot_be_used_as_layout(self):
        other = self.env['doc.template'].create({'name': '普通範本'})
        with self.assertRaises(ValidationError):
            self.content.layout_id = other.id

    def test_builtin_layouts_are_idempotent(self):
        Template = self.env['doc.template']
        Template.action_create_default_layouts()
        first = Template.with_context(active_test=False).search_count(
            [('role', '=', 'layout')],
        )
        Template.action_create_default_layouts()
        second = Template.with_context(active_test=False).search_count(
            [('role', '=', 'layout')],
        )
        self.assertEqual(first, second, '重複執行不該再建一份')

    def test_builtin_layout_tree_shape(self):
        tmpl = self.env['doc.template'].create({
            'name': 'L', 'role': 'layout', 'page_format': 'A4',
        })
        tree = tmpl._build_layout_tree('side')
        self.assertIn('header', tree)
        self.assertIn('footer', tree)
        table = tree['header'][0]
        self.assertEqual(table['type'], 'table')
        # 欄寬要加總回內寬，否則表格在編輯器裡溢出頁面
        self.assertEqual(
            sum(c['width'] for c in table['colgroup']),
            794 - 96 - 96,
        )
        # 每個儲存格都要以換行結尾，否則編輯器裡點進去沒有游標位置
        for row in table['trList']:
            for cell in row['tdList']:
                self.assertEqual(cell['value'][-1]['value'], '\n')

    def test_builtin_layout_has_logo_details_and_page_fields(self):
        tmpl = self.env['doc.template'].create({'name': 'L', 'role': 'layout'})
        tree = tmpl._build_layout_tree('side')
        sources = []
        for element in self.Mixin._iter_elements(tree):
            meta = self.Mixin._element_field_meta(element)
            if meta:
                sources.append((meta.get('source'), meta.get('path'),
                                meta.get('part')))
        self.assertIn(('image', 'company_id.logo_web', None), sources)
        self.assertIn(('html', 'company_id.company_details', None), sources)
        self.assertIn(('page', None, 'number'), sources)
        self.assertIn(('page', None, 'count'), sources)

    def test_layout_table_is_borderless_in_output(self):
        tmpl = self.env['doc.template'].create({'name': 'L', 'role': 'layout'})
        tree = tmpl._build_layout_tree('side')
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree), zone='header',
        )
        self.assertIn('class="doc-block"', html)


def _cell(*elements, **kw):
    return dict({'colspan': 1, 'rowspan': 1,
                 'value': list(elements) + [_text('\n')]}, **kw)


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
