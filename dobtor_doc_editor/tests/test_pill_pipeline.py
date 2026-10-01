"""Phase 3-4（藥丸改版）：快照 / 攤平 / 元素樹轉 HTML。

這些測試釘住的是「靜默錯誤」——本改版最大的風險不是崩潰，而是
匯出一份看起來正常、值卻是錯的或空的文件。因此每則測試都對應一個
具體的靜默失效情境，而不只是覆蓋率。
"""
import json

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
        """決策三：空值印空白，不印底線、不擋匯出。"""
        tree = {'main': [_pill('備註', source='record', path='comment')]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(tree['main'][0]['value'], '')

    def test_snapshot_static_source(self):
        tree = {'main': [_pill('固定', source='static', static='合約編號 A-001')]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(tree['main'][0]['value'], '合約編號 A-001')

    def test_snapshot_broken_expression_does_not_raise(self):
        """一個壞欄位不該讓整份文件產不出來。"""
        tree = {'main': [_pill('壞的', source='record', path='no_such_field_here')]}
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
        )]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(tree['main'][0]['value'], '')

    def test_sandbox_env_is_hardened_class(self):
        env_j = self.Mixin._get_sandbox_env(self.partner)
        self.assertFalse(env_j.is_safe_attribute(self.partner, 'sudo', None))
        self.assertFalse(env_j.is_safe_attribute(self.partner, 'env', None))
