"""藥丸管線測試 — Jinja 沙箱與求值：helper、白名單、金額與日期格式、recordset repr。
對應 models/render/sandbox.py。

這一批是從 test_pill_pipeline.py 拆出來的（原本 3921 行、43 個類別）。
按**被測的那一層**分，讓「某一層壞了」一眼看得出是哪一批紅。
共用的 _text / _pill helper 在 test_pill_helpers.py。
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from .test_pill_helpers import _cell, _pill, _text


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
class TestReportHelperWhitelist(TransactionCase):
    """report_helper —— 沙箱裡呼叫底線方法的那道窄門。

    沙箱擋掉所有底線開頭的方法（提權的主要入口），但原生報表確實會呼叫
    幾個純計算的輔助方法，擋掉的後果是單據上那一段印成空白、沒有訊息。
    所以開一道窄門：方法名與模型都要在白名單上。

    這裡刻意用 res.partner._display_address（真的底線方法、真的只讀）來測
    機制，而不是用 account 的那幾個——本模組不相依 account/sale，測試不該
    因為某個模組沒裝就紅。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({
            'name': '窄門測試', 'street': '信義路五段 7 號', 'city': '台北市',
        })

    def _render(self, expression, record=None):
        record = record or self.partner
        env_j = self.Mixin._get_sandbox_env(record)
        return env_j.from_string('{{ %s }}' % expression).render(
            object=record, user=self.env.user,
        )

    def _allow(self, *entries):
        self.patch(type(self.Mixin), '_SAFE_REPORT_METHODS',
                   frozenset(entries))

    def test_whitelisted_method_is_callable(self):
        self._allow(('res.partner', '_display_address'))
        self.assertIn(
            '信義路五段 7 號',
            self._render("report_helper(object, '_display_address')"),
        )

    def test_direct_call_is_still_blocked(self):
        """白名單只開 report_helper 這條路，沙箱本身不放寬。"""
        self._allow(('res.partner', '_display_address'))
        with self.assertRaises(Exception):
            self._render('object._display_address()')

    def test_unlisted_method_returns_empty(self):
        self._allow(('res.partner', '_display_address'))
        self.assertEqual(
            self._render("report_helper(object, '_write')"), '')

    def test_unlisted_method_has_no_side_effect(self):
        """就算方法名猜對了，不在名單上就不該被呼叫到。"""
        self._allow(('res.partner', '_display_address'))
        self._render("report_helper(object, 'write', {'name': 'HACK'})")
        self.assertEqual(self.partner.name, '窄門測試')

    def test_right_name_wrong_model_returns_empty(self):
        """名單是 (模型, 方法名) 配對——只比對方法名等於沒有名單。"""
        self._allow(('res.currency', '_display_address'))
        self.assertEqual(
            self._render("report_helper(object, '_display_address')"), '')

    def test_zero_is_not_treated_as_empty(self):
        """0.0 == False。寫成 value in (None, False) 的話，金額剛好是 0
        的那一期會印成空白——那是最難發現的一種錯。"""
        self._allow(('res.partner', '_zero_probe'))
        # create=True：這支方法本來不存在，mock 預設會拒絕 patch 不存在的屬性
        self.startPatcher(patch.object(
            type(self.env['res.partner']), '_zero_probe',
            lambda self: 0.0, create=True,
        ))
        self.assertEqual(
            self._render("report_helper(object, '_zero_probe')"), '0.0')

    def test_qr_code_generator_is_not_whitelisted(self):
        """account.move._generate_qr_code 會在回傳前回寫 qr_code_method。

        也就是「印一張 PDF 會改資料」。轉換器改走公開的
        res.partner.bank.build_qr_code_base64()（只讀、參數相同）。
        這則測試釘住那個決定，避免之後有人為了讓 QR 印出來就加進名單。
        """
        self.assertNotIn(('account.move', '_generate_qr_code'),
                         self.Mixin._SAFE_REPORT_METHODS)

    def test_len_is_available(self):
        """Jinja 沒有 len()，而 QWeb 條件到處寫 len(x) > 1。

        沒有這個 helper，那種條件會以 UndefinedError 收場——而條件求值失敗
        是「當真」，於是該藏起來的區塊照印。
        """
        self.assertEqual(self._render('len(object.child_ids)'), '0')
        self.assertEqual(
            self._render('1 if len(object.child_ids) > 1 else 0'), '0')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRecordsetReprGuard(TransactionCase):
    """many2one 藥丸不可以印出 Python repr。

    Jinja 的字串化把 recordset 變成 "res.partner(7,)"。使用者寫
    t-field="o.partner_id" 要的是名稱，而印出一個 repr 不會報錯——
    實測：出貨單的收件人欄位整段就是 "res.partner(14570,)"。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.parent = self.env['res.partner'].create({'name': '母公司名'})
        self.partner = self.env['res.partner'].create({
            'name': '子公司名', 'parent_id': self.parent.id})

    def _value(self, **meta):
        tree = {'main': [_pill('X', **meta), _text('\n')]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        return tree['main'][0]['value']

    def test_many2one_path_uses_display_name(self):
        value = self._value(source='record', path='parent_id')
        self.assertEqual(value, self.parent.display_name)
        self.assertNotIn('res.partner(', value)

    def test_many2one_expression_uses_display_name(self):
        value = self._value(source='record', expression='object.parent_id')
        self.assertEqual(value, self.parent.display_name)

    def test_plain_text_is_untouched(self):
        """只在「輸出剛好長得像 repr」時才多算一次，其他取值不受影響。"""
        self.assertEqual(
            self._value(source='record', path='name'), '子公司名')

    def test_text_that_looks_like_a_call_is_untouched(self):
        """像函式呼叫的字串不是 recordset repr——不可以被改掉。"""
        self.partner.ref = 'f(1)'
        self.assertEqual(self._value(source='record', path='ref'), 'f(1)')

    def test_line_pill_in_repeat_row_also_fixed(self):
        """重複列用的是另一條求值路徑（_eval_for），兩邊都要修。"""
        tree = {'header': [], 'footer': [], 'main': [
            {'type': 'table', 'value': '', 'colgroup': [{'width': 300}],
             'trList': [{'tdList': [_cell(
                 _pill('明細', source='repeat', path='child_ids',
                       repeatId='rp1'),
                 _pill('母公司', source='line', path='parent_id'),
             )]}]},
            _text('\n'),
        ]}
        snapped = self.Mixin._snapshot_content_json(tree, self.parent)
        values = [el.get('value')
                  for row in snapped['main'][0]['trList']
                  for cell in row['tdList'] for el in cell['value']
                  if (el.get('value') or '') != '\n']
        self.assertEqual(values, [self.parent.display_name])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestLocaleDateFormat(TransactionCase):
    """format_date 的兩個語言格式。

    原生報表印的是語言格式（10/08/2026），ISO 的 2026-10-08 在單據上是
    看得出來的差別。但**預設值刻意不動**：既有範本（含使用者手工做的）
    的輸出不該因為這個改動而位移，要語言格式的是轉換器產生的表達式，
    它會明寫 'lang'。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '日期格式'})

    def _render(self, expression):
        env_j = self.Mixin._get_sandbox_env(self.partner)
        return env_j.from_string('{{ %s }}' % expression).render(
            object=self.partner, user=self.env.user)

    def test_default_is_still_iso(self):
        self.assertEqual(
            self._render("format_date(object.create_date)"),
            self.partner.create_date.strftime('%Y-%m-%d'),
        )

    def test_lang_uses_odoo_date_format(self):
        from odoo.tools.misc import format_date as odoo_format_date
        self.assertEqual(
            self._render("format_date(object.create_date, 'lang')"),
            odoo_format_date(self.env, self.partner.create_date),
        )

    def test_lang_datetime_includes_the_time(self):
        from odoo.tools.misc import format_datetime
        self.assertEqual(
            self._render("format_date(object.create_date, 'lang_datetime')"),
            format_datetime(self.env, self.partner.create_date),
        )

    def test_empty_value_is_still_empty(self):
        self.assertEqual(self._render("format_date(False, 'lang')"), '')

    def test_bad_value_does_not_raise(self):
        """格式化不了就退回字串——一個壞欄位不該讓整份文件產不出來。"""
        self.assertEqual(self._render("format_date('不是日期', 'lang')"),
                         '不是日期')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestHasGroupHelper(TransactionCase):
    """has_group —— 對應 QWeb 節點的 groups 屬性。

    沙箱不開放 env，所以「使用者在不在某個群組」只能由 helper 代為查。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '群組測試'})

    def _render(self, expression):
        env_j = self.Mixin._get_sandbox_env(self.partner)
        return env_j.from_string('{{ %s }}' % expression).render(
            object=self.partner, user=self.env.user)

    def test_true_for_a_group_the_user_has(self):
        self.assertEqual(self._render("has_group('base.group_user')"), 'True')

    def test_false_for_a_group_the_user_lacks(self):
        self.assertEqual(self._render("has_group('base.group_portal')"),
                         'False')

    def test_unknown_group_is_false_not_an_error(self):
        """群組不存在時回 False（與 Odoo 的 has_group 一致），不可以拋例外。

        條件求值失敗的策略是「當真」，所以拋例外會變成「那一段照印」——
        與原生（看不到該群組就不印）相反。
        """
        self.assertEqual(self._render("has_group('nope.nope')"), 'False')

    def test_env_is_still_blocked(self):
        """helper 開的是一道窄門，不是把 env 放出來。"""
        with self.assertRaises(Exception):
            self._render("env.user.has_group('base.group_user')")


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestModelReportValues(TransactionCase):
    """模型可以自備一支 doc_report_values() 回 dict，範本用 data.<鍵>。

    為什麼需要這道口：_SAFE_REPORT_METHODS 那份白名單是給**別人家的**方法
    開的窄門，每加一筆都要讀過 Odoo 原始碼確認不寫資料。整合者要加自己算的
    值（分段稅率表、客製編號、跨模型彙總）時那是錯的門——那是他自己寫的
    程式碼，不需要我們信任誰。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '自備值測試'})

    def _render(self, expression, record=None):
        tree = {'main': [
            _pill('X', source='expression', expression=expression), _text('\n')]}
        self.Mixin._snapshot_content_json(tree, record or self.partner)
        return tree['main'][0]['value']

    def test_values_are_available_as_data(self):
        with patch.object(
            type(self.partner), 'doc_report_values',
            create=True, return_value={'口號': '德博資訊', '件數': 3},
        ):
            self.assertEqual(self._render("data['口號']"), '德博資訊')
            self.assertEqual(self._render("data['件數']"), '3')

    def test_called_once_per_snapshot_not_once_per_pill(self):
        """每顆藥丸各建一個沙箱 env，所以這很容易變成 N 次呼叫。

        整合者的方法可能很重（跨模型彙總）。一份快照呼叫一次是約定。
        """
        calls = []

        def _values(record_self):
            calls.append(1)
            return {'n': len(calls)}

        tree = {'main': [
            _pill('A', source='expression', expression="data['n']"),
            _pill('B', source='expression', expression="data['n']"),
            _pill('C', source='expression', expression="data['n']"),
            _text('\n'),
        ]}
        with patch.object(type(self.partner), 'doc_report_values',
                          _values, create=True):
            self.Mixin._snapshot_content_json(tree, self.partner)
        self.assertEqual(len(calls), 1, '呼叫了 %d 次' % len(calls))
        # 三顆藥丸都看到同一份值
        self.assertEqual(
            [el['value'] for el in tree['main'][:3]], ['1', '1', '1'])

    def test_failure_leaves_data_empty_and_document_still_renders(self):
        """整合者的一支輔助方法不該讓整張單據產不出來。

        藥丸自己那一段會被規則 A 收掉（段落內藥丸全空 → 整段移除，標籤一起），
        那是定案行為；要釘的是**別的段落還在**、而且沒有拋例外。
        """
        with patch.object(
            type(self.partner), 'doc_report_values',
            create=True, side_effect=ValueError('壞了'),
        ):
            tree = {'main': [
                _pill('X', source='expression', expression="data['任何']"),
                _text('\n'),
                _text('留下來的本文'), _text('\n'),
            ]}
            self.Mixin._snapshot_content_json(tree, self.partner)
            self.assertEqual(
                self.Mixin._model_report_values(self.partner), {})
        values = [el.get('value') for el in tree['main']]
        self.assertIn('留下來的本文', values, '別的段落被連帶刪掉了')
        self.assertNotIn('X', values, '壞掉的 data 藥丸應該收掉，不是印標籤')

    def test_non_dict_return_is_ignored(self):
        """回的不是 dict 就當沒有——不要讓單據上出現一段 Python repr。"""
        with patch.object(type(self.partner), 'doc_report_values',
                          create=True, return_value=['不是', 'dict']):
            self.assertEqual(
                self.Mixin._model_report_values(self.partner), {})

    def test_model_without_the_method_is_fine(self):
        self.assertEqual(self.Mixin._model_report_values(self.partner), {})
        self.assertEqual(self._render("data"), '{}')
