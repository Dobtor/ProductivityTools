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
