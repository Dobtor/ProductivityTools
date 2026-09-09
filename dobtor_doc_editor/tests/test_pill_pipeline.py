"""Phase 3-5（藥丸改版）：快照 / 攤平 / 元素樹轉 HTML / alias 遷移。

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


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestAliasMigration(TransactionCase):
    """決策二：一次性遷移。三類 alias 形態都要接住。"""

    def setUp(self):
        super().setUp()
        self.Migration = self.env['doc.alias.migration']

    def test_plain_path_becomes_record_source(self):
        meta = self.Migration._meta_from_expression('object.partner_id.name', '客戶')
        self.assertEqual(meta['source'], 'record')
        self.assertEqual(meta['path'], 'partner_id.name')

    def test_helper_call_falls_back_to_expression(self):
        """沒有 expression 逃生口，這類 alias 會靜默失去值。"""
        meta = self.Migration._meta_from_expression("selection_label('state')", '狀態')
        self.assertEqual(meta['source'], 'expression')
        self.assertEqual(meta['expression'], "selection_label('state')")

    def test_format_date_call_falls_back_to_expression(self):
        meta = self.Migration._meta_from_expression(
            "format_date(object.date_start, '%Y')", '起日',
        )
        self.assertEqual(meta['source'], 'expression')

    def test_split_element_creates_pill_and_keeps_style(self):
        aliases = self.Migration._split_aliases({'客戶': 'object.name'})
        pieces = self.Migration._split_element(
            _text('立約人 《客戶》 敬啟', bold=True), aliases,
        )
        self.assertEqual(len(pieces), 3)
        self.assertEqual(pieces[1]['type'], 'label')
        self.assertEqual(pieces[1]['extension']['dobtorField']['path'], 'name')
        # 被拆開的文字片段必須沿用原樣式，否則會掉字型與顏色
        self.assertTrue(pieces[0]['bold'])
        self.assertTrue(pieces[2]['bold'])

    def test_split_element_handles_var_syntax(self):
        aliases = self.Migration._split_aliases({'project_name': 'object.name'})
        pieces = self.Migration._split_element(_text('工程：{{ project_name }}'), aliases)
        self.assertEqual(pieces[1]['type'], 'label')

    def test_unknown_token_left_alone(self):
        aliases = self.Migration._split_aliases({'客戶': 'object.name'})
        self.assertIsNone(self.Migration._split_element(_text('《沒對映的》'), aliases))

    def test_dry_run_writes_nothing(self):
        template = self.env['doc.template'].create({
            'name': '遷移測試範本',
            'field_aliases': {'客戶': 'object.name'},
            'content_json': json.dumps({'main': [_text('《客戶》')]}),
        })
        before = template.content_json
        stats = self.Migration.run(dry_run=True)
        self.assertTrue(stats['dry_run'])
        self.assertGreaterEqual(stats['records_changed'], 1)
        self.assertEqual(template.content_json, before, '乾跑不可寫入')

    def test_legacy_odoo_field_control_in_document_is_converted(self):
        """舊 odoo_field 的 control 元素在「文件」裡，不在範本裡。

        只掃範本的話一個都找不到——這是實作時抓到的真 bug。
        """
        template = self.env['doc.template'].create({'name': '舊欄位範本'})
        signer = self.env['doc.template.signer'].create({
            'template_id': template.id, 'name': '甲方',
        })
        legacy = self.env['doc.template.field'].create({
            'template_id': template.id,
            'signer_id': signer.id,
            'field_type': 'odoo_field',
            'odoo_field_name': 'partner_id.name',
            'placeholder_text': '客戶名稱',
        })
        doc = self.env['doc.document'].create({
            'name': '含舊欄位的文件',
            'template_id': template.id,
            'content_json': json.dumps({'main': [
                {'type': 'control', 'value': '',
                 'control': {'conceptId': str(legacy.id), 'type': 'text'}},
            ]}),
        })

        self.Migration.run(dry_run=False)

        tree = json.loads(doc.content_json)
        labels = [el for el in tree['main'] if el.get('type') == 'label']
        self.assertEqual(len(labels), 1, '文件內的舊 control 應被換成藥丸')
        self.assertEqual(
            labels[0]['extension']['dobtorField']['path'], 'partner_id.name',
        )
        self.assertFalse(legacy.exists(), '轉換後舊欄位記錄應被刪除')

    def test_legacy_records_deleted_only_after_full_scan(self):
        """同一批舊記錄可能被多份文件引用，不可掃完一份就刪。"""
        template = self.env['doc.template'].create({'name': '共用舊欄位範本'})
        signer = self.env['doc.template.signer'].create({
            'template_id': template.id, 'name': '甲方',
        })
        legacy = self.env['doc.template.field'].create({
            'template_id': template.id,
            'signer_id': signer.id,
            'field_type': 'odoo_field',
            'odoo_field_name': 'name',
            'placeholder_text': '名稱',
        })
        payload = json.dumps({'main': [
            {'type': 'control', 'value': '',
             'control': {'conceptId': str(legacy.id), 'type': 'text'}},
        ]})
        docs = self.env['doc.document'].create([
            {'name': '文件A', 'template_id': template.id, 'content_json': payload},
            {'name': '文件B', 'template_id': template.id, 'content_json': payload},
        ])

        self.Migration.run(dry_run=False)

        for doc in docs:
            tree = json.loads(doc.content_json)
            labels = [el for el in tree['main'] if el.get('type') == 'label']
            self.assertEqual(len(labels), 1, f'{doc.name} 的舊 control 應已轉換')

    def test_real_run_converts_and_persists(self):
        template = self.env['doc.template'].create({
            'name': '遷移測試範本2',
            'field_aliases': {'客戶': 'object.name'},
            'content_json': json.dumps({'main': [_text('《客戶》')]}),
        })
        self.Migration.run(dry_run=False)
        tree = json.loads(template.content_json)
        labels = [el for el in tree['main'] if el.get('type') == 'label']
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0]['extension']['dobtorField']['path'], 'name')
