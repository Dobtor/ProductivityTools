"""doc.qweb.converter 的轉換規則。

這支存在的理由：轉換器是整個模組裡唯一會「猜」的地方（_REWRITE_RULES），
而它的輸出是一份 JSON 樹——錯了不會拋例外，只會轉出一張看起來像、但明細
少一欄或條件失效的範本。之前它只靠手動對原生報表試跑驗證，版本一換就沒人
記得當初驗過什麼。

這裡的 arch 一律是自己寫的最小範例，不依賴 Odoo 原生報表的 XML：
原生範本每個版本都會動，拿它當斷言基準的測試遲早變成「改版就紅」。
"""

import json
import itertools
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

_SEQ = itertools.count()


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestQwebConverterBase(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Conv = self.env['doc.qweb.converter']

    def _convert(self, body, model='res.partner', **kw):
        """把一段 QWeb 片段包成報表範本再轉換。"""
        key = 'dobtor_doc_editor.conv_test_%d' % next(_SEQ)
        arch = '<t t-name="%s">%s</t>' % (key, body)
        self.env['ir.ui.view'].create({
            'name': key, 'type': 'qweb', 'key': key, 'arch': arch,
        })
        report = self.env['ir.actions.report'].create({
            'name': key, 'model': model, 'report_type': 'qweb-pdf',
            'report_name': key,
        })
        res = self.Conv.convert_report(report, **kw)
        res['tree'] = json.loads(res['content_json'] or '{}')
        return res

    # ── 取出結構的小工具 ─────────────────────────────────────────

    def _tables(self, elements):
        for el in elements:
            if el.get('type') == 'table':
                yield el
                for row in el.get('trList') or []:
                    for cell in row.get('tdList') or []:
                        yield from self._tables(cell.get('value') or [])

    def _metas(self, elements):
        for el in elements:
            meta = (el.get('extension') or {}).get('dobtorField')
            if meta:
                yield meta
            if el.get('type') == 'table':
                for row in el.get('trList') or []:
                    for cell in row.get('tdList') or []:
                        yield from self._metas(cell.get('value') or [])

    def _texts(self, elements):
        out = []
        for el in elements:
            if el.get('type') == 'table':
                for row in el.get('trList') or []:
                    for cell in row.get('tdList') or []:
                        out.extend(self._texts(cell.get('value') or []))
            elif not (el.get('extension') or {}).get('dobtorField'):
                value = (el.get('value') or '').strip()
                if value:
                    out.append(value)
        return out


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestNonTableForeach(TestQwebConverterBase):
    """清單式的 t-foreach（<div> 不是 <tr>）。

    原本這種只會留一句「請改用表格呈現」的待辦，然後把迴圈體當成靜態內容
    印一次——轉出來的範本上那段只會出現一筆，而且使用者看不出哪裡不對。
    """

    def test_list_foreach_becomes_one_column_repeat_table(self):
        res = self._convert(
            '<div t-foreach="o.child_ids" t-as="kid">'
            '<span t-out="kid.name"/> 的電話：<span t-out="kid.phone"/>'
            '</div>'
        )
        tables = list(self._tables(res['tree']['main']))
        self.assertEqual(len(tables), 1, '應該剛好包出一張表格')
        table = tables[0]
        self.assertEqual(len(table['colgroup']), 1, '單欄')
        self.assertEqual(len(table['trList']), 1, '一列（會被後端展開）')
        # 無框：原本是 <div> 清單，畫出框線版面就變了
        self.assertEqual(table.get('borderType'), 'empty')

        metas = list(self._metas(res['tree']['main']))
        repeats = [m for m in metas if m.get('source') == 'repeat']
        self.assertEqual(len(repeats), 1)
        self.assertEqual(repeats[0].get('path'), 'child_ids')
        self.assertFalse(repeats[0].get('unbound'),
                         '路徑是從 arch 讀出來的，不該標成待確認')
        # 迴圈體的欄位要變成 line 來源，否則每一列都印主記錄的值
        lines = [m for m in metas if m.get('source') == 'line']
        self.assertEqual({m.get('path') for m in lines}, {'name', 'phone'})
        self.assertIn('的電話：', ''.join(self._texts(res['tree']['main'])))

    def test_foreach_body_with_table_is_flagged_not_nested(self):
        """迴圈體裡有表格時不包——包起來會變巢狀表格。"""
        res = self._convert(
            '<div t-foreach="o.child_ids" t-as="kid">'
            '<table><tr><td><span t-out="kid.name"/></td></tr></table>'
            '</div>'
        )
        metas = list(self._metas(res['tree']['main']))
        self.assertFalse([m for m in metas if m.get('source') == 'repeat'],
                         '不該硬包成重複表格')
        self.assertTrue(any('巢狀表格' in n for n in res['notes']),
                        '必須明講為什麼沒轉：%s' % res['notes'])

    def test_condition_on_the_loop_node_wraps_in_condition_block(self):
        """t-if 與 t-foreach 掛在同一個節點。

        前者是「整段要不要印」、後者是「逐筆重複」，兩者都要保留：
        條件區塊在外、重複表格在內。順序寫錯的話（先走條件分支）
        t-foreach 會整個被丟掉，迴圈體只印一次——實測過的錯誤。
        """
        res = self._convert(
            '<div t-if="len(o.child_ids) &gt; 1" t-foreach="o.child_ids"'
            ' t-as="kid"><span t-out="kid.name"/></div>'
        )
        tables = list(self._tables(res['tree']['main']))
        self.assertEqual(len(tables), 2, '外層條件區塊 + 內層重複表格')
        outer, inner = tables
        self.assertEqual((outer.get('extension') or {}).get('dobtorBlock'),
                         'condition')
        self.assertIsNone((inner.get('extension') or {}).get('dobtorBlock'))
        metas = list(self._metas(res['tree']['main']))
        conds = [m for m in metas if m.get('source') == 'condition']
        self.assertEqual(len(conds), 1)
        self.assertIn('object.child_ids', conds[0].get('expression') or '')
        repeats = [m for m in metas if m.get('source') == 'repeat']
        self.assertEqual(repeats[0].get('path'), 'child_ids',
                         '重複不可以被條件分支吃掉')

    def test_loop_index_becomes_running_pill(self):
        """QWeb 的 <t-as>_index + 1 就是項次。"""
        res = self._convert(
            '<div t-foreach="o.child_ids" t-as="kid">'
            '<span t-out="kid_index + 1"/>. <span t-out="kid.name"/></div>'
        )
        metas = list(self._metas(res['tree']['main']))
        running = [m for m in metas if m.get('source') == 'running']
        self.assertEqual(len(running), 1, '應轉成流水序號藥丸：%s' % metas)
        self.assertEqual(running[0].get('op'), 'index')
        self.assertFalse([m for m in metas
                          if (m.get('labelText') or '').startswith('待確認')],
                         '不該再留下待確認藥丸')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRowCondition(TestQwebConverterBase):
    """<tr t-if="..."> 的條件原本整個被忽略。

    後果是明細表把不該印的列也印出來——而範本上看不出任何異常。
    """

    def test_tr_condition_becomes_condition_pill(self):
        res = self._convert(
            '<table><tr><th>名稱</th></tr>'
            '<tr t-if="o.active"><td><span t-out="o.name"/></td></tr>'
            '</table>'
        )
        metas = list(self._metas(res['tree']['main']))
        conds = [m for m in metas if m.get('source') == 'condition']
        self.assertEqual(len(conds), 1, '列條件要轉成條件藥丸：%s' % metas)
        self.assertEqual(conds[0].get('expression'), 'object.active')

    def test_tr_condition_inside_loop_uses_line(self):
        """迴圈內的列條件要以明細求值，不是主記錄。"""
        res = self._convert(
            '<table><t t-foreach="o.child_ids" t-as="kid">'
            '<tr t-if="kid.phone"><td><span t-out="kid.name"/></td></tr>'
            '</t></table>'
        )
        conds = [m for m in self._metas(res['tree']['main'])
                 if m.get('source') == 'condition']
        self.assertEqual(len(conds), 1)
        self.assertEqual(conds[0].get('expression'), 'line.phone')

    def test_dict_loop_var_subscript_is_mapped(self):
        """迴圈變數是 dict 時 QWeb 寫下標：kid['x'] 也要換成 line['x']。"""
        res = self._convert(
            '<table><t t-foreach="o.child_ids" t-as="kid">'
            '<tr t-if="kid[\'phone\']"><td><span t-out="kid.name"/></td></tr>'
            '</t></table>'
        )
        conds = [m for m in self._metas(res['tree']['main'])
                 if m.get('source') == 'condition']
        self.assertEqual(conds[0].get('expression'), "line['phone']")


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestSymbolExpansion(TestQwebConverterBase):

    def test_self_referential_tset_does_not_nest(self):
        """<t t-set="x" t-value="o.x"/> 是 QWeb 常見寫法。

        名稱出現在自己的值裡，不擋的話展開會一路套到深度上限，
        轉出來是 object.(object.(object.(...)))——實測過的錯誤。
        """
        res = self._convert(
            '<t t-set="child_ids" t-value="o.child_ids"/>'
            '<table><t t-foreach="child_ids" t-as="kid">'
            '<tr><td><span t-out="kid.name"/></td></tr></t></table>'
        )
        raw = res['content_json']
        self.assertNotIn('object.(', raw, '不該出現層層套疊的根變數')
        repeats = [m for m in self._metas(res['tree']['main'])
                   if m.get('source') == 'repeat']
        self.assertEqual(repeats[0].get('path'), 'child_ids',
                         '剝掉內聯加的括號後就是一條乾淨路徑')

    def test_inlined_symbol_paren_is_unwrapped(self):
        res = self._convert(
            '<t t-set="kids" t-value="o.child_ids"/>'
            '<table><t t-foreach="kids" t-as="kid">'
            '<tr><td><span t-out="kid.name"/></td></tr></t></table>'
        )
        repeats = [m for m in self._metas(res['tree']['main'])
                   if m.get('source') == 'repeat']
        self.assertEqual(repeats[0].get('path'), 'child_ids')
        self.assertFalse(repeats[0].get('sourceExpression'),
                         '能用路徑就不要用表達式（使用者在右欄看得懂）')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestContactWidget(TestQwebConverterBase):
    """widget="contact" 的 fields 決定要不要印名稱。

    _display_address() 不含名稱，而原生 contact widget 的 fields 預設含
    "name"。少了這一段，收件人區塊只剩一串地址。
    """

    def test_contact_without_fields_keeps_name(self):
        res = self._convert(
            '<div t-field="o.parent_id" t-options=\'{"widget": "contact"}\'/>'
        )
        metas = [m for m in self._metas(res['tree']['main'])
                 if m.get('source') == 'record']
        self.assertIn('with_name=True', metas[0].get('expression') or '')

    def test_contact_with_explicit_fields_follows_arch(self):
        res = self._convert(
            '<div t-field="o.parent_id" t-options=\'{"widget": "contact",'
            ' "fields": ["address"]}\'/>'
        )
        metas = [m for m in self._metas(res['tree']['main'])
                 if m.get('source') == 'record']
        expression = metas[0].get('expression') or ''
        self.assertIn('format_address(', expression)
        self.assertNotIn('with_name', expression,
                         'arch 沒要名稱就不要自己加')

    def test_contact_with_name_in_fields(self):
        res = self._convert(
            '<div t-field="o.parent_id" t-options=\'{"widget": "contact",'
            ' "fields": ["address", "name"]}\'/>'
        )
        metas = [m for m in self._metas(res['tree']['main'])
                 if m.get('source') == 'record']
        self.assertIn('with_name=True', metas[0].get('expression') or '')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestSafeMethodRewrite(TestQwebConverterBase):
    """底線方法的三條路：白名單、語意改寫、標待辦。

    沙箱擋掉所有底線開頭的方法，但原生報表會呼叫幾個。這裡測的是轉換器
    怎麼分派——用 res.partner 的方法測機制，不相依 account/sale。
    """

    def _allow(self, *entries):
        Mixin = self.env['doc.render.mixin']
        self.patch(type(Mixin), '_SAFE_REPORT_METHODS', frozenset(entries))

    def test_whitelisted_method_becomes_report_helper(self):
        self._allow(('res.partner', '_display_address'))
        res = self._convert('<span t-out="o.parent_id._display_address()"/>')
        metas = list(self._metas(res['tree']['main']))
        self.assertEqual(
            metas[0].get('expression'),
            "report_helper(object.parent_id, '_display_address')",
        )
        self.assertTrue(any('白名單' in n for n in res['notes']))

    def test_whitelisted_method_keeps_arguments(self):
        self._allow(('res.partner', '_display_address'))
        res = self._convert(
            '<span t-out="o._display_address(without_company=True)"/>')
        metas = list(self._metas(res['tree']['main']))
        self.assertEqual(
            metas[0].get('expression'),
            "report_helper(object, '_display_address', without_company=True)",
        )

    def test_unlisted_method_is_flagged_not_rewritten(self):
        """不在名單上的不要亂改——留原式＋待辦，使用者才知道該看哪裡。"""
        self._allow(('res.partner', '_display_address'))
        res = self._convert('<span t-out="o._whatever_private()"/>')
        metas = list(self._metas(res['tree']['main']))
        self.assertIn('_whatever_private', metas[0].get('expression') or '')
        self.assertTrue(metas[0].get('unbound'))
        self.assertNotIn('report_helper', metas[0].get('expression') or '')
        self.assertTrue(any('請確認' in n for n in res['notes']),
                        '要有待辦，使用者才知道該看哪裡：%s' % res['notes'])

    def test_whitelisted_method_as_repeat_source_still_resolves(self):
        """白名單方法當明細來源，要真的取得到明細。

        改寫後根變數後面接的是逗號（report_helper(object, '…')），
        判斷寫成 'object.' in mapped 會判成「對不上」→ 明細來源變成待設定
        → 整張明細表印不出來。實測過：銷售訂單的品名與章節全部消失，
        而範本上看起來只是「來源待設定」，沒人會把兩件事連起來。
        """
        self._allow(('res.partner', '_kids_to_report'))
        self.startPatcher(patch.object(
            type(self.env['res.partner']), '_kids_to_report',
            lambda self: self.child_ids, create=True,
        ))
        parent = self.env['res.partner'].create({'name': '來源母公司'})
        child = self.env['res.partner'].create({
            'name': '來源子公司', 'parent_id': parent.id})
        res = self._convert(
            '<t t-set="kids" t-value="o._kids_to_report()"/>'
            '<table><t t-foreach="kids" t-as="kid">'
            '<tr><td><span t-out="kid.name"/></td></tr></t></table>'
        )
        repeats = [m for m in self._metas(res['tree']['main'])
                   if m.get('source') == 'repeat']
        source = repeats[0].get('sourceExpression') or ''
        self.assertIn('report_helper', source)
        self.assertIn('object', source, '根變數要換成沙箱認識的名字')
        lines = self.env['doc.render.mixin']._resolve_repeat_records(
            parent, repeats[0])
        self.assertEqual(lines, [child], '來源要真的取得到明細')

    def test_generate_qr_code_goes_through_public_method(self):
        """_generate_qr_code 會回寫 qr_code_method（印 PDF 就改資料）。

        所以不走白名單，改用公開的 build_qr_code_base64()：參數與原生相同、
        qr_method 留空讓它自己挑，差別只在不回寫。
        """
        res = self._convert(
            '<span t-out="o._generate_qr_code(silent_errors=True)"/>',
            model='account.move' if self.env['ir.model']._get('account.move')
            else 'res.partner',
        )
        expression = list(self._metas(res['tree']['main']))[0].get(
            'expression') or ''
        self.assertIn('build_qr_code_base64', expression)
        self.assertNotIn('_generate_qr_code', expression)
        self.assertTrue(any('回寫 qr_code_method' in n for n in res['notes']))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestDictLoopVarSource(TestQwebConverterBase):
    """迴圈變數是 dict 時，藥丸的 source 必須還是 line。

    原本判斷寫 `'line.' in expr`，而 dict 寫的是下標 line['date']，
    於是 source 變成 record——渲染時那顆藥丸以主記錄求值，印出來是空的，
    而且沒有任何訊息。
    """

    def test_subscript_value_pill_is_line_source(self):
        res = self._convert(
            '<table><t t-foreach="o.child_ids" t-as="kid">'
            '<tr><td><span t-out="kid[\'name\']"/></td></tr></t></table>'
        )
        values = [m for m in self._metas(res['tree']['main'])
                  if m.get('source') in ('line', 'record')]
        self.assertEqual(values[0].get('source'), 'line')
        self.assertEqual(values[0].get('expression'), "line['name']")

    def test_subscript_branch_pill_is_line_source(self):
        """行內 t-if/t-else 收成三元式時也是同一個判斷。"""
        res = self._convert(
            '<table><t t-foreach="o.child_ids" t-as="kid">'
            '<tr><td><t t-if="kid[\'phone\']">有</t>'
            '<t t-else="">無</t></td></tr></t></table>'
        )
        pills = [m for m in self._metas(res['tree']['main'])
                 if (m.get('expression') or '').find('line[') >= 0]
        self.assertTrue(pills, '三元式應保留 line 下標：%s'
                        % list(self._metas(res['tree']['main'])))
        self.assertEqual(pills[0].get('source'), 'line')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestValidationProbePerRow(TestQwebConverterBase):
    """試算要用「該列自己的明細」。

    同一張單據上可以有好幾個形狀不同的重複（發票同時有明細列與付款列，
    後者的一筆是 dict）。全樹共用一筆明細的話，另一個重複的 line 藥丸
    會得到一整批假失敗——而假失敗會把藥丸標成待確認，使用者就去檢查一個
    其實沒問題的地方。
    """

    def setUp(self):
        super().setUp()
        self.parent = self.env['res.partner'].create({'name': '母公司'})
        self.child = self.env['res.partner'].create({
            'name': '子公司', 'parent_id': self.parent.id})

    def test_targets_carry_their_own_row_line(self):
        res = self._convert(
            '<table><t t-foreach="o.child_ids" t-as="kid">'
            '<tr><td><span t-out="kid.name"/></td></tr></t></table>'
            '<p><span t-out="o.name"/></p>'
        )
        pairs = list(self.Conv._iter_validation_targets(
            res['tree'], self.parent))
        by_source = {}
        for element, line, _loop in pairs:
            meta = (element.get('extension') or {}).get('dobtorField')
            if meta:
                by_source[meta.get('source')] = line
        self.assertEqual(by_source.get('line'), self.child,
                         '重複列內的藥丸要配到該列的明細')
        self.assertIsNone(by_source.get('record'),
                          '重複列外的藥丸沒有明細')

    def test_empty_repeat_source_is_skipped_not_failed(self):
        """取不到樣本明細時「沒試算」，不是「試算失敗」。"""
        empty = self.env['res.partner'].create({'name': '沒有子公司'})
        res = self._convert(
            '<table><t t-foreach="o.child_ids" t-as="kid">'
            '<tr><td><span t-out="kid.name"/></td></tr></t></table>',
            validate_with=empty,
        )
        self.assertEqual(res['stats']['validate_failed'], 0)
        self.assertTrue(res['stats']['validate_skipped'] >= 1)
        self.assertTrue(any('沒試算' in n for n in res['notes']))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestLoneCondition(TestQwebConverterBase):
    """掛在非區塊節點上的單獨 t-if。

    這種條件原本被整個忽略，內容照印。實測後果：沒有提前付款折扣的發票也
    印出一句「due if paid before」加一個日期——那一段的條件就是掛在 <t> 上。
    區塊標籤（div/p/…）上的 t-if 早就有條件區塊可走，只有行內節點沒有。
    """

    def test_value_node_with_condition_becomes_ternary(self):
        """條件與值在同一個節點：收成三元式，不動版面。"""
        res = self._convert('<span t-if="o.ref" t-out="o.ref"/>')
        metas = list(self._metas(res['tree']['main']))
        self.assertEqual(len(metas), 1, '一顆藥丸就夠，不要多一個區塊容器')
        self.assertEqual(metas[0].get('expression'),
                         'object.ref if (object.ref) else ""')
        self.assertFalse(list(self._tables(res['tree']['main'])),
                         '不該產生區塊容器')

    def test_text_only_branch_becomes_ternary(self):
        res = self._convert('<t t-if="o.vat">有統編</t>')
        metas = list(self._metas(res['tree']['main']))
        self.assertEqual(metas[0].get('expression'),
                         '"有統編" if (object.vat) else ""')

    def test_mixed_inline_content_becomes_condition_block(self):
        """文字＋多個取值混排收不成一句表達式 → 條件區塊（會自成一段）。

        多一個換行比「印出一段該藏起來的內容」好得多，而且會留待辦說明。
        """
        res = self._convert(
            '<t t-if="o.vat">統編：<span t-out="o.vat"/>'
            '（<span t-out="o.name"/>）</t>'
        )
        tables = list(self._tables(res['tree']['main']))
        self.assertEqual(len(tables), 1)
        self.assertEqual((tables[0].get('extension') or {}).get('dobtorBlock'),
                         'condition')
        conds = [m for m in self._metas(res['tree']['main'])
                 if m.get('source') == 'condition']
        self.assertEqual(conds[0].get('expression'), 'object.vat')
        self.assertTrue(any('行內節點' in n for n in res['notes']),
                        '版面會變，要留待辦：%s' % res['notes'])

    def test_condition_inside_loop_uses_line(self):
        res = self._convert(
            '<table><t t-foreach="o.child_ids" t-as="kid">'
            '<tr><td><span t-if="kid.phone" t-out="kid.phone"/></td></tr>'
            '</t></table>'
        )
        metas = [m for m in self._metas(res['tree']['main'])
                 if (m.get('expression') or '').startswith('line.phone')]
        self.assertTrue(metas, '%s' % list(self._metas(res['tree']['main'])))
        self.assertEqual(metas[0].get('source'), 'line')
        self.assertEqual(metas[0].get('expression'),
                         'line.phone if (line.phone) else ""')

    def test_block_tag_condition_still_becomes_block(self):
        """區塊標籤上的 t-if 行為不變——那條路早就有測試與使用者的範本在用。"""
        res = self._convert(
            '<div t-if="o.vat">統編：<span t-out="o.vat"/></div>')
        tables = list(self._tables(res['tree']['main']))
        self.assertEqual(len(tables), 1)
        self.assertEqual((tables[0].get('extension') or {}).get('dobtorBlock'),
                         'condition')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestConditionalContentNode(TestQwebConverterBase):
    """條件掛在「內容節點」自己身上時，要轉它自己、不是轉它的子節點。

    <table t-if="…"> 只轉子節點的話，thead/tbody 會被當成一般容器——
    tr 上的 t-foreach 永遠不會被看到，明細整批消失。
    實測：出貨單的兩張明細表就是 <table t-if> / <table t-elif> 的一對，
    轉出來連客戶名與品名都沒有。
    """

    def test_table_with_condition_keeps_its_foreach(self):
        res = self._convert(
            '<table t-if="o.active"><tbody>'
            '<t t-foreach="o.child_ids" t-as="kid">'
            '<tr><td><span t-out="kid.name"/></td></tr></t>'
            '</tbody></table>'
        )
        tables = list(self._tables(res['tree']['main']))
        self.assertEqual(len(tables), 2, '外層條件區塊 + 內層明細表')
        self.assertEqual((tables[0].get('extension') or {}).get('dobtorBlock'),
                         'condition')
        repeats = [m for m in self._metas(res['tree']['main'])
                   if m.get('source') == 'repeat']
        self.assertTrue(repeats, '明細的重複標記不可以消失')
        self.assertEqual(repeats[0].get('path'), 'child_ids')

    def test_table_pair_in_if_else_chain_keeps_both_foreach(self):
        """<table t-if> / <table t-elif> 的一對（出貨單就是這個形狀）。"""
        res = self._convert(
            '<table t-if="o.active"><tbody>'
            '<t t-foreach="o.child_ids" t-as="kid">'
            '<tr><td><span t-out="kid.name"/></td></tr></t></tbody></table>'
            '<table t-else=""><tbody>'
            '<t t-foreach="o.bank_ids" t-as="bank">'
            '<tr><td><span t-out="bank.acc_number"/></td></tr></t>'
            '</tbody></table>'
        )
        repeats = [m for m in self._metas(res['tree']['main'])
                   if m.get('source') == 'repeat']
        self.assertEqual({m.get('path') for m in repeats},
                         {'child_ids', 'bank_ids'},
                         '兩個分支的明細都要留著：%s' % repeats)

    def test_widget_survives_on_a_non_simple_expression(self):
        """算式型的取值不可以把 widget 掉掉。

        原生出貨單寫 t-out="o.move_ids[0].partner_id or o.partner_id"
        並帶 widget="contact"。widget 掉了之後單據上印的是
        "res.partner(7,)"——而且不會報錯。
        """
        res = self._convert(
            '<div t-out="o.parent_id or o.commercial_partner_id"'
            ' t-options=\'{"widget": "contact"}\'/>'
        )
        expression = list(self._metas(res['tree']['main']))[0].get(
            'expression') or ''
        self.assertIn('format_address(', expression)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestFilteredLambdaRewrite(TestQwebConverterBase):
    """filtered(lambda …) 是 Odoo 最常見的慣用寫法，而 Jinja 沒有 lambda。

    留著就是 TemplateSyntaxError，而條件／來源求值失敗的策略是「寧可多印」
    ——該濾掉的列會全部印出來。
    """

    def _source(self, value):
        res = self._convert(
            '<t t-set="rows" t-value="%s"/>'
            '<table><t t-foreach="rows" t-as="row">'
            '<tr><td><span t-out="row.name"/></td></tr></t></table>' % value
        )
        repeats = [m for m in self._metas(res['tree']['main'])
                   if m.get('source') == 'repeat']
        return (repeats[0].get('path')
                or repeats[0].get('sourceExpression') or ''), res

    def test_truthy_attribute(self):
        source, _res = self._source("o.child_ids.filtered(lambda x: x.phone)")
        self.assertIn("selectattr('phone')", source)

    def test_negated_attribute(self):
        source, _res = self._source(
            "o.child_ids.filtered(lambda x: not x.phone)")
        self.assertIn("rejectattr('phone')", source)

    def test_comparison(self):
        source, _res = self._source(
            "o.child_ids.filtered(lambda x: x.type == 'invoice')")
        self.assertIn("selectattr('type', '==', 'invoice')", source)

    def test_not_in_tuple(self):
        source, _res = self._source(
            "o.child_ids.filtered(lambda x: x.type not in ('invoice', 'other'))")
        self.assertIn("rejectattr('type', 'in', ('invoice', 'other'))", source)

    def test_rewritten_source_actually_resolves(self):
        """改寫完要真的取得到明細——語法對了不代表 Jinja 吃得下去。"""
        parent = self.env['res.partner'].create({'name': 'FL 母公司'})
        with_phone = self.env['res.partner'].create({
            'name': 'FL 有電話', 'parent_id': parent.id, 'phone': '02-1234'})
        self.env['res.partner'].create({
            'name': 'FL 沒電話', 'parent_id': parent.id})
        res = self._convert(
            '<t t-set="rows" t-value="o.child_ids.filtered(lambda x: x.phone)"/>'
            '<table><t t-foreach="rows" t-as="row">'
            '<tr><td><span t-out="row.name"/></td></tr></t></table>'
        )
        meta = [m for m in self._metas(res['tree']['main'])
                if m.get('source') == 'repeat'][0]
        lines = self.env['doc.render.mixin']._resolve_repeat_records(
            parent, meta)
        self.assertEqual(lines, [with_phone])

    def test_unrewritable_lambda_is_left_alone_with_a_note(self):
        """認不出來的形狀不要亂猜——留原樣並留待辦。"""
        res = self._convert(
            '<t t-set="rows" t-value="o.child_ids.filtered('
            'lambda x: x.phone and x.email)"/>'
            '<table><t t-foreach="rows" t-as="row">'
            '<tr><td><span t-out="row.name"/></td></tr></t></table>'
        )
        meta = [m for m in self._metas(res['tree']['main'])
                if m.get('source') == 'repeat'][0]
        self.assertTrue(meta.get('unbound'),
                        '改寫不了就要標成待確認：%s' % meta)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestSubTemplateInlining(TestQwebConverterBase):
    """t-call 的子範本要併進樹裡。

    原本整段丟掉並留一句「需要人工處理」。出貨單的明細列（序號版與彙總版）
    都在子範本裡，所以那張表只會剩表頭。
    """

    def _sub(self, body):
        key = 'dobtor_doc_editor.conv_sub_%d' % next(_SEQ)
        self.env['ir.ui.view'].create({
            'name': key, 'type': 'qweb', 'key': key,
            'arch': '<t t-name="%s">%s</t>' % (key, body),
        })
        return key

    def test_sub_template_rows_join_the_caller_table(self):
        sub = self._sub('<tr><td><span t-out="kid.name"/></td></tr>')
        res = self._convert(
            '<table><tbody><t t-foreach="o.child_ids" t-as="kid">'
            '<t t-call="%s"/></t></tbody></table>' % sub
        )
        tables = list(self._tables(res['tree']['main']))
        self.assertEqual(len(tables), 1, '子範本的列要併進同一張表格')
        repeats = [m for m in self._metas(res['tree']['main'])
                   if m.get('source') == 'repeat']
        self.assertEqual(repeats[0].get('path'), 'child_ids')
        lines = [m for m in self._metas(res['tree']['main'])
                 if m.get('source') == 'line']
        self.assertEqual([m.get('path') for m in lines], ['name'])

    def test_sub_template_cells_join_the_caller_row(self):
        """子範本的內容是 <td>（出貨單的序號明細就是這個形狀）。"""
        sub = self._sub('<td><span t-out="kid.name"/></td>'
                        '<td><span t-out="kid.phone"/></td>')
        res = self._convert(
            '<table><tbody><tr t-foreach="o.child_ids" t-as="kid">'
            '<t t-call="%s"/></tr></tbody></table>' % sub
        )
        table = list(self._tables(res['tree']['main']))[0]
        self.assertEqual(len(table['trList'][0]['tdList']), 2,
                         '兩個格子都要在同一列裡')

    def test_condition_on_the_call_node_is_kept(self):
        """t-call 節點自己的 t-if 不可以被吃掉。

        併入後那個節點就是「一個帶 t-if 的行內節點」，而它裡面只有一個取值
        ——走的是三元式那條路（等價、不多一個區塊容器），所以這裡驗的是
        條件有沒有進到表達式裡。
        """
        sub = self._sub('<p><span t-out="o.name"/></p>')
        # 呼叫端要自己有內容（這裡放一張表格）：_resolve_document_view 看到
        # 「只有外殼、沒有自己的 t-field／表格」時會往下追 t-call，把子範本
        # 當成真正的本文——那樣就驗不到呼叫端的條件了。
        res = self._convert(
            '<table><tr><td>x</td></tr></table>'
            '<div><t t-if="o.active" t-call="%s"/></div>' % sub
        )
        exprs = [(m.get('expression') or '')
                 for m in self._metas(res['tree']['main'])]
        self.assertTrue(
            any('if (object.active)' in e for e in exprs),
            '條件不見了：%s' % list(self._metas(res['tree']['main'])),
        )

    def test_missing_sub_template_is_reported(self):
        res = self._convert('<div><t t-call="nowhere.not_a_template"/></div>')
        self.assertTrue(any('找不到子範本' in n for n in res['notes']),
                        '%s' % res['notes'])

    def test_same_sub_template_twice_gets_separate_sources(self):
        """同一個子範本被呼叫兩次、參數不同。

        不給每個呼叫點自己的變數名的話，同一個名字被賦值多次會被當成
        QWeb 累加器而不內聯——那一整段的取值全部變成待確認。
        """
        sub = self._sub(
            '<tr t-foreach="rows" t-as="row">'
            '<td><span t-out="rows[row][\'x\']"/></td></tr>')
        res = self._convert(
            '<table><tbody>'
            '<t t-set="rows" t-value="o.child_ids"/>'
            '<t t-call="%(sub)s"/>'
            '<t t-set="rows" t-value="o.bank_ids"/>'
            '<t t-call="%(sub)s"/>'
            '</tbody></table>' % {'sub': sub}
        )
        repeats = [m for m in self._metas(res['tree']['main'])
                   if m.get('source') == 'repeat']
        sources = {(m.get('path') or m.get('sourceExpression') or '')
                   for m in repeats}
        self.assertEqual(len(sources), 2,
                         '兩個呼叫點要有各自的來源：%s' % sources)
        self.assertEqual({m.get('repeatId') for m in repeats}.__len__(), 2,
                         'repeatId 不可以撞——撞了會被當成同一組的列型，'
                         '而來源只取第一個')

    def test_source_subscript_collapses_to_line(self):
        """QWeb 對 dict 跑 t-foreach 是走鍵，取值寫 SOURCE[key][...]。"""
        sub = self._sub(
            '<tr t-foreach="rows" t-as="row">'
            '<td><span t-out="rows[row][\'name\']"/></td></tr>')
        res = self._convert(
            '<table><tbody><t t-set="rows" t-value="o.child_ids"/>'
            '<t t-call="%s"/></tbody></table>' % sub
        )
        lines = [m for m in self._metas(res['tree']['main'])
                 if m.get('source') == 'line']
        self.assertEqual(lines[0].get('expression'), "line['name']")


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRowWrapperConditions(TestQwebConverterBase):
    """列被 <t t-if=…> 包起來時的條件。

    _emit_table 直接走 .//tr 找列，中間那層 <t t-if> 的條件原本就消失了。
    實測後果：出貨單上「沒有包裝的品項」那一段的章節列，在有包裝的單據上
    也會印出來。
    """

    def test_wrapper_condition_becomes_row_condition(self):
        res = self._convert(
            '<table><tbody><t t-if="o.active">'
            '<tr><td><span t-out="o.name"/></td></tr>'
            '</t></tbody></table>'
        )
        conds = [m for m in self._metas(res['tree']['main'])
                 if m.get('source') == 'condition']
        self.assertEqual([m.get('expression') for m in conds],
                         ['object.active'])

    def test_wrapper_else_becomes_a_negation(self):
        res = self._convert(
            '<table><tbody>'
            '<t t-if="o.active"><tr><td>A</td></tr></t>'
            '<t t-else=""><tr><td>B</td></tr></t>'
            '</tbody></table>'
        )
        conds = [(m.get('expression') or '') for m in
                 self._metas(res['tree']['main'])
                 if m.get('source') == 'condition']
        self.assertIn('object.active', conds)
        self.assertIn('not (object.active)', conds,
                      't-else 的條件是「前面分支都不成立」：%s' % conds)

    def test_loop_index_is_mapped_to_loop_context(self):
        """原生的章節小計條件：line_last or lines[line_index+1].display_type…"""
        res = self._convert(
            '<table><tbody><t t-foreach="o.child_ids" t-as="kid">'
            '<t t-if="kid_last or o.child_ids[kid_index+1].phone">'
            '<tr><td><span t-out="kid.name"/></td></tr></t>'
            '</t></tbody></table>'
        )
        conds = [(m.get('expression') or '') for m in
                 self._metas(res['tree']['main'])
                 if m.get('source') == 'condition']
        self.assertTrue(conds)
        self.assertIn('loop_last', conds[0])
        self.assertIn('loop_index', conds[0])
        self.assertNotIn('kid_', conds[0], '迴圈位置變數要換成沙箱認識的名字')
