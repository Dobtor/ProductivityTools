"""ConvBlocks — 區塊級構造：圖片、稅額彙總、重複（表格與非表格）、條件。

表格那一段最大，因為明細表是報表的主體：重複列、列變體（t-if 在 tr 上）、
欄寬、合併、分組都在這裡。
"""
import ast
import contextlib
import json
import logging
import re
import unicodedata
from odoo import models
from .constants import (
    _logger,
    _ROOT_VARS,
    _WRAPPER_TEMPLATES,
    _LAYOUT_TEMPLATES,
    _TAX_TOTALS_TEMPLATES,
    _TAX_TOTALS_COMPANY_TEMPLATES,
    _WIDGET_WRAPPERS,
    _BLOCK_TAGS,
    _SKIP_TAGS,
    _SIMPLE_PATH_RE,
    _LIT,
    _ROOT_TOKEN_RE,
    _LINE_TOKEN_RE,
)


class ConvBlocks:

    # ─── 圖片 ───────────────────────────────────────────────────────

    def _image_pill(self, node, state):
        src = node.get('t-att-src') or node.get('src') or ''
        m = re.match(r'^image_data_uri\((.+)\)$', (src or '').strip())
        if m:
            path, kind = self._strip_root(m.group(1).strip(), state)
            if path and _SIMPLE_PATH_RE.match(path):
                return self._pill('圖：%s' % path.split('.')[-1], state,
                                  source='image', path=path)
        if 'barcode' in (src or ''):
            self._note(state, '條碼圖片已轉成 QR 藥丸，請確認型別與取值欄位。')
            return self._pill('條碼', state, source='image',
                              barcodeType='QR', path='name', unbound=True)

        # 來源是 t-set 出來的變數或算出來的（發票的付款 QR 就是
        # o._generate_qr_code(...) 的結果）。展開後若是一條欄位路徑就綁路徑，
        # 否則用表達式——圖片藥丸兩種都收。
        expanded, _used = self._expand_symbols(src, state)
        path, _kind = self._strip_root(expanded, state)
        if path and _SIMPLE_PATH_RE.match(path):
            return self._pill('圖：%s' % path.split('.')[-1], state,
                              source='image', path=path)
        mapped = self._map_condition(expanded, state)
        if mapped and _ROOT_TOKEN_RE.search(mapped):
            self._note(
                state,
                '圖片來源是算出來的，已改成表達式請確認：%s → %s'
                % (src[:40], mapped[:90]),
            )
            return self._pill('圖片', state, source='image',
                              expression=mapped, unbound=True)

        self._note(state, '圖片來源需要人工確認：%s' % (src or '（無 src）')[:80])
        return self._pill('圖片（待確認）', state, source='image',
                          path='', unbound=True)


    # ─── 稅額彙總 ───────────────────────────────────────────────────

    # 彙總區塊裡寫死的標籤 → 多語文字藥丸。
    # 稅前小計與稅別的名稱是 Odoo 給的（已經依記錄語言翻好），只有「總計」
    # 與「現金捨入」是我們自己寫的字——寫死中文的話，英文單據上就會夾一個
    # 中文的「總計」。
    _TAX_TOTALS_LABELS = {
        'total': ('doc_tax_total', {'zh_TW': '總計', 'en_US': 'Total'}),
        'rounding': ('doc_tax_rounding',
                     {'zh_TW': '現金捨入', 'en_US': 'Rounding'}),
    }

    def _tax_totals_block(self, state, mode='document'):
        def val(part, field, label):
            return self._pill(label, state, source='taxTotals', part=part,
                              field=field, currencyMode=mode)

        def label(part):
            key, texts = self._TAX_TOTALS_LABELS[part]
            return self._pill(texts['zh_TW'], state, source='i18n',
                              key=key, texts=dict(texts))

        cell = lambda *els: {'colspan': 1, 'rowspan': 1,
                             'value': list(els) + [self._newline()]}
        inner = self._inner_width(state)
        return {
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'taxTotals'},
            'borderType': 'empty',
            'colgroup': [{'width': int(inner * 0.6)},
                         {'width': inner - int(inner * 0.6)}],
            'trList': [
                # 小計列依 tax_totals['subtotals'] 的筆數複製（多稅基時有好幾列）
                {'tdList': [cell(val('untaxed', 'label', '稅前小計')),
                            cell(val('untaxed', 'amount', '金額'))]},
                {'tdList': [cell(val('groups', 'label', '稅別')),
                            cell(val('groups', 'amount', '稅額'))]},
                # 現金捨入：沒設定時 tax_totals 裡沒有那個鍵，這一列不印
                {'tdList': [cell(label('rounding')),
                            cell(val('rounding', 'amount', '捨入金額'))]},
                {'tdList': [cell(label('total')),
                            cell(val('total', 'amount', '總計金額'))]},
            ],
        }

    def _ternary_pill(self, node, value_expr, cond, state):
        """「有條件的取值」→ 一顆 Jinja 三元式藥丸。

        完全等價、不動版面、也不必多一個區塊容器。條件不成立時印空字串，
        而空字串會讓段落收合規則（規則 A）把整段帶走——跟原生「整段不印」
        的結果一致。
        """
        mapped = self._map_condition(cond, state, expand=True)
        whole = '%s if (%s) else ""' % (value_expr, mapped)
        label = ''
        # 取值節點裡的文字是設計師放的範例值（<span t-field="…">27.00</span>），
        # 拿來當標籤會在編輯器裡看到一顆「27.00」，像是寫死的數字。用欄位名
        has_value = (any(node.get(a) for a in ('t-field', 't-out', 't-esc'))
                     or node.xpath('.//*[@t-field or @t-out or @t-esc]'))
        if not has_value:
            label = ' '.join((''.join(node.itertext()) or '').split())[:20]
        if not label:
            paths = re.findall(r'\b(?:object|line)\.([\w.]+)', value_expr or '')
            label = (paths[0].split('.')[-1] if paths
                     else (value_expr or '').split('.')[-1].strip('()\'"'))[:20]
        state['stats']['condition'] += 1
        return self._pill(
            label or '條件取值', state,
            source='line' if _LINE_TOKEN_RE.search(whole) else 'record',
            expression=whole,
            unbound=bool(state.get('chain_unsure')),
        )

    def _lone_condition(self, node, cond, out, state):
        """掛在非區塊節點上的單獨 t-if。處理掉回 True，沒處理回 False。

        兩條路：
          ① 分支能收成一句表達式（純文字、或只有一個取值節點）→ 三元式藥丸。
          ② 其他 → 條件區塊。那會自成一段（比原本多一個換行），但「印出一段
             該藏起來的內容」比「版面多一個換行」嚴重得多。
        """
        state['chain_unsure'] = False
        expr = self._branch_expr(node, state)
        if expr is not None:
            out.append(self._ternary_pill(node, expr, cond, state))
            return True

        with self._in_width(state, self._block_body_width(state)):
            inner = self._conditional_body(node, state)
        if not inner:
            return True
        if (inner[-1].get('value') or '') != '\n':
            inner.append(self._newline())
        self._note(
            state,
            '條件「%s」原本掛在行內節點上，已包成條件區塊（會自成一段）。'
            '若它原本是句子中間的一小段，版面會多一個換行。' % cond[:60],
        )
        out.append(self._condition_wrap(cond, inner, state))
        out.append(self._newline())
        return True


    # ─── 非表格的重複 ───────────────────────────────────────────────

    def _repeat_block(self, node, state):
        """非表格的 t-foreach → 單欄無框表格，一列重複。回不了就 None。

        編輯器的重複只認「表格列」（後端 _expand_repeat_rows 複製的是 trList
        裡的列），所以 QWeb 用 <div>／<li> 跑的清單必須先變成一欄的表格。
        自己包表格比丟一句「請改用表格呈現」好兩件事：內容會留著，而且
        使用者拿到的是一個已經會重複的結構，只要把來源欄位挑對就能用。

        發票的分期明細（payment_term_details）就是這一類。
        """
        # 迴圈體裡有表格或表格列時不能包：canvas-editor 的巢狀表格在
        # 編輯器與 PDF 兩邊都不可靠（這也是整個管線只做到「列」粒度的原因）。
        if node.xpath('.//table | .//tr'):
            return None
        expr = node.get('t-foreach')
        as_var = node.get('t-as') or 'line'
        # 同一個節點上的 t-if 是「整個迴圈要不要印」，不是逐筆條件。
        # 兩者語意不同，所以不能當成 rowFilter——包一層條件區塊才對。
        cond = node.get('t-if') or node.get('t-elif')
        marker = self._repeat_marker((expr, as_var), state)

        # 迴圈體＝這個節點自己的內容。屬性在這裡處理完了，不要再往下看，
        # 否則 t-foreach 會被子層再認一次。
        holder = self._new_element('t')
        holder.text = node.text
        for child in list(node):
            holder.append(child)
        # 有條件時這張表格本身在條件區塊裡，要再窄一層
        table_w = (self._block_body_width(state) if cond
                   else self._inner_width(state))
        state['loop_vars'].append(as_var)
        state.setdefault('loop_sources', []).append((expr or '').strip())
        state.setdefault('loop_models', []).append(self._loop_model(state, expr))
        try:
            inner = []
            with self._in_width(state, table_w - self._CELL_PADDING):
                self._emit_children(holder, inner, state)
        finally:
            state['loop_vars'].pop()
            if state.get('loop_sources'):
                state['loop_sources'].pop()
            if state.get('loop_models'):
                state['loop_models'].pop()
        if not inner or (inner[-1].get('value') or '') != '\n':
            inner.append(self._newline())

        state['stats']['repeat'] += 1
        self._note(
            state,
            '清單式的 t-foreach="%s" 已轉成單欄表格（重複只支援表格列）；'
            '外框是無框的，版面看起來與原本一致。' % expr[:60],
        )
        table = {
            'type': 'table', 'value': '',
            'borderType': 'empty',
            'colgroup': [{'width': table_w}],
            'trList': [{'tdList': [{
                'colspan': 1, 'rowspan': 1,
                'value': [marker] + inner,
            }]}],
        }
        if not cond:
            return table
        self._note(
            state,
            '重複區塊「%s」外面原本的條件「%s」是「整段要不要印」，'
            '已包成一個條件區塊。' % (expr[:40], cond[:50]),
        )
        return self._condition_wrap(cond, [table, self._newline()], state)


    # ─── 表格 ───────────────────────────────────────────────────────

    # canvas-editor 的 tdPadding 左右各 5px，再加左右框線
    _CELL_PADDING = 12

    def _inner_width(self, state):
        """目前這一層可用的寬度（px）。

        在格子或條件區塊裡面時是那一格的寬度，不是整頁寬：以前一律回整頁寬，
        格子裡的條件區塊在編輯器裡會超出右邊距（PDF 會自動縮，看不出來）。
        """
        stack = state.get('width_stack')
        if stack:
            return stack[-1]
        page_w = 1123 if state.get('page_format') == 'A4_landscape' else 794
        return max(200, page_w - 192)

    @contextlib.contextmanager
    def _in_width(self, state, width):
        """在這個區塊內轉出來的巢狀表格，寬度以 width 為上限。"""
        stack = state.setdefault('width_stack', [])
        stack.append(max(40, int(width)))
        try:
            yield
        finally:
            stack.pop()

    def _block_body_width(self, state):
        """包在單欄區塊（條件、重複）裡的內容可用的寬度。"""
        return self._inner_width(state) - self._CELL_PADDING

    def _table_tax_totals(self, node):
        """表格裡有沒有稅額彙總子範本的呼叫。

        回 (mode, 是否排在第一列之前)；沒有回 (None, False)。
        順序要看：發票那張表格除了稅額彙總還有付款紀錄列，原生是
        「先彙總、後付款」。
        """
        mode = None
        call_pos = None
        for idx, el in enumerate(node.iter()):
            key = (el.get('t-call') or '').strip() if isinstance(el.tag, str) \
                else ''
            if not key:
                continue
            if key in _TAX_TOTALS_COMPANY_TEMPLATES:
                mode, call_pos = 'company', idx
                break
            if key in _TAX_TOTALS_TEMPLATES:
                mode, call_pos = 'document', idx
                break
        if mode is None:
            return None, False
        first_row = None
        for idx, el in enumerate(node.iter()):
            tag = el.tag if isinstance(el.tag, str) else ''
            if tag.lower() == 'tr' and self._closest_table(el) is node:
                first_row = idx
                break
        return mode, first_row is None or call_pos < first_row

    def _closest_table(self, node):
        parent = node.getparent()
        while parent is not None:
            tag = parent.tag if isinstance(parent.tag, str) else ''
            if tag.lower() == 'table':
                return parent
            parent = parent.getparent()
        return None

    def _emit_table(self, node, state):
        # 一律用 .//tr 再濾掉巢狀表格的列。
        # 原本寫 './tbody/tr' 的後果是明細列整個消失：QWeb 習慣把
        # <tr> 包在 <t t-foreach> 裡，那樣 tr 就不是 tbody 的直接子節點，
        # 而表頭那一列有找到，所以 fallback 也不會啟動——轉出一張只有表頭的表。
        rows_src = [tr for tr in node.xpath('.//tr')
                    if self._closest_table(tr) is node]

        # t-foreach 可能掛在 tr 上，也可能包在 <t t-foreach> 裡
        foreach_rows = {}
        for wrapper in node.xpath('.//t[@t-foreach]'):
            expr = wrapper.get('t-foreach')
            as_var = wrapper.get('t-as') or 'line'
            for tr in wrapper.xpath('.//tr'):
                foreach_rows[tr] = (expr, as_var)
        for tr in rows_src:
            if tr.get('t-foreach'):
                foreach_rows[tr] = (tr.get('t-foreach'),
                                    tr.get('t-as') or 'line')

        # 欄數取「實際格數最多的那一列」。
        # 不能用 colspan 總和：QWeb 用 colspan="99" 當「跨滿整列」的慣用寫法，
        # 加總會得到 99 欄的 colgroup，表格在編輯器裡直接爆掉。
        max_cols = 1
        for tr in rows_src:
            branches = self._row_branches(tr)
            if branches:
                # 各分支是「同一列的不同版面」，格子不該加總
                for _cond, holder in branches:
                    max_cols = max(
                        max_cols, len(holder.xpath('./td | ./th')) or 1,
                    )
            else:
                max_cols = max(max_cols, len(self._row_cells(tr)) or 1)

        inner = self._inner_width(state)
        colgroup = self._colgroup_from_widths(rows_src, max_cols, inner)
        fit_cols = None
        if colgroup is None:
            colgroup, fit_cols = self._colgroup_from_content(
                rows_src, max_cols, inner, state, foreach_rows)
        if colgroup is None:
            colgroup = self._colgroup_even(max_cols, inner)
        col_widths = [c['width'] for c in colgroup]

        # 欄條件：同一個 t-if 同時出現在 th 與 td 上 → 欄層級
        th_conds = {}
        for tr in rows_src:
            for idx, cell in enumerate(tr.xpath('./th')):
                if cell.get('t-if'):
                    th_conds[cell.get('t-if')] = idx
        # 表頭用 <td> 寫的也算（選購商品表的「折扣%」就是）：同一個條件
        # 出現在兩列以上的格子上，就是整欄的條件，不是某一格的
        seen_rows = {}
        for r_idx, tr in enumerate(rows_src):
            for idx, cell in enumerate(self._row_cells(tr)):
                cond = cell.get('t-if')
                if cond and cond not in th_conds:
                    seen_rows.setdefault(cond, {}).setdefault(r_idx, idx)
        for cond, rows in seen_rows.items():
            if len(rows) >= 2:
                th_conds[cond] = next(iter(rows.values()))

        # 印累加器的那一列＝原生的章節小計列。本模組用「分組重複」表達：
        # 重複列設分組切分條件，再放一列分組小計。
        acc_rows = {}
        acc_meta = state.get('accumulator_meta') or {}
        for tr in rows_src:
            for el in tr.xpath('.//*[@t-out or @t-field or @t-esc]'):
                expr = (el.get('t-out') or el.get('t-field')
                        or el.get('t-esc') or '')
                for name in acc_meta:
                    if re.search(r'(?<![\w.])%s\b' % re.escape(name), expr):
                        acc_rows[tr] = name
                        break
                if tr in acc_rows:
                    break
        if acc_rows:
            name = next(iter(acc_rows.values()))
            info = acc_meta.get(name) or {}
            state['group_split'] = info.get('reset') or ''
            # 分隔列本身也要印出來：原生把章節列當成明細的一種列型印出，
            # 分組之後若不把分隔列放回組內，章節名稱整排消失（實測）。
            # 有列型分派就表示範本裡有一列是給章節用的。
            state['group_include_header'] = any(
                len(self._row_branches(tr)) > 1 for tr in rows_src)
            self._note(
                state,
                '「%s」這個累加器已轉成「分組重複」：重複列的分組切分條件取'
                '它歸零的那個條件（%s），小計列改用 group.lines|sum。%s'
                % (name, (info.get('reset') or '沒抓到，請在右欄自己指定'),
                   '' if info.get('reset')
                   else '（右欄的「分組方式」要選「依條件切分」並填條件）'),
            )

        tr_list = []
        for tr in rows_src:
            wrapper_conds = self._row_wrapper_conditions(tr, node)
            repeat = foreach_rows.get(tr)
            if tr in acc_rows:
                # 外層條件交給 _group_row_conditions 挑：分組邊界那段丟掉，
                # 「有章節才印」「訂金那一節不印」這種真條件要留
                row = self._table_row(
                    tr, state, repeat, th_conds, max_cols,
                    wrapper_conds=wrapper_conds, group_role='footer',
                    col_widths=col_widths,
                )
                if row is not None:
                    tr_list.append(row)
                continue
            branches = self._row_branches(tr)
            if branches and repeat:
                # 迴圈內的 t-if / t-elif / t-else 包住不同的格子組合
                # ——那就是「列型分派」：一筆明細依型別挑一種版面。
                for b_idx, (cond, holder) in enumerate(branches):
                    row = self._table_row(
                        holder, state, repeat, th_conds, max_cols,
                        row_filter=self._map_condition(
                            cond, state, expand=True) if cond else '',
                        with_marker=True, wrapper_conds=wrapper_conds,
                        col_widths=col_widths,
                    )
                    if row is not None:
                        tr_list.append(row)
                state['notes'].append(
                    '明細有 %d 種列型（商品／章節／備註…），已各自建一列。'
                    '有條件的列型優先，條件留空的那一列接住其餘。' % len(branches)
                )
                continue
            row = self._table_row(tr, state, repeat, th_conds, max_cols,
                                  wrapper_conds=wrapper_conds,
                                  col_widths=col_widths)
            if row is not None:
                tr_list.append(row)
        if foreach_rows:
            state['stats']['repeat'] += 1
        return {
            'type': 'table', 'value': '',
            # fixedCols：PDF 照這裡的欄寬印——自動排版會依內容重分，數字欄
            # 又被擠成兩行，與編輯器畫面也不一樣。
            # fitCols：哪幾欄是照內容估的窄欄，給 _merge_languages 取各語言
            # 裡最寬的（表頭「單價」兩個字，英文是「Unit Price」）
            'extension': dict({'fixedCols': True},
                              **({'fitCols': fit_cols} if fit_cols else {})),
            'colgroup': colgroup,
            'trList': tr_list or [{'tdList': [
                {'colspan': 1, 'rowspan': 1, 'value': [self._newline()]}]}],
        }

    def _align_cell(self, elements, align):
        """格子的對齊（td 上的 text-end）寫到格子裡每一段。

        以前只寫在結尾的換行上：一段若是以表格收尾（數量欄後面接著包裝數量的
        條件區塊），前面那段永遠拿不到對齊——原生靠右的數量印成靠左。
        已有自己對齊的元素（裡面的 div 另外寫了 text-center）不覆蓋。
        """
        for el in elements:
            if el.get('type') != 'table' and not el.get('rowFlex'):
                el['rowFlex'] = align
        if elements:
            elements[-1]['rowFlex'] = align

    def _colgroup_even(self, max_cols, inner):
        per = inner // max_cols
        colgroup = [{'width': per} for _ in range(max_cols)]
        colgroup[-1]['width'] = inner - per * (max_cols - 1)
        return colgroup

    def _colgroup_from_widths(self, rows_src, max_cols, inner):
        """欄寬：有 style="width: N%" 就照它，其餘平分剩下的寬度。
        一欄都沒寫回 None，交給 _colgroup_from_content 估。

        原生用百分比寬度指定明細表的欄寬（36 張報表有 22 處）。不讀的話
        每一欄都一樣寬——品名欄被壓窄、金額欄留一大片空白。
        """
        pct = [None] * max_cols
        for tr in rows_src:
            col = 0
            for cell in self._row_cells(tr):
                span = max(1, min(int(cell.get('colspan') or 1), max_cols))
                m = re.search(r'width\s*:\s*([\d.]+)\s*%',
                              cell.get('style') or '')
                if m and span == 1 and col < max_cols and pct[col] is None:
                    try:
                        pct[col] = float(m.group(1))
                    except ValueError:
                        pass
                col += span
            if all(p is not None for p in pct):
                break
        known = [p for p in pct if p is not None]
        if not known:
            return None
        used = min(sum(known), 95.0)
        rest = [i for i, p in enumerate(pct) if p is None]
        share = (100.0 - used) / len(rest) if rest else 0.0
        widths = [int(inner * ((p if p is not None else share) / 100.0))
                  for p in pct]
        widths = [max(20, w) for w in widths]
        # 最後一欄吸收湊整的誤差，總寬要剛好等於可用寬度
        widths[-1] = max(20, inner - sum(widths[:-1]))
        return [{'width': w} for w in widths]

    # 照內容估欄寬用的數字。字寬是編輯器預設 16px 字級下英數字的平均寬度；
    # 字數是各型別在單據上常見的長度（金額「$ 12,345.00」、數量「3.00」、
    # 單位「Units」），不是上限——估多了品名欄就被壓窄。
    _EST_CHAR_PX = 8
    _EST_TYPE_CHARS = {
        'monetary': 11, 'float': 6, 'integer': 4, 'date': 10,
        'datetime': 16, 'many2one': 5, 'selection': 6, 'many2many': 6,
        'boolean': 1,
    }
    # 這幾種型別的值會換行、長短不定，所在的欄要留給「吃剩下寬度」的那一邊
    _EST_TEXT_TYPES = ('char', 'text', 'html')
    _EST_COMPACT_CLASSES = frozenset({'text-end', 'text-center', 'text-nowrap'})
    # 窄欄合計的上限：再寬就輪不到品名欄了
    _EST_COMPACT_MAX = 0.75

    def _colgroup_from_content(self, rows_src, max_cols, inner, state,
                               foreach_rows):
        """報表沒寫欄寬時照內容估：數字欄給剛好放得下的寬度，其餘欄平分剩下的。

        原生明細表靠瀏覽器自動排版：數字欄靠右、加了 text-nowrap，寬度由內容
        撐開，品名欄吃掉剩下的。編輯器的表格只有固定欄寬，平均分的結果是
        品名欄被壓窄、「3.00 Units」「Unit Price」擠成兩行（銷售訂單實測）。

        靠右／置中／不換行的欄算「窄欄」，寬度取表頭與內容估出來的字數；
        內容是文字欄位（品名）的欄不算窄欄。
        回 (colgroup, 每一欄是不是窄欄)；分不出窄欄與寬欄時回 (None, None)。
        """
        var_models = {}
        for expr, as_var in foreach_rows.values():
            if as_var not in var_models:
                var_models[as_var] = self._loop_model(state, expr)
        compact = [False] * max_cols
        wide = [False] * max_cols
        chars = [0] * max_cols
        for tr in rows_src:
            # 列型分派的每一組格子各自是一種版面，欄位置要分開算
            holders = [h for _c, h in self._row_branches(tr)]
            cell_groups = ([h.xpath('./td | ./th') for h in holders] if holders
                           else [self._row_cells(tr)])
            for cells in cell_groups:
                col = 0
                for cell in cells:
                    span = max(1, int(cell.get('colspan') or 1))
                    if span == 1 and col < max_cols:
                        n, is_text = self._estimate_cell_chars(
                            cell, state, var_models)
                        chars[col] = max(chars[col], n)
                        if is_text:
                            wide[col] = True
                        if self._class_tokens(cell) & self._EST_COMPACT_CLASSES:
                            compact[col] = True
                    col += span
        flags = [compact[i] and not wide[i] for i in range(max_cols)]
        if all(flags) or not any(flags):
            return None, None
        widths = [max(40, n * self._EST_CHAR_PX + self._CELL_PADDING)
                  if fit else 0 for n, fit in zip(chars, flags)]
        return self._fit_widths(widths, flags, inner), flags

    def _fit_widths(self, widths, flags, inner):
        """窄欄照 widths，其餘欄平分剩下的寬度 → colgroup。

        窄欄合計超過上限時等比縮小，品名欄至少留四分之一。
        """
        fit = [w if f else 0 for w, f in zip(widths, flags)]
        cap = int(inner * self._EST_COMPACT_MAX)
        total = sum(fit)
        if total > cap:
            fit = [int(w * cap / total) for w in fit]
        rest = [i for i, f in enumerate(flags) if not f]
        share = (inner - sum(fit)) // len(rest)
        for i in rest:
            fit[i] = share
        # 最後一個寬欄吸收湊整的誤差，總寬要剛好等於可用寬度
        fit[rest[-1]] += inner - sum(fit)
        return [{'width': w} for w in fit]

    @staticmethod
    def _text_units(text):
        """字數，中日韓全形字算兩個：16px 的中文字差不多是兩個英數字寬。"""
        return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
                   for ch in text)

    def _estimate_cell_chars(self, cell, state, var_models):
        """格子內容大約幾個字、裡面有沒有文字欄位 → (字數, 有文字欄位)。

        取值節點裡的字是設計師放的範例值（<span t-field="x">3</span>），
        不算進字數，改看欄位型別。有條件才印的部分（數量後面的包裝數量）
        不算：多半不會印，算進去數量欄會寬一倍。
        """
        pieces = []
        has_text = False

        def walk(node):
            nonlocal has_text
            for attr in ('t-field', 't-out', 't-esc'):
                expr = node.get(attr)
                if expr:
                    n, is_text = self._estimate_value_chars(
                        node, expr, state, var_models)
                    pieces.append(n)
                    has_text = has_text or is_text
                    return
            text = (node.text or '').strip()
            if text:
                pieces.append(self._text_units(text))
            for child in node:
                if isinstance(child.tag, str) and not any(
                        child.get(a) is not None
                        for a in ('t-if', 't-elif', 't-else')):
                    walk(child)
                tail = (child.tail or '').strip()
                if tail:
                    pieces.append(self._text_units(tail))

        walk(cell)
        # 片段之間大多隔一個空白（「3.00 Units」）
        total = sum(pieces) + max(0, len(pieces) - 1)
        return total, has_text

    def _estimate_value_chars(self, node, expr, state, var_models):
        """取值節點 → (字數, 是不是文字欄位)。查不到欄位時看範例值的長度。"""
        sample = self._text_units(' '.join(''.join(node.itertext()).split())) or 6
        root, _dot, path = (expr or '').strip().partition('.')
        if not path or not _SIMPLE_PATH_RE.match(path):
            return min(sample, 8), False
        if root in var_models:
            model = var_models[root]
        elif root in _ROOT_VARS:
            model = state.get('model')
        else:
            return min(sample, 8), False
        field = self._resolve_field(model, path) if model else None
        ftype = getattr(field, 'type', None)
        if ftype in self._EST_TEXT_TYPES:
            return sample, True
        return self._EST_TYPE_CHARS.get(ftype, min(sample, 8)), False

    def _row_cells(self, tr):
        """這一列的格子。

        用 .//td 再濾掉巢狀表格的格子：QWeb 常把格子包在 <t t-if> 裡
        （商品列／章節列各一組），用 ./td 會找不到任何格子、整列被丟掉
        ——轉出一張只有表頭的明細表。
        """
        return [c for c in tr.xpath('.//td | .//th')
                if self._closest_row(c) is tr]

    def _closest_row(self, node):
        parent = node.getparent()
        while parent is not None:
            tag = parent.tag if isinstance(parent.tag, str) else ''
            if tag.lower() == 'tr':
                return parent
            parent = parent.getparent()
        return None

    def _row_branches(self, tr):
        """列內用 t-if/t-elif/t-else 包起來的格子組合 → [(條件, 容器)]。"""
        wrappers = [w for w in tr.xpath('./t')
                    if w.get('t-if') is not None
                    or w.get('t-elif') is not None
                    or w.get('t-else') is not None]
        if len(wrappers) < 2:
            return []
        out = []
        for w in wrappers:
            cond = w.get('t-if') or w.get('t-elif')
            out.append((cond, w))
        return out

    def _row_wrapper_conditions(self, tr, table):
        """列被 <t t-if=…> 包起來時的條件（由外而內）。

        原本整個被忽略：_emit_table 直接走 .//tr 找列，中間那層 <t t-if> 的
        條件就消失了。實測後果：出貨單上「沒有包裝的品項」那一段的章節列，
        在有包裝的單據上也會印出來。
        t-else 的條件是「前面分支都不成立」，所以取反；t-elif 兩者都要。
        """
        conds = []
        parent = tr.getparent()
        while parent is not None and parent is not table:
            tag = parent.tag if isinstance(parent.tag, str) else ''
            if tag == 't':
                negation = self._chain_negation(parent)
                if parent.get('t-if') is not None:
                    conds.append(parent.get('t-if'))
                elif parent.get('t-elif') is not None:
                    cond = parent.get('t-elif')
                    conds.append('(%s) and %s' % (cond, negation)
                                 if negation else cond)
                elif parent.get('t-else') is not None and negation:
                    conds.append(negation)
            parent = parent.getparent()
        return [c for c in reversed(conds) if (c or '').strip()]

    # QWeb 迴圈位置變數的字尾（line_last、line_index…）
    _LOOP_POSITION_SUFFIXES = ('index', 'first', 'last', 'size',
                               'parity', 'even', 'odd', 'value')

    def _group_row_conditions(self, tr, wrapper_conds, repeat, state):
        """分組小計列要保留的原生條件 → 轉好的沙箱表達式清單。

        原生小計列外面那層條件（sale 報價單）：
            current_section and (line_last or lines[line_index+1].display_type
            == 'line_section' or …) and not line.is_downpayment
        拆成三段看：
          「是不是這一節最後一列」→ 丟掉。分組之後每組本來就只印一次。
          current_section（有章節才印）→ group.header（這一組有章節標題）。
          not line.is_downpayment（訂金那節不印）→ 照轉。印的時候 line 是
            這一組最後一筆明細，跟原生在最後一筆時判斷一樣。
        以前整條丟掉，訂金那一節和第一個章節之前的明細都多印一行小計。
        """
        loop_var = (repeat or ('', 'line'))[1] or 'line'
        collection = ((repeat or ('', ''))[0] or '').strip()
        accumulators = set(state.get('accumulators') or ())
        # 「目前章節」：在迴圈裡被設成迴圈變數本身的累加器
        # （<t t-set="current_section" t-value="line"/>）
        root = tr.getroottree().getroot()
        holders = {
            name for name in accumulators
            if root.xpath('//t[@t-set=%s][@t-value=%s]'
                          % (json.dumps(name), json.dumps(loop_var)))
        }
        boundary = accumulators | {
            '%s_%s' % (loop_var, suffix)
            for suffix in self._LOOP_POSITION_SUFFIXES
        }
        if collection.isidentifier():
            # lines_to_report[line_index+1]：拿下一筆來比，也是在判斷邊界
            boundary.add(collection)
        out = []
        for cond in wrapper_conds:
            try:
                body = ast.parse(' '.join(cond.split()), mode='eval').body
            except SyntaxError:
                self._note(state, '小計列的條件看不懂，沒有帶過來：%s' % cond[:80])
                continue
            parts = (body.values
                     if isinstance(body, ast.BoolOp) and isinstance(body.op, ast.And)
                     else [body])
            for part in parts:
                if isinstance(part, ast.Name) and part.id in holders:
                    out.append('group.header')
                    continue
                names = {n.id for n in ast.walk(part) if isinstance(n, ast.Name)}
                if names & boundary:
                    continue
                out.append(self._map_condition(ast.unparse(part), state, expand=True))
        return out

    def _chain_negation(self, node):
        """「前面的 t-if / t-elif 分支都不成立」的條件式。"""
        conds = []
        sib = node.getprevious()
        while sib is not None and isinstance(sib.tag, str):
            if sib.get('t-elif') is not None:
                conds.append(sib.get('t-elif'))
            elif sib.get('t-if') is not None:
                conds.append(sib.get('t-if'))
                break
            else:
                break
            sib = sib.getprevious()
        if not conds:
            return None
        return ' and '.join('not (%s)' % c for c in reversed(conds))

    def _table_row(self, tr, state, repeat, th_conds, max_cols,
                   row_filter='', with_marker=None, wrapper_conds=(),
                   group_role='', col_widths=None):
        pushed = False
        col_widths = list(col_widths or [])
        col_pos = 0
        if repeat:
            expr, as_var = repeat
            state['loop_vars'].append(as_var)
            state.setdefault('loop_sources', []).append((expr or '').strip())
            state.setdefault('loop_models', []).append(
                self._loop_model(state, expr))
            pushed = True
        try:
            # 分支容器（<t t-if>）本身不是 tr，所以 _row_cells 的 closest_row
            # 比對會失敗——那種情況直接取它的直接子格子
            tag = tr.tag if isinstance(tr.tag, str) else ''
            cells = (self._row_cells(tr) if tag.lower() == 'tr'
                     else tr.xpath('./td | ./th'))
            # <tr t-if="..."> 原本被整個忽略——轉出來的明細表會把不該印的列
            # 也印出來（發票的付款列就是這樣）。列條件管線支援這件事，
            # 條件藥丸放列內任一格即可。
            # 分支容器（<t t-if>）的條件已經當成 rowFilter 用掉了，不要再加。
            row_cond = tr.get('t-if') if tag.lower() == 'tr' else None
            if group_role:
                row_cond = None
            td_list = []
            first = True
            row_static_style = {}
            for cell in cells:
                value = []
                # 欄條件 / 格條件
                cond = cell.get('t-if')
                cell_cond = None
                if cond:
                    if cond in th_conds:
                        value.append(self._pill(
                            '欄條件', state, source='column',
                            expression=self._map_condition(
                                cond, state, expand=True),
                        ))
                        state['stats']['condition'] += 1
                    else:
                        # 只有這一格有條件（訂金列不印金額那種）。以前只留一句
                        # 待辦、條件整個不見，訂金列多印一格「$ 0.00」
                        cell_cond = cond
                if first and group_role:
                    # 分組小計列：標記換成 groupFooter。外層條件只留真條件
                    # ——「是這一節的最後一列」是累加器時代的產物，分組之後
                    # 每組輸出一次就已經是對的。
                    value.append(self._pill(
                        '〔分組小計〕', state, source='group%s'
                        % group_role.capitalize(), isMarker=True,
                        repeatId=self._repeat_id(
                            (repeat or ('', 'line'))[1],
                            (repeat or ('', ''))[0], state),
                    ))
                    for expression in self._group_row_conditions(
                            tr, wrapper_conds, repeat, state):
                        value.append(self._pill(
                            '列條件', state, source='condition',
                            expression=expression,
                        ))
                        state['stats']['condition'] += 1
                    first = False
                if first:
                    # <tr t-att-class="'fw-bold' if … else ''"> → 列層級
                    markers, static_style = self._format_markers_for(tr, state)
                    value.extend(markers)
                    row_static_style.update(static_style)
                    for wrapper in wrapper_conds:
                        value.append(self._pill(
                            '列條件', state, source='condition',
                            expression=self._map_condition(
                                wrapper, state, expand=True),
                        ))
                        state['stats']['condition'] += 1
                    if row_cond:
                        value.append(self._pill(
                            '列條件', state, source='condition',
                            expression=self._map_condition(
                                row_cond, state, expand=True),
                        ))
                        state['stats']['condition'] += 1
                    if repeat and with_marker is not False:
                        # 重複標記放第一格：後端找「含該標記的那一列」，
                        # 放哪一格都可以，第一格最容易被看到
                        value.append(self._repeat_marker(
                            repeat, state, row_filter=row_filter,
                        ))
                    first = False
                span = max(1, min(int(cell.get('colspan') or 1), max_cols))
                cell_w = sum(col_widths[col_pos:col_pos + span])
                col_pos += span
                cell_start = len(value)
                if cell_cond:
                    # 格子裡只有一個值（或純文字）→ 收成一顆三元式藥丸；
                    # 包成條件區塊的話每一列都會多出區塊的上下空白，明細表整個變高
                    state['chain_unsure'] = False
                    expr = self._branch_expr(cell, state)
                    if expr is not None:
                        value.append(self._ternary_pill(
                            cell, expr, cell_cond, state))
                        cell_cond = None
                    else:
                        self._note(
                            state,
                            '儲存格條件「%s」已包成格子裡的條件區塊：不成立時'
                            '那一格留白（原生是少一格）。' % cell.get('t-if')[:70],
                        )
                body_w = cell_w - self._CELL_PADDING if cell_w else 0
                if cell_cond and body_w:
                    body_w -= self._CELL_PADDING  # 內容在格子裡的條件區塊裡
                if len(value) == cell_start:
                    with (self._in_width(state, body_w) if body_w
                          else contextlib.nullcontext()):
                        self._emit_children(cell, value, state)
                cell_style = self._node_style(cell, 'td')
                if cell_style:
                    for el in value[cell_start:]:
                        if self._takes_style(el):
                            el.update(cell_style)
                # 金額欄的右對齊就是靠這個：原生把 text-end 放在 <td>
                # 或裡面那個 <span> 上，段落的對齊掛在結尾的換行元素
                align = self._node_align(cell)
                if cell_cond:
                    inner = value[cell_start:]
                    del value[cell_start:]
                    if not inner or (inner[-1].get('value') or '') != '\n':
                        inner.append(self._newline())
                    if align:
                        self._align_cell(inner, align)
                    with (self._in_width(state, cell_w - self._CELL_PADDING)
                          if cell_w else contextlib.nullcontext()):
                        value.append(self._condition_wrap(
                            cell_cond, inner, state))
                if not value or (value[-1].get('value') or '') != '\n':
                    value.append(self._newline())
                if align:
                    self._align_cell(value, align)
                # colspan 夾在欄數內：QWeb 的 colspan="99" 是「跨滿整列」
                td = {'colspan': max(1, min(int(cell.get('colspan') or 1),
                                            max_cols)),
                      'rowspan': int(cell.get('rowspan') or 1),
                      'value': value}
                td_list.append(td)
            if not td_list:
                return None
            if row_static_style:
                align = row_static_style.pop('align', None)
                for cell in td_list:
                    for el in cell.get('value') or []:
                        if self._takes_style(el):
                            el.update(row_static_style)
                        if align and (el.get('value') or '') == '\n':
                            el['rowFlex'] = align
            return {'tdList': td_list}
        finally:
            if pushed:
                state['loop_vars'].pop()
                if state.get('loop_sources'):
                    state['loop_sources'].pop()
                if state.get('loop_models'):
                    state['loop_models'].pop()

    def _loop_model(self, state, expr):
        """這個迴圈跑的是哪個模型（查不出來回 None，那時就不自動補格式）。

        先用 t-foreach 的原式，不行再展開 t-set 中間變數。
        """
        bare = dict(state, loop_vars=[], loop_sources=[], loop_models=[])
        expanded = self._expand_symbols(expr, bare)[0]
        for candidate in (expr, expanded):
            path, kind = self._strip_root(candidate or '', bare)
            if not path or not _SIMPLE_PATH_RE.match(path):
                continue
            field = self._resolve_field(self._path_model(state, kind), path)
            comodel = getattr(field, 'comodel_name', None)
            if comodel:
                return comodel
        # 路徑查不出來（來源是白名單方法或一串 filter）→ 拿樣本實際跑一次。
        # 銷售訂單的明細就是這種：來源是
        # report_helper(object, '_get_order_lines_to_report')，
        # 查不出模型的話整張明細表的數字都不會被格式化（2.0 而不是 2.00）。
        sample = state.get('sample')
        if sample:
            mapped = self._map_condition(expanded, bare)
            try:
                lines = self.env['doc.render.mixin']._eval_collection(
                    mapped, sample)
            except Exception:
                lines = []
            for line in lines[:1]:
                name = getattr(line, '_name', None)
                if name:
                    return name
        return None

    def _repeat_id(self, as_var, expr, state):
        """同一個 (迴圈變數, 來源) 用同一個 repeatId，不同來源給不同的。

        列型分派（商品／章節／備註各一種版面）靠「同一個 repeatId 的多個列」
        表達，所以同源的分支必須拿到同一個 id。
        反過來，子範本被展開到同一張表格好幾次時（出貨單的彙總明細列就被
        展開三次，各自的來源不同），id 不能撞——撞了會被當成同一組的列型，
        而來源只取第一個，結果是「第一個來源剛好是 0 筆」就整組不印。
        """
        ids = state.setdefault('repeat_ids', {})
        key = (as_var, (expr or '').strip())
        if key not in ids:
            taken = sum(1 for k in ids if k[0] == as_var)
            ids[key] = ('rp_%s' % as_var) if not taken \
                else ('rp_%s_%d' % (as_var, taken + 1))
        return ids[key]

    def _repeat_marker(self, repeat, state, row_filter=''):
        expr, as_var = repeat
        repeat_id = self._repeat_id(as_var, expr, state)
        # t-foreach 的來源常是上面 t-set 出來的變數（lines_to_report），
        # 那個變數在這裡看不到定義 → 標成待辦讓使用者選欄位
        bare = dict(state, loop_vars=[], loop_sources=[], loop_models=[])
        path, kind = self._strip_root(expr, bare)
        label = ('列型 × %s' % path) if row_filter else ('明細 × %s' % path)
        shared_kw = {}
        if state.get('group_split') is not None:
            # 分組設定掛在同一個 repeatId 的每一個列型上。後端取第一個列型的
            # 設定，所以至少要有一個帶著；全部帶著最省事也不會互相矛盾。
            split = state.get('group_split') or ''
            shared_kw = {'groupMode': 'marker'}
            if split:
                shared_kw['groupSplitOn'] = self._map_condition(
                    split, state, expand=True)
            if state.get('group_include_header'):
                shared_kw['groupIncludeHeader'] = True
        # 明細是哪一張資料表：編輯器靠它列出左欄的「明細欄位」。來源是算出來的
        # （report_helper(object, '_get_order_lines_to_report')）時沒有路徑可查，
        # 以前就沒帶，轉換出來的範本因此拖不出明細欄位。_loop_model 查不到路徑
        # 時會拿樣本實際跑一次。
        relation = self._loop_model(state, expr)
        if relation:
            shared_kw['relation'] = relation
        if path and _SIMPLE_PATH_RE.match(path):
            return self._pill(label, state, source='repeat',
                              path=path, repeatId=repeat_id,
                              rowFilter=row_filter, **shared_kw)

        # lines_to_report / lines 這類中間變數：展開後多半就是真正的
        # 一對多欄位（或帶篩選／排序的表達式）
        expanded, used_rule = self._expand_symbols(expr, bare)
        path2, _k2 = self._strip_root(expanded, bare)
        if path2 and _SIMPLE_PATH_RE.match(path2):
            return self._pill(
                ('列型 × %s' if row_filter else '明細 × %s') % path2,
                state, source='repeat', path=path2,
                repeatId=repeat_id, rowFilter=row_filter,
                unbound=used_rule, **shared_kw,
            )
        mapped = self._map_condition(expanded, bare)
        # 同樣用 token 比對：白名單改寫後的來源是
        # report_helper(object, '_get_order_lines_to_report')，根變數後面接
        # 的是逗號。寫 'object.' in mapped 會判成「對不上」，明細來源變成
        # 待設定——整張明細表印不出來（實測：銷售訂單的品名／章節全消失）。
        if mapped and mapped != expr and _ROOT_TOKEN_RE.search(mapped):
            self._note(
                state,
                '重複來源已自動改寫，請確認：%s → %s'
                % (expr[:50], mapped[:80]),
            )
            return self._pill(
                '列型 × 明細' if row_filter else '明細',
                state, source='repeat', path='', sourceExpression=mapped,
                repeatId=repeat_id, rowFilter=row_filter,
                unbound=True, **shared_kw,
            )
        self._note(
            state,
            '重複來源「%s」是範本內的中間變數，請在右欄改成實際的一對多欄位'
            '（或填「來源表達式」）。' % expr[:70],
            # 關鍵詞會判成 check（有「請在右欄」），但來源沒設定＝整張明細表
            # 印不出來，那是 blocker。明寫覆蓋。
            level='blocker',
        )
        return self._pill(
            '列型（待設定）' if row_filter else '明細（待設定）',
            state, source='repeat', path='', repeatId=repeat_id,
            rowFilter=row_filter, unbound=True, **shared_kw,
        )


    # ─── 條件 ───────────────────────────────────────────────────────

    def _map_condition(self, expr, state, expand=False):
        """QWeb 條件 → 沙箱表達式。做根變數替換（必要時先展開 t-set 變數）。"""
        out = (expr or '').strip()
        if expand:
            out, _used = self._expand_symbols(out, state)
        # 整個 token 一起換，不要只換「變數後面接點」的形式：
        #   payment_vals['date']   dict 型迴圈變數寫下標
        #   report_helper(o, …)    白名單改寫後根變數後面接的是逗號
        # 只換帶點的形式會漏掉這兩種，表達式就留著沙箱不認識的名字。
        # 前面不接 \w 或點：避免把 partner.name 裡的 name（剛好是迴圈變數名）
        # 換成 partner.line。
        out = self._collapse_loop_subscript(out, state)
        for var in reversed(state.get('loop_vars') or []):
            # QWeb 的迴圈位置變數（<var>_index / _first / _last / _size）。
            # 要排在整個 token 替換之前，不然 line_index 這種名字會被
            # 「line → line」那條規則留在原地，變成沙箱認不得的名字。
            for suffix, target in (('_index', 'loop_index'),
                                   ('_first', 'loop_first'),
                                   ('_last', 'loop_last'),
                                   ('_size', 'loop_size'),
                                   ('_value', 'line')):
                out = re.sub(
                    r'(?<![\w.])%s%s\b' % (re.escape(var), suffix),
                    target, out)
            out = re.sub(r'(?<![\w.])%s\b' % re.escape(var), 'line', out)
        for var in _ROOT_VARS:
            if var == 'object':
                continue
            out = re.sub(r'(?<![\w.])%s\b' % re.escape(var), 'object', out)
        return out

    # 節點自己就是內容（不是「包著內容的容器」）的標籤
    _SELF_CONTENT_TAGS = frozenset({'table', 'img'})

    def _is_content_tag(self, node):
        tag = (node.tag if isinstance(node.tag, str) else '').lower()
        return tag in self._SELF_CONTENT_TAGS

    def _strip_condition_attrs(self, node):
        """複製一份節點並移掉條件屬性（條件已經移到標記上，不要再重入）。"""
        import copy
        clone = copy.deepcopy(node)
        for attr in ('t-if', 't-elif', 't-else'):
            if attr in clone.attrib:
                del clone.attrib[attr]
        return clone

    def _conditional_body(self, node, state):
        """條件節點的內容 → 元素串列。

        節點自己就是內容（<table t-if=…>、<img t-if=…>，或身上帶 t-field /
        t-out / t-foreach / t-call）時，要把**它自己**轉出來，不是轉它的
        子節點。只轉子節點的話，<table t-if> 的 thead/tbody 會被當成一般
        容器——tr 上的 t-foreach 永遠不會被看到，明細整批消失。
        實測：出貨單（stock.action_report_delivery）的兩張明細表就是
        <table t-if> / <table t-elif> 的一對，轉出來連客戶名與品名都沒有。
        """
        tag = (node.tag if isinstance(node.tag, str) else '').lower()
        selfish = tag in self._SELF_CONTENT_TAGS or any(
            node.get(attr) for attr in
            ('t-field', 't-out', 't-esc', 't-foreach', 't-call')
        )
        inner = []
        if selfish:
            self._emit(self._strip_condition_attrs(node), inner, state)
            return inner
        holder = self._new_element('t')
        holder.text = node.text
        for child in list(node):
            holder.append(child)
        self._emit_children(holder, inner, state)
        return inner

    def _collapse_loop_subscript(self, expr, state):
        """把「來源[迴圈變數]」收斂成 line。

        QWeb 對 dict 跑 t-foreach 是走鍵，所以範本內一律寫
        aggregated_lines[line]['name'] 取值——那整段其實就是「當前這一筆」。
        必須在 t-set 展開**之前**做：展開後文字會變成
        (report_helper(…))[line]['name']，正則就配不到來源名字了。
        """
        out = expr or ''
        pairs = list(zip(state.get('loop_vars') or [],
                         state.get('loop_sources') or []))
        for var, src in reversed(pairs):
            if not src or not _SIMPLE_PATH_RE.match(src):
                continue
            out = re.sub(
                r'(?<![\w.])%s\s*\[\s*%s\s*\]'
                % (re.escape(src), re.escape(var)), 'line', out)
        return out

    def _condition_block(self, node, cond, state):
        with self._in_width(state, self._block_body_width(state)):
            inner = self._conditional_body(node, state)
        if not inner or (inner[-1].get('value') or '') != '\n':
            inner.append(self._newline())
        return self._condition_wrap(cond, inner, state)

    def _condition_wrap(self, cond, inner, state):
        """把一串元素包進一個條件區塊（單欄虛線表格）。"""
        state['stats']['condition'] += 1
        return {
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'condition'},
            'borderType': 'dash',
            'colgroup': [{'width': self._inner_width(state)}],
            'trList': [{'tdList': [{
                'colspan': 1, 'rowspan': 1,
                'value': [self._pill(
                    '條件', state, source='condition',
                    expression=self._map_condition(
                        cond, state, expand=True),
                )] + list(inner),
            }]}],
        }
