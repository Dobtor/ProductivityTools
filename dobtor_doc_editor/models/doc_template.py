import html as html_mod
import json

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


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
    # 只提供兩張。Odoo 的 external_layout 實測有七種（standard / boxed / bold /
    # striped / folder / wave / bubble），但那七種的差異幾乎全在 CSS（底色、
    # 分隔線、字重、背景圖），canvas-editor 沒有 CSS 繼承，逐一復刻要把每個
    # 樣式手刻進元素屬性，投報率很低。而客戶真正要的通常是「我們公司自己的
    # 版面」，不是 Odoo 的其中一種。
    #
    # 所以這兩張的定位是「起點」，不是「復刻」——命名也刻意用排版方式而不是
    # Odoo 的版面代號，避免讓人以為會長得一樣。

    _LAYOUT_VARIANTS = {
        'side': '標準（logo 左、公司資訊右）',
        'stacked': '置中（logo 置中、公司資訊在下）',
    }

    @staticmethod
    def _layout_cell(*elements, **kw):
        """表格儲存格。結尾一定補換行——canvas-editor 的儲存格都是這個形狀，
        少了它在編輯器裡點進去會沒有可放游標的位置。"""
        value = list(elements) + [{'value': '\n'}]
        return dict({'colspan': 1, 'rowspan': 1, 'value': value}, **kw)

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
            {'value': '\n'},
        ]

        footer = [
            pill('頁尾文字', source='html', path='company_id.report_footer'),
            {'value': '\n'},
            {'value': '第 '},
            pill('頁碼', source='page', part='number'),
            {'value': ' / '},
            pill('總頁數', source='page', part='count'),
            {'value': ' 頁'},
            {'value': '\n', 'rowFlex': 'center'},
        ]
        return {'header': header, 'main': [], 'footer': footer}

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
        tmpl = self.create({
            'name': name,
            'role': 'layout',
            'description': '由模組產生的起點外框，可自由修改。'
                           'logo 與公司資訊取自單據的 company_id。',
        })
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

    def frame_template(self):
        """提供頁首／頁尾與紙張設定的那一張範本。

        沒設外框就是自己——既有範本的行為完全不變。
        """
        self.ensure_one()
        return self.layout_id or self

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

    def action_auto_init_aliases(self):
        """從 self.model_id 自動補上欄位對映（保留既有）。

        **目前沒有 UI 入口**：alias 機制退場中（見 doc_template_views.xml
        的「不再提供新增對映入口」註解），所以這支只剩 API 用途。
        留著是因為 action_* 可能被主模組的視圖以名稱引用，刪掉會讓那邊
        ParseError；真的要清除要先確認沒有外部引用。
        """
        self.ensure_one()
        if not self.model_id:
            raise UserError('請先設定「適用模型」後再使用此功能。')
        result = self.init_aliases_from_model_for(self.model_id.model, overwrite=False)
        if not result.get('success'):
            raise UserError(result.get('error') or '自動生成失敗')
        added = len(result.get('added') or [])
        skipped = len(result.get('skipped') or [])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '自動生成完成',
                'message': f'已新增 {added} 個對映、跳過 {skipped} 個既有對映。',
                'type': 'success',
                'sticky': False,
            },
        }

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
