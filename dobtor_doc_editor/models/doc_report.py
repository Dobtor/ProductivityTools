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
import copy
import logging
import re

import lxml.html
from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.image import base64_to_image

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
        help='只用在這個語言的客戶（依單據上客戶的語言挑，與原生報表一致）。'
             '留空＝所有語言的後備值。範本裡打好的固定文字只有一種語言，'
             '要給不同語言的客戶不同文字，可以各綁一張範本，或在範本裡改用多語文字。',
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

    @api.model
    def _customer_lang(self, record):
        """這筆記錄該用哪個語言印：客戶的語言，沒有客戶就用操作者的。

        與原生報表一致（sale 的範本是 doc.with_context(lang=doc.partner_id.lang)）。
        以前挑定義用的是操作者語言，英文客戶的報價單會被中文介面的業務印成中文。
        """
        Mixin = self.env['doc.render.mixin'].with_context(doc_render_lang=None)
        return (Mixin._render_lang(record) or self.env.context.get('lang')
                or self.env.user.lang or 'en_US')

    @api.model
    def _resolve_for_records(self, report, records):
        """整批列印要不要接管、以哪一筆定義為主：看第一筆記錄的客戶語言。

        每一筆實際用哪張範本，_build_report_html 會再照各自的客戶語言挑
        （_binding_for_record）；這裡只決定「接不接管」與頁首頁尾、紙張用誰的。
        """
        lang = self._customer_lang(records[:1]) if records else None
        return self._resolve_for_report(report, lang=lang)

    def _binding_for_record(self, record):
        """這一筆該用哪一筆定義、用什麼語言印。回傳 (定義, 語言)。

        定義照客戶語言挑：有該語言專屬的就用它，沒有就用後備（語言留空）的；
        兩者都沒有就沿用 self（整批被選中的那一筆）——這時範本裡打好的固定文字
        是那張範本的語言，只有從單據帶出來的值照客戶語言。
        """
        self.ensure_one()
        lang = self._customer_lang(record)
        binding = self._resolve_for_report(self.report_id, lang=lang) or self
        return binding, lang

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

        # 樣式要放進每一個 header／footer／article 裡面，放在 <head> 會被丟掉：
        # Odoo 的 _prepare_html 只把這三種 div 拆出來，各自重新包進
        # web.minimal_layout 交給 wkhtmltopdf，原本的 <head> 整個不要了。
        # 少了這份樣式，表格縮成內容寬度、條件區塊的格線被印出來、
        # 頁首還會被 Odoo 報表版面自己的內距往下推，壓到本文。
        style = '<style>%s</style>' % self._report_css(template.text_style())
        articles = []
        frozen_trees = {}
        langs = {}
        for raw_record in records:
            # 這一筆用哪一筆定義、什麼語言印：都照客戶語言（見 _binding_for_record）
            binding, lang = self._binding_for_record(raw_record)
            # 語言要同時套在「記錄」與「求值的環境」上。只換記錄的話，商品名稱、
            # 稅額標籤照客戶語言，日期格式卻照操作者語言——同一張單據中英混雜。
            LangMixin = Mixin.with_context(lang=lang)
            record = LangMixin._record_in_lang(raw_record, lang)
            langs[raw_record.id] = lang
            # 這一筆要用哪張範本：先看客戶語言對應的定義，再看記錄自己有沒有指定。
            # 頁首頁尾（frame_tree）仍然只有一份——wkhtmltopdf 的頁首頁尾是整份
            # PDF 共用的，做不到逐筆不同。外框不一樣時留 log 並沿用綁定那一份外框。
            record_template = (
                binding._record_template_for(record) or binding.template_id)
            if record_template != template:
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
                body = this_template.with_context(lang=lang)._render_template(
                    this_template.get_content_html(), record,
                )
                frozen_trees[record.id] = None
            else:
                tree = LangMixin._snapshot_content_json(
                    copy.deepcopy(this_tree), record,
                )
                frozen_trees[record.id] = tree
                body = LangMixin._content_json_to_html(
                    LangMixin._flatten_content_json(copy.deepcopy(tree))
                )
            articles.append(
                '<div class="article" data-oe-model="%s" data-oe-id="%s" data-oe-lang="%s">'
                '%s%s</div>' % (
                    record._name, record.id, lang, style, body,
                )
            )

        header_footer = ''
        head_px = foot_px = 0
        if frame_tree is not None:
            # 頁首頁尾一定要走 snapshot + flatten。少了這一步的後果是靜默的：
            #   * 頁首頁尾裡的藥丸原樣印出標籤文字（單據上出現「客戶名稱」四個字）
            #   * 頁碼藥丸不會變成 wkhtmltopdf 認得的 <span class="page">
            # 只取 header/footer 兩區——main 已經逐筆處理過，再展開一次是白做工。
            #
            # 以第一筆記錄求值：wkhtmltopdf 的頁首頁尾是「整份文件一份、每頁重複」，
            # 多筆記錄一起印時沒有逐筆帶值的餘地（那是 wkhtmltopdf 的限制，
            # 不是這裡的選擇）。所以頁首頁尾適合放公司資訊與頁碼，不適合放單據欄位。
            hf_tree = {
                zone: copy.deepcopy(frame_tree.get(zone) or [])
                for zone in ('header', 'footer')
            }
            first = records[:1]
            # 頁首頁尾的語言跟第一筆走（同一份 PDF 只有一份頁首頁尾）
            HfMixin = Mixin.with_context(lang=langs[first.id]) if first else Mixin
            if first:
                HfMixin._snapshot_content_json(
                    hf_tree, HfMixin._record_in_lang(first, langs[first.id]),
                )
            HfMixin._flatten_content_json(hf_tree)
            head = HfMixin._content_json_to_html(hf_tree, zone='header')
            foot = HfMixin._content_json_to_html(hf_tree, zone='footer')
            scope_js = self._page_scope_script(head + foot)
            if head.strip() and head != '<p><br/></p>':
                header_footer += '<div class="header">%s%s%s%s</div>' % (
                    style, self._zone_style(frame, 'header'), scope_js, head)
                head_px = self._estimate_html_height(head, template.text_style())
            if foot.strip() and foot != '<p><br/></p>':
                header_footer += '<div class="footer">%s%s%s%s</div>' % (
                    style, self._zone_style(frame, 'footer'), scope_js, foot)
                foot_px = self._estimate_html_height(foot, template.text_style())

        html = (
            '<html %s><head><meta charset="utf-8"/></head>'
            '<body><main>%s%s</main></body></html>' % (
                self._paperformat_attrs(head_px, foot_px),
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

    # 編輯器（canvas-editor）的頁首從紙張頂端往下 30px 開始畫，頁尾畫到離紙張
    # 底端 30px 為止；頁首頁尾比邊距高時，編輯器會把本文往內推。PDF 照同一套。
    _HEADER_TOP_PX = 30
    _FOOTER_BOTTOM_PX = 30

    def _paperformat_attrs(self, head_px=0, foot_px=0):
        """範本的頁面邊距 → 根 <html> 的 data-report-* 屬性。

        定案：**範本的版面設定優先於報表的 paperformat**。
        理由是「編輯器裡看到的就是列印結果」是這個模組的賣點；
        若讓 paperformat 贏，使用者調完版面列印出來卻不一樣，模組就沒有意義。

        head_px / foot_px 是頁首頁尾的估計高度（_estimate_html_height）。
        頁首頁尾要自己算位置，因為 wkhtmltopdf 不會依內容留空間：Odoo 的
        web.minimal_layout 把頁首頁尾文件的高度設成 0（<html style="height:0">），
        結果是頁首一律從「上邊距 − 頁首間距」那條線往下畫、頁尾一律從
        「下邊距 − 頁尾間距」那條線往下畫，內容多高都一樣。所以：
          * 頁首從 30px 開始畫：頁首間距參數 = 上邊距 − 30px
          * 頁尾畫到離底 30px：頁尾間距參數 = 下邊距 − 30px − 頁尾高度
          * 頁首（或頁尾）加上範本設定的間距超過邊距時，邊距跟著加大，
            本文往內推，不會被壓到
        """
        self.ensure_one()
        # 紙張與邊距屬於「外框」。設了外框範本就由它決定——否則同一個外框底下
        # 各張內容範本的邊距不一致，頁首會在不同單據上落在不同高度。
        tmpl = self.template_id.frame_template()
        px_to_mm = 25.4 / 96
        top = tmpl.margin_top or 96
        bottom = tmpl.margin_bottom or 96
        header_gap = tmpl.header_spacing or 5
        footer_gap = tmpl.footer_spacing or 5
        if head_px:
            # 頁首下方分隔線：border 1px＋padding 4px（見 _zone_style）
            head_px += 5 if tmpl.header_rule else 0
            top = max(top, self._HEADER_TOP_PX + head_px + header_gap / px_to_mm)
            header_gap = (top - self._HEADER_TOP_PX) * px_to_mm
        if foot_px:
            foot_px += 5 if tmpl.footer_rule else 0
            bottom = max(bottom, self._FOOTER_BOTTOM_PX + foot_px + footer_gap / px_to_mm)
            footer_gap = (bottom - self._FOOTER_BOTTOM_PX - foot_px) * px_to_mm
        attrs = {
            'data-report-margin-top': round(top * px_to_mm, 1),
            'data-report-margin-bottom': round(bottom * px_to_mm, 1),
            'data-report-margin-left': round((tmpl.margin_left or 96) * px_to_mm, 1),
            'data-report-margin-right': round((tmpl.margin_right or 96) * px_to_mm, 1),
            # Odoo 只讀 data-report-header-spacing（ir_actions_report.py:339），
            # footer-spacing 由 models/report_overrides.py 的覆寫補上。
            'data-report-header-spacing': round(header_gap, 1),
            'data-report-footer-spacing': round(footer_gap, 1),
            # 關掉 wkhtmltopdf 的自動縮小，1px 才會等於編輯器的 1px
            # （models/report_overrides.py 的 _build_wkhtmltopdf_args 讀這個）
            'data-report-disable-shrinking': 1,
        }
        return ' '.join('%s="%s"' % (k, v) for k, v in attrs.items())

    # ─── 估計頁首頁尾的高度 ─────────────────────────────────────────
    #
    # 數字要跟 _report_css 一致：字級 16px、行高 1.25、<p> 上下各 8px、
    # 一般表格格子下內距 5px（區塊容器是 0）。
    _EST_FONT_PX = 16
    _EST_LINE_HEIGHT = 1.25
    _EST_P_PADDING_PX = 16
    _EST_TD_PADDING_PX = 5
    _EST_BLOCK_TAGS = frozenset((
        'p', 'div', 'table', 'ul', 'ol', 'li', 'blockquote', 'address',
        'section', 'article', 'header', 'footer',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    ))
    _EST_FONT_RE = re.compile(r'font-size\s*:\s*(\d+(?:\.\d+)?)px')
    _EST_HEIGHT_RE = re.compile(r'(?:^|;)\s*height\s*:\s*(\d+(?:\.\d+)?)px')

    def _estimate_html_height(self, html, style=None):
        """估計一段頁首／頁尾 HTML 印出來有多高（px）。

        wkhtmltopdf 不會依頁首內容留空間（見 _paperformat_attrs），只好在這裡估。
        只算會把高度撐開的東西：段落（含 <br> 斷行）、圖片、表格的列。
        不算自動換行——頁首頁尾放的多半是短字串；估多了只是多留一點白，
        估少了才會壓到本文，所以有疑問時往大的估。
        """
        if not (html or '').strip():
            return 0
        try:
            root = lxml.html.fragment_fromstring(html, create_parent='div')
        except (etree.ParserError, ValueError):
            return 0
        metrics = self._est_metrics(style)
        return int(round(self._est_node_height(root, metrics['font'], metrics)))

    def _est_font(self, node, font):
        match = self._EST_FONT_RE.search(node.get('style') or '')
        return float(match.group(1)) if match else font

    def _est_img_height(self, node):
        """圖片高度：有寫 height 用它；沒寫就讀圖檔本身的尺寸（有 width 時等比例換算）。"""
        raw = node.get('height')
        if raw and raw.isdigit():
            return float(raw)
        match = self._EST_HEIGHT_RE.search(node.get('style') or '')
        if match:
            return float(match.group(1))
        src = node.get('src') or ''
        if not src.startswith('data:image/') or ',' not in src:
            return 0.0
        try:
            width, height = base64_to_image(src.split(',', 1)[1]).size
        except Exception:
            return 0.0
        attr_w = node.get('width')
        if attr_w and attr_w.isdigit() and width:
            return height * float(attr_w) / width
        return float(height)

    def _est_metrics(self, style):
        """估計用的字級、行高倍數、<p> 上下內距——跟 _report_text_css 同一套算法。"""
        style = style or self.env['doc.template']._DEFAULT_TEXT_STYLE
        size = style.get('size') or self._EST_FONT_PX
        row_margin = style.get('row_margin') or 1.0
        if row_margin == 1.0:
            return {'font': size, 'line_height': self._EST_LINE_HEIGHT,
                    'p_padding': self._EST_P_PADDING_PX}
        return {'font': size,
                'line_height': self._EST_LINE_HEIGHT + 16 * row_margin / size,
                'p_padding': 0}

    def _est_node_height(self, node, font, metrics=None):
        metrics = metrics or self._est_metrics(None)
        tag = node.tag if isinstance(node.tag, str) else ''
        if tag in ('style', 'script'):
            return 0.0
        font = self._est_font(node, font)
        if tag == 'img':
            return self._est_img_height(node)
        if tag == 'table':
            pad = 0 if 'doc-block' in (node.get('class') or '') else self._EST_TD_PADDING_PX
            total = 0.0
            for row in node.xpath('./tr|./*/tr'):
                cells = row.xpath('./td|./th')
                total += max(
                    [self._est_node_height(cell, font, metrics) + pad
                     for cell in cells] or [0.0])
            return total

        height = 0.0
        line = None  # 目前這一列的高度；None 表示這一列還沒開始

        def add_to_line(value):
            nonlocal line
            line = max(line or 0.0, value)

        def end_line():
            nonlocal height, line
            if line is not None:
                height += line
            line = None

        line_height = metrics['line_height']

        def walk(el, el_font):
            nonlocal height
            if (el.text or '').strip():
                add_to_line(el_font * line_height)
            for child in el:
                child_tag = child.tag if isinstance(child.tag, str) else ''
                child_font = self._est_font(child, el_font)
                if child_tag in ('style', 'script'):
                    pass
                elif child_tag == 'br':
                    # <br> 收掉目前這一列；接連兩個 <br> 中間是一列空白
                    if line is None:
                        add_to_line(child_font * line_height)
                    end_line()
                elif child_tag == 'img':
                    # 圖片坐在文字基線上，下面還有一截字的下緣
                    add_to_line(self._est_img_height(child) + 4)
                elif child_tag in self._EST_BLOCK_TAGS:
                    end_line()
                    height += self._est_node_height(child, child_font, metrics)
                else:
                    walk(child, child_font)
                if (child.tail or '').strip():
                    add_to_line(el_font * line_height)

        walk(node, font)
        end_line()
        if tag == 'p':
            height += metrics['p_padding']
        return height

    # 模組預設的字型。範本指定的字型（Lato）沒有中文字，排在它後面的這幾個
    # 接住中文——跟官方報表一樣，最後落在系統的 Noto Sans CJK
    _REPORT_FONT_STACK = "'Microsoft JhengHei','Noto Sans TC',Arial,sans-serif"

    def _report_text_css(self, style):
        """文字的字型、字級、行距、顏色 → CSS（照編輯器的列高算）。

        canvas-editor 每一列的高度是「字高 ＋ 上下各一份留白」，留白＝
        8px × 每列留白倍數（字級 12～30px 時不隨字級放大）。
          * 留白倍數是預設的 1（上下各 8px）：用 <p> 的上下內距表達——一直以來
            的寫法，手做範本的版面不動
          * 範本指定了留白倍數（轉換出來的範本）：留白算進行高，自動換行的
            每一列也有留白，跟編輯器一列一列畫的結果一樣；13px、0.2 倍時
            行高約 1.5，與官方報表相同
        """
        size = style.get('size') or 16
        row_margin = style.get('row_margin') or 1.0
        font = style.get('font') or ''
        family = ("'%s',%s" % (font.replace("'", ''), self._REPORT_FONT_STACK)
                  if font else self._REPORT_FONT_STACK)
        color = style.get('color') or '#000'
        if row_margin == 1.0:
            return ("body{font-family:%s;font-size:%spx;line-height:1.25;"
                    "color:%s;margin:0}p{margin:0;padding:8px 0}"
                    % (family, size, color))
        margin = 8 * row_margin
        line_height = 1.25 + 2 * margin / size
        return ("body{font-family:%s;font-size:%spx;line-height:%.3f;"
                "color:%s;margin:0}p{margin:0;padding:0}"
                % (family, size, line_height, color))

    def _report_css(self, style=None):
        """列印用的最小樣式。

        刻意不帶藥丸網底——定案決策四：匯出只輸出值，網底屬編輯輔助。
        （_flatten_content_json 已經把 label 攤平成純文字，這裡是第二道保險。）

        數字照編輯器（canvas-editor）的預設值，印出來才會跟畫面一樣：
        預設字級 16px；每一列上下各留 8px（字級 12～30px 時固定 8px，
        不隨字級放大，所以用 padding 而不是 line-height 倍數）；
        表格格線黑色、格內距上 0、右下左 5px。
        範本有自己的文字樣式時照範本（style＝doc.template.text_style()）。
        """
        style = style or self.env['doc.template']._DEFAULT_TEXT_STYLE
        return (
            # 先抵銷 Odoo 報表版面（web.minimal_layout）自帶的樣式：
            #   * <body> 是 Bootstrap 的 .container，有最大寬度與左右內距；
            #     紙張設了 css_margins（Odoo 預設的 A4 就是）時再多 11mm 左右內距、
            #     頁首再多 11mm 上內距。邊距已經由範本的 data-report-margin-*
            #     交給 wkhtmltopdf，這些疊上去本文會往內縮、頁首會往下掉
            #   * Bootstrap 的 <p> 有 1rem 下邊距，編輯器的段落之間沒有
            # 選擇器要比 Odoo 的 .o_body_pdf.o_css_margins 更具體才蓋得過
            "body.o_body_pdf.container{padding:0;margin:0;max-width:none}"
            "body.o_body_pdf.container .header{padding-top:0}"
            + self._report_text_css(style) +
            "table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #000;padding:0 5px 5px 5px;vertical-align:top}"
            # 區塊容器（條件區塊／稅額彙總）用單格表格當邊界，但它不是表格，
            # 不可印框線。見 doc.render.mixin._element_block_kind。
            ".doc-block,.doc-block td{border:none;padding:0}"
            # wkhtmltopdf 在 collapse 模式下，沒有框線的表格仍會畫出淡灰色細線
            # （實測），區塊容器改用 separate 才真的看不到
            ".doc-block{border-collapse:separate;border-spacing:0}"
            # 編輯器裡設成無框線的表格：只印格子自己的線（inline 的 border-*），
            # 同樣用 separate 避開 wkhtmltopdf 的淡灰色細線
            ".doc-noborder{border-collapse:separate;border-spacing:0}"
            ".doc-noborder td{border:none}"
            # 並排區塊（外框地址、資訊欄）照編輯器的欄寬：自動排版會把空的
            # 那一格縮成 0，右邊的地址跟著跑到最左邊
            ".doc-layout{table-layout:fixed;width:100%}"
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
