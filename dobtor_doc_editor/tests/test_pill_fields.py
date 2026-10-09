"""藥丸管線測試 — 欄位清單與型別→格式表、欄位標籤。
對應 models/render/fields.py。

這一批是從 test_pill_pipeline.py 拆出來的（原本 3921 行、43 個類別）。
按**被測的那一層**分，讓「某一層壞了」一眼看得出是哪一批紅。
共用的 _text / _pill helper 在 test_pill_helpers.py。
"""

from odoo.tests.common import TransactionCase, tagged

from .test_pill_helpers import _pill, _text


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
        # 常數的權威在 doc_editor_shared.js——doc_editor.js 2026-10-09 拆成
        # 四層 mixin 時把模組層級常數搬到那裡（避免循環 import）。
        # 這一則原本指著 doc_editor.js，拆檔後就紅了，正是它該有的行為。
        path = os.path.join(
            here, 'static', 'src', 'components', 'doc_editor',
            'doc_editor_shared.js',
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
class TestTypeFormatTable(TransactionCase):
    """「欄位型別該怎麼格式化」只有一份表，而且在渲染層。

    原本有五份（轉換器、編輯器左欄主記錄、編輯器左欄明細、本組小計、
    已退場的 alias），互不相交。症狀全都是靜默的：
      * 轉換器不補 selection → t-field="o.state" 印 done 而不是「完成」
      * 編輯器左欄拖一個 date 進去印 2026-10-08 00:00:00、float 印 100.0
      * 巢狀 selection（客戶-狀態）印代碼——那三份都只處理頂層
      * 數量欄位的 digits 是 'Product Unit of Measure'（字串），
        舊的 isinstance(tuple) 判斷不成立 → 退回兩位，而原生印三位
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.parent = self.env['res.partner'].create({'name': '母公司'})
        self.partner = self.env['res.partner'].create({
            'name': '型別測試', 'parent_id': self.parent.id,
            'type': 'invoice', 'partner_latitude': 12.5,
        })

    def _value(self, record=None, **meta):
        tree = {'main': [_pill('X', **meta), _text('\n')]}
        self.Mixin._snapshot_content_json(tree, record or self.partner)
        return tree['main'][0]['value']

    # ── selection ───────────────────────────────────────────────
    def test_selection_path_prints_label_not_key(self):
        """只帶 path 的 selection 藥丸要印標籤。轉換器產生的就是這種。"""
        value = self._value(source='record', path='type')
        expected = dict(
            self.partner._fields['type']._description_selection(self.env)
        )['invoice']
        self.assertEqual(value, expected)
        self.assertNotEqual(value, 'invoice', 'selection 印出代碼')

    def test_nested_selection_path_prints_label(self):
        """巢狀路徑也要——編輯器那份判斷有 `!parent` 條件，漏掉這種。"""
        self.parent.type = 'delivery'
        value = self._value(source='record', path='parent_id.type')
        expected = dict(
            self.parent._fields['type']._description_selection(self.env)
        )['delivery']
        self.assertEqual(value, expected)

    # ── 數字與日期 ──────────────────────────────────────────────
    def test_float_uses_field_digits(self):
        """digits=(10, 7) → 七位小數，不是寫死的兩位。"""
        value = self._value(source='record', path='partner_latitude')
        self.assertEqual(value, '12.5000000')

    def test_float_digits_from_decimal_precision_name(self):
        """digits 是 decimal.precision 的**名字**時也要讀對。

        舊寫法 isinstance(digits, tuple) 不成立 → 退回兩位。數量欄位全中。
        """
        field = self.env['sale.order.line']._fields.get('product_uom_qty') \
            if 'sale.order.line' in self.env else None
        if field is None:
            self.skipTest('sale 未安裝')
        scale = self.Mixin._field_scale(field)
        precision = self.env['decimal.precision'].precision_get(
            'Product Unit of Measure')
        self.assertEqual(scale, precision)
        self.assertEqual(
            self.Mixin._type_format_expression(
                'sale.order.line', 'product_uom_qty', 'line.product_uom_qty'),
            "format_number(line.product_uom_qty, ',.%df')" % precision)

    def test_date_uses_locale_format(self):
        expr = self.Mixin._type_format_expression(
            'ir.sequence.date_range', 'date_from', 'object.date_from')
        self.assertEqual(expr, "format_date(object.date_from, 'lang')")

    def test_datetime_includes_the_time(self):
        expr = self.Mixin._type_format_expression(
            'res.partner', 'write_date', 'object.write_date')
        self.assertEqual(
            expr, "format_date(object.write_date, 'lang_datetime')")

    def test_integer_gets_thousands_separator(self):
        expr = self.Mixin._type_format_expression(
            'res.partner', 'color', 'object.color')
        self.assertEqual(expr, "format_number(object.color, ',.0f')")

    # ── 關聯欄位：事前依型別，不是事後猜輸出長相 ────────────────
    def test_many2one_formatted_by_type_not_by_repr_guess(self):
        expr = self.Mixin._type_format_expression(
            'res.partner', 'parent_id', 'object.parent_id')
        self.assertEqual(expr, 'object.parent_id.display_name')
        self.assertEqual(
            self._value(source='record', path='parent_id'),
            self.parent.display_name)

    def test_many2many_joined_by_names_helper(self):
        expr = self.Mixin._type_format_expression(
            'res.partner', 'category_id', 'object.category_id')
        self.assertEqual(expr, 'names(object.category_id)')
        tag = self.env['res.partner.category'].create({'name': '甲類'})
        tag2 = self.env['res.partner.category'].create({'name': '乙類'})
        self.partner.category_id = [(6, 0, (tag + tag2).ids)]
        value = self._value(source='record', path='category_id')
        self.assertIn('甲類', value)
        self.assertIn('乙類', value)
        self.assertNotIn('res.partner.category(', value)

    # ── 不在表裡的：刻意的 ──────────────────────────────────────
    def test_boolean_is_deliberately_not_in_the_table(self):
        """原生 QWeb 對布林沒有 field converter。放進表會與原生不一致。"""
        self.assertIsNone(self.Mixin._type_format_expression(
            'res.partner', 'is_company', 'object.is_company'))

    def test_checkmark_helper_is_available_for_opt_in(self):
        """要方框的範本（自主檢查表）明寫 checkmark()。"""
        self.partner.is_company = True
        self.assertEqual(
            self._value(source='expression',
                        expression='checkmark(object.is_company)'), '☑')
        self.partner.is_company = False
        self.assertEqual(
            self._value(source='expression',
                        expression='checkmark(object.is_company)'), '☐')

    def test_unknown_field_returns_none_rather_than_guessing(self):
        self.assertIsNone(self.Mixin._type_format_expression(
            'res.partner', 'no_such_field', 'object.no_such_field'))
        self.assertIsNone(self.Mixin._type_format_expression(
            'no.such.model', 'name', 'object.name'))

    # ── 優先序 ──────────────────────────────────────────────────
    def test_explicit_expression_beats_the_table(self):
        """原範本有 widget、或使用者自己打的，不可以被預設蓋掉。"""
        meta = {'source': 'record', 'path': 'partner_latitude',
                'expression': 'object.partner_latitude'}
        self.assertEqual(
            self.Mixin._field_meta_expression(meta, self.partner),
            'object.partner_latitude')

    def test_meta_format_beats_the_table(self):
        meta = {'source': 'record', 'path': 'write_date', 'format': '%Y/%m'}
        self.assertEqual(
            self.Mixin._field_meta_expression(meta, self.partner),
            "format_date(object.write_date, '%Y/%m')")

    def test_without_record_falls_back_to_plain_path(self):
        """查不到型別就印原值——至少看得出是什麼。"""
        self.assertEqual(
            self.Mixin._field_meta_expression(
                {'source': 'record', 'path': 'partner_latitude'}),
            'object.partner_latitude')

    # ── 轉換器用的是同一份表 ────────────────────────────────────
    def test_converter_shares_the_same_table(self):
        Conv = self.env['doc.qweb.converter']
        state = {'model': 'res.partner', 'loop_models': []}
        for path in ('partner_latitude', 'color', 'write_date'):
            self.assertEqual(
                Conv._auto_format(None, state, path, 'record',
                                  'object.%s' % path),
                self.Mixin._type_format_expression(
                    'res.partner', path, 'object.%s' % path,
                    numeric_only=True),
                '轉換器又長出自己的一份表了（%s）' % path)

    def test_converter_leaves_relational_to_the_render_layer(self):
        """轉換器只補數字與日期：那組範圍是已經量過保真度的現狀。

        selection / 關聯欄位改成讓藥丸只帶 path，由渲染層處理——同一條路
        也照顧到手工做的範本。
        """
        Conv = self.env['doc.qweb.converter']
        state = {'model': 'res.partner', 'loop_models': []}
        for path in ('type', 'parent_id', 'category_id'):
            self.assertIsNone(
                Conv._auto_format(None, state, path, 'record',
                                  'object.%s' % path))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestFieldLabelPill(TransactionCase):
    """欄位標籤藥丸：翻譯取自 Odoo 的欄位定義，不要逐語言手打。

    表頭的「品名／數量／單價」就是欄位標籤。走 i18n 藥丸等於請使用者把
    Odoo 的 .po 再抄一遍，而且之後兩邊各自漂移。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '標籤測試'})

    def _value(self, record=None, **meta):
        tree = {'main': [_pill('後備文字', **meta), _text('\n')]}
        self.Mixin._snapshot_content_json(tree, record or self.partner)
        return tree['main'][0]['value']

    def test_prints_the_field_label(self):
        expected = self.env['res.partner'].fields_get(
            ['vat'], ['string'])['vat']['string']
        self.assertEqual(
            self._value(source='fieldLabel', path='vat'), expected)

    def test_label_model_lets_a_header_name_a_line_field(self):
        """表頭那顆藥丸放在重複列外面，求值記錄是主記錄——模型要明講。"""
        if 'sale.order.line' not in self.env:
            self.skipTest('sale 未安裝')
        expected = self.env['sale.order.line'].fields_get(
            ['price_unit'], ['string'])['price_unit']['string']
        self.assertEqual(
            self._value(source='fieldLabel', path='price_unit',
                        labelModel='sale.order.line'),
            expected)

    def test_nested_path_uses_the_owning_model(self):
        expected = self.env['res.country'].fields_get(
            ['name'], ['string'])['name']['string']
        self.assertEqual(
            self._value(source='fieldLabel', path='country_id.name'), expected)

    def test_unknown_path_falls_back_to_label_text(self):
        """空白在單據上像資料掉了；後備文字看得出是哪一顆藥丸要修。"""
        self.assertEqual(
            self._value(source='fieldLabel', path='no_such_field'), '後備文字')
        self.assertEqual(
            self._value(source='fieldLabel', path=''), '後備文字')

    def test_follows_the_render_language(self):
        """換語言時標籤跟著換——這正是不用 i18n 藥丸的理由。"""
        lang = self.env['res.lang']._activate_lang('zh_TW') \
            or self.env['res.lang'].search([('code', '=', 'zh_TW')], limit=1)
        if not lang:
            self.skipTest('zh_TW 未安裝')
        record = self.partner.with_context(lang='zh_TW')
        value_tw = self._value(record=record, source='fieldLabel', path='vat')
        expected = self.env['res.partner'].with_context(
            lang='zh_TW').fields_get(['vat'], ['string'])['vat']['string']
        self.assertEqual(value_tw, expected)

    def test_is_not_treated_as_a_marker(self):
        """標記藥丸不會印；這一顆要印。"""
        element = _pill('標籤', source='fieldLabel', path='vat')
        self.assertFalse(self.Mixin._is_marker_element(element))
