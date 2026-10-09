"""藥丸管線測試 — 攤平、元素樹轉 HTML、圖片／頁碼／Html 藥丸、外框、HTML→content_json。
對應 models/render/output.py。

這一批是從 test_pill_pipeline.py 拆出來的（原本 3921 行、43 個類別）。
按**被測的那一層**分，讓「某一層壞了」一眼看得出是哪一批紅。
共用的 _text / _pill helper 在 test_pill_helpers.py。
"""
import json

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from .test_pill_helpers import _pill, _text


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
class TestImageExpressionSource(TransactionCase):
    """圖片藥丸的來源可以是算出來的，不只是 binary 欄位路徑。

    發票的付款 QR 是 partner_bank_id.build_qr_code_base64(...) 的結果，
    不對應任何欄位。
    """

    _DATA_URI = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB'
                 'CAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU'
                 '5ErkJggg==')

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({
            'name': '圖片表達式', 'ref': self._DATA_URI,
        })

    def test_expression_data_uri_is_used(self):
        value = self.Mixin._image_data_uri(
            self.partner, {'source': 'image', 'expression': 'object.ref'})
        self.assertEqual(value, self._DATA_URI)

    def test_expression_that_is_not_an_image_is_dropped(self):
        """算出來的不是圖就當沒有圖——印一張破圖而且不報錯更糟。"""
        self.partner.ref = '這不是圖'
        value = self.Mixin._image_data_uri(
            self.partner, {'source': 'image', 'expression': 'object.ref'})
        self.assertEqual(value, '')

    def test_path_still_wins(self):
        """同時給 path 與 expression 時以 path 為準（binary 欄位要原始 bytes）。"""
        value = self.Mixin._image_data_uri(self.partner, {
            'source': 'image', 'path': 'image_1920',
            'expression': 'object.ref',
        })
        self.assertEqual(value, '', '沒有大頭貼就是空的，不該掉回表達式')


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




@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestHtmlToContentJson(TransactionCase):
    """HTML → content_json，用「來回轉換」釘住正確性。

    為什麼需要這支：模組自己出貨的 6 張 data 範本只有 content_html，所以列印
    走舊路，**享受不到任何藥丸功能**。要讓它們享受得到就得有 content_json。

    Phase 5 的註解寫著「HTML → IElement 需要 canvas-editor 的 executeSetHTML，
    那是瀏覽器端的東西」——對**任意** HTML 是對的。這支只處理我們自己寫的
    那個子集（出貨範本實際用到的 12 個標籤）。

    正確性靠 round-trip：html → content_json → html 要與原 html 等價。
    那比逐個標籤寫斷言可靠，因為反向那條路本來就在用。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']

    def _round(self, html):
        tree = self.Mixin._html_to_content_json(html)
        return self.Mixin._content_json_to_html(tree)

    def _norm(self, html):
        """比較時忽略空白與屬性順序差異。"""
        import re
        t = re.sub(r'>\s+<', '><', html or '')
        return re.sub(r'\s+', ' ', t).strip()

    # ── 來回轉換 ────────────────────────────────────────────────
    def test_paragraph_round_trip(self):
        self.assertEqual(self._norm(self._round('<p>一段文字</p>')),
                         '<p>一段文字</p>')

    def test_bold_round_trip(self):
        out = self._round('<p>前<b>粗</b>後</p>')
        self.assertIn('font-weight:bold', out)
        self.assertIn('粗', out)
        self.assertIn('前', out)
        self.assertIn('後', out)

    def test_alignment_round_trip(self):
        out = self._round('<p style="text-align:center">置中</p>')
        self.assertIn('text-align:center', out)

    def test_heading_becomes_sized_bold_text(self):
        """標題沒有專屬元素型別——canvas-editor 用 size + bold 表達。"""
        out = self._round('<h1>大標</h1>')
        self.assertIn('font-size:24px', out)
        self.assertIn('font-weight:bold', out)
        self.assertIn('大標', out)

    def test_br_becomes_a_paragraph_break(self):
        out = self._round('<p>上<br/>下</p>')
        self.assertEqual(out.count('<p>'), 2, '一個 <br> 應該切成兩段')

    def test_empty_paragraph_survives(self):
        """空段落要留著，否則版面的留白會塌掉。"""
        self.assertIn('<br/>', self._round('<p><br></p>'))

    def test_table_round_trip(self):
        out = self._round(
            '<table><tr><td>甲</td><td>乙</td></tr>'
            '<tr><td>丙</td><td>丁</td></tr></table>')
        self.assertEqual(out.count('<tr>'), 2)
        self.assertEqual(out.count('<td>'), 4)
        for t in ('甲', '乙', '丙', '丁'):
            self.assertIn(t, out)

    def test_th_cells_become_bold(self):
        out = self._round('<table><tr><th>表頭</th></tr></table>')
        self.assertIn('font-weight:bold', out)

    def test_colspan_and_rowspan_survive(self):
        out = self._round(
            '<table><tr><td colspan="2" rowspan="3">合併</td></tr></table>')
        self.assertIn('colspan="2"', out)
        self.assertIn('rowspan="3"', out)

    def test_table_gets_a_colgroup(self):
        """canvas-editor 沒有 colgroup 畫不出表格。"""
        tree = self.Mixin._html_to_content_json(
            '<table><tr><td>甲</td><td>乙</td></tr></table>')
        table = tree['main'][0]
        self.assertEqual(len(table['colgroup']), 2)
        self.assertTrue(all(c['width'] > 0 for c in table['colgroup']))

    # ── 邊界 ────────────────────────────────────────────────────
    def test_empty_input(self):
        self.assertEqual(
            self.Mixin._html_to_content_json(''),
            {'header': [], 'main': [], 'footer': []})

    def test_unsupported_tag_is_noted_not_swallowed(self):
        """子集外的標籤要留下說明——靜默吞掉會讓人以為轉乾淨了。"""
        notes = []
        self.Mixin._html_to_content_json('<p>甲</p><blockquote>乙</blockquote>',
                                         notes=notes)
        self.assertTrue(any('blockquote' in n for n in notes), notes)

    def test_result_survives_the_snapshot_pipeline(self):
        """轉出來的樹要能走完整條快照管線（這是它存在的目的）。"""
        partner = self.env['res.partner'].create({'name': '來回測試'})
        tree = self.Mixin._html_to_content_json(
            '<h1>標題</h1><table><tr><td><b>欄</b></td><td>值</td></tr></table>')
        self.Mixin._snapshot_content_json(tree, partner)
        html = self.Mixin._content_json_to_html(
            self.Mixin._flatten_content_json(tree))
        self.assertIn('標題', html)
        self.assertIn('欄', html)
        self.assertIn('值', html)

    # ── 真正的目標：6 張出貨範本 ────────────────────────────────
    def test_html_comments_are_not_content(self):
        """☠️ lxml 的註解節點 .tag 不是字串而是 callable。

        沒擋的話註解會掉進「未知標籤」分支，**內文被當成正文輸出**。
        實測：估驗計價單範本裡有一段 <!-- Sprint Y12.2… --> 的註解，轉出來
        那張範本印出註解文字、而且後面的內容整段不見。
        """
        out = self._round('<p>甲</p><!-- 這是註解 --><p>乙</p>')
        self.assertNotIn('這是註解', out)
        self.assertIn('甲', out)
        self.assertIn('乙', out)

    def test_comment_inside_a_table_is_dropped(self):
        out = self._round(
            '<table><!-- 註解 --><tr><td>值</td></tr></table>')
        self.assertNotIn('註解', out)
        self.assertIn('值', out)

    def test_shipped_templates_render_the_same_text_as_the_old_path(self):
        """**這一則才是遷移的驗收**：新路徑（藥丸管線）印出來的文字要與舊路徑
        （content_html + Jinja）一致。

        只比文字不比標籤：content_json 走的是 canvas-editor 的元素模型，
        標題變成 size+bold 而不是 <h1>，表格的 colgroup 也是新加的。
        要釘的是「內容沒有掉」。

        上一版的測試只驗「轉得過、沒有 note」，所以沒抓到註解被當成正文那個
        缺陷——內容掉了一整張它也是綠的。
        """
        import copy
        import re as _re
        partner = self.env['res.partner'].create({'name': '遷移驗收'})
        xmlids = [
            'doc_template_blank', 'template_meeting_record',
            'template_self_inspection', 'template_defect_improvement',
            'template_payment_estimate', 'template_review_control',
        ]

        def text_of(html):
            return _re.sub(r'\s+', ' ', _re.sub(r'<[^>]+>', ' ', html or '')).strip()

        for xmlid in xmlids:
            tmpl = self.env.ref('dobtor_doc_editor.%s' % xmlid,
                                raise_if_not_found=False)
            if not tmpl:
                continue
            html = _re.sub(r'\{\{.*?\}\}', '', tmpl.get_content_html() or '')
            tree = self.Mixin._html_to_content_json(html)
            snapped = self.Mixin._snapshot_content_json(
                copy.deepcopy(tree), partner)
            new = self.Mixin._content_json_to_html(
                self.Mixin._flatten_content_json(snapped))
            self.assertEqual(
                text_of(new), text_of(html),
                '%s 遷移後文字不一致' % xmlid)

    def test_every_shipped_template_converts_cleanly(self):
        """6 張出貨範本都要轉得過，而且不留下「不支援的標籤」。"""
        xmlids = [
            'doc_template_blank', 'template_meeting_record',
            'template_self_inspection', 'template_defect_improvement',
            'template_payment_estimate', 'template_review_control',
        ]
        for xmlid in xmlids:
            tmpl = self.env.ref('dobtor_doc_editor.%s' % xmlid,
                                raise_if_not_found=False)
            if not tmpl:
                continue
            notes = []
            tree = self.Mixin._html_to_content_json(
                tmpl.get_content_html(), notes=notes)
            self.assertFalse(notes, '%s 有不支援的標籤：%s' % (xmlid, notes))
            self.assertTrue(tree['main'], '%s 轉出空的 main' % xmlid)
