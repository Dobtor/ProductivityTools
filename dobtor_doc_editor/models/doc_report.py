"""報表輸出定義：把 doc.template 綁到 Odoo 原生 ir.actions.report。

這一層就是 QWeb 報表的替代品，但**不取代報表動作本身**——使用者按的還是
Odoo 原生的「列印」按鈕、走原生的下載流程，只有「HTML 從哪裡來」被換掉。

定案決策一（逐一綁定）：查不到綁定時一律 super()，與原生 QWeb 共存。
客戶可以一張報表一張報表換，出問題退回原生只要停用一筆 doc.report。

攔截點的選擇（見 models/report_overrides.py）：
    ir.actions.report._render_qweb_html()
    ——不是 _render_qweb_pdf_prepare_streams，也不是 selection_add 新 report_type。
    理由與 Odoo 期待的 HTML 結構都寫在 _build_report_html() 的註解裡。

「附頁」是上面那個選擇的**唯一例外**：把別的報表或固定 PDF 接在單據後面
必須在 PDF 層做（HTML 裡沒有 PDF 可接），所以多了第二個攔截點
_render_qweb_pdf_prepare_streams。只有設了附頁的綁定會走到那裡，
沒設的完全不碰——見 report_overrides.py 的那支覆寫。
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
        help="下載檔名，可用 {{ object.name }} 這類表達式（與範本同一套語法）。\n"
             "留空時沿用報表自己的 print_report_name。\n"
             "會自動把 / \\ : * ? 等不能當檔名的字換成底線"
             "——單號常含 /（S00001/2026），不換掉下載會壞。\n"
             "只在「單筆列印」時生效：多筆合併成一份 PDF 時沒有單一記錄可取值。",
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
    # ─── 附頁：把別的報表或固定 PDF 接在這張單據後面 ───────────────
    #
    # 真實需求是「這張單據**不只**我們產的那幾頁」：合約後面接標準條款、
    # 出貨單後面接 MSDS、估驗計價單後面接原生的明細報表。
    # 以前的做法是列印兩次再自己用 PDF 工具合併——而人會忘記，或接錯版本。
    #
    # 逐筆記錄合併（不是整批合併完才接）：接的是「這張單據的附頁」，
    # 多筆列印時每張單據後面都要有自己那份。
    append_report_ids = fields.Many2many(
        'ir.actions.report',
        'doc_report_append_report_rel', 'doc_report_id', 'report_id',
        string='附加報表',
        domain="[('report_type', 'in', ['qweb-pdf', 'qweb-html'])]",
        help='接在這張單據後面的其他報表（會以同一筆記錄渲染）。\n'
             '模型必須與本報表相同，否則那一張會被跳過並留下 log。',
    )
    append_attachment_ids = fields.Many2many(
        'ir.attachment',
        'doc_report_append_attachment_rel', 'doc_report_id', 'attachment_id',
        string='附加固定 PDF',
        domain="[('mimetype', '=', 'application/pdf')]",
        help='接在後面的固定 PDF（標準條款、安全資料表…）。與記錄無關，每張單據都接同一份。',
    )
    append_position = fields.Selection(
        [('after', '接在後面'), ('before', '放在前面')],
        string='附頁位置', default='after', required=True,
        help='「放在前面」給封面頁用。',
    )
    append_record_policy = fields.Selection(
        [('always', '每一筆都附'),
         ('opt_out', '預設附，記錄可以關掉'),
         ('opt_in', '預設不附，記錄要開啟')],
        string='附頁適用範圍', default='always', required=True,
        help='「每一筆都附」＝不看記錄怎麼說（預設，設定了附頁就生效）。\n'
             '另兩個會去問記錄的 doc_report_append_enabled()——'
             'doc.linked.mixin 的實作是讀「附加附頁」那個勾選。\n'
             '記錄沒有那支方法時：opt_out 當成要附、opt_in 當成不附。',
    )

    output_count = fields.Integer(string='輸出筆數', compute='_compute_output_count')

    # 記錄這一側的約定方法。名字不以底線開頭：要能被繼承者一眼看出是公開約定
    #（與 doc_report_values() 同一套做法）。
    _RECORD_HOOKS = {
        'enabled': 'doc_report_append_enabled',
        'pdfs': 'doc_report_append_pdfs',
        'template': 'doc_report_template',
    }

    def _record_append_enabled(self, record):
        """這一筆要不要接附頁。

        policy='always' 時根本不問記錄——設定了附頁就生效，否則「在綁定上設好
        附頁卻什麼都沒發生」會是個找不到原因的坑。
        記錄沒有那支方法時：opt_out 當成要附、opt_in 當成不附（兩邊都取
        「設定者寫下的預設」而不是猜）。
        """
        policy = self.append_record_policy or 'always'
        if policy == 'always':
            return True
        hook = self._RECORD_HOOKS['enabled']
        if not hasattr(record, hook):
            return policy == 'opt_out'
        try:
            return bool(getattr(record, hook)())
        except Exception as e:
            _logger.warning(
                '[doc.report] %s(%s).%s() 失敗，依政策 %s 處理：%s',
                record._name, record.id, hook, policy, e)
            return policy == 'opt_out'

    def _record_append_pdfs(self, record):
        """記錄自己提供的 PDF（ir.attachment 或一串 bytes 都收）。

        這是靜態設定補不上的那一半：出貨單要附的是**這一張單自己上傳的**
        檢驗報告，每筆都不一樣。
        """
        hook = self._RECORD_HOOKS['pdfs']
        if not hasattr(record, hook):
            return []
        try:
            value = getattr(record, hook)()
        except Exception as e:
            _logger.warning('[doc.report] %s(%s).%s() 失敗，略過記錄自備附頁：%s',
                            record._name, record.id, hook, e)
            return []
        out = []
        if hasattr(value, '_name') and hasattr(value, 'ids'):
            for att in value:
                try:
                    # sudo 同固定附頁：決定「哪些附件要印」的是業務程式碼，
                    # 不是操作者的讀取權（他本來就看得到這張單據）
                    raw = att.sudo().raw
                except Exception as e:
                    _logger.warning('[doc.report] 記錄附件 %s 讀取失敗：%s',
                                    att.display_name, e)
                    continue
                if raw:
                    out.append(raw)
            return out
        for item in (value or []):
            if isinstance(item, bytes) and item:
                out.append(item)
        return out

    def _record_template_for(self, record):
        """這一筆要用的範本；回空＝用綁定那一張。

        模型對不上就忽略並留 log：拿 sale.order 的範本去印 account.move，
        印出來會是一張看起來正常、值全空的單據——那比印出綁定的範本糟。
        """
        hook = self._RECORD_HOOKS['template']
        if not hasattr(record, hook):
            return self.env['doc.template'].browse()
        try:
            template = getattr(record, hook)()
        except Exception as e:
            _logger.warning('[doc.report] %s(%s).%s() 失敗，用綁定的範本：%s',
                            record._name, record.id, hook, e)
            return self.env['doc.template'].browse()
        if not template:
            return self.env['doc.template'].browse()
        template = template[:1]
        model = template.model_id.model if template.model_id else None
        if model and model != record._name:
            _logger.warning(
                '[doc.report] %s(%s) 指定的範本「%s」是 %s 的，與 %s 不符，已忽略',
                record._name, record.id, template.name, model, record._name)
            return self.env['doc.template'].browse()
        return template

    def _append_streams_for(self, record):
        """這筆記錄要接的 PDF 位元串清單（依設定順序）。

        三段：綁定設定的報表 → 綁定設定的固定 PDF → **記錄自己提供的**。
        記錄自備的放最後，因為它是「這一張單的附件」，順序上在通用條款之後。

        拿不到的那一張跳過並留 log，不讓整張單據失敗——使用者要的是手上
        那張單據，附頁壞掉是次要的（與留存輸出失敗同一個取捨）。
        """
        if not self._record_append_enabled(record):
            return []
        out = []
        for report in self.append_report_ids:
            if report.model != record._name:
                _logger.warning(
                    '[doc.report] 附加報表 %s 的模型是 %s，與 %s 不符，已跳過',
                    report.report_name, report.model, record._name,
                )
                continue
            try:
                content, ext = report.with_context(
                    # 防遞迴：附加的報表若自己也綁了 doc.report 並且附加回來，
                    # 不擋的話會無限互叫。看到這個旗標就不再接附頁。
                    doc_report_no_append=True,
                    # 測試模式下 Odoo 會把 _render_qweb_pdf 短路成 HTML
                    #（ir_actions_report.py:1008，怕 worker 不夠跑 wkhtmltopdf）。
                    # 不強制的話這裡拿到的是 str，接下去 merge_pdf 會炸。
                    force_report_rendering=True,
                )._render_qweb_pdf(report.id, [record.id])
            except Exception as e:
                _logger.warning('[doc.report] 附加報表 %s 產生失敗：%s',
                                report.report_name, e)
                continue
            if not isinstance(content, bytes):
                # 只收 bytes。拿到別的東西（HTML、None）就跳過並講清楚，
                # 不要讓它流到 merge_pdf 變成一個看不懂的例外。
                _logger.warning(
                    '[doc.report] 附加報表 %s 回的不是 PDF 位元串（%s / %s），已跳過',
                    report.report_name, type(content).__name__, ext)
                continue
            if content:
                out.append(content)
        for att in self.append_attachment_ids:
            try:
                # sudo 讀位元組：這幾份 PDF 是**報表設定的一部分**，由能編輯
                # doc.report 的人挑的（標準條款、安全資料表），不是使用者資料。
                # 不 sudo 的話，沒有該附件讀取權的一般使用者列印時會靜默少頁。
                raw = att.sudo().raw
            except Exception as e:
                _logger.warning('[doc.report] 附加 PDF %s 讀取失敗：%s', att.name, e)
                continue
            if raw:
                out.append(raw)
        out.extend(self._record_append_pdfs(record))
        return out

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
        # 逐筆範本覆寫（記錄身上的 doc_report_template()）。
        # 解析結果依範本 id 快取：十張單據都指定同一張特別範本時只解析一次。
        # 沒有任何記錄覆寫時這個 dict 一直是空的，等於這段不存在。
        tree_cache = {template.id: base_tree}

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
            # 這一筆要用哪張範本。頁首頁尾（frame_tree）仍然只有一份——
            # wkhtmltopdf 的頁首頁尾是整份 PDF 共用的，做不到逐筆不同。
            # 覆寫的範本如果外框不一樣，會留下 log 並沿用綁定那一份外框。
            record_template = self._record_template_for(record)
            if record_template and record_template != template:
                if record_template.id not in tree_cache:
                    tree_cache[record_template.id] = Mixin._parse_content_json(
                        record_template.content_json)
                    if record_template.frame_template() != frame:
                        _logger.warning(
                            '[doc.report] %s(%s) 指定的範本「%s」外框與綁定不同，'
                            '頁首頁尾仍沿用綁定那一份（wkhtmltopdf 的頁首頁尾'
                            '整份 PDF 共用）',
                            record._name, record.id, record_template.name)
                this_tree = tree_cache[record_template.id]
                this_template = record_template
            else:
                this_tree = base_tree
                this_template = template
            if this_tree is None:
                # 範本還沒用編輯器存過（只有 content_html）：退回舊的 alias 渲染，
                # 至少印得出東西，而不是給一張空白紙。
                body = this_template._render_template(
                    this_template.get_content_html(), record,
                )
                frozen_trees[record.id] = None
            else:
                import copy as _copy
                tree = Mixin._snapshot_content_json(
                    _copy.deepcopy(this_tree), record,
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
            scope_js = self._page_scope_script(head + foot)
            if head.strip() and head != '<p><br/></p>':
                header_footer += '<div class="header">%s%s%s</div>' % (
                    self._zone_style(frame, 'header'), scope_js, head)
            if foot.strip() and foot != '<p><br/></p>':
                header_footer += '<div class="footer">%s%s%s</div>' % (
                    self._zone_style(frame, 'footer'), scope_js, foot)

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

    # ─── 頁首頁尾的版面與「哪一頁要出現」 ─────────────────────────
    #
    # Odoo 把我們的 div.header / div.footer 整個序列化後塞進 web.minimal_layout
    # 的 <body>（ir_actions_report.py:441，Markup 不逸出），再交給 wkhtmltopdf
    # 當 --header-html。wkhtmltopdf **每一頁都重載一次**那份 HTML，並在網址上
    # 帶 page / topage 等參數——Odoo 自己的 subst() 就是靠這個填頁碼
    #（web/views/report_templates.xml:239）。
    #
    # 所以「首頁不同」「奇偶頁不同」只能在那一刻決定：我們一起塞一小段
    # script，讓它依 page 參數在 <body> 上掛 class，再用 CSS 決定哪一段顯示。
    # 不能在後端算——後端不知道這一頁是第幾頁。

    _PAGE_SCOPE_SCRIPT = (
        '<style>'
        '.doc-page-first,.doc-page-rest,.doc-page-odd,.doc-page-even'
        '{display:none}'
        'body.doc-pg-first .doc-page-first,'
        'body.doc-pg-rest .doc-page-rest,'
        'body.doc-pg-odd .doc-page-odd,'
        'body.doc-pg-even .doc-page-even{display:block}'
        '</style>'
        '<script>(function(){'
        'var v={},a=document.location.search.substring(1).split("&");'
        'for(var i=0;i<a.length;i++){var kv=a[i].split("=",2);v[kv[0]]=kv[1];}'
        'var p=parseInt(v.page||v.sitepage||"1",10)||1;'
        'var c=document.body||document.documentElement;'
        'c.className+=" doc-pg-"+(p===1?"first":"rest")'
        '+" doc-pg-"+(p%2?"odd":"even");'
        '})();</script>'
    )

    def _page_scope_script(self, html):
        """頁首頁尾裡有頁面範圍標記時才塞那段 script／style。

        沒用到就不塞：頁首是每一頁都重載一次的，多一段沒用的 script 是
        每一頁的成本，而且會讓 debug 時的 HTML 更難讀。
        """
        return self._PAGE_SCOPE_SCRIPT if 'doc-page-' in (html or '') else ''

    def _zone_style(self, frame, zone):
        """頁首／頁尾自己的左右內距與分隔線。

        wkhtmltopdf 的頁首是另一份文件、鋪滿紙張寬度，本文的左右邊距對它
        無效——所以要在這裡自己留，否則頁首會與本文左右對不齊。
        """
        pad = frame['%s_padding_x' % zone] or 0
        rule = frame['%s_rule' % zone]
        bits = []
        if pad:
            bits.append('padding-left:%dpx;padding-right:%dpx' % (pad, pad))
        if rule:
            side = 'bottom' if zone == 'header' else 'top'
            bits.append('border-%s:1px solid #000;padding-%s:4px' % (side, side))
        if not bits:
            return ''
        return '<style>div.%s{%s}</style>' % (zone, ';'.join(bits))

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
