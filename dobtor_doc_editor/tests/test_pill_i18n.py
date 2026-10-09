"""藥丸管線測試 — 渲染語言、多語藥丸、CSV 匯入匯出。
對應 models/render/i18n.py。

這一批是從 test_pill_pipeline.py 拆出來的（原本 3921 行、43 個類別）。
按**被測的那一層**分，讓「某一層壞了」一眼看得出是哪一批紅。
共用的 _text / _pill helper 在 test_pill_helpers.py。
"""
import json

from odoo.tests.common import TransactionCase, tagged

from .test_pill_helpers import _pill, _text


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
