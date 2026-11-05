import html as html_mod
import json

from lxml import etree

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class DocTemplate(models.Model):
    _name = 'doc.template'
    _description = '文件範本'
    _inherit = ['doc.render.mixin']
    _order = 'name asc'

    name = fields.Char(string='範本名稱', required=True)
    content_html = fields.Html(
        string='範本內容',
        sanitize=False,
        sanitize_attributes=False,
    )
    # Phase 1（藥丸改版）：範本改為可直接在編輯器中編輯，權威格式與 doc.document 對齊。
    #   content_json — canvas-editor IElement[] 序列化結果，編輯器讀寫的主格式。
    #   content_html — 降級為攤平備份，供舊匯出鏈、全文檢索與尚未開過編輯器的舊範本使用。
    # 兩者同時維護：編輯器存檔時一併寫回 content_html（getHTML().main）。
    content_json = fields.Text(
        string='範本內容（Canvas JSON）',
        copy=True,
        help='canvas-editor 的 IElement[] 序列化結果。範本編輯的權威格式；'
             'content_html 為攤平備份，不再是渲染來源。',
    )
    model_id = fields.Many2one(
        'ir.model',
        string='適用模型',
        ondelete='set null',
        help='此範本適用的 Odoo 模型，留空表示通用範本',
    )
    category = fields.Selection([
        ('general', '一般'),
        ('contract', '合約'),
        ('report', '報告'),
        ('letter', '信函'),
        ('other', '其他'),
    ], string='分類', default='general')
    description = fields.Text(string='說明')
    active = fields.Boolean(string='啟用', default=True)
    company_id = fields.Many2one(
        'res.company',
        string='公司',
        default=lambda self: self.env.company,
        help='留空表示所有公司共用此範本。',
    )
    # ─── Phase 1：版本快照（範本開放直接編輯後必須可回溯）───────────────
    # 刻意不與 doc.document 共用 mixin：doc.document 的版本邏輯已被 test_versions.py
    # 覆蓋且牽涉 attachment / chatter，抽共用會動到正常運作的程式。範本沒有大文件
    # attachment 也沒有 mail.thread，自己這份反而更短。日後要合併再一起重構。
    version_number = fields.Integer(
        string='版本號',
        default=0,
        copy=False,
        help='範本版本流水號，每次儲存版本快照時 +1',
    )
    versions_data = fields.Json(
        string='版本快照陣列',
        default=list,
        copy=False,
        help='每筆含 version_no/created_at/author_id/author_name/label/'
             'content_html/content_json。',
    )
    # 頁面邊距（px，與 doc.document 同單位）。
    # 範本必須擁有完整版面設定——報表引擎的前提是「編輯器裡看到的就是列印結果」，
    # 而列印邊距若只存在 doc.document 上，範本模式就沒有邊距可調、
    # 報表渲染也無從取得（原本 _load_template_payload 為此硬寫 96）。
    # ─── 外框範本 ───────────────────────────────────────────────────
    #
    # external_layout 在 Odoo 裡是公司級的共用外框，被所有報表共用。複製進
    # 每一張範本之後，改一次公司地址要改 N 張，而且漏掉哪一張完全看不出來。
    # 所以把「外框」獨立成另一種角色的範本，內容範本只管 main 區。
    role = fields.Selection(
        [('content', '內容範本'), ('layout', '外框範本')],
        string='範本角色', default='content', required=True,
        help='外框範本只提供頁首／頁尾與紙張設定，供多張內容範本共用。',
    )
    layout_id = fields.Many2one(
        'doc.template', string='外框範本',
        domain="[('role', '=', 'layout'), ('id', '!=', id)]",
        ondelete='restrict',
        help='設定後，頁首／頁尾與紙張設定一律取自外框範本。',
    )
    margin_top = fields.Integer(string='上邊距 (px)', default=96)
    margin_bottom = fields.Integer(string='下邊距 (px)', default=96)
    margin_left = fields.Integer(string='左邊距 (px)', default=96)
    margin_right = fields.Integer(string='右邊距 (px)', default=96)
    # wkhtmltopdf 的頁首是「疊在上邊距區」的，頁首比上邊距高就會壓到本文。
    # Odoo 的 paperformat 有 header_spacing 專門處理，模組原本沒有暴露。
    header_spacing = fields.Integer(
        string='頁首間距 (mm)', default=5,
        help='頁首與本文之間的間距。頁首內容比上邊距高時要調大，'
             '否則頁首會壓到本文。',
    )
    footer_spacing = fields.Integer(
        string='頁尾間距 (mm)', default=5,
        help='頁尾與本文之間的間距。',
    )
    # ─── 頁首頁尾的版面屬性（對應 LibreOffice Writer 的「頁首／頁尾」頁籤）
    #
    # LibreOffice 有這幾個，這裡的對照與取捨：
    #   間距（頁首與本文之間）     → header_spacing / footer_spacing（已有）
    #   高度 / 自動調整高度        → 不另開欄位：wkhtmltopdf 的頁首高度就是
    #                              上邊距（margin_top）扣掉間距，另開一個會
    #                              出現「兩個欄位互相矛盾」的狀態
    #   左／右邊距                 → header_padding_x / footer_padding_x
    #                              （wkhtmltopdf 的頁首是另一份文件、鋪滿紙寬，
    #                               本文的左右邊距對它無效，所以要自己留）
    #   邊框（頁首下方那條線）     → header_rule / footer_rule
    #   背景                       → 不做：單據上的頁首底色實務上極少，
    #                              要的話用藥丸放一張圖更可控
    #   「首頁相同」「左右頁相同」 → 不是版面欄位，走頁面範圍標記
    #                              （_PAGE_SCOPE_SOURCE）。理由見那裡的註解
    header_padding_x = fields.Integer(
        string='頁首左右內距 (px)', default=0,
        help='頁首是鋪滿紙張寬度的另一份文件，本文的左右邊距對它無效。\n'
             '要讓頁首與本文對齊，這裡填與左邊距相同的值；\n'
             '要讓 logo 貼齊紙張邊緣就填 0。',
    )
    footer_padding_x = fields.Integer(
        string='頁尾左右內距 (px)', default=0,
        help='同頁首。',
    )
    header_rule = fields.Boolean(
        string='頁首下方分隔線',
        help='對應 LibreOffice 頁首的「邊框」。單據上幾乎都要這條線。',
    )
    footer_rule = fields.Boolean(
        string='頁尾上方分隔線',
        help='對應 LibreOffice 頁尾的「邊框」。',
    )
    # ─── 預設文字樣式
    #
    # 沒設的元素用這組值；留空＝模組預設（16px、正黑體、每列上下各留 8px、黑字）。
    # 編輯器與列印用同一組值，畫面才會跟印出來的一樣。
    # 從原生報表轉換的範本會帶上官方報表的樣式（_OFFICIAL_TEXT_STYLE）；
    # 使用者自己做的範本不受影響。
    text_font = fields.Char(
        string='預設字型',
        help='例如 Lato（Odoo 官方報表用的字型）。中文字一律退回系統的中文字型。',
    )
    text_size = fields.Integer(string='預設字級 (px)')
    text_row_margin = fields.Float(
        string='每列上下留白倍數', digits=(3, 2),
        help='1＝每一列上下各留 8px（編輯器預設）；0.2＝各留 1.6px，接近官方報表的行距。',
    )
    text_color = fields.Char(string='預設文字顏色', help='例如 #212529。')

    page_format = fields.Selection([
        ('A4', 'A4'),
        ('A3', 'A3'),
        ('A5', 'A5'),
        ('letter', 'Letter'),
        ('legal', 'Legal'),
    ], string='預設頁面格式', default='A4')
    field_aliases = fields.Json(
        string='欄位別名對映',
        default=dict,
        help=(
            '範本級全域 alias 對映。所有使用此範本的 doc.document 預覽渲染時都會繼承。'
            'Key 支援兩種形式：'
            '1) 中文 token（如「工程名稱」），文件內寫 《工程名稱》 會被替換。'
            '2) 純變數名（如「project_name」），文件內寫 {{ project_name }} 會被替換。'
        ),
    )

    # Phase 8 Template UI Builder（ADR-022）
    signer_ids = fields.One2many(
        'doc.template.signer',
        'template_id',
        string='簽約人角色',
    )
    field_ids = fields.One2many(
        'doc.template.field',
        'template_id',
        string='範本欄位',
    )
    signer_count = fields.Integer(string='簽約人數', compute='_compute_phase8_counts')
    field_count = fields.Integer(string='欄位數', compute='_compute_phase8_counts')

    def _compute_phase8_counts(self):
        for rec in self:
            rec.signer_count = len(rec.signer_ids)
            rec.field_count = len(rec.field_ids)

    # ─── Phase 1：直接在編輯器中編輯範本 ─────────────────────────────

    @api.constrains('role', 'layout_id')
    def _check_layout_chain(self):
        """外框不可再掛外框。

        允許鏈結的話，「這張範本的頁首到底來自哪裡」要追好幾層，而且一旦成環
        就會無限遞迴。一層就夠：外框是共用外框，不是繼承樹。
        """
        for tmpl in self:
            if tmpl.layout_id and tmpl.role == 'layout':
                raise ValidationError(
                    '外框範本不可再指定外框範本（不支援多層外框）。'
                )
            if tmpl.layout_id and tmpl.layout_id.role != 'layout':
                raise ValidationError(
                    '「%s」不是外框範本，不能當作外框使用。'
                    % tmpl.layout_id.display_name
                )

    # ─── 內建外框範本 ───────────────────────────────────────────────
    #
    # 「標準」「置中」兩張是起點。Odoo 的 external_layout 實測有七種（standard /
    # boxed / bold / striped / folder / wave / bubble），但那七種的差異幾乎全在
    # CSS（底色、分隔線、字重、背景圖），canvas-editor 沒有 CSS 繼承，逐一復刻
    # 要把每個樣式手刻進元素屬性，投報率很低。而客戶真正要的通常是「我們公司
    # 自己的版面」，不是 Odoo 的其中一種。所以這兩張的定位是「起點」，不是
    # 「復刻」——命名也刻意用排版方式而不是 Odoo 的版面代號。
    #
    # 例外是第三張「Odoo 標準」：照 web.external_layout_standard 印出來的樣子
    # 做（logo 在左、公司資訊在 logo 下方、頁尾一條線＋灰字頁碼、左右邊距
    # 約 9mm），給從原生報表轉換的範本用——轉換的目標是印得跟官方一樣。
    # 位置與大小照官方 PDF 實測（96dpi 量），一樣換算成本模組 1:1 的版面。

    # Odoo 官方報表的文字樣式，換算成本模組 1:1 的版面：
    # 官方的 CSS 是 Lato 16px、行高 1.5、#212529，但 wkhtmltopdf 會把 1140px 寬的
    # 版面縮到紙寬，實際印出來約 0.8 倍——字級 12.8px、行距 19.2px（實測官方 PDF
    # 的中文字寬推回來）。本模組的 PDF 不縮放，所以直接用縮放後的值。
    # 每列上下留白 0.2 倍（各 1.6px）：13px × 1.25 ＋ 3.2px ≈ 19.5px，接近官方行距。
    _OFFICIAL_TEXT_STYLE = {
        'text_font': 'Lato',
        'text_size': 13,
        'text_row_margin': 0.2,
        'text_color': '#212529',
    }

    _LAYOUT_VARIANTS = {
        'side': '標準（logo 左、公司資訊右）',
        'stacked': '置中（logo 置中、公司資訊在下）',
        'odoo': 'Odoo 標準（與官方報表相同）',
    }
    # 「Odoo 標準」外框的紙張設定（px @96dpi）：
    #   左右 35px＝官方內容離紙邊的距離；上 212px 讓本文（地址）從約 235px 開始；
    #   下 130px 讓本文停在頁尾那條線（約 1003px）上面。
    #   頁首頁尾的左右內距留 0：實測頁首頁尾已經跟著左右邊距內縮，再加內距
    #   會比本文多縮一段
    _LAYOUT_VARIANT_VALS = {
        'odoo': dict({
            'margin_top': 212, 'margin_bottom': 130,
            'margin_left': 35, 'margin_right': 35,
            'footer_rule': True,
        }, **_OFFICIAL_TEXT_STYLE),
    }

    @staticmethod
    def _layout_cell(*elements, **kw):
        """表格儲存格。

        結尾不補換行：canvas-editor 載入格子時一律在最前面補一個段落起點
        （isForceCompensation），游標本來就有位置；結尾的換行反而是
        「下一段的開頭」，會讓每一格多一行空白。
        """
        return dict({'colspan': 1, 'rowspan': 1, 'value': list(elements)}, **kw)

    @staticmethod
    def _layout_pill(label, **meta):
        payload = dict(meta)
        payload['labelText'] = label
        return {
            'type': 'label', 'value': label,
            'label': {'backgroundColor': '#e3f2fd', 'color': '#1976d2'},
            'extension': {'dobtorField': payload},
        }

    def _build_layout_tree(self, variant='side'):
        """產生外框範本的 content_json 結構（header / footer 兩區）。

        欄寬以紙張內寬計算：A4 @96dpi 是 794px，扣掉左右邊距。寬度算錯不會
        報錯，只會讓表格在編輯器裡溢出頁面——那看起來像編輯器壞了。
        """
        self.ensure_one()
        page_w = 1123 if (self.page_format or 'A4') == 'A4_landscape' else 794
        inner = max(200, page_w - (self.margin_left or 96) - (self.margin_right or 96))
        pill = self._layout_pill
        cell = self._layout_cell

        logo = pill('公司 logo', source='image',
                    path='company_id.logo_web', height=48)
        details = pill('公司資訊', source='html',
                       path='company_id.company_details')
        tagline = pill('公司標語', source='html',
                       path='company_id.report_header')

        if variant == 'odoo':
            return self._build_odoo_layout_tree(inner)

        if variant == 'stacked':
            header_rows = [
                {'tdList': [cell(logo)]},
                {'tdList': [cell(details)]},
            ]
            colgroup = [{'width': inner}]
        else:
            logo_w = min(220, int(inner * 0.35))
            header_rows = [{'tdList': [
                cell(logo), cell(details),
            ]}]
            colgroup = [{'width': logo_w}, {'width': inner - logo_w}]

        header = [
            {
                'type': 'table', 'value': '',
                # 外框的版面容器——輸出時不印框線（見 _element_block_kind）
                'extension': {'dobtorBlock': 'layout'},
                'borderType': 'empty',
                'colgroup': colgroup,
                'trList': header_rows,
            },
            {'value': '\n'},
            tagline,
        ]

        footer = [
            pill('頁尾文字', source='html', path='company_id.report_footer'),
        ] + self._page_line_elements()
        return {'header': header, 'main': [], 'footer': footer}

    # 官方頁尾的頁碼是 text-muted 灰字
    _OFFICIAL_MUTED_COLOR = '#6c757d'
    # 官方頁尾離紙底約 100px，本模組的頁尾畫到離底 30px（doc.report
    # 的 _FOOTER_BOTTOM_PX），差的那一段用頁碼下面的空白列補（一列約 19.5px）
    _OFFICIAL_FOOTER_BLANK_ROWS = 3
    # 整列補完還差 6px（頁尾線比官方低一截）：最後再補一列小字級的空白
    _OFFICIAL_FOOTER_TAIL_SIZE = 4

    def _build_odoo_layout_tree(self, inner):
        """「Odoo 標準」外框：照 web.external_layout_standard 的樣子。

        頁首第一列 logo 在左、公司標語（report_header，粗體）在右；
        第二列公司資訊在 logo 下方。頁尾上方一條線（footer_rule）、
        公司頁尾文字，頁碼靠左、灰字，字照官方外框的翻譯（繁中「頁：1 / 1」）。
        位置照官方 PDF 實測（與本文同樣換算成 1:1）：logo 高 51px；logo 與標語
        上下置中（官方是 align-items-center，標語不是貼頂）；logo 下方留一小段
        （官方 mb-2）再接公司資訊。
        """
        pill = self._layout_pill
        cell = self._layout_cell
        logo = pill('公司 logo', source='image', path='company_id.logo_web',
                    height=51)
        tagline = pill('公司標語', source='html', path='company_id.report_header')
        tagline['rowFlex'] = 'right'
        tagline['bold'] = True
        # 官方的 .o_company_tagline 是公司主色（印的時候照公司設定上色）
        tagline['extension'][self.COMPANY_COLOR_KEY] = 'primary'
        half = inner // 2
        header = [
            # 頁首以表格開頭時編輯器會在上面補一列空行（PDF 照印）；字級壓到
            # 最小，logo 才不會比官方低一截
            {'value': '\n', 'size': 3},
            {
                'type': 'table', 'value': '',
                'extension': {'dobtorBlock': 'layout', 'fixedCols': True},
                'borderType': 'empty',
                'colgroup': [{'width': half}, {'width': inner - half}],
                'trList': [{'tdList': [cell(logo, verticalAlign='middle'),
                                       cell(tagline, verticalAlign='middle')]}],
            },
            # logo 與公司資訊之間的留白（官方 mb-2）
            {'value': '\n', 'size': 4},
            {'value': '\n'},
            pill('公司資訊', source='html', path='company_id.company_details'),
        ]
        footer = (
            [pill('頁尾文字', source='html', path='company_id.report_footer')]
            + self._page_line_elements(
                align='left', color=self._OFFICIAL_MUTED_COLOR, official=True)
            + [{'value': '\n'} for _ in range(self._OFFICIAL_FOOTER_BLANK_ROWS)]
            + [{'value': '\n', 'size': self._OFFICIAL_FOOTER_TAIL_SIZE}]
        )
        return {'header': header, 'main': [], 'footer': footer}

    # 頁尾頁碼「第 1 / 1 頁」。繁中沿用這個寫法；其他語言照 Odoo 自己外框的翻譯
    # （web 的「Page <頁碼> / <總頁數>」），沒有翻譯的語言用英文。以前寫死中文，
    # 範本內文依客戶語言切換之後，英文單據的頁尾還夾一行中文。
    _PAGE_LINE_OVERRIDES = {
        'zh_TW': ('第 ', ' / ', ' 頁'),
        'zh_CN': ('第 ', ' / ', ' 页'),
    }
    _PAGE_LINE_DEFAULT = ('Page ', ' / ', '')

    def _page_line_parts(self, official=False):
        """{語言: (頁碼前, 頁碼與總頁數之間, 總頁數後)}，涵蓋所有已啟用語言與 en_US。

        official：照官方外框的字（繁中是「頁：1 / 1」），不套本模組的
        「第 1 / 1 頁」。
        """
        view = self.env.ref('web.external_layout_standard', raise_if_not_found=False)
        parts = {}
        for code, _name in self.env['res.lang'].get_installed():
            parts[code] = ((None if official else self._PAGE_LINE_OVERRIDES.get(code))
                           or self._odoo_page_line(view, code)
                           or self._PAGE_LINE_DEFAULT)
        parts.setdefault('en_US', self._PAGE_LINE_DEFAULT)
        return parts

    def _odoo_page_line(self, view, lang):
        """Odoo 外框裡 <span class="page"/> 那一行在這個語言的前後文字；讀不到回 None。"""
        if view is None:
            return None
        try:
            root = etree.fromstring(view.with_context(lang=lang).arch)
            page = root.xpath('//span[@class="page"]')[0]
            topage = root.xpath('//span[@class="topage"]')[0]
        except (etree.LxmlError, ValueError, IndexError):
            return None
        holder = page.getparent()
        if topage.getparent() is not holder:
            return None
        return (holder.text or '', page.tail or '', topage.tail or '')

    def _page_line_elements(self, align='center', color=None, official=False):
        """頁尾頁碼那一行的元素（開頭的換行算在內）。

        頁碼前後的字各是一顆多語文字；所有語言都一樣的（「 / 」）就用純文字。
        allowEmpty：英文的「頁」那個位置是空的，要真的不印，不能退回印中文。
        換行是下一段的開頭：對齊寫在開頭的換行與每個元素上，不是寫在結尾
        （見 doc.render.mixin._elements_to_html）。
        """
        parts = self._page_line_parts(official=official)
        base = self.env.lang if self.env.lang in parts else 'en_US'
        pill = self._layout_pill

        def piece(idx, placeholder):
            texts = {code: values[idx] for code, values in parts.items()}
            if len(set(texts.values())) == 1:
                value = next(iter(texts.values()))
                return [{'value': value}] if value else []
            element = self._i18n_pill({}, texts[base] if texts[base].strip() else placeholder,
                                      texts)
            element['extension'][self.DOBTOR_FIELD_KEY]['allowEmpty'] = True
            return [element]

        line = ([{'value': '\n'}]
                + piece(0, '頁碼前的字')
                + [pill('頁碼', source='page', part='number')]
                + piece(1, '頁碼之間')
                + [pill('總頁數', source='page', part='count')]
                + piece(2, '頁碼後的字'))
        for el in line:
            el['rowFlex'] = align
            if color and el.get('value') != '\n':
                el['color'] = color
        return line

    # 舊版外框寫死中文的那一行：換行之後的五個元素
    _OLD_PAGE_LINE = ('第 ', 'number', ' / ', 'count', ' 頁')

    def _upgrade_page_line(self, tree):
        """把外框頁尾寫死中文的「第 X / Y 頁」換成多語寫法（就地改寫）。回傳有沒有換。

        只換跟舊版一模一樣的那一行：使用者改過字（或刪掉頁碼）的不碰，
        猜錯會蓋掉他的設定。
        """
        footer = tree.get('footer') if isinstance(tree, dict) else None
        if not isinstance(footer, list):
            return False

        def signature(el):
            meta = self._element_field_meta(el)
            if meta and meta.get('source') == 'page':
                return meta.get('part')
            if isinstance(el, dict) and (el.get('type') or 'text') == 'text':
                return el.get('value')
            return None

        size = len(self._OLD_PAGE_LINE)
        for idx in range(len(footer) - size):
            newline = footer[idx]
            window = footer[idx + 1:idx + 1 + size]
            if (isinstance(newline, dict) and newline.get('value') == '\n'
                    and tuple(signature(el) for el in window) == self._OLD_PAGE_LINE):
                footer[idx:idx + 1 + size] = self._page_line_elements()
                return True
        return False

    @api.model
    def find_or_create_layout(self, variant='side'):
        """取得（必要時建立）內建外框範本。

        轉換器用：每轉一張報表就建一張新外框的話，公司資訊又散回 N 份了
        ——外框存在的意義就是共用。所以同名的就直接沿用。
        """
        label = self._LAYOUT_VARIANTS.get(variant) or variant
        name = '外框：%s' % label
        existing = self.with_context(active_test=False).search(
            [('role', '=', 'layout'), ('name', '=', name)], limit=1,
        )
        if existing:
            return existing
        tmpl = self.create(dict({
            'name': name,
            'role': 'layout',
            'description': '由模組產生的起點外框，可自由修改。'
                           'logo 與公司資訊取自單據的 company_id。',
        }, **self._LAYOUT_VARIANT_VALS.get(variant, {})))
        tmpl.content_json = json.dumps(
            tmpl._build_layout_tree(variant), ensure_ascii=False,
        )
        return tmpl

    @api.model
    def action_create_default_layouts(self):
        """建立內建外框範本（可重複執行，已存在的不動）。

        刻意不在安裝時種資料：種了之後使用者改過內容，模組升級又碰到
        noupdate 的老問題（改 XML 無效、要寫 migration）。做成可重跑的動作，
        要就按、不要就不按，升級也不會覆蓋他改過的版本。
        """
        for variant in self._LAYOUT_VARIANTS:
            self.find_or_create_layout(variant)
        return {
            'type': 'ir.actions.act_window',
            'name': '外框範本',
            'res_model': 'doc.template',
            'view_mode': 'list,form',
            'domain': [('role', '=', 'layout')],
            'context': {'default_role': 'layout'},
        }

    def _preview_tree(self, tree, record):
        """範本「顯示實際值」：用一筆範例記錄跑完整快照，回傳填好值的元素樹（不存檔）。

        跟報表接管列印走同一套（doc.report._build_report_html）：條件、重複列、
        稅額彙總全部展開，語言也照列印時的規則挑。這樣在範本裡看到的就是
        印給這筆記錄時會長的樣子。tree 會被就地改寫，呼叫端要給一份副本。
        """
        self.ensure_one()
        lang = self.env['doc.report']._customer_lang(record)
        # 語言要套在求值環境上，不只記錄——不然日期格式照操作者語言
        in_lang = self.with_context(lang=lang)
        return in_lang._snapshot_content_json(tree, in_lang._record_in_lang(record, lang))

    def frame_template(self):
        """提供頁首／頁尾與紙張設定的那一張範本。

        沒設外框就是自己——既有範本的行為完全不變。
        """
        self.ensure_one()
        return self.layout_id or self

    # 模組預設：與 canvas-editor 的預設值一致（官方報表的樣式 _OFFICIAL_TEXT_STYLE
    # 定義在內建外框那一段之前，「Odoo 標準」外框要用它）
    _DEFAULT_TEXT_STYLE = {
        'font': '', 'size': 16, 'row_margin': 1.0, 'color': '#000000',
    }

    def text_style(self):
        """這張範本的預設文字樣式（沒設的取模組預設）→ {font, size, row_margin, color}。

        編輯器（canvas-editor 的 defaultFont／defaultSize／defaultRowMargin／
        defaultColor）與列印（doc.report._report_css）都讀這一份。
        """
        style = dict(self._DEFAULT_TEXT_STYLE)
        if not self:
            return style
        self.ensure_one()
        if self.text_font:
            style['font'] = self.text_font.strip()
        if self.text_size and self.text_size > 0:
            style['size'] = self.text_size
        if self.text_row_margin and self.text_row_margin > 0:
            style['row_margin'] = self.text_row_margin
        if self.text_color:
            style['color'] = self.text_color.strip()
        return style

    @api.model
    def action_new_and_open_editor(self):
        """建一張空白範本後直接進編輯器（跳過表單）。

        以前刻意**不**這樣做，理由是「沒有適用模型就沒有欄位可拖，編輯器只會
        叫使用者去表單設」——進去第一件事是再出來。那個缺口已經補掉：左欄在
        沒有模型時提供「設定適用模型」的就地選單
        （/dobtor_doc/models + /dobtor_doc/set_model）。

        角色預設 content：外框範本是少數，而且通常是從既有的複製出來的。
        """
        template = self.create({
            'name': _('未命名範本'),
            'role': 'content',
        })
        return template.action_open_editor()

    def action_open_settings_form(self):
        """開這張範本的表單（清單點一筆會直接進編輯器，設定要有另一條路）。

        表單上才有而編輯器沒有的：適用模型、角色（內容／外框）、使用的外框、
        紙張格式、頁首頁尾的版面屬性、簽約人與待填欄位。那些是**設計時決定
        一次**的設定，不是內容。
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('範本設定'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_open_editor(self):
        """開啟全螢幕編輯器編輯「範本本身」。

        與 doc.document.action_open_editor 走同一支 client action，
        差別在 context 帶的是 template_id，前端據此進入 editTarget='template'。
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'dobtor_doc_editor.action_doc_editor',
            'context': {
                'template_id': self.id,
                'doc_name': self.name,
            },
            'target': 'fullscreen',
        }

    def get_content_html(self):
        """與 doc.document.get_content_html() 同名，讓控制器可統一呼叫。

        範本沒有大文件 attachment 機制，直接回 content_html。
        """
        self.ensure_one()
        return self.content_html or ''

    # ─── Phase 1：版本快照 ───────────────────────────────────────────

    def action_save_version(self, label=None):
        """儲存範本版本快照。回傳 {'version_number': N}。"""
        self.ensure_one()
        self.version_number = (self.version_number or 0) + 1
        versions = list(self.versions_data or [])
        versions.append({
            'version_no': self.version_number,
            'created_at': fields.Datetime.now().isoformat(),
            'author_id': self.env.user.id,
            'author_name': self.env.user.name or '匿名',
            'label': label or '',
            'content_html': self.content_html or '',
            'content_json': self.content_json or '',
        })
        self.versions_data = versions
        return {'version_number': self.version_number}

    def get_version_list(self):
        """版本清單（不含 content，輕量）。最新版在前。"""
        self.ensure_one()
        versions = sorted(
            list(self.versions_data or []),
            key=lambda v: v.get('version_no', 0),
            reverse=True,
        )
        return [
            {
                'version_id': v.get('version_no'),
                'version_number': v.get('version_no'),
                'date': v.get('created_at'),
                'author_id': v.get('author_id'),
                'author_name': v.get('author_name', '匿名'),
                'label': v.get('label', ''),
            }
            for v in versions
        ]

    def _find_version_entry(self, version_id):
        for v in (self.versions_data or []):
            if v.get('version_no') == version_id:
                return v
        return None

    def get_version_content(self, version_id):
        """取單一版本的完整內容。"""
        self.ensure_one()
        entry = self._find_version_entry(version_id)
        if not entry:
            return {'error': f'版本 {version_id} 不存在'}
        return {
            'version_number': entry.get('version_no'),
            'content_html': entry.get('content_html', ''),
            'content_json': entry.get('content_json', ''),
            'label': entry.get('label', ''),
        }

    def restore_version(self, version_id):
        """還原到指定版本。還原前先把「當前內容」存成一個新版本，避免覆蓋後無法回頭。"""
        self.ensure_one()
        entry = self._find_version_entry(version_id)
        if not entry:
            return {'success': False, 'error': f'版本 {version_id} 不存在'}
        self.action_save_version(label=f'還原 v{version_id} 前的自動快照')
        self.write({
            'content_html': entry.get('content_html', ''),
            'content_json': entry.get('content_json', ''),
        })
        return {'success': True, 'version_number': self.version_number}

    def diff_versions(self, version_id_a, version_id_b):
        """段落層級 diff 兩個版本。回傳 opcodes，或 None（任一版本不存在）。

        與 doc.document.diff_versions 是同一份純函式邏輯（只依賴 get_version_content）。
        刻意複製而非抽共用：抽出去要動 doc.document 那份被 test_versions.py 覆蓋的程式，
        為了 40 行去冒回歸風險不划算。兩份要一起改時 grep diff_versions 即可。
        """
        self.ensure_one()
        import difflib
        import re as _re
        from html import unescape

        def _to_lines(html):
            t = _re.sub(
                r'<br\s*/?>|</(p|div|h\d|li|tr)>',
                '\n', html or '', flags=_re.I,
            )
            t = _re.sub(r'<[^>]+>', '', t)
            t = unescape(t)
            return [ln.strip() for ln in t.split('\n') if ln.strip()]

        a = self.get_version_content(version_id_a)
        b = self.get_version_content(version_id_b)
        if not a or a.get('error') or not b or b.get('error'):
            return None

        lines_a = _to_lines(a.get('content_html'))
        lines_b = _to_lines(b.get('content_html'))
        sm = difflib.SequenceMatcher(None, lines_a, lines_b)
        return {
            'a_version': a.get('version_number'),
            'b_version': b.get('version_number'),
            'a_date': None,
            'b_date': None,
            'opcodes': [
                {'op': tag, 'a_lines': lines_a[i1:i2], 'b_lines': lines_b[j1:j2]}
                for tag, i1, i2, j1, j2 in sm.get_opcodes()
            ],
        }

    # ─── L2-v2 範本級 alias 管理（form view 用）──────────────────────
    alias_count = fields.Integer(
        string='對映數',
        compute='_compute_alias_count',
        help='範本目前定義的中文/變數名 alias 對映總數',
    )
    field_aliases_display = fields.Html(
        string='對映預覽',
        compute='_compute_field_aliases_display',
        sanitize=False,
        sanitize_attributes=False,
        store=False,
    )

    @api.depends('field_aliases')
    def _compute_alias_count(self):
        for rec in self:
            rec.alias_count = len(rec.field_aliases or {})

    @api.depends('field_aliases')
    def _compute_field_aliases_display(self):
        for rec in self:
            aliases = rec.field_aliases or {}
            if not aliases:
                rec.field_aliases_display = (
                    '<div style="padding:16px;background:#fef9c3;border:1px solid #fde047;'
                    'border-radius:6px;color:#713f12;text-align:center">'
                    '<i class="fa fa-info-circle me-2"/>'
                    '尚未建立任何對映。按下方「從關聯模型自動生成」開始'
                    '</div>'
                )
                continue
            # 分組：中文 token vs 變數名
            import re as _re
            token_rows, var_rows = [], []
            for key in sorted(aliases.keys(), key=lambda k: (not _re.match(r'^[A-Za-z_]\w*$', k), k)):
                val = aliases[key]
                row = (
                    '<tr>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #f1f5f9">'
                    f'<code style="background:#e3f2fd;color:#1565c0;padding:1px 6px;border-radius:3px">'
                    f'{html_mod.escape(key)}</code></td>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;color:#475569">→</td>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;font-family:monospace;font-size:12px">'
                    f'{html_mod.escape(val)}</td>'
                    '</tr>'
                )
                if _re.match(r'^[A-Za-z_]\w*$', key):
                    var_rows.append(row)
                else:
                    token_rows.append(row)

            def _section(title, rows):
                if not rows:
                    return ''
                return (
                    f'<h6 style="margin:12px 0 6px;color:#475569">{title}（{len(rows)}）</h6>'
                    '<table style="width:100%;border-collapse:collapse;font-size:13px">'
                    + ''.join(rows) +
                    '</table>'
                )

            rec.field_aliases_display = (
                f'<div style="padding:8px">'
                f'{_section("中文 Token（《xxx》 形式）", token_rows)}'
                f'{_section("變數名（{{ xxx }} 形式）", var_rows)}'
                '</div>'
            )

    def action_clear_aliases(self):
        """清空所有對映（需確認）。"""
        self.ensure_one()
        self.field_aliases = {}
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '已清空',
                'message': '所有對映已移除。',
                'type': 'warning',
                'sticky': False,
            },
        }

    # ─── Selection 欄位速查 ────────────────────────────────────────────
    selection_fields_display = fields.Html(
        string='Selection 欄位速查',
        compute='_compute_selection_fields_display',
        sanitize=False,
        sanitize_attributes=False,
        store=False,
    )

    @api.depends('model_id')
    def _compute_selection_fields_display(self):
        for rec in self:
            if not rec.model_id:
                rec.selection_fields_display = (
                    '<div style="padding:16px;background:#f8fafc;border:1px dashed #cbd5e1;'
                    'border-radius:6px;color:#64748b;text-align:center">'
                    '請先設定「適用模型」以列出 Selection 欄位。</div>'
                )
                continue
            model_name = rec.model_id.model
            if model_name not in rec.env:
                rec.selection_fields_display = (
                    f'<div style="color:#dc2626">模型「{html_mod.escape(model_name)}」未載入</div>'
                )
                continue
            try:
                Model = rec.env[model_name]
                rows = []
                # ir.model.fields 比 _fields 慢但能拿到 field_description（中文 label）
                selection_recs = rec.env['ir.model.fields'].sudo().search([
                    ('model', '=', model_name),
                    ('ttype', '=', 'selection'),
                ], order='field_description asc')
                for f in selection_recs:
                    label = html_mod.escape(f.field_description or '')
                    name = html_mod.escape(f.name)
                    # 拿可能值（透過 model field 取 _description_selection）
                    options_html = ''
                    try:
                        field = Model._fields.get(f.name)
                        if field:
                            choices = field._description_selection(rec.env)
                            opts = []
                            for val, lab in choices:
                                opts.append(
                                    f'<span style="background:#fef3c7;color:#78350f;'
                                    f'padding:1px 6px;border-radius:3px;margin-right:4px;'
                                    f'font-size:11px;display:inline-block;margin-bottom:2px">'
                                    f'{html_mod.escape(str(val))} = {html_mod.escape(str(lab))}'
                                    '</span>'
                                )
                            options_html = ''.join(opts) or '<em style="color:#94a3b8">（無選項）</em>'
                    except Exception as exc:
                        options_html = f'<em style="color:#dc2626">無法取得選項：{html_mod.escape(str(exc))}</em>'

                    rows.append(
                        '<tr>'
                        f'<td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;'
                        f'vertical-align:top;white-space:nowrap">'
                        f'<strong>{label}</strong><br/>'
                        f'<code style="font-size:11px;color:#64748b">{name}</code>'
                        '</td>'
                        f'<td style="padding:6px 8px;border-bottom:1px solid #f1f5f9">'
                        f'{options_html}'
                        '</td>'
                        '</tr>'
                    )
                if not rows:
                    rec.selection_fields_display = (
                        f'<div style="padding:16px;background:#f8fafc;border:1px dashed #cbd5e1;'
                        f'border-radius:6px;color:#64748b">'
                        f'模型「{html_mod.escape(model_name)}」沒有 Selection 欄位。</div>'
                    )
                else:
                    rec.selection_fields_display = (
                        f'<div style="margin-bottom:8px;font-size:12px;color:#64748b">'
                        f'模型 <code>{html_mod.escape(model_name)}</code> 共 {len(rows)} 個 Selection 欄位。'
                        f'渲染時可用 <code>selection_label(\'欄位名\')</code> 取得中文 label。</div>'
                        '<table style="width:100%;border-collapse:collapse;font-size:13px">'
                        '<thead><tr style="background:#f1f5f9">'
                        '<th style="padding:6px 8px;text-align:left;width:25%">欄位</th>'
                        '<th style="padding:6px 8px;text-align:left">可能值</th>'
                        '</tr></thead>'
                        '<tbody>'
                        + ''.join(rows) +
                        '</tbody></table>'
                    )
            except Exception as exc:
                rec.selection_fields_display = (
                    f'<div style="color:#dc2626;padding:12px">'
                    f'掃描失敗：{html_mod.escape(str(exc))}</div>'
                )
