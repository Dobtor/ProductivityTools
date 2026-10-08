"""RenderTree — 元素樹的詞彙與走訪。

canvas-editor 的 content_json 是一棵「扁平元素串列 + 表格巢狀」的樹。
這個模組只放兩件事：**詞彙**（各種 source 常數、meta 的讀取）與**走訪**
（走到每個元素、每張表格、每個段落）。

為什麼走訪要獨立成一層：條件、重複、格式、輸出四條路都要走同一棵樹，
而「段落的邊界是 value == '\n'」「表格是唯一可靠的巢狀容器」這兩個前提
一旦有人在某一條路上自己重寫，就會出現「某一關看得到、另一關看不到」的
不對稱——那種 bug 不會報錯，只會少印東西。
"""
import re


class RenderTree:

    # ─── 元素樹走訪 ──────────────────────────────────────────────────
    #
    # content_json 是 canvas-editor getValue().data，形狀為
    #   {header: [...], main: [...], footer: [...]}
    # 只走 main 會漏掉頁首頁尾的變數；不遞迴 trList/tdList 會漏掉表格內的變數。
    # 快照、攤平、遷移三支共用這裡，不各寫一份。

    _ELEMENT_ZONES = ('header', 'main', 'footer')

    def _iter_element_lists(self, tree):
        """yield 樹中每一個「元素串列」（含頁首/頁尾/表格儲存格/超連結子串）。

        yield 的是 list 物件本身，呼叫端可就地改寫（攤平需要換掉元素）。
        """
        if isinstance(tree, dict):
            roots = [tree[z] for z in self._ELEMENT_ZONES
                     if isinstance(tree.get(z), list)]
            if not roots and not any(z in tree for z in self._ELEMENT_ZONES):
                # 少數舊資料直接存成單一 list 包在 dict 裡的情況，盡量容錯
                roots = [v for v in tree.values() if isinstance(v, list)]
        elif isinstance(tree, list):
            roots = [tree]
        else:
            return

        stack = list(roots)
        while stack:
            elements = stack.pop()
            yield elements
            for el in elements:
                if not isinstance(el, dict):
                    continue
                # 超連結 / 日期等群組元素的子串
                if isinstance(el.get('valueList'), list):
                    stack.append(el['valueList'])
                # 表格：trList → tdList → value（value 在儲存格內是元素串列）
                for row in (el.get('trList') or []):
                    if not isinstance(row, dict):
                        continue
                    for cell in (row.get('tdList') or []):
                        if isinstance(cell, dict) and isinstance(cell.get('value'), list):
                            stack.append(cell['value'])

    def _iter_elements(self, tree):
        """yield 樹中每一個元素 dict。"""
        for elements in self._iter_element_lists(tree):
            for el in elements:
                if isinstance(el, dict):
                    yield el

    # ─── 藥丸綁定 meta ───────────────────────────────────────────────

    DOBTOR_FIELD_KEY = 'dobtorField'

    # ─── 圖片與頁碼 ─────────────────────────────────────────────────
    #
    # 這兩種藥丸的共同點：**值不是文字**，所以攤平時不能變成文字元素。
    # 圖片要變成 image 元素（否則 data URI 會被當字串印出來，實測確認過），
    # 頁碼要變成 wkhtmltopdf 認得的 span。
    #
    # 圖片對應原生報表的 image_data_uri(doc.signature)——客戶簽名每張單據都
    # 不同，所以不能像公司 logo 那樣貼死一張圖。
    _IMAGE_SOURCE = 'image'
    _PAGE_SOURCE = 'page'
    # Html 欄位（條款、公司資訊、頁尾文字）。純量藥丸會把值逸出成可見的
    # <p>、<strong> 標籤——實測確認過，而且完全不報錯。
    # external_layout 的外框幾乎全是 Html 欄位，所以這個來源是外框轉換的前提。
    _HTML_SOURCE = 'html'
    # i18n：使用者自己打進範本的靜態文字。欄位「值」的語言由 ORM 依
    # with_context(lang=) 負責，不需要這個。
    _I18N_SOURCE = 'i18n'
    # 欄位標籤（不是值）。明細表的表頭「品名／數量／單價／小計」就是欄位
    # 標籤，而 Odoo 自己的 .po 早就翻好了——走 i18n 藥丸等於請使用者把
    # Odoo 的翻譯再抄一遍，每個語言一次，而且之後各自漂移。
    # 這個來源直接讀 fields_get()['string']，語言跟著渲染語言走。
    _FIELD_LABEL_SOURCE = 'fieldLabel'
    # 頁面範圍標記：這一段只在「首頁／續頁／奇數頁／偶數頁」出現。
    # 對應 LibreOffice 的「首頁相同」與「左右頁相同」兩個勾選，但做法不同：
    # 那兩個是版面設定，這裡是標記——因為我們的頁首頁尾是一份 HTML，
    # wkhtmltopdf 每頁重畫一次並在網址上帶 page 參數，所以「哪一段要出現」
    # 只能在那一刻決定（見 doc.report._page_scope_script）。
    _PAGE_SCOPE_SOURCE = 'pageScope'
    _PAGE_SCOPES = ('first', 'rest', 'odd', 'even')

    def _element_field_meta(self, element):
        """取出元素的綁定定義；不是模型變數藥丸就回 None。"""
        if not isinstance(element, dict) or element.get('type') != 'label':
            return None
        meta = (element.get('extension') or {}).get(self.DOBTOR_FIELD_KEY)
        return meta if isinstance(meta, dict) else None

    # ─── 區塊容器 ────────────────────────────────────────────────────
    #
    # 「條件區塊」「稅額彙總」這類需要包住多段內容的構件，容器一律用
    # 單格表格。理由：元素串列是扁平的，只有 value=='\n' 與表格列是可靠邊界；
    # 跨段落的起訖標記在使用者編輯時極易被拆散，而拆散後的結果無從察覺。
    # 表格則是原子結構——使用者刪就整個刪，不可能只刪掉一半。
    #
    # 副作用：容器本身是表格，輸出時必須不印框線（見 _table_to_html 的
    # doc-block class 與四條輸出路徑的 CSS）。

    _BLOCK_KEY = 'dobtorBlock'

    def _element_block_kind(self, element):
        """表格元素的區塊種類（'condition' / 'taxTotals'）；不是區塊容器回 ''。"""
        if not isinstance(element, dict) or element.get('type') != 'table':
            return ''
        kind = (element.get('extension') or {}).get(self._BLOCK_KEY)
        return kind if isinstance(kind, str) else ''

    # ─── i18n 工具 ──────────────────────────────────────────────────
    #
    # 沒有這兩個工具，i18n 藥丸不會被用起來：沒人會回頭把一張做好的中文範本
    # 裡幾十段文字一個一個改成藥丸，也沒人會為了翻譯讓譯者登入 Odoo。

    def _iter_text_runs(self, tree):
        """yield (元素串列, 起, 迄, 文字)。

        連續的純文字元素合成一個「run」。換行、藥丸、表格都是 run 的邊界——
        跨越這些邊界合併會把兩段不相干的文字黏成一個翻譯字串。
        """
        for elements in self._iter_element_lists(tree):
            start = None
            for idx, el in enumerate(elements + [None]):
                is_text = (
                    isinstance(el, dict)
                    and (el.get('type') or 'text') == 'text'
                    and (el.get('value') or '') != '\n'
                    and el.get('value')
                )
                if is_text:
                    if start is None:
                        start = idx
                    continue
                if start is not None:
                    text = ''.join(
                        elements[i].get('value') or ''
                        for i in range(start, idx)
                    )
                    if text.strip():
                        yield elements, start, idx, text
                    start = None

    def _html_has_content(self, html):
        """等同原生報表的 is_html_empty()：沒有可見文字也沒有圖就算空。"""
        if not html:
            return False
        if '<img' in html or '<table' in html:
            return True
        try:
            from lxml import html as lhtml
            text = lhtml.fromstring('<div>%s</div>' % html).text_content()
        except Exception:
            text = re.sub(r'<[^>]+>', '', html)
        return bool((text or '').replace('\u00a0', ' ').strip())

    # ─── 重複列（表格明細）─────────────────────────────────────────
    #
    # 業務單據的核心需求：訂單明細、發票行、出貨品項。純量藥丸只能帶一個值，
    # 多筆必須有「列複製」機制。
    #
    # 兩種新來源：
    #   source='repeat'  放在某一列的任一格，宣告「這一列對 path 重複」
    #                    path 指向主記錄的 one2many / many2many 欄位
    #   source='line'    該列內的欄位，path 相對於「當前明細」而非主記錄
    #
    # 為什麼標記放在「列內的藥丸」而不是列物件（trList[i]）的自訂屬性：
    #   canvas-editor 對 tr 只做 delete n.id、看起來會保留其他 key，但那無法在
    #   沒有瀏覽器的環境實測；而 element.extension 已實測確認會存活序列化。
    #   不確定時選已驗證的機制。副作用是列首多一個可見標記——這其實是優點，
    #   使用者看得到哪一列會重複，刪掉標記就是取消重複。
    #
    # 範圍：只做「表格列重複」，不做任意區塊重複。canvas-editor 的元素串列是
    #   扁平的，任意區塊的起訖標記在使用者編輯時極易被拆散；表格列有天然邊界。

    _REPEAT_SOURCE = 'repeat'
    _LINE_SOURCE = 'line'
    # 分組：標題列每組開頭印一次、小計列每組結尾印一次。
    # 為什麼做「分組」而不做 QWeb 那種累加器（current_subtotal = current_subtotal + ...）：
    #   累加器是 QWeb 因為只能單次順序掃描而被迫採用的實作手法，不是使用者的需求。
    #   使用者心裡想的是「依章節分組，每組印小計」。我們手上有完整 recordset，
    #   可以先分組再聚合——小計變成 group.lines|sum(attribute='...')，實測可用。
    #   在 WYSIWYG 編輯器裡暴露「宣告變數／每列更新／歸零」等於要使用者寫程式，
    #   而且寫錯了只會印出錯誤的數字，沒有任何訊息。
    # 標記（宣告這一列的角色）與取值藥丸分開：
    #   groupHeader / groupFooter  列角色標記
    #   group                      取值藥丸（組名、小計…），放哪一種列都一樣
    # 合成一種的話，「在標題列放一顆小計藥丸」會讓該列被誤判成小計列。
    _GROUP_HEADER_SOURCE = 'groupHeader'
    _GROUP_FOOTER_SOURCE = 'groupFooter'
    _GROUP_VALUE_SOURCE = 'group'
    # 流水藥丸：項次（1,2,3…）與逐列累計。這兩個是真的需要跨列狀態的少數情況，
    # 範圍極小（一個整數／一個浮點數），就放在展開的順序迴圈裡。
    _RUNNING_SOURCE = 'running'
    # 結構期（展開／條件）就處理完的來源：純量求值那一輪一律跳過。
    # 不跳過的後果各不相同但都是靜默的：
    #   line / running / group 會以主記錄重新求值，把每列各自的值蓋成同一個
    #   column 會把條件表達式當成值印出 True / False
    # 放錯位置的藥丸因此會原樣保留標籤文字——讓錯誤在文件上看得見。
    _EXPANSION_SOURCES = (
        _REPEAT_SOURCE, _LINE_SOURCE,
        _GROUP_HEADER_SOURCE, _GROUP_FOOTER_SOURCE, _GROUP_VALUE_SOURCE,
        _RUNNING_SOURCE, 'taxTotals', 'column', 'page',
    )

    # 「宣告」而不是「內容」的藥丸。正常路徑上各自那一關會吃掉它們，但
    # only_pending=True 的匯出路徑不跑那些關卡（它只補值），所以攤平時一定
    # 要丟掉——不丟的話單據上會多出「條件格式」這種標籤文字，更糟的是條件
    # 標記會印出「條件求值的結果」，看起來像真的內容。（實測過三種都會印）
    _MARKER_SOURCES = (
        _REPEAT_SOURCE, _GROUP_HEADER_SOURCE, _GROUP_FOOTER_SOURCE,
        'condition', 'format', 'column',
        # pageScope 不在這裡：它要活到攤平那一刻，由 _flatten_content_json
        # 轉成一個不印字的 pageScope 元素，讓 _elements_to_html 把它變成
        # 段落的 class。放進這個清單會讓它在攤平時被整個丟掉。
    )

    def _is_marker_element(self, element):
        meta = self._element_field_meta(element)
        if not meta:
            return False
        return (bool(meta.get('isMarker'))
                or (meta.get('source') or '') in self._MARKER_SOURCES)

    def _iter_tables(self, tree):
        """yield 樹中所有表格元素（含表格內巢狀表格）。"""
        tables = []
        for elements in self._iter_element_lists(tree):
            for el in elements:
                if (isinstance(el, dict) and el.get('type') == 'table'
                        and isinstance(el.get('trList'), list)):
                    tables.append(el)
        return tables

    def _row_source_meta(self, row, sources):
        """列內第一個 source 落在 sources 的標記藥丸 → (元素, meta, source)。"""
        if not isinstance(row, dict):
            return None, None, ''
        for cell in (row.get('tdList') or []):
            if not isinstance(cell, dict):
                continue
            for el in (cell.get('value') or []):
                meta = self._element_field_meta(el)
                if not meta:
                    continue
                src = (meta.get('source') or '').strip()
                if src in sources:
                    return el, meta, src
        return None, None, ''

    def _row_repeat_meta(self, row):
        """這一列是否為重複列；是則回 (標記藥丸, meta)，否則 (None, None)。"""
        el, meta, _src = self._row_source_meta(row, (self._REPEAT_SOURCE,))
        return el, meta

    def _row_group_meta(self, row):
        """這一列是分組標題／小計列嗎 → (標記藥丸, meta, 'header'|'footer'|'')。"""
        el, meta, src = self._row_source_meta(
            row, (self._GROUP_HEADER_SOURCE, self._GROUP_FOOTER_SOURCE),
        )
        role = ''
        if src == self._GROUP_HEADER_SOURCE:
            role = 'header'
        elif src == self._GROUP_FOOTER_SOURCE:
            role = 'footer'
        return el, meta, role

    def _traverse_path(self, record, path):
        """沿 a.b.c 走值；中途取不到或遇到空值回 False。"""
        target = record
        for part in (path or '').split('.'):
            if not part:
                return False
            try:
                target = target[part]
            except Exception:
                return False
            if target is False or target is None:
                return False
        return target

    def _line_key(self, item, key):
        """取明細的排序鍵。recordset 與 dict 都用 item[key]。"""
        try:
            return item[key]
        except Exception:
            return None

    # ─── 稅額彙總（內建區塊）────────────────────────────────────────
    #
    # 對應原生報表的 t-call="sale.document_tax_totals"——那支子範本自己有迴圈，
    # 單純內聯進範本做不到。
    #
    # 為什麼做成「內建區塊」而不是讓使用者用 repeat 對 tax_totals 這個 dict 重複：
    #   稅額彙總的版型在各國法規下變化不大，但 tax_totals 這個資料結構每個 Odoo
    #   版本都在改（amount_by_group 在 18 就已經消失）。做成內建區塊，升版時改
    #   模組一處；走通用重複則是每個客戶的範本裡都埋著一串
    #   object.tax_totals['subtotals']，升版時要一張一張改，而且錯了只會印出空白。
    #
    # 結構沿用重複列的作法：三列各放一個標記，part 決定它是哪一列。
    # 稅別列會依稅別數複製，其餘兩列原地填值。使用者因此可以各自調整樣式
    # （把總計那列加粗之類），而不是面對一個不能動的黑盒子。
    _TAX_TOTALS_SOURCE = 'taxTotals'

    def _row_tax_totals_meta(self, row):
        el, meta, _src = self._row_source_meta(row, (self._TAX_TOTALS_SOURCE,))
        return el, meta

    # ─── 條件式列印 ───────────────────────────────────────────────────
    #
    # 真實 Odoo 報表的條件分佈（銷售訂單 20 個 t-if 實測）：
    #   單純「欄位有值」10、「欄位沒值」2、值比較 5、複合邏輯 2、呼叫 1
    # 一半是「有值才印」——那類不該要使用者設定條件，用自動收合處理。
    #
    # 三種機制，各有對應的 t-if 類型：
    #   ① 自動收合空段落        涵蓋「欄位有值才印」（規則 A：連靜態標籤一起消失）
    #   ② source='condition'   涵蓋值比較與複合邏輯（段落或表格列）
    #   ③ repeat 的 filter     涵蓋逐明細判斷（not line.display_type 之類）
    #
    # 刻意不做「任意區塊條件」與 t-else：元素串列是扁平的，跨段落的起訖標記在
    # 使用者編輯時極易被拆散，而且拆散後的結果無從察覺。要二擇一就放兩段互補
    # 條件，或做兩張範本由 doc.report 挑。

    _CONDITION_SOURCE = 'condition'

    # ─── 條件式格式 ─────────────────────────────────────────────────
    #
    # 「條件成立就把這一列（或這一段）變成粗體／改色／改對齊」。
    # 為什麼需要它：原生報表用 t-att-class 做這件事
    #   <tr t-att-class="'fw-bold o_line_section' if line.display_type == …">
    # 而我們只能吃靜態 class——條件式的那些只能留待辦。
    #
    # 設計與條件標記對稱（同一套心智模型，使用者學一次就會）：
    #   * 標記藥丸放哪裡決定作用範圍：放在表格列內＝整列，放在段落裡＝整段
    #   * 條件成立才套用；條件求值失敗一律「不套用」
    #     ——這裡刻意與條件標記的「寧可多印」相反：格式套錯（整份變粗體）
    #     比沒套上難追得多，而沒套上只是看起來樸素一點
    #   * 套用完標記就移除，不會印出來
    _FORMAT_SOURCE = 'format'

    def _element_format_meta(self, element):
        meta = self._element_field_meta(element)
        if meta and (meta.get('source') or '') == self._FORMAT_SOURCE:
            return meta
        return None

    def _element_condition_meta(self, element):
        meta = self._element_field_meta(element)
        if meta and (meta.get('source') or '') == self._CONDITION_SOURCE:
            return meta
        return None

    # ─── 段落切分 ────────────────────────────────────────────────────
    #
    # 段落在扁平元素串列裡有可靠邊界：value == '\n' 的元素。
    # 這不是推測——_elements_to_html() 本身就是用它切段落的，所以「整段移除」
    # 與渲染結果一定一致。這也是為什麼條件與重複都只做到段落／列的粒度。

    def _iter_paragraph_spans(self, elements):
        """回傳 [(start, end_exclusive, nl_index or None), ...]。

        nl_index 是該段落結尾的換行元素位置；最後一段可能沒有換行。
        """
        spans = []
        start = 0
        for idx, el in enumerate(elements):
            if isinstance(el, dict) and (el.get('value') or '') == '\n':
                spans.append((start, idx, idx))
                start = idx + 1
        if start < len(elements):
            spans.append((start, len(elements), None))
        return spans

    def _drop_span(self, elements, span):
        """移除一個段落（含其結尾換行，否則會留下一條空行）。"""
        start, end, nl = span
        stop = (nl + 1) if nl is not None else end
        del elements[start:stop]

    # ─── ②b 欄條件 ───────────────────────────────────────────────────
    #
    # 對應原生報表的「折扣欄」那種寫法：一個 t-if 同時掛在 <th> 與每一列的
    # <td> 上（sale 的 display_discount，ir_actions_report_templates.xml:82,119）。
    #
    # 列條件與欄條件是對稱的兩件事：表格有 colgroup，欄邊界跟列一樣可靠。
    # 標記放在該欄的任一格（通常是表頭），後端依該格的起始欄索引把所有列的
    # 同一欄刪掉，colgroup 也一起處理——不然 canvas-editor 的欄寬會跟實際
    # 格數對不上，表格整個歪掉。
    #
    # 跑在列條件之後：列條件的標記可能就放在某一欄裡，先刪欄會讓那個列條件
    # 無聲消失。反過來（列先刪掉、連帶失去欄標記）則是「欄留著」——
    # 與條件求值失敗一致的「寧可多印」方向。

    _COLUMN_SOURCE = 'column'
