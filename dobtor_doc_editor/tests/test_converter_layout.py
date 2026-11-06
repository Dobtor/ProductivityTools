"""轉換器的版面：並排欄位、外框地址區塊、格子裡的巢狀區塊寬度。

原生報價單轉換後，資訊欄（你的參考／報價日期／到期日／銷售人員）變成直排
四個整頁寬的框；地址區塊左右各一份客戶地址、名稱印兩次；格子裡的條件區塊
在編輯器裡超出右邊距。這支釘住修正後的形狀。
"""

import base64
import io

from PIL import Image

from odoo.tests.common import TransactionCase, tagged

from .test_pill_helpers import _cell, _pill, _text
from .test_qweb_converter import TestQwebConverterBase


def _layout(cells, widths, flags):
    return {
        'type': 'table', 'value': '',
        'extension': {'dobtorBlock': 'layout', 'reflowCols': list(flags)},
        'borderType': 'empty',
        'colgroup': [{'width': w} for w in widths],
        'trList': [{'tdList': list(cells)}],
    }


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestConverterLayoutBase(TestQwebConverterBase):

    def _kind(self, el):
        return (el.get('extension') or {}).get('dobtorBlock')

    def _cell_widths(self, table):
        return [c['width'] for c in table.get('colgroup') or []]

    def _assert_fits(self, table, limit):
        """table 和它裡面的每一層巢狀表格都不超過可用寬度。"""
        self.assertLessEqual(sum(self._cell_widths(table)), limit,
                             '表格比所在的格子寬：%s' % self._cell_widths(table))
        widths = self._cell_widths(table)
        for row in table.get('trList') or []:
            col = 0
            for cell in row.get('tdList') or []:
                span = cell.get('colspan') or 1
                cell_w = sum(widths[col:col + span])
                col += span
                for el in cell.get('value') or []:
                    if el.get('type') == 'table':
                        self._assert_fits(el, cell_w)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestGridRow(TestConverterLayoutBase):
    """div.row ＞ div.col… → 並排的無框表格。"""

    ROW = (
        '<div class="row">'
        '<div class="col" t-if="o.ref"><strong>參考</strong>'
        '<div t-field="o.ref"/></div>'
        '<div class="col"><strong>名稱</strong><div t-field="o.name"/></div>'
        '<div class="col-3"><strong>電話</strong><div t-field="o.phone"/></div>'
        '</div>'
    )

    def test_columns_are_side_by_side(self):
        res = self._convert(self.ROW)
        table = res['tree']['main'][0]
        self.assertEqual(table.get('type'), 'table')
        self.assertEqual(self._kind(table), 'layout')
        self.assertEqual(len(table['trList']), 1, '應該是一列、不是直排')
        self.assertEqual(len(table['trList'][0]['tdList']), 3)

    def test_widths_follow_bootstrap_columns(self):
        res = self._convert(self.ROW)
        table = res['tree']['main'][0]
        widths = self._cell_widths(table)
        self.assertEqual(sum(widths), 602)
        # col-3 是 3/12；兩個 col 平分剩下的 9/12
        self.assertAlmostEqual(widths[2], 602 * 3 / 12, delta=3)
        self.assertEqual(widths[0], widths[1])
        self.assertEqual(table['extension']['reflowCols'], [True, True, False])

    def test_column_condition_stays_inside_its_cell(self):
        res = self._convert(self.ROW)
        table = res['tree']['main'][0]
        first = table['trList'][0]['tdList'][0]['value']
        blocks = [el for el in first if el.get('type') == 'table']
        self.assertEqual(len(blocks), 1)
        self.assertEqual(self._kind(blocks[0]), 'condition')
        self._assert_fits(table, 602)

    def test_label_and_value_are_separate_paragraphs(self):
        """<strong>標題</strong><div t-field> 是「標題在上、值在下」。"""
        res = self._convert(self.ROW)
        cell = res['tree']['main'][0]['trList'][0]['tdList'][1]['value']
        values = [el.get('value') for el in cell]
        label_at = values.index('名稱')
        pill_at = next(i for i, el in enumerate(cell)
                       if (el.get('extension') or {}).get('dobtorField'))
        self.assertIn('\n', values[label_at + 1:pill_at],
                      '標題跟值擠在同一行：%s' % values)

    def test_row_with_other_children_is_left_alone(self):
        res = self._convert(
            '<div class="row"><div class="col">甲</div><span>乙</span></div>')
        self.assertFalse(
            [t for t in self._tables(res['tree']['main'])
             if self._kind(t) == 'layout'],
            '混了非欄位的子節點時不該猜成並排')

    def test_row_condition_wraps_the_whole_row(self):
        res = self._convert(
            '<div class="row" t-if="o.ref">'
            '<div class="col">甲</div><div class="col">乙</div></div>')
        outer = res['tree']['main'][0]
        self.assertEqual(self._kind(outer), 'condition')
        inner = [el for el in outer['trList'][0]['tdList'][0]['value']
                 if el.get('type') == 'table']
        self.assertEqual(self._kind(inner[0]), 'layout')
        self._assert_fits(outer, 602)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestInlineValueParagraph(TestConverterLayoutBase):

    def test_inline_value_stays_on_the_same_line(self):
        res = self._convert('<p><span>名稱</span> <span t-field="o.name"/></p>')
        values = [el.get('value') for el in res['tree']['main']]
        label_at = values.index('名稱')
        self.assertNotIn('\n', values[label_at:label_at + 3])

    def test_block_value_after_row_marker_has_no_blank_line(self):
        """格子開頭的標記（重複列）印出來會拿掉，值不可以被擠到第二行。"""
        res = self._convert(
            '<table><tr t-foreach="o.child_ids" t-as="c">'
            '<td><div t-field="c.name"/></td></tr></table>')
        table = next(self._tables(res['tree']['main']))
        cell = table['trList'][0]['tdList'][0]['value']
        first_value = next(
            i for i, el in enumerate(cell)
            if ((el.get('extension') or {}).get('dobtorField') or {})
            .get('source') == 'line')
        self.assertNotIn('\n', [el.get('value') for el in cell[:first_value]])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestNestedBlockWidth(TestConverterLayoutBase):
    """格子與條件區塊裡的巢狀表格，寬度跟著所在的格子。"""

    def test_condition_inside_cell_fits_the_cell(self):
        res = self._convert(
            '<table><tr>'
            # 兩個取值才收不成一句（一個取值的會串成三元式藥丸，不包區塊）
            '<td style="width: 20%"><span t-field="o.name"/>'
            '<span t-if="o.ref">(<span t-field="o.ref"/> <span t-field="o.phone"/>)'
            '</span></td>'
            '<td>乙</td></tr></table>')
        table = next(self._tables(res['tree']['main']))
        nested = [el for el in table['trList'][0]['tdList'][0]['value']
                  if el.get('type') == 'table']
        self.assertTrue(nested, '格子裡應該有一個條件區塊')
        self._assert_fits(table, 602)

    def test_table_inside_condition_fits_the_block(self):
        res = self._convert(
            '<table t-if="o.ref"><tr><td>甲</td><td>乙</td></tr></table>')
        outer = res['tree']['main'][0]
        self.assertEqual(self._kind(outer), 'condition')
        self._assert_fits(outer, 602)

    def test_nested_if_else_fits(self):
        res = self._convert(
            '<div t-if="o.ref"><table><tr><td>甲</td></tr></table></div>'
            '<div t-elif="o.phone"><table><tr><td>乙</td></tr></table></div>'
            '<div t-else=""><table><tr><td>丙</td></tr></table></div>')
        self._assert_fits(res['tree']['main'][0], 602)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestAttfClassStaticPart(TestConverterLayoutBase):
    """t-attf-class 裡寫死的 class 照轉（原生的數量欄、稅別欄靠右）。"""

    def test_static_text_end_aligns_right(self):
        res = self._convert(
            '<table><tr><td t-attf-class="text-end '
            '{{ \'text-nowrap\' if o.ref else \'\' }}">'
            '<span t-field="o.name"/></td></tr></table>')
        table = next(self._tables(res['tree']['main']))
        cell = table['trList'][0]['tdList'][0]['value']
        self.assertIn('right', [el.get('rowFlex') for el in cell])

    def test_alignment_reaches_text_before_a_block(self):
        """數量欄：值後面接著包裝數量的條件區塊，前面那段也要靠右。"""
        res = self._convert(
            '<table><tr><td class="text-end"><span t-field="o.name"/>'
            '<span t-if="o.ref">(<span t-field="o.ref"/>)</span></td>'
            '</tr></table>')
        table = next(self._tables(res['tree']['main']))
        cell = table['trList'][0]['tdList'][0]['value']
        first_pill = next(el for el in cell
                          if (el.get('extension') or {}).get('dobtorField'))
        self.assertEqual(first_pill.get('rowFlex'), 'right')

    def test_layout_only_dynamic_part_is_not_reported(self):
        res = self._convert(
            '<div t-attf-class="text-end {{ \'text-nowrap\' if o.ref else \'\' }}">'
            '甲</div>'
            '<div t-attf-class="#{\'col-6\' if o.ref else \'col-sm-7\'} ms-auto">'
            '乙</div>')
        self.assertFalse([n for n in res['notes'] if '動態 class' in n],
                         '%s' % res['notes'])

    def test_visible_dynamic_part_is_still_reported(self):
        res = self._convert(
            '<div t-attf-class="{{ \'fw-bold\' if o.active else \'\' }}">甲</div>')
        self.assertTrue([n for n in res['notes'] if '動態 class' in n],
                        '%s' % res['notes'])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestAddressBlock(TestConverterLayoutBase):
    """外框的 address／information_block。"""

    ARCH = (
        '<t t-call="web.external_layout">'
        '<t t-set="address"><div t-field="o.parent_id"'
        ' t-options=\'{"widget": "contact", "fields": ["address", "name"]}\'/></t>'
        '<t t-if="o.parent_id != o.commercial_partner_id">'
        '<t t-set="information_block"><strong>寄送地址</strong>'
        '<div t-field="o.commercial_partner_id"'
        ' t-options=\'{"widget": "contact", "fields": ["address", "name"]}\'/>'
        '</t></t>'
        '<div class="page"><p>本文</p></div>'
        '</t>'
    )

    def test_information_block_keeps_its_condition(self):
        res = self._convert(self.ARCH)
        table = res['tree']['main'][0]
        left = table['trList'][0]['tdList'][0]['value']
        blocks = [el for el in left if el.get('type') == 'table']
        self.assertEqual(len(blocks), 1, '左格應該包在條件裡：%s' % left)
        self.assertEqual(self._kind(blocks[0]), 'condition')
        cond = next(m for m in self._metas([blocks[0]])
                    if m.get('source') == 'condition')
        self.assertIn('object.parent_id != object.commercial_partner_id',
                      cond.get('expression') or '')
        self.assertFalse([n for n in res['notes'] if '已取第一份' in n],
                         '%s' % res['notes'])

    def test_address_column_is_five_twelfths_and_left_aligned(self):
        """有沒有 information_block，原生的 address 都在右邊 5/12、文字靠左。"""
        res = self._convert(self.ARCH)
        table = res['tree']['main'][0]
        widths = self._cell_widths(table)
        self.assertAlmostEqual(widths[1], 602 * 5 / 12, delta=2)
        right = table['trList'][0]['tdList'][1]['value']
        self.assertNotIn('right', [el.get('rowFlex') for el in right])
        self._assert_fits(table, 602)

    def test_still_asks_for_the_frame(self):
        """拿掉空殼時不可以連外框呼叫一起拿掉——那會讓轉出來的範本沒有外框。"""
        res = self._convert(self.ARCH)
        self.assertTrue(res['needs_layout'])

    def test_no_empty_shell_pill_left_behind(self):
        """區塊搬走後只剩空殼的 <t t-if> 不可以變成一顆「"" if …」藥丸。"""
        res = self._convert(self.ARCH)
        for meta in self._metas(res['tree']['main'][1:]):
            self.assertFalse(
                (meta.get('expression') or '').startswith('""'),
                '多了一顆空殼藥丸：%s' % meta)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestFormatAddressNoDuplicateCompany(TransactionCase):
    """帶名稱的地址不可以把公司名稱印兩次（原生是 without_company=True）。"""

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.company = self.env['res.partner'].create({
            'name': '甲乙測試股份有限公司', 'is_company': True,
            'street': '信義路五段 7 號', 'city': '台北市', 'zip': '110',
        })
        self.person = self.env['res.partner'].create({
            'name': '王測試', 'parent_id': self.company.id, 'type': 'contact',
        })

    def _render(self, expression, record):
        env_j = self.Mixin._get_sandbox_env(record)
        return env_j.from_string('{{ %s }}' % expression).render(
            object=record, user=self.env.user)

    def test_company_name_once(self):
        out = self._render('format_address(object, with_name=True)', self.company)
        self.assertEqual(out.count('甲乙測試股份有限公司'), 1, out)
        self.assertIn('信義路五段 7 號', out)

    def test_contact_under_company_name_once(self):
        out = self._render('format_address(object, with_name=True)', self.person)
        self.assertEqual(out.count('甲乙測試股份有限公司'), 1, out)
        self.assertIn('王測試', out)

    def test_without_name_keeps_company_line(self):
        """不帶名稱時照舊：地址第一行就是公司名稱，收件人才看得出是誰。"""
        out = self._render('format_address(object)', self.person)
        self.assertIn('甲乙測試股份有限公司', out)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestReflowLayoutColumns(TransactionCase):
    """並排區塊整欄空白時拿掉，寬度分給彈性欄。"""

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '並排測試'})

    def _widths(self, table):
        return [c['width'] for c in table['colgroup']]

    def test_blank_flex_column_is_dropped_and_width_shared(self):
        table = _layout([_cell(_text('')), _cell(_text('乙')), _cell(_text('丙'))],
                        [200, 200, 200], [True, True, False])
        tree = {'main': [table, _text('\n')]}
        self.Mixin._reflow_layout_columns(tree)
        self.assertEqual(len(table['trList'][0]['tdList']), 2)
        # 空出來的 200 全給唯一的彈性欄，固定欄不放大
        self.assertEqual(self._widths(table), [400, 200])
        self.assertEqual(table['extension']['reflowCols'], [True, False])

    def test_fixed_columns_do_not_grow(self):
        """全是固定寬度欄（出貨單的 col-3）：其他欄往左靠、空欄搬到最後。

        不能直接拿掉：PDF 的欄寬是照總寬的比例印的，拿掉一欄剩下的會被
        等比放大（三欄變三等分，「Customer Reference」跑到右邊）。
        """
        table = _layout([_cell(_text('甲')), _cell(_text('')), _cell(_text('丙'))],
                        [150, 150, 150], [False, False, False])
        tree = {'main': [table, _text('\n')]}
        self.Mixin._reflow_layout_columns(tree)
        self.assertEqual(self._widths(table), [150, 150, 150])
        values = [[e.get('value') for e in c['value']]
                  for c in table['trList'][0]['tdList']]
        self.assertEqual([v[0] for v in values], ['甲', '丙', ''])

    def test_all_blank_drops_the_table(self):
        table = _layout([_cell(_text('')), _cell(_text(' '))],
                        [300, 300], [True, True])
        tree = {'main': [_text('甲'), table, _text('\n'), _text('乙')]}
        self.Mixin._reflow_layout_columns(tree)
        self.assertFalse([el for el in tree['main'] if el.get('type') == 'table'])

    def test_user_table_is_left_alone(self):
        """使用者自己畫的表格空著一格是刻意的。"""
        table = {
            'type': 'table', 'value': '', 'colgroup': [{'width': 300}] * 2,
            'trList': [{'tdList': [_cell(_text('')), _cell(_text('乙'))]}],
        }
        tree = {'main': [table, _text('\n')]}
        self.Mixin._reflow_layout_columns(tree)
        self.assertEqual(len(table['trList'][0]['tdList']), 2)

    def test_false_condition_in_cell_reflows_in_snapshot(self):
        """格子裡的條件不成立 → 條件區塊拿掉 → 那一欄空了 → 整欄拿掉。"""
        cond = {
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'condition'},
            'borderType': 'dash', 'colgroup': [{'width': 180}],
            'trList': [{'tdList': [_cell(
                _pill('條件', source='condition', expression='False'),
                _text('不該出現'))]}],
        }
        table = _layout([_cell(cond), _cell(_text('乙'))], [300, 300],
                        [True, True])
        tree = {'main': [table, _text('\n')]}
        self.Mixin._snapshot_content_json(tree, self.partner)
        tables = [el for el in tree['main'] if el.get('type') == 'table']
        self.assertEqual(len(tables[0]['trList'][0]['tdList']), 1)
        self.assertEqual(self._widths(tables[0]), [600])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestSplitMultilinePills(TransactionCase):
    """「顯示實際值」：多行的值拆成一行一顆，編輯器才畫得出多行。"""

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']

    def test_multiline_value_becomes_rows(self):
        pill = _pill('地址', source='record', path='contact_address')
        pill['rowFlex'] = 'left'
        pill['value'] = '甲公司\n信義路\n\n台北市'
        tree = {'main': [pill, _text('\n')]}
        self.Mixin._preview_display_pills(tree)
        main = tree['main']
        self.assertEqual([el.get('value') for el in main],
                         ['甲公司', '\n', '信義路', '\n', '台北市', '\n'])
        self.assertEqual(main[1].get('rowFlex'), 'left', '換行要帶原本段落的對齊')
        self.assertTrue(all(main[i].get('type') == 'label' for i in (0, 2, 4)))

    def test_single_line_is_untouched(self):
        one = _pill('名稱', source='record', path='name')
        one['value'] = '甲'
        tree = {'main': [one]}
        self.Mixin._preview_display_pills(tree)
        self.assertEqual(tree['main'], [one])

    def test_image_value_becomes_an_image(self):
        """簽名在預覽裡不可以印成一長串 data:image/png;base64,…"""
        buf = io.BytesIO()
        Image.new('RGB', (900, 300), 'white').save(buf, 'PNG')
        uri = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
        image = _pill('圖：signature', source='image', path='signature')
        image['value'] = uri
        tree = {'main': [image]}
        self.Mixin._preview_display_pills(tree)
        el = tree['main'][0]
        self.assertEqual(el.get('type'), 'image')
        self.assertEqual(el.get('value'), uri)
        # 太寬的等比例縮小
        self.assertEqual((el['width'], el['height']), (600, 200))

    def test_empty_image_stays_a_pill(self):
        image = _pill('圖：signature', source='image', path='signature')
        image['value'] = ''
        tree = {'main': [image]}
        self.Mixin._preview_display_pills(tree)
        self.assertEqual(tree['main'][0].get('type'), 'label')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestCellCondition(TestConverterLayoutBase):
    """只有某一格帶 t-if（原生訂金列不印金額）。"""

    def test_single_value_cell_becomes_ternary_pill(self):
        res = self._convert(
            '<table><tr t-foreach="o.child_ids" t-as="c">'
            '<td><span t-field="c.name"/></td>'
            '<td t-if="not c.is_company" class="text-end">'
            '<span t-field="c.ref"/></td></tr></table>')
        table = next(self._tables(res['tree']['main']))
        cell = table['trList'][0]['tdList'][1]['value']
        self.assertFalse([el for el in cell if el.get('type') == 'table'],
                         '單一個值不必包條件區塊（每列會變高）')
        expr = next(m.get('expression') for m in self._metas(cell)
                    if m.get('source') == 'line')
        self.assertIn('if (not line.is_company) else ""', expr)
        self.assertIn('right', [el.get('rowFlex') for el in cell])

    def test_ternary_label_is_the_field_not_the_sample_value(self):
        """<span t-field="…">27.00</span> 的 27.00 是範例值，不可當標籤。"""
        res = self._convert(
            '<table><tr t-foreach="o.child_ids" t-as="c">'
            '<td t-if="not c.is_company"><span t-field="c.ref">27.00</span></td>'
            '</tr></table>')
        labels = [m.get('labelText') for m in self._metas(res['tree']['main'])
                  if m.get('source') == 'line']
        # 標籤是欄位名稱（不是技術名稱 ref——那在窄欄裡比值還長）
        self.assertIn(self.env['ir.model.fields']._get(
            'res.partner', 'ref').field_description, labels)
        self.assertNotIn('27.00', labels)

    def test_complex_cell_becomes_condition_block_that_fits(self):
        res = self._convert(
            '<table><tr><td style="width: 30%">甲</td>'
            '<td t-if="o.ref"><span t-field="o.ref"/><br/>'
            '<span t-field="o.name"/></td></tr></table>')
        table = next(self._tables(res['tree']['main']))
        cell = table['trList'][0]['tdList'][1]['value']
        blocks = [el for el in cell if el.get('type') == 'table']
        self.assertEqual(self._kind(blocks[0]), 'condition')
        self._assert_fits(table, 602)

    def test_same_condition_on_header_td_is_a_column(self):
        """表頭用 <td> 寫的欄條件（原生選購商品表的「折扣%」）。"""
        res = self._convert(
            '<table>'
            '<tr><td>品名</td><td t-if="o.ref">折扣</td></tr>'
            '<tr t-foreach="o.child_ids" t-as="c"><td><span t-field="c.name"/></td>'
            '<td t-if="o.ref"><span t-field="c.ref"/></td></tr>'
            '</table>')
        sources = [m.get('source') for m in self._metas(res['tree']['main'])]
        self.assertEqual(sources.count('column'), 2, sources)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestInlineStyleOnPills(TestConverterLayoutBase):

    def test_strong_makes_branch_pill_bold(self):
        res = self._convert(
            '<p><strong><t t-if="o.ref">甲</t><t t-else="">乙</t></strong></p>')
        pill = next(el for el in res['tree']['main']
                    if (el.get('extension') or {}).get('dobtorField'))
        self.assertTrue(pill.get('bold'), pill)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestLayoutColumnWidthsInHtml(TransactionCase):
    """轉換器排的並排區塊在 PDF 照編輯器的欄寬；其他表格維持自動排版。"""

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']

    def test_fixed_layout_emits_colgroup(self):
        table = _layout([_cell(_text('')), _cell(_text('地址'))], [350, 250],
                        [False, False])
        table['extension']['fixedCols'] = True
        html = self.Mixin._content_json_to_html({'main': [table]})
        self.assertIn('doc-layout', html)
        self.assertIn('<col style="width:58.33%"/>', html)

    def test_converted_data_table_keeps_widths_and_borders(self):
        """轉換出來的明細表照估好的欄寬印，但它是真的表格，框線要留著。"""
        table = {
            'type': 'table', 'value': '',
            'extension': {'fixedCols': True},
            'colgroup': [{'width': 400}, {'width': 200}],
            'trList': [{'tdList': [_cell(_text('品名')), _cell(_text('金額'))]}],
        }
        html = self.Mixin._content_json_to_html({'main': [table]})
        self.assertIn('<table class="doc-layout">', html)
        self.assertIn('<col style="width:66.67%"/>', html)
        self.assertNotIn('doc-block', html)

    def test_other_tables_stay_automatic(self):
        frame_header = {
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'layout'},
            'colgroup': [{'width': 210}, {'width': 392}],
            'trList': [{'tdList': [_cell(_text('logo')), _cell(_text('公司'))]}],
        }
        html = self.Mixin._content_json_to_html({'main': [frame_header]})
        self.assertNotIn('<colgroup>', html)
        self.assertNotIn('doc-layout', html)
