"""ConvStructure — 走訪與 t-if / t-elif / t-else 兄弟鏈。

兄弟鏈是這一層最難的地方：QWeb 的條件是「兄弟節點之間的關係」，
而藥丸的條件是「標記 + groupId」。配對錯的症狀是該藏的區塊照印。
"""
import json
import logging
import re
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


class ConvStructure:

    # ─── 走訪 ───────────────────────────────────────────────────────

    def _append_text(self, out, raw):
        """把一段原始文字加進輸出，保留「原本有沒有前後空白」。

        原本一律 .strip()，於是標籤與值之間那個空格不見了——實測印出
        「Date2026-10-08」「2.0Units」「AddressW1」。HTML 把連續空白算成
        一個空格，所以這裡照同一個規則：壓成一個空格、但不要讓它消失。
        段落開頭的空格仍然丟掉（那個是縮排，不是內容）。
        """
        if not raw:
            return
        collapsed = ' '.join(raw.split())
        if collapsed:
            value = '%s%s%s' % (' ' if raw[:1].isspace() else '',
                                collapsed,
                                ' ' if raw[-1:].isspace() else '')
        else:
            # 純空白：兩個行內元素之間的那一個空格
            value = ' '
        prev = (out[-1].get('value') or '') if out else ''
        if not out or prev == '\n' or prev.endswith(' '):
            value = value.lstrip()
        if not value:
            return
        out.append(self._text(value))

    def _emit_children(self, node, out, state):
        self._append_text(out, node.text)
        children = list(node)
        idx = 0
        while idx < len(children):
            child = children[idx]
            chain = self._collect_chain(children, idx)
            if chain:
                self._emit_chain(chain, out, state)
                idx += len(chain)
                last = chain[-1][1]
                self._append_text(out, last.tail)
                continue
            self._emit(child, out, state)
            self._append_text(out, child.tail)
            idx += 1


    # ─── t-if / t-elif / t-else 兄弟鏈 ──────────────────────────────
    #
    # 這是待辦清單裡最常見的一項（發票 24 條待辦有 12 條是它）。分兩種處理：
    #
    #   * 分支內容都是純文字 → 收成**一顆**表達式藥丸，用 Jinja 的
    #     「A if cond else B」巢狀三元式。完全等價、不改版面、沒有待辦。
    #     單據標題（Pro-Forma / Quotation / Order）就是這一類。
    #   * 分支內含藥丸或表格 → 巢狀的「若／否則」條件區塊（已實測三擇一可行）。
    #     那是區塊級的，會換行，所以只在不得不時才用。

    def _collect_chain(self, children, idx):
        """從 idx 開始收一串 t-if → t-elif* → t-else?。沒有鏈回 None。"""
        first = children[idx]
        if not isinstance(first.tag, str) or first.get('t-if') is None:
            return None
        chain = [(first.get('t-if'), first)]
        j = idx + 1
        while j < len(children):
            nxt = children[j]
            if not isinstance(nxt.tag, str):
                break
            if nxt.get('t-elif') is not None:
                chain.append((nxt.get('t-elif'), nxt))
            elif nxt.get('t-else') is not None:
                chain.append((None, nxt))
                j += 1
                break
            else:
                break
            j += 1
        return chain if len(chain) > 1 else None

    def _branch_is_text_only(self, node):
        """分支裡沒有藥丸來源、沒有表格、沒有圖片——可以收成一句表達式。"""
        if self._is_content_tag(node):
            return False
        if self._parse_options(node) == 'barcode':
            return False
        if node.xpath('.//table | .//tr | .//img'
                      ' | .//*[@t-field or @t-out or @t-esc'
                      ' or @t-foreach or @t-call]'):
            return False
        for attr in ('t-field', 't-out', 't-esc', 't-foreach', 't-call'):
            if node.get(attr):
                return False
        return True

    def _branch_expr(self, node, state):
        """分支 → Jinja 表達式片段。收不成回 None。

        兩種可收的分支：
          * 純文字（單據標題「Quotation #」那類）→ 字面值
          * 只含一個取值節點（折扣價 vs 原價那類）→ 該節點的表達式
        收不成就得退回區塊級的巢狀若／否則，而那會在表格儲存格裡塞一個
        子表格——價格欄變成一個方框，版面直接壞掉。所以這裡要盡量收得起來。
        """
        for attr in ('t-field', 't-out', 't-esc'):
            if node.get(attr):
                return self._branch_value(node, node.get(attr), state)
        values = node.xpath('.//*[@t-field or @t-out or @t-esc]')
        # 節點自己是表格（或裡面有表格列）時不可以收成一顆藥丸——整張表
        # 會被丟掉。實測：<table t-if> 的表身剛好只有一個取值節點時，
        # 出貨單的明細表整張變成一顆三元式藥丸。
        # 分支裡除了那個值還有別的文字時也不能收：那段文字會被丟掉
        #（實測採購單少印「Order Deadline」「Request for Quotation」）。
        if (len(values) == 1
                and not self._is_content_tag(node)
                and not node.xpath('.//table | .//tr | .//img')
                # 條碼是圖，收成三元式就變成印出條碼的文字
                and self._parse_options(values[0]) != 'barcode'
                and not self._branch_extra_text(node, values[0])):
            v = values[0]
            for attr in ('t-field', 't-out', 't-esc'):
                if v.get(attr):
                    return self._branch_value(v, v.get(attr), state)
        if self._branch_is_text_only(node):
            return json.dumps(
                ' '.join((''.join(node.itertext()) or '').split()),
                ensure_ascii=False,
            )
        return None

    def _branch_extra_text(self, node, value_node):
        """分支裡除了那個取值節點，還有沒有其他可見文字。

        <div><strong>Order Deadline:</strong><p t-field="o.date_order"/></div>
        收成「只有值」的三元式會把標籤整段丟掉。節點內的文字是設計師放的
        範例值，所以比對時要先把取值節點自己的文字扣掉。
        """
        whole = ''.join(node.itertext())
        inner = ''.join(value_node.itertext())
        rest = whole.replace(inner, '', 1) if inner else whole
        return bool(rest.strip())

    def _branch_value(self, node, expr, state):
        """分支裡的取值節點 → 表達式片段。

        不是簡單路徑（例如 (1 - line.discount / 100.0) * line.price_unit）
        時，**仍然收下來**，只做根變數替換並標成待確認。
        退回區塊級的巢狀若／否則會在價格欄裡塞一個子表格——版面直接壞掉，
        而且使用者不會想到那是「未支援的算式」造成的。
        """
        mapped = self._mapped_value_expr(node, expr, state)
        if mapped is not None:
            return mapped
        state['chain_unsure'] = True
        self._note(
            state,
            '分支裡的算式已原樣保留，請確認是否可求值：%s' % expr[:90],
        )
        # widget 不可以在這條路上掉掉：原生的
        # t-out="o.move_ids[0].partner_id or o.partner_id"
        # 帶 widget="contact"，掉了之後單據上印的是 "res.partner(7,)"。
        # expand=True 也不可少：慣用寫法的改寫（.sudo()、filtered(lambda …)）
        # 都在 _apply_rules 裡，少了這一步分支裡的算式會原樣留著
        # ——實測出貨單的 incoterm 欄留著 object.sudo()，試算直接 SecurityError。
        return self._wrap_widget(
            node, self._map_condition(expr, state, expand=True))

    def _emit_chain(self, chain, out, state):
        state['chain_unsure'] = False
        exprs = [(cond, self._branch_expr(node, state))
                 for cond, node in chain]
        if all(e is not None for _c, e in exprs):
            out.append(self._chain_value_pill(chain, exprs, state))
            return
        state['notes'].append(
            '多重分支已轉成巢狀「若／否則」區塊（會自成段落）：%s'
            % (chain[0][0] or '')[:70]
        )
        out.append(self._chain_blocks(chain, state))
        out.append(self._newline())

    def _chain_value_pill(self, chain, exprs, state):
        """分支收成一顆 Jinja 三元式藥丸（完全等價、不改版面、沒有待辦）。"""
        expr = exprs[-1][1] if chain[-1][0] is None else '""'
        tail = exprs[:-1] if chain[-1][0] is None else exprs
        for cond, piece in reversed(tail):
            # expand=True：慣用寫法的改寫（.sudo()、filtered(lambda …)）在
            # _apply_rules 裡，少了這一步分支的條件會原樣留著
            # ——實測出貨單的 incoterm 條件留著 sudo()，試算 SecurityError。
            expr = '%s if (%s) else %s' % (
                piece, self._map_condition(cond, state, expand=True), expr,
            )
        label = ' '.join((''.join(chain[0][1].itertext()) or '').split())
        if not label:
            # 取值型分支沒有文字可當標籤，用第一個分支的欄位名
            label = (exprs[0][1] or '').split('.')[-1].strip('()')
        state['stats']['condition'] += 1
        # 在重複列內要用 line 來源，否則會以主記錄求值、每列同一個值
        source = 'line' if _LINE_TOKEN_RE.search(expr) else 'record'
        return self._pill(label[:20] or '多重分支', state,
                          source=source, expression=expr,
                          unbound=bool(state.get('chain_unsure')))

    def _chain_blocks(self, chain, state):
        """複雜分支 → 巢狀的若／否則區塊（實測三擇一可行）。"""
        state['chain_seq'] = state.get('chain_seq', 0) + 1
        gid = 'cg%d' % state['chain_seq']
        cond, node = chain[0]
        # 用 _conditional_body 而不是 _emit_children：分支節點自己就是內容的
        # 情況（<table t-if> / <table t-elif> 的一對）只轉子節點會讓
        # tr 上的 t-foreach 永遠看不到，明細整批消失。
        if_inner = self._conditional_body(node, state)
        if not if_inner or (if_inner[-1].get('value') or '') != '\n':
            if_inner.append(self._newline())

        rest = chain[1:]
        else_inner = []
        if len(rest) == 1 and rest[0][0] is None:
            else_inner = self._conditional_body(rest[0][1], state)
        elif rest:
            else_inner.append(self._chain_blocks(rest, state))
        if not else_inner or (else_inner[-1].get('value') or '') != '\n':
            else_inner.append(self._newline())

        state['stats']['condition'] += 1
        cell = lambda *els: {'colspan': 1, 'rowspan': 1, 'value': list(els)}
        return {
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'condition'},
            'borderType': 'dash',
            'colgroup': [{'width': self._inner_width(state)}],
            'trList': [
                {'tdList': [cell(*([self._pill(
                    '若', state, source='condition', groupId=gid, role='if',
                    expression=self._map_condition(
                        cond, state, expand=True),
                )] + if_inner))]},
                {'tdList': [cell(*([self._pill(
                    '否則', state, source='condition', groupId=gid,
                    role='else',
                )] + else_inner))]},
            ],
        }

    def _emit(self, node, out, state):
        tag = node.tag if isinstance(node.tag, str) else ''
        if not tag or tag in _SKIP_TAGS:
            return
        tag = tag.lower()

        # ── 稅額彙總子範本 → 內建區塊
        call = node.get('t-call')
        if call in _TAX_TOTALS_TEMPLATES or call in _TAX_TOTALS_COMPANY_TEMPLATES:
            mode = 'company' if call in _TAX_TOTALS_COMPANY_TEMPLATES \
                else 'document'
            out.append(self._tax_totals_block(state, mode))
            state['stats']['taxTotals'] += 1
            return
        if call in _WRAPPER_TEMPLATES:
            # 外殼範本（html_container / basic_layout / minimal_layout）本身
            # 只有版面骨架，真正的本文是「呼叫節點的子節點」——QWeb 用
            # t-out="0" 把它們塞進外殼裡。原本連子節點一起丟掉，所以凡是
            # 本文直接寫在外殼裡（沒有再包 external_layout）的報表整份都是
            # 空的。實測：36 張報表有 17 張（標籤與條碼類）就是這樣變空白。
            self._emit_children(node, out, state)
            return
        if call:
            self._note(state, '子範本 t-call="%s" 未轉換，需要人工處理。' % call)
            return

        # ── 值
        for attr in ('t-field', 't-out', 't-esc'):
            expr = node.get(attr)
            if expr:
                # 節點內的文字是給設計師看的範例值（<span t-field="x">3</span>
                # 裡的那個 3），不可當成內容——原生渲染時也會被值取代
                if self._parse_options(node) == 'barcode':
                    # 條碼是圖，收不成三元式。節點上的 t-if 幾乎都是
                    # 「欄位有值才印」，而值為空時圖本來就不印、段落收合會把
                    # 那一段帶走——結果與原生一致。
                    out.append(self._barcode_value_pill(node, expr, state))
                    return
                cond = node.get('t-if')
                if cond and not node.get('t-foreach'):
                    # <span t-if="o.ref" t-field="o.ref"/>：條件與值在同一個
                    # 節點上。原本只收值、條件整個不見——欄位有值時剛好一樣，
                    # 沒值時會印出一段本來不該出現的東西。
                    out.append(self._ternary_pill(
                        node, self._branch_value(node, expr, state),
                        cond, state,
                    ))
                    return
                out.append(self._value_pill(node, expr, state))
                return

        # ── 圖片
        if tag == 'img':
            out.append(self._image_pill(node, state))
            state['stats']['image'] += 1
            return

        # ── 換行與分頁
        if tag == 'br':
            out.append(self._newline())
            return

        # ── 表格
        if tag == 'table':
            # 稅額彙總的 t-call 常常直接掛在 <table> 下面（銷售訂單與發票
            # 都是），而 _emit_table 只走 tr / td——那個節點永遠到不了
            # _emit 的稅額彙總分支，結果是「稅前小計／稅額／總計」整塊不印。
            # 實測：那是三張單據上最大的一塊漏印。
            totals_mode, totals_first = self._table_tax_totals(node)
            rows = [tr for tr in node.xpath('.//tr')
                    if self._closest_table(tr) is node]
            pieces = []
            if totals_mode:
                block = self._tax_totals_block(state, totals_mode)
                state['stats']['taxTotals'] += 1
                if not rows:
                    # 這張表格本身就是稅額彙總表（內容全在子範本裡）
                    pieces = [block]
                elif totals_first:
                    pieces = [block, self._newline(),
                              self._emit_table(node, state)]
                    state['stats']['table'] += 1
                else:
                    pieces = [self._emit_table(node, state), self._newline(),
                              block]
                    state['stats']['table'] += 1
            else:
                pieces = [self._emit_table(node, state)]
                state['stats']['table'] += 1
            # <table t-if="…"> 的條件原本被丟掉（表格分支排在條件分支前面）。
            # 出貨單的兩張明細表就是這個形狀。
            table_cond = node.get('t-if')
            if table_cond:
                out.append(self._condition_wrap(
                    table_cond, pieces + [self._newline()], state))
            else:
                out.extend(pieces)
            out.append(self._newline())
            return

        # ── t-foreach 不在表格列上（清單、卡片、發票的分期明細）
        #    必須排在「區塊條件」之前：<div t-if=... t-foreach=...> 這種寫法
        #    若先走條件分支，t-foreach 會被整個丟掉——迴圈體只印一次，
        #    而且迴圈變數變成待確認藥丸。條件在 _repeat_block 裡處理。
        if node.get('t-foreach') and tag != 'tr':
            block = self._repeat_block(node, state)
            if block is not None:
                out.append(block)
                out.append(self._newline())
                return
            # 迴圈體本身含表格／表格列 → 包不起來（會變巢狀的表格列）。
            # 這種只剩人工處理，但內容照原樣印出來，不要整段消失。
            self._note(
                state,
                '非表格的 t-foreach="%s" 未轉換：迴圈體裡有表格，'
                '包成單欄表格會變成巢狀表格。請人工調整。'
                % (node.get('t-foreach') or '')[:60],
            )

        # ── 區塊條件：t-if 掛在區塊元素上 → 條件區塊
        cond = node.get('t-if')
        if cond and tag in _BLOCK_TAGS:
            out.append(self._condition_block(node, cond, state))
            out.append(self._newline())
            return
        # ── 掛在非區塊節點上的單獨 t-if（<t t-if="…">、<span t-if="…">）
        #    原本整個被忽略、內容照印。實測後果：沒有提前付款折扣的發票也
        #    印出一句「due if paid before」加一個日期——那段的條件就是掛在
        #    <t> 上的。
        if cond and self._lone_condition(node, cond, out, state):
            return

        if node.get('t-elif') is not None or node.get('t-else') is not None:
            # 走到這裡表示它沒被 _collect_chain 收走（前面的 t-if 不是直接
            # 兄弟節點）。孤立的 elif/else 無從判斷互斥關係，一律列印並標待辦
            # ——印出來比漏印好追。
            self._note(
                state,
                '孤立的 t-elif／t-else 需要人工確認（它的 t-if 不是相鄰節點）：%s'
                % (node.get('t-elif') or '（else）')[:70],
            )

        # ── 一般容器
        if tag in _BLOCK_TAGS:
            if out and (out[-1].get('value') or '') != '\n':
                out.append(self._newline())
            start = len(out)
            block_markers, block_static = self._format_markers_for(node, state)
            out.extend(block_markers)
            self._emit_children(node, out, state)
            style = dict(self._node_style(node, tag) or {})
            style.update({k: v for k, v in block_static.items()
                          if k != 'align'})
            if style:
                for el in out[start:]:
                    if el.get('type') not in ('label', 'table'):
                        el.update(style)
            align = self._node_align(node)
            if out and (out[-1].get('value') or '') != '\n':
                out.append(self._newline())
            if align and len(out) > start:
                # 段落的對齊掛在結尾那個換行元素上（_elements_to_html 就是
                # 讀它的 rowFlex 決定 text-align）
                out[-1]['rowFlex'] = align
            return

        # span / strong / t 等行內容器
        inline = []
        self._emit_children(node, inline, state)
        style = self._node_style(node, tag)
        for el in inline:
            if style and el.get('type') != 'label':
                el.update(style)
        out.extend(inline)

    # Bootstrap class → 文件屬性。只收「表達得出來又看得出來」的那幾個：
    # text-end/center 120+101 處（金額欄的右對齊）、fw-bold 13 處。
    # 其餘（text-nowrap、col-*、mb-*…）是版面網格，文件模型沒有對應物。
    _CLASS_STYLE = {
        'fw-bold': {'bold': True},
        'fw-bolder': {'bold': True},
        'fw-semibold': {'bold': True},
        'fst-italic': {'italic': True},
        'text-decoration-underline': {'underline': True},
        'text-muted': {'color': '#6c757d'},
    }
    _CLASS_ALIGN = {
        'text-end': 'right',
        'text-center': 'center',
        'text-start': 'left',
    }

    # cond and 'a' or 'b' → 'a' if cond else 'b'（先正規化再走鏈式解析）
    _AND_OR_CLASS_RE = re.compile(
        r"^\s*(?P<cond>.+?)\s+and\s+(?P<a>%s)\s+or\s+(?P<b>%s|None)\s*$"
        % (_LIT, _LIT), re.S)

    def _parse_class_chain(self, raw):
        """class 的三元式鏈 → [(條件 or None, class 字串)]。認不出來回 []。

        不能用一條正則：原生寫的是**鏈式**三元式
            'fw-bold …' if <章節> else 'fst-italic …' if <備註> else ''
        非貪婪的 .+? 會為了讓結尾對上而把中間那段吞進條件裡
        （實測吞出一個 TemplateSyntaxError）。所以自己掃到「括號深度 0 的
        else」為止。
        """
        text = ' '.join((raw or '').split())
        m = self._AND_OR_CLASS_RE.match(text)
        if m:
            other = m.group('b')
            text = "%s if %s else %s" % (
                m.group('a'), m.group('cond'),
                "''" if other == 'None' else other)
        out = []
        while True:
            head = re.match(r"^\s*(%s)\s+if\s+(.+)$"
                            % _LIT, text, re.S)
            if not head:
                break
            classes, rest = head.group(1), head.group(2)
            depth, idx, i = 0, None, 0
            while i < len(rest):
                ch = rest[i]
                if ch in '([{':
                    depth += 1
                elif ch in ')]}':
                    depth -= 1
                elif depth == 0 and rest.startswith(' else ', i):
                    idx = i
                    break
                i += 1
            if idx is None:
                return []
            out.append((rest[:idx].strip(), classes))
            text = rest[idx + len(' else '):].strip()
        tail = re.match(r"^\s*(%s)\s*$" % _LIT, text)
        if tail:
            out.append((None, tail.group(1)))
        elif text:
            return []
        return out

    def _style_of_classes(self, raw):
        """一串 class 字面值 → 文件屬性（含 align）。"""
        style = {}
        for token in (raw or '').strip('\'"').split():
            style.update(self._CLASS_STYLE.get(token) or {})
            if token in self._CLASS_ALIGN:
                style['align'] = self._CLASS_ALIGN[token]
        return style

    def _format_markers_for(self, node, state):
        """t-att-class → (條件式格式標記清單, 靜態屬性)。

        原生就是這樣做「章節列要粗體、備註列要斜體」：
            <tr t-att-class="'fw-bold o_line_section' if <章節>
                             else 'fst-italic o_line_note' if <備註> else ''">
        只吃得懂靜態 class 的話，這一類格式只能留待辦。
        """
        source = node
        tag = (node.tag if isinstance(node.tag, str) else '').lower()
        if tag != 'tr':
            # 列型分派時 _table_row 收到的是 <t> 分支容器，而 class 在它的
            # **祖先** tr 上（分支包的是格子，不是整列）。往上找，找不到再往下。
            ancestor = self._closest_row(node)
            if ancestor is not None:
                source = ancestor
            else:
                inner = node.xpath('./tr')
                if inner:
                    source = inner[0]
        raw = (source.get('t-att-class') or '').strip()
        if not raw:
            return [], {}
        chain = self._parse_class_chain(raw)
        if not chain:
            return [], {}
        markers = []
        static = {}
        seen_conds = []
        for cond, classes in chain:
            style = self._style_of_classes(classes)
            if cond is None:
                if not style:
                    continue
                if not seen_conds:
                    static = style          # 只有字面值＝固定格式
                    continue
                expression = ' and '.join(
                    'not (%s)' % c for c in seen_conds)
            else:
                mapped = self._map_condition(cond, state, expand=True)
                seen_conds.append(mapped)
                if not style:
                    continue
                # 鏈式三元式的後面幾段要排除前面幾段（原生的 elif 語意）
                parts = ['(%s)' % mapped] + [
                    'not (%s)' % c for c in seen_conds[:-1]]
                expression = ' and '.join(parts)
            markers.append(self._pill(
                '條件格式', state, source='format',
                expression=expression, **style,
            ))
        if markers or static:
            # 刻意不刪屬性：同一個 tr 的多個列型各自都要拿到自己的那一顆標記
            self._note(
                state,
                '動態 class「%s」已轉成%s。' % (
                    ' '.join(raw.split())[:56],
                    '條件式格式標記（條件成立才套用）' if markers
                    else '固定格式'),
            )
        return markers, static

    def _class_tokens(self, node):
        return set((node.get('class') or '').split())

    def _node_style(self, node, tag):
        """標籤與 class 一起決定的文字屬性。"""
        style = {}
        if tag in ('strong', 'b'):
            style['bold'] = True
        elif tag in ('em', 'i'):
            style['italic'] = True
        elif tag == 'u':
            style['underline'] = True
        for token in self._class_tokens(node):
            style.update(self._CLASS_STYLE.get(token) or {})
        return style or None

    def _node_align(self, node):
        """節點（或它的第一個子節點）的對齊 class。

        原生常把 text-end 放在 <td> 上，也常放在裡面那個 <span> 上。
        """
        for candidate in [node] + list(node)[:1]:
            if not isinstance(candidate.tag, str):
                continue
            for token in self._class_tokens(candidate):
                if token in self._CLASS_ALIGN:
                    return self._CLASS_ALIGN[token]
        return None

