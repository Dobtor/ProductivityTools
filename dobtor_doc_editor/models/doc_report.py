"""報表輸出定義：把 doc.template 綁到 Odoo 原生 ir.actions.report。

這一層就是 QWeb 報表的替代品，但**不取代報表動作本身**——使用者按的還是
Odoo 原生的「列印」按鈕、走原生的下載流程，只有「HTML 從哪裡來」被換掉。

定案決策一（逐一綁定）：查不到綁定時一律 super()，與原生 QWeb 共存。
客戶可以一張報表一張報表換，出問題退回原生只要停用一筆 doc.report。

攔截點的選擇（見 models/report_overrides.py）：
    ir.actions.report._render_qweb_html()
    ——不是 _render_qweb_pdf_prepare_streams，也不是 selection_add 新 report_type。
    理由與 Odoo 期待的 HTML 結構都寫在 _build_report_html() 的註解裡。
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _lang_get(self):
    return self.env['res.lang'].get_installed()


class DocReport(models.Model):
    _name = 'doc.report'
    _description = '報表輸出定義'
    _order = 'sequence, id'

    name = fields.Char(string='名稱', required=True)
    active = fields.Boolean(string='啟用', default=True)
    sequence = fields.Integer(
        string='順序',
        default=10,
        help='同一個報表有多筆定義時，數字小的優先採用。',
    )
    template_id = fields.Many2one(
        'doc.template',
        string='使用範本',
        required=True,
        ondelete='restrict',
        # 外框範本只有頁首頁尾、沒有本文，綁上去會印出一張只有頁眉的空白紙
        domain="[('role', '=', 'content')]",
        help='列印時用哪一張範本。ondelete=restrict：範本被報表綁住時不可刪除。',
    )
    report_id = fields.Many2one(
        'ir.actions.report',
        string='接管的報表',
        required=True,
        ondelete='cascade',
        domain="[('report_type', 'in', ['qweb-pdf', 'qweb-html'])]",
        help='按下這個報表的「列印」時，改用上方範本產生內容。',
    )
    report_model = fields.Char(
        string='報表模型',
        related='report_id.model',
        store=True,
        readonly=True,
        help='用來比對 data-oe-model；由報表定義決定，不可自行指定。',
    )
    lang = fields.Selection(
        _lang_get,
        string='語言',
        help='只在此語言生效。留空＝所有語言的後備值。'
             'content_json 是整份版面、不走 i18n，所以多語言的做法是'
             '「一語言一筆定義指向不同範本」，而不是翻譯範本內容。',
    )
    company_id = fields.Many2one(
        'res.company',
        string='公司',
        help='只在此公司生效。留空＝所有公司的後備值。',
    )
    filename_pattern = fields.Char(
        string='檔名樣式',
        help="下載檔名，可用 {{ object.name }} 這類表達式。"
             "留空時沿用報表自己的 print_report_name。",
    )
    persist_output = fields.Boolean(
        string='留存輸出紀錄',
        default=False,
        help='開啟時每次列印都建立一筆 doc.output（可在編輯器中唯讀瀏覽）。\n'
             '預設關閉——列印是高頻動作，不該讓每次列印都長資料。'
             '需要稽核的單據（合約、正式發函）才開。',
    )
    retention_days = fields.Integer(
        string='輸出保留天數',
        default=0,
        help='0＝永久保留。大於 0 時由排程清理逾期的輸出紀錄。',
    )
    output_count = fields.Integer(string='輸出筆數', compute='_compute_output_count')

    def _compute_output_count(self):
        data = self.env['doc.output']._read_group(
            [('doc_report_id', 'in', self.ids)],
            groupby=['doc_report_id'],
            aggregates=['__count'],
        )
        mapped = {report.id: count for report, count in data}
        for rec in self:
            rec.output_count = mapped.get(rec.id, 0)

    @api.constrains('template_id', 'report_id')
    def _check_template_model_matches(self):
        """範本的適用模型若有設定，必須與報表模型一致。

        不一致的話藥丸的欄位路徑會對不上來源記錄，求值全部落空——
        而求值失敗是靜默的（回空字串），所以必須在設定階段擋下來。
        """
        for rec in self:
            tmpl_model = rec.template_id.model_id.model
            if tmpl_model and rec.report_model and tmpl_model != rec.report_model:
                raise UserError(_(
                    "範本「%(tmpl)s」的適用模型是 %(tmpl_model)s，"
                    "但報表「%(report)s」印的是 %(report_model)s。\n"
                    "模型不一致時，範本裡的變數會全部取不到值（而且不會報錯）。",
                    tmpl=rec.template_id.display_name,
                    tmpl_model=tmpl_model,
                    report=rec.report_id.display_name,
                    report_model=rec.report_model,
                ))

    # ─── 解析：這個報表現在該用哪一筆定義 ─────────────────────────────

    @api.model
    def _resolve_for_report(self, report, lang=None, company=None):
        """找出適用的 doc.report；找不到回空 recordset（呼叫端應 super()）。

        挑選規則：先過濾「語言／公司相符或留空」，再依
        「明確指定者優先 → sequence → id」排序取第一筆。
        明確指定優先的意思是：有 zh_TW 專屬定義時不會被 lang 留空的後備值搶走。
        """
        if not report:
            return self.browse()
        lang = lang or self.env.context.get('lang') or self.env.user.lang
        company = company or self.env.company

        candidates = self.sudo().search([
            ('report_id', '=', report.id),
            ('lang', 'in', [lang, False]),
            ('company_id', 'in', [company.id, False]),
        ])
        if not candidates:
            return self.browse()

        def specificity(rec):
            # 明確指定的欄位越多越優先（負值讓 sort 升冪即可）
            return (
                -(1 if rec.lang else 0) - (1 if rec.company_id else 0),
                rec.sequence,
                rec.id,
            )

        return candidates.sorted(key=specificity)[0]

    # ─── HTML 組裝 ───────────────────────────────────────────────────

    def _build_report_html(self, records):
        """產生 Odoo 報表管線看得懂的完整 HTML。

        Odoo 的 _prepare_html()（ir_actions_report.py:368）對結構有硬要求，
        不照著做會以 IndexError 或 UserError 收場：

          * **必須有 <main>**——`root.xpath('//main')[0]`，沒有就 IndexError
          * 每筆記錄一個 `<div class="article" data-oe-model data-oe-id>`
            ——Odoo 據此把單一 PDF 切回每筆記錄的 stream。
            report.attachment 開啟且 id 對不上時會直接 raise UserError
          * `data-oe-lang` 決定該段的渲染語言
          * 根 <html> 上的 `data-report-*` 屬性會變成 specific_paperformat_args
            ——範本的頁面邊距就是靠這個傳下去（左右兩側另需
            models/report_overrides.py 的 _build_wkhtmltopdf_args 覆寫才生效）
          * `<div class="header">` / `<div class="footer">` 會被抽出來交給
            wkhtmltopdf 當每頁重複的頁首頁尾

        定案決策三：留存時存的是「凍結後的元素樹」，所以這裡產生的 tree
        要交給呼叫端留存，不要在這裡丟掉。
        """
        self.ensure_one()
        template = self.template_id
        frame = template.frame_template()
        Mixin = self.env['doc.render.mixin']
        base_tree = Mixin._parse_content_json(template.content_json)
        frame_tree = (
            base_tree if frame == template
            else Mixin._parse_content_json(frame.content_json)
        )

        articles = []
        frozen_trees = {}
        langs = {}
        for raw_record in records:
            # 渲染語言必須套用到「記錄」而不只是 data-oe-lang：少了這一步，
            # 綁定上設了 zh_TW 仍會把商品名稱、selection 標籤、付款條件
            # 印成操作者的語言，而且完全不報錯。
            lang = (
                self.lang
                or Mixin.with_context(doc_render_lang=None)._render_lang(raw_record)
                or self.env.context.get('lang') or 'en_US'
            )
            record = Mixin._record_in_lang(raw_record, lang)
            langs[raw_record.id] = lang
            if base_tree is None:
                # 範本還沒用編輯器存過（只有 content_html）：退回舊的 alias 渲染，
                # 至少印得出東西，而不是給一張空白紙。
                body = template._render_template(
                    template.get_content_html(), record,
                )
                frozen_trees[record.id] = None
            else:
                import copy as _copy
                tree = Mixin._snapshot_content_json(
                    _copy.deepcopy(base_tree), record,
                )
                frozen_trees[record.id] = tree
                body = Mixin._content_json_to_html(
                    Mixin._flatten_content_json(_copy.deepcopy(tree))
                )
            articles.append(
                '<div class="article" data-oe-model="%s" data-oe-id="%s" data-oe-lang="%s">'
                '%s</div>' % (
                    record._name, record.id, lang, body,
                )
            )

        header_footer = ''
        if frame_tree is not None:
            # 頁首頁尾一定要走 snapshot + flatten。少了這一步的後果是靜默的：
            #   * 頁首頁尾裡的藥丸原樣印出標籤文字（單據上出現「客戶名稱」四個字）
            #   * 頁碼藥丸不會變成 wkhtmltopdf 認得的 <span class="page">
            # 只取 header/footer 兩區——main 已經逐筆處理過，再展開一次是白做工。
            #
            # 以第一筆記錄求值：wkhtmltopdf 的頁首頁尾是「整份文件一份、每頁重複」，
            # 多筆記錄一起印時沒有逐筆帶值的餘地（那是 wkhtmltopdf 的限制，
            # 不是這裡的選擇）。所以頁首頁尾適合放公司資訊與頁碼，不適合放單據欄位。
            import copy as _copy
            hf_tree = {
                zone: _copy.deepcopy(frame_tree.get(zone) or [])
                for zone in ('header', 'footer')
            }
            first = records[:1]
            if first:
                Mixin._snapshot_content_json(
                    hf_tree,
                    Mixin._record_in_lang(first, langs.get(first.id)),
                )
            Mixin._flatten_content_json(hf_tree)
            head = Mixin._content_json_to_html(hf_tree, zone='header')
            foot = Mixin._content_json_to_html(hf_tree, zone='footer')
            if head.strip() and head != '<p><br/></p>':
                header_footer += '<div class="header">%s</div>' % head
            if foot.strip() and foot != '<p><br/></p>':
                header_footer += '<div class="footer">%s</div>' % foot

        html = (
            '<html %s><head><meta charset="utf-8"/><style>%s</style></head>'
            '<body><main>%s%s</main></body></html>' % (
                self._paperformat_attrs(),
                self._report_css(),
                header_footer,
                ''.join(articles),
            )
        )
        return html, frozen_trees

    def _paperformat_attrs(self):
        """範本的頁面邊距 → 根 <html> 的 data-report-* 屬性。

        定案：**範本的版面設定優先於報表的 paperformat**。
        理由是「編輯器裡看到的就是列印結果」是這個模組的賣點；
        若讓 paperformat 贏，使用者調完版面列印出來卻不一樣，模組就沒有意義。
        """
        self.ensure_one()
        # 紙張與邊距屬於「外框」。設了外框範本就由它決定——否則同一個外框底下
        # 各張內容範本的邊距不一致，頁首會在不同單據上落在不同高度。
        tmpl = self.template_id.frame_template()
        px_to_mm = 25.4 / 96
        attrs = {
            'data-report-margin-top': round((tmpl.margin_top or 96) * px_to_mm, 1),
            'data-report-margin-bottom': round((tmpl.margin_bottom or 96) * px_to_mm, 1),
            'data-report-margin-left': round((tmpl.margin_left or 96) * px_to_mm, 1),
            'data-report-margin-right': round((tmpl.margin_right or 96) * px_to_mm, 1),
            # wkhtmltopdf 的頁首疊在上邊距區，比邊距高就壓到本文。
            # Odoo 只讀 data-report-header-spacing（ir_actions_report.py:339），
            # footer-spacing 由 models/report_overrides.py 的覆寫補上。
            'data-report-header-spacing': tmpl.header_spacing or 5,
            'data-report-footer-spacing': tmpl.footer_spacing or 5,
        }
        return ' '.join('%s="%s"' % (k, v) for k, v in attrs.items())

    def _report_css(self):
        """列印用的最小樣式。

        刻意不帶藥丸網底——定案決策四：匯出只輸出值，網底屬編輯輔助。
        （_flatten_content_json 已經把 label 攤平成純文字，這裡是第二道保險。）
        """
        return (
            "body{font-family:'Microsoft JhengHei','Noto Sans TC',Arial,sans-serif;"
            "font-size:12px;line-height:1.6;color:#000;margin:0}"
            "table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #999;padding:4px 6px}"
            # 區塊容器（條件區塊／稅額彙總）用單格表格當邊界，但它不是表格，
            # 不可印框線。見 doc.render.mixin._element_block_kind。
            ".doc-block,.doc-block td{border:none;padding:0}"
            ".doc-page-break{page-break-after:always}"
            ".article{page-break-after:always}"
            ".article:last-child{page-break-after:auto}"
        )

    # ─── 動作 ────────────────────────────────────────────────────────

    def action_view_outputs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('輸出紀錄'),
            'res_model': 'doc.output',
            'view_mode': 'list,form',
            'domain': [('doc_report_id', '=', self.id)],
            'context': {'search_default_group_res_model': 1},
        }

    def action_open_template(self):
        self.ensure_one()
        return self.template_id.action_open_editor()
