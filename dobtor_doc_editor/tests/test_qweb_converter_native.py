"""把原生報表實際轉一遍再渲染——轉換器的整合測試。

為什麼要有：規則的單元測試（test_qweb_converter.py）用的是自己寫的最小
arch，擋得住語法層面的回歸，但擋不住「規則互相影響」那一類。這一輪實際
踩到的就是後者——把白名單改寫接上去之後，明細來源的判斷失效
（'object.' in mapped 對不上 report_helper(object, '…')），
銷售訂單的品名與章節整批消失，而單元測試全綠。

所以這裡不去斷言「幾顆藥丸、幾條待辦」那種會隨 Odoo 小版本變動的數字，
只斷言兩件不該變的事：
  1. 試算失敗必須是 0——轉出來的每個表達式都要算得出來。
  2. 單據上該出現的字要出現，標記文字不可殘留。

sale / account 沒裝就跳過（本模組不相依它們）。
"""

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class NativeReportCase(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Conv = self.env['doc.qweb.converter']

    def _need(self, model, report_xmlid):
        if model not in self.env:
            self.skipTest('%s 未安裝，原生報表轉換未驗證' % model.split('.')[0])
        report = self.env.ref(report_xmlid, raise_if_not_found=False)
        if not report:
            self.skipTest('找不到報表 %s' % report_xmlid)
        return report

    def _convert_and_render(self, report, record):
        res = self.Conv.convert_report(report, validate_with=record)
        self.assertTrue(res['content_json'], '轉換沒有產出內容')
        template = self.env['doc.template'].create({
            'name': 'NAT %s' % report.id,
            'role': 'content',
            'model_id': self.env['ir.model']._get(report.model).id,
            'content_json': res['content_json'],
        })
        binding = self.env['doc.report'].create({
            'name': 'NAT 綁定 %s' % report.id,
            'template_id': template.id,
            'report_id': report.id,
        })
        html, _footer = binding._build_report_html(record)
        return res, html

    def _failures(self, res):
        return [n for n in res['notes'] if n.startswith('試算失敗')]

    def _assert_only_known_failures(self, res, allowed=()):
        """試算失敗清單只能剩下已知、說明過的那幾項。"""
        unexpected = [n for n in self._failures(res)
                      if not any(token in n for token in allowed)]
        self.assertFalse(unexpected, '出現沒預期到的試算失敗：%s' % unexpected)

    def _assert_no_leftovers(self, html):
        """標記文字殘留＝某個機制沒跑到，而使用者只會看到單據上多幾個怪字。"""
        for token in ('明細 ×', '列型 ×', '〔分組標題〕', '〔分組小計〕',
                      '待確認', '條件', '欄條件', '列條件'):
            self.assertNotIn(token, html, '標記文字殘留：%s' % token)


class TestNativeSaleOrderReport(NativeReportCase):

    def _order(self):
        partner = self.env['res.partner'].create({'name': 'NAT 銷售客戶'})
        product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        if not product:
            product = self.env['product.product'].create({'name': 'NAT 品項'})
        return self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [
                (0, 0, {'name': 'NAT 甲區', 'display_type': 'line_section'}),
                (0, 0, {'product_id': product.id, 'name': 'NAT A 品',
                        'product_uom_qty': 2, 'price_unit': 100,
                        'discount': 10}),
                (0, 0, {'name': 'NAT 這是備註',
                        'display_type': 'line_note'}),
                (0, 0, {'product_id': product.id, 'name': 'NAT B 品',
                        'product_uom_qty': 3, 'price_unit': 100}),
            ],
        })

    def test_sale_order_report_converts_and_renders(self):
        report = self._need('sale.order', 'sale.action_report_saleorder')
        order = self._order()
        res, html = self._convert_and_render(report, order)
        self.assertEqual(
            res['stats']['validate_failed'], 0,
            '有表達式算不出來：%s'
            % [n for n in res['notes'] if n.startswith('試算失敗')],
        )
        for probe in ('NAT 銷售客戶', 'NAT A 品', 'NAT B 品',
                      'NAT 甲區', 'NAT 這是備註'):
            self.assertIn(probe, html, '單據上少了「%s」' % probe)
        self._assert_no_leftovers(html)

    def test_detail_table_has_one_row_per_line(self):
        """明細來源壞掉時最明顯的症狀就是列數不對（整批消失或只剩一列）。"""
        report = self._need('sale.order', 'sale.action_report_saleorder')
        order = self._order()
        _res, html = self._convert_and_render(report, order)
        # 四行明細（章節／商品／備註／商品）都要有自己的一列
        self.assertEqual(html.count('NAT A 品'), 1)
        self.assertEqual(html.count('NAT B 品'), 1)


class TestNativeInvoiceReport(NativeReportCase):
    """發票用草稿單就夠——不必過帳，所以不依賴會計科目設定。"""

    def _invoice(self, term=None):
        partner = self.env['res.partner'].create({'name': 'NAT 發票客戶'})
        product = self.env['product.product'].search([], limit=1)
        line = {'name': 'NAT 發票品', 'quantity': 2, 'price_unit': 500}
        if product:
            line['product_id'] = product.id
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'invoice_payment_term_id': term.id if term else False,
            'invoice_line_ids': [
                (0, 0, {'name': 'NAT 乙區', 'display_type': 'line_section'}),
                (0, 0, line),
                (0, 0, {'name': 'NAT 發票備註',
                        'display_type': 'line_note'}),
            ],
        })

    def test_invoice_report_converts_and_renders(self):
        report = self._need('account.move', 'account.account_invoices')
        move = self._invoice()
        res, html = self._convert_and_render(report, move)
        self.assertEqual(
            res['stats']['validate_failed'], 0,
            '有表達式算不出來：%s'
            % [n for n in res['notes'] if n.startswith('試算失敗')],
        )
        for probe in ('NAT 發票客戶', 'NAT 發票品', 'NAT 乙區',
                      'NAT 發票備註'):
            self.assertIn(probe, html, '單據上少了「%s」' % probe)
        self._assert_no_leftovers(html)

    def test_installment_list_is_printed(self):
        """分期清單是非表格 t-foreach（<div> 清單），要轉成單欄重複表格。

        payment_term_details 是回傳 list of dict 的計算欄位，重複來源原本
        只收 recordset——那時整段不印而且沒有任何訊息。
        """
        report = self._need('account.move', 'account.account_invoices')
        term = self.env['account.payment.term'].create({
            'name': 'NAT 兩期', 'display_on_invoice': True,
            'line_ids': [
                (0, 0, {'value': 'percent', 'value_amount': 50,
                        'nb_days': 0}),
                (0, 0, {'value': 'percent', 'value_amount': 50,
                        'nb_days': 30}),
            ],
        })
        move = self._invoice(term)
        self.assertEqual(len(move.payment_term_details or []), 2,
                         '樣本資料不對，驗不到分期清單')
        _res, html = self._convert_and_render(report, move)
        # 兩期各一列：原生的字樣是「N - Installment of …」
        self.assertEqual(html.count('Installment'), 2,
                         '分期清單應該每期一列')

    def test_early_payment_discount_block(self):
        """提前付款折扣用到兩個底線方法（白名單）與一個底線條件。"""
        report = self._need('account.move', 'account.account_invoices')
        term = self.env['account.payment.term'].create({
            'name': 'NAT 折扣', 'display_on_invoice': True,
            'early_discount': True, 'discount_percentage': 2,
            'discount_days': 7,
            'line_ids': [(0, 0, {'value': 'percent', 'value_amount': 100,
                                 'nb_days': 30})],
        })
        move = self._invoice(term)
        _res, html = self._convert_and_render(report, move)
        self.assertIn('due if paid before', html)
        # 1000 的 2% 折扣 → 980；金額算不出來時這段只會剩下文字
        self.assertIn('980', html, '折扣金額沒算出來（白名單沒生效？）')

    def test_discount_block_hidden_without_early_discount(self):
        """沒有提前付款折扣的單據不該印那一段。

        它的條件是 o._is_eligible_for_early_payment_discount(…)——掛在
        <t> 上的單獨 t-if。那種條件原本被整個忽略，於是每張單都印出一句
        「due if paid before」加一個日期。

        樣本刻意用「有付款條件但沒有提前折扣」：完全沒有付款條件時，那一段
        的藥丸全部求值為空，會被段落收合規則順手清掉——測試就會因為錯誤的
        理由通過。_get_last_discount_date_formatted() 不看 early_discount，
        所以有付款條件時日期照算，段落留下來。
        """
        report = self._need('account.move', 'account.account_invoices')
        term = self.env['account.payment.term'].create({
            'name': 'NAT 無折扣兩期', 'display_on_invoice': True,
            'line_ids': [
                (0, 0, {'value': 'percent', 'value_amount': 50,
                        'nb_days': 0}),
                (0, 0, {'value': 'percent', 'value_amount': 50,
                        'nb_days': 30}),
            ],
        })
        move = self._invoice(term)
        self.assertFalse(
            move._is_eligible_for_early_payment_discount(
                move.currency_id, move.invoice_date),
            '樣本資料不對：這張單其實符合提前付款折扣',
        )
        _res, html = self._convert_and_render(report, move)
        self.assertNotIn('due if paid before', html)


class TestNativeDeliveryReport(NativeReportCase):
    """出貨單——這張是整組樣本裡最難的一張。

    它的明細表是 <table t-if> / <table t-elif> 的一對（條件掛在表格自己
    身上）、來源是 filtered(lambda …)、收件人用 widget="contact" 配一條
    or 算式。這三件各自壞過一次，而症狀都一樣：單據上什麼都沒有。
    """

    def _picking(self):
        partner = self.env['res.partner'].create({
            'name': 'NAT 出貨客戶', 'street': '松仁路 100 號'})
        product = self.env['product.product'].create({
            'name': 'NAT 出貨品', 'is_storable': True})
        picking_type = self.env['stock.picking.type'].search(
            [('code', '=', 'outgoing')], limit=1)
        if not picking_type:
            self.skipTest('沒有出貨作業類型，無法建樣本')
        src = (picking_type.default_location_src_id.id
               or self.env.ref('stock.stock_location_stock').id)
        dest = (picking_type.default_location_dest_id.id
                or self.env.ref('stock.stock_location_customers').id)
        picking = self.env['stock.picking'].create({
            'partner_id': partner.id,
            'picking_type_id': picking_type.id,
            'location_id': src, 'location_dest_id': dest,
            'move_ids': [(0, 0, {
                'name': 'NAT 異動', 'product_id': product.id,
                'product_uom_qty': 5,
                'location_id': src, 'location_dest_id': dest,
            })],
        })
        picking.action_confirm()
        return picking

    def test_delivery_report_converts_and_renders(self):
        report = self._need('stock.picking', 'stock.action_report_delivery')
        picking = self._picking()
        res, html = self._convert_and_render(report, picking)
        self.assertEqual(res['stats']['validate_failed'], 0,
                         '有表達式算不出來：%s' % self._failures(res))
        for probe in (picking.name, 'NAT 出貨客戶', 'NAT 出貨品'):
            self.assertIn(probe, html, '單據上少了「%s」' % probe)
        self._assert_no_leftovers(html)

    def test_recipient_is_a_name_not_a_recordset_repr(self):
        """收件人是 widget="contact" 配一條 or 算式。

        widget 在「算式型取值」那條路上掉掉的話，單據上印的是
        "res.partner(7,)"——而且不會報錯。
        """
        report = self._need('stock.picking', 'stock.action_report_delivery')
        picking = self._picking()
        _res, html = self._convert_and_render(report, picking)
        self.assertNotIn('res.partner(', html)
        self.assertIn('松仁路 100 號', html, '地址沒印出來')

    def test_detail_table_survives_the_condition_on_the_table_itself(self):
        """條件掛在 <table> 自己身上時，表格與它的 t-foreach 都要留著。"""
        report = self._need('stock.picking', 'stock.action_report_delivery')
        picking = self._picking()
        res, _html = self._convert_and_render(report, picking)
        self.assertGreaterEqual(
            res['stats']['repeat'], 1,
            '一個重複列都沒有＝明細表被條件分支吃掉了')


class TestNativePurchaseReport(NativeReportCase):

    def _purchase(self):
        partner = self.env['res.partner'].create({'name': 'NAT 供應商'})
        product = self.env['product.product'].search(
            [('purchase_ok', '=', True)], limit=1)
        if not product:
            product = self.env['product.product'].create(
                {'name': 'NAT 採購品', 'purchase_ok': True})
        return self.env['purchase.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id, 'name': 'NAT 採購明細',
                'product_qty': 4, 'price_unit': 250,
                'date_planned': fields.Datetime.now(),
            })],
        })

    def test_purchase_order_report_converts_and_renders(self):
        report = self._need('purchase.order',
                            'purchase.action_report_purchase_order')
        order = self._purchase()
        res, html = self._convert_and_render(report, order)
        # 已知且已說明的一項：any(u._is_portal() for u in …) 是 Python 生成式，
        # Jinja 沒有，而裡面是方法呼叫所以改寫不了（待辦有寫清楚）。
        self._assert_only_known_failures(res, allowed=('for u in',))
        for probe in ('NAT 供應商', 'NAT 採購明細'):
            self.assertIn(probe, html, '單據上少了「%s」' % probe)
        self._assert_no_leftovers(html)

    def test_generator_expression_is_explained(self):
        """改寫不了的生成式要留一條說得清楚的待辦，不是只有語法錯誤。"""
        report = self._need('purchase.order',
                            'purchase.action_report_purchase_order')
        res = self.Conv.convert_report(report)
        self.assertTrue(
            any('生成式' in n for n in res['notes']),
            '待辦裡要講清楚為什麼沒改寫：%s' % res['notes'],
        )
