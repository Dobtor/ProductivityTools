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
            if self._is_float_end(child):
                # 浮動靠右的區塊：後面的兄弟節點都繞在它左邊排（見 _float_end_table）
                out.append(self._float_end_table(child, children[idx + 1:], state))
                out.append(self._newline())
                return
            run = self._float_start_run(children, idx)
            if run:
                # 連續幾個靠左浮動的區塊並排（揀貨作業的單號標題＋條碼）
                out.append(self._float_start_table(run, state))
                out.append(self._newline())
                self._append_text(out, run[-1].tail)
                idx += len(run)
                continue
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
        concat = self._branch_concat(node, values, state)
        if concat is not None:
            return concat
        if self._branch_is_text_only(node):
            return json.dumps(
                ' '.join((''.join(node.itertext()) or '').split()),
                ensure_ascii=False,
            )
        return None

    # 可以跟前後文字串成一句的取值節點（行內、沒有自己的樣式）
    _CONCAT_VALUE_TAGS = frozenset({'span', 't'})

    def _branch_concat(self, node, values, state):
        """「文字＋一個行內取值＋文字」的分支 → 串起來的表達式；不是這個形狀回 None。

        採購單的標題寫成三個獨立的 t-if：
            <t t-if="o.state in ['purchase', 'done']">Purchase Order #<span t-field="o.name"/></t>
        以前收不成一句，包成條件區塊；標題的字級只套在最外層，條件區塊裡的字
        印成內文大小。串成 "Purchase Order #" ~ 值 之後就是一顆藥丸，字級、
        顏色照標題套；字串照各語言翻譯（_translate_literals）。
        取值節點有自己的樣式（粗體、class）或是區塊元素時不串：那是「標籤＋值」
        各自一段，串起來會把換行與粗體弄丟。
        """
        if len(values) != 1 or self._is_content_tag(node):
            return None
        tag = (node.tag if isinstance(node.tag, str) else '').lower()
        if tag in _BLOCK_TAGS:
            return None
        value = values[0]
        children = [c for c in node if isinstance(c.tag, str)]
        v_tag = (value.tag if isinstance(value.tag, str) else '').lower()
        if children != [value] or v_tag not in self._CONCAT_VALUE_TAGS:
            return None
        if (len(value) or value.get('class') or value.get('style')
                or any(value.get(a) is not None
                       for a in ('t-if', 't-elif', 't-else', 't-foreach'))
                or self._parse_options(value) == 'barcode'):
            return None
        lead = re.sub(r'\s+', ' ', node.text or '').lstrip()
        trail = re.sub(r'\s+', ' ', value.tail or '').rstrip()
        if not lead.strip() and not trail.strip():
            return None
        attr = next(a for a in ('t-field', 't-out', 't-esc') if value.get(a))
        piece = self._branch_value(value, value.get(attr), state)
        parts = []
        if lead:
            parts.append(json.dumps(lead, ensure_ascii=False))
        parts.append('((%s) or "")' % piece)
        if trail:
            parts.append(json.dumps(trail, ensure_ascii=False))
        return '(%s)' % ' ~ '.join(parts)

    def _set_empty_text(self, node, pill):
        """t-field 節點裡的字 → 藥丸的「空值時印的字」（emptyText）。

        QWeb 的 t-field 在欄位沒有值時，改印節點裡的字：訂金那一列沒有單位，
        原生的 <span t-field="line.product_uom">units</span> 就印出「units」，
        數量欄是「0.00 units」。有值時那些字會被值取代，所以平常看不到。
        只收純文字（裡面還有取值節點的不是範例值），而且只收簡單欄位路徑
        ——空不空要看欄位本身，算式的結果分不出「沒值」與「值是空字串」。
        各語言的字由 _merge_languages 補上（中文是「單位」）。
        """
        meta = (pill.get('extension') or {}).get('dobtorField') or {}
        if not meta.get('path') or len(node):
            return
        text = ' '.join(''.join(node.itertext()).split())
        if text:
            meta['emptyText'] = {self.env.lang or 'en_US': text}

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
            pill = self._chain_value_pill(chain, exprs, state)
            tags = {node.tag.lower() for _c, node in chain
                    if isinstance(node.tag, str)}
            if len(tags) == 1 and tags <= _BLOCK_TAGS:
                # 分支本身是區塊（出貨單的 <div t-if t-field> / <div t-else
                # t-field>）：收成藥丸後也要自成一段，不然值擠到標籤同一行
                self._append_value(chain[0][1], tags.pop(), pill, out)
            else:
                out.append(pill)
            return
        state['notes'].append(
            '多重分支已轉成巢狀「若／否則」區塊（會自成段落）：%s'
            % (chain[0][0] or '')[:70]
        )
        # 分支裡第一個區塊的上邊距要跟外面前一段的下邊距合併（見 _top_spacer_rows）
        outer = state.get('outer_tail_px')
        Mixin = self.env['doc.render.mixin']
        state['outer_tail_px'] = self._trailing_spacer_px(
            [el for el in out if not Mixin._is_marker_element(el)])
        try:
            out.append(self._chain_blocks(chain, state))
        finally:
            state['outer_tail_px'] = outer
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
            # 取值型分支沒有文字可當標籤，用第一個分支的欄位名稱（查不到才用
            # 技術名稱——那比值還長，窄欄裡會蓋到隔壁欄）
            found = re.findall(r'\b(object|line)\.([\w.]+)', exprs[0][1] or '')
            label = ((self._field_display_label(
                state, 'line' if found[0][0] == 'line' else 'record', found[0][1])
                if found else None)
                or (exprs[0][1] or '').split('.')[-1].strip('()'))
        state['stats']['condition'] += 1
        # 在重複列內要用 line 來源，否則會以主記錄求值、每列同一個值
        source = 'line' if _LINE_TOKEN_RE.search(expr) else 'record'
        pill = self._pill(label[:20] or '多重分支', state,
                          source=source, expression=expr,
                          unbound=bool(state.get('chain_unsure')))
        # 分支節點自己的樣式要跟著藥丸走：原生的
        # <strong t-if>Quotation Date</strong><strong t-else>Order Date</strong>
        # 收成藥丸後，粗體是寫在分支節點上的，不套就印成一般字
        styles = [self._branch_style(node) for _cond, node in chain]
        if styles[0] and all(s == styles[0] for s in styles):
            pill.update(styles[0])
        # 公司顏色（資訊欄的「Order Date／Invoice Date」是 #informations 裡的 strong）
        roles = {self._branch_color_role(node) for _cond, node in chain}
        if len(roles) == 1 and None not in roles:
            self._mark_company_color(pill, roles.pop())
        return pill

    def _branch_color_role(self, node):
        """分支的公司顏色；分支是 <t> 包一個節點時看裡面那個（同 _branch_style）。"""
        if not isinstance(node.tag, str):
            return None
        tag = node.tag.lower()
        if tag == 't':
            children = [c for c in node if isinstance(c.tag, str)]
            if len(children) == 1:
                return self._branch_color_role(children[0])
            return None
        return self._company_color_role(node, tag)

    def _branch_style(self, node):
        """分支的文字樣式：分支節點自己的；分支是 <t> 包一個節點時看裡面那個。

        發票寫成 <t t-if=…><strong>Invoice Date</strong></t>：粗體在裡面一層，
        只看分支節點（<t>）的話是一般字。
        """
        if not isinstance(node.tag, str):
            return None
        tag = node.tag.lower()
        if tag == 't':
            children = [c for c in node if isinstance(c.tag, str)]
            if len(children) == 1 and not (node.text or '').strip() \
                    and not (children[0].tail or '').strip():
                return self._branch_style(children[0])
            return None
        return self._node_style(node, tag)

    def _chain_blocks(self, chain, state):
        """複雜分支 → 巢狀的若／否則區塊（實測三擇一可行）。"""
        state['chain_seq'] = state.get('chain_seq', 0) + 1
        gid = 'cg%d' % state['chain_seq']
        cond, node = chain[0]
        block_w = self._inner_width(state)
        body_w = self._block_body_width(state)
        # 用 _conditional_body 而不是 _emit_children：分支節點自己就是內容的
        # 情況（<table t-if> / <table t-elif> 的一對）只轉子節點會讓
        # tr 上的 t-foreach 永遠看不到，明細整批消失。
        with self._in_width(state, body_w):
            if_inner = self._conditional_body(node, state)
        if not if_inner or (if_inner[-1].get('value') or '') != '\n':
            if_inner.append(self._newline())

        rest = chain[1:]
        else_inner = []
        with self._in_width(state, body_w):
            if len(rest) == 1 and rest[0][0] is None:
                else_inner = self._conditional_body(rest[0][1], state)
            elif rest:
                else_inner.append(self._chain_blocks(rest, state))
        if not else_inner or (else_inner[-1].get('value') or '') != '\n':
            else_inner.append(self._newline())

        state['stats']['condition'] += 1
        return {
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'condition'},
            'borderType': 'dash',
            'colgroup': [{'width': block_w}],
            'trList': [
                {'tdList': [self._condition_cell(self._pill(
                    '若', state, source='condition', groupId=gid, role='if',
                    expression=self._map_condition(
                        cond, state, expand=True),
                ), if_inner)]},
                {'tdList': [self._condition_cell(self._pill(
                    '否則', state, source='condition', groupId=gid,
                    role='else',
                ), else_inner)]},
            ],
        }

    def _table_pieces(self, node, rows, totals_mode, totals_first, state):
        """<table> → [明細表, 稅額彙總] 依原生順序排好的元素。"""
        if not totals_mode:
            state['stats']['table'] += 1
            return [self._emit_table(node, state)]
        block = self._tax_totals_block(state, totals_mode,
                                       span=self._ancestor_col_span(node))
        state['stats']['taxTotals'] += 1
        if not rows:
            # 這張表格本身就是稅額彙總表（內容全在子範本裡）
            return [block]
        state['stats']['table'] += 1
        if totals_first:
            return [block, self._newline(), self._emit_table(node, state)]
        return [self._emit_table(node, state), self._newline(), block]

    def _keep_line_before_break(self, out):
        """<br/> 前面這一段只有取值時，空值也要留一行（藥丸標 keepEmpty）。

        原生的 <span t-if="…note" t-field="…note"/><br/>：值是空的，<br/> 照樣
        撐出一行空白（發票付款條件那一行）。本模組的「空段落自動收合」會把
        整段拿掉，付款說明就比官方高一行。有固定文字的段落本來就不會收合，不用標。
        """
        Mixin = self.env['doc.render.mixin']
        pills = []
        for el in reversed(out):
            if (el.get('value') or '') == '\n':
                break
            meta = Mixin._element_field_meta(el)
            if not meta:
                return
            if not Mixin._is_marker_element(el):
                pills.append(meta)
        for meta in pills:
            meta['keepEmpty'] = True

    def _append_value(self, node, tag, pill, out):
        """取值節點 → 藥丸；節點是區塊元素（<div t-field>）時自成一段。

        原生的「標題在上、值在下」就是靠這個：
            <strong>Your Reference</strong><div t-field="doc.client_order_ref"/>
        以前不管標籤一律當行內，標題跟值擠在同一行；地址區塊的
        「發票及送貨地址」後面直接接地址也是這個原因。
        """
        if tag not in _BLOCK_TAGS:
            out.append(pill)
            return
        if not self._at_paragraph_start(out):
            out.append(self._newline())
        out.append(pill)
        out.append(self._newline())
        align = self._node_align(node)
        if align:
            out[-1]['rowFlex'] = align
        # 區塊取值節點下方的留白（mb-3；address 見 _spacing_px）
        out.extend(self._spacer_rows(node, 'bottom'))

    def _at_paragraph_start(self, out):
        """out 現在是不是在段落開頭（空的、剛換行、或前面只有標記藥丸）。

        標記（重複、條件、格式）印出來會被拿掉，排在它們後面的仍算段落開頭；
        不這樣算的話，格子第一個 <div t-field> 會在標記後面多一個空行。
        """
        Mixin = self.env['doc.render.mixin']
        for el in reversed(out):
            if (el.get('value') or '') == '\n':
                return True
            if Mixin._is_marker_element(el):
                continue
            return False
        return True

    # col / col-6 / col-sm-7 / col-auto
    def _is_float_end(self, node):
        """沒有條件的 div.float-end（發票的合計區 #right-elements）。"""
        if not isinstance(node.tag, str) or node.tag.lower() != 'div':
            return False
        if any(node.get(a) is not None for a in ('t-if', 't-elif', 't-else', 't-foreach')):
            return False
        return 'float-end' in self._class_tokens(node)

    def _float_start_run(self, children, idx):
        """從 idx 起連續、沒有條件的 div.float-start（至少兩個）；沒有回 None。"""
        run = []
        for child in children[idx:]:
            if (not isinstance(child.tag, str) or child.tag.lower() != 'div'
                    or 'float-start' not in self._class_tokens(child)
                    or any(child.get(a) is not None for a in
                           ('t-if', 't-elif', 't-else', 't-foreach'))):
                break
            run.append(child)
            if (child.tail or '').strip():
                break
        return run if len(run) >= 2 else None

    # 估字寬：單號這類大寫英數字平均約 0.65 個字級寬（0.55 的話「WH/OUT/00001」
    # 放不下、折成兩行）
    _FLOAT_CHAR_EM = 0.65

    def _float_start_table(self, run, state):
        """並排的靠左浮動區塊 → 一列無框表格：前面幾格照內容估寬，最後一格吃剩下的。

        揀貨作業寫成 <div class="float-start"><h1 t-field="o.name"/></div>
        <div class="float-start">條碼</div>，官方條碼緊接在單號右邊。
        以前一個一個往下排，條碼掉到單號下面。
        浮動區塊的寬度是內容撐出來的；編輯器只有固定欄寬，所以用字數乘字級
        估（單號用範例值 WH/OUT/00001 的長度）。
        """
        inner = self._inner_width(state)
        widths = []
        for node in run[:-1]:
            heading = next((el for el in node.iter()
                            if isinstance(el.tag, str)
                            and re.match(r'^h[1-6]$', el.tag.lower())), None)
            size = self._heading_size(heading.tag.lower() if heading is not None
                                      else 'p')
            text = ' '.join(''.join(node.itertext()).split())
            widths.append(int(self._text_units(text) * size * self._FLOAT_CHAR_EM)
                          + 2 * self._CELL_PADDING)
        rest = inner - sum(widths)
        if rest < inner // 4:
            # 估出來太寬（範例值很長）就平分，至少不要把最後一格擠沒
            widths = [inner // len(run)] * (len(run) - 1)
            rest = inner - sum(widths)
        widths.append(rest)
        cells = []
        for node, width in zip(run, widths):
            value = []
            with self._in_width(state, width - self._CELL_PADDING):
                self._emit_children(node, value, state)
            if not value or (value[-1].get('value') or '') != '\n':
                value.append(self._newline())
            cells.append({'colspan': 1, 'rowspan': 1, 'value': value})
        state['stats']['table'] += 1
        return {
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'layout', 'fixedCols': True},
            'borderType': 'empty',
            'colgroup': [{'width': w} for w in widths],
            'trList': [{'tdList': cells}],
        }

    # 浮動區塊沒寫 col-N 時佔幾份（發票寫 col-5）
    _FLOAT_DEFAULT_SPAN = 5

    def _float_end_table(self, node, following, state):
        """浮動靠右的區塊 → 兩格無框表格：左格是後面的內容、右格是浮動區塊。

        官方發票把合計區寫成 div.col-5.float-end，後面的付款條件、付款說明、
        QR code、備註都繞在它左邊排。編輯器沒有浮動排版，以前合計區印完
        才接著印付款說明，整段掉到合計區下面。
        """
        span = self._FLOAT_DEFAULT_SPAN
        for token in self._class_tokens(node):
            m = self._COL_CLASS_RE.match(token)
            if m and (m.group('n') or '').isdigit() and not m.group('bp'):
                span = int(m.group('n'))
        inner = self._inner_width(state)
        right_w = int(inner * span / 12)
        left_w = inner - right_w
        holder = self._new_element('t')
        holder.text = node.tail
        for sibling in following:
            holder.append(sibling)
        left, right = [], []
        with self._in_width(state, left_w - self._CELL_PADDING):
            self._emit_children(holder, left, state)
        # 右格裡的稅額合計不再自己留左半邊空白（它已經在右邊了）
        state['in_float_end'] = state.get('in_float_end', 0) + 1
        try:
            with self._in_width(state, right_w - self._CELL_PADDING):
                self._emit_children(node, right, state)
        finally:
            state['in_float_end'] -= 1
        for cell in (left, right):
            if not cell or (cell[-1].get('value') or '') != '\n':
                cell.append(self._newline())
        left_td = {'colspan': 1, 'rowspan': 1, 'value': left}
        lift = self._negative_top_px(node)
        if lift:
            # 官方的合計區被第一個子元素的負上邊距（發票 #total 的 mt-n3）往上拉，
            # 左邊的付款說明不跟著上去；兩格同高起排時左格要往下補回這一段。
            # 格子開頭放不了小字級的空白列（canvas-editor 載入格子時一律在最前面
            # 補一個預設字級的段落起點），所以記在格子上，印的時候當上內距
            left_td['extension'] = {'paddingTop': round(lift, 1)}
        state['stats']['table'] += 1
        return {
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'layout', 'fixedCols': True},
            'borderType': 'empty',
            'colgroup': [{'width': left_w}, {'width': right_w}],
            'trList': [{'tdList': [
                left_td,
                {'colspan': 1, 'rowspan': 1, 'value': right},
            ]}],
        }

    _NEGATIVE_TOP_RE = re.compile(r'^m[ty]?-n(?P<n>[1-5])$')

    def _negative_top_px(self, node):
        """節點第一個子元素的負上邊距（mt-nN／my-nN／m-nN，px，正值）。"""
        child = next((c for c in node if isinstance(c.tag, str)), None)
        if child is None:
            return 0.0
        px = 0.0
        for token in self._class_tokens(child):
            m = self._NEGATIVE_TOP_RE.match(token)
            if m:
                px = max(px, self._SPACING_REM[m.group('n')] * self._SPACING_REM_PX)
        return px

    _COL_CLASS_RE = re.compile(
        r'^col(?:-(?P<bp>sm|md|lg|xl|xxl))?(?:-(?P<n>\d{1,2}|auto))?$')

    def _grid_columns(self, node):
        """div.row 的欄 → [(欄節點或二選一的分支鏈, 份數 or None)]；不是格線列回 None。

        份數是 Bootstrap 的 12 等分；None 是 col／col-auto（平分剩下的寬度）。
        只認「每個子節點都是 div.col…」的列，混了其他東西就照舊一段一段轉
        ——猜錯的並排比直排更難看懂。
        """
        tag = (node.tag if isinstance(node.tag, str) else '').lower()
        if tag != 'div' or 'row' not in self._class_tokens(node):
            return None
        if (node.text or '').strip():
            return None
        children = [c for c in node if isinstance(c.tag, str)]  # 略過註解
        columns = []
        idx = 0
        while idx < len(children):
            # t-if → t-elif → t-else 的幾欄是同一個位置二選一（採購單的
            # 「Order Date」／「Order Deadline」）：當成一欄，內容是若／否則。
            # 以前遇到 t-elif 就整列放棄，資訊欄變成一欄一欄往下排
            chain = self._collect_chain(children, idx)
            members = [n for _c, n in chain] if chain else [children[idx]]
            spans = []
            for child in members:
                if (child.tail or '').strip() or child.tag.lower() != 'div':
                    return None
                # 迴圈表達不了；落單的 elif／else（前面不是 t-if）也是
                if child.get('t-foreach') or (not chain and (
                        child.get('t-elif') is not None
                        or child.get('t-else') is not None)):
                    return None
                span = self._col_span(child)
                if span is False:
                    return None
                spans.append(span)
            # 二選一的欄寬取第一個分支的（最常見的那種狀態）
            columns.append((chain or members[0], spans[0]))
            idx += len(members)
        return columns if len(columns) >= 2 else None

    def _ancestor_col_span(self, node):
        """表格外層最近一個寫了 col-N 的 div 佔 12 等分的幾份；沒有回 None。

        採購單的合計區寫成 <div class="row justify-content-end"><div class="col-4">
        <table>…，官方只佔右邊 4/12；以前一律排成右半邊。
        """
        parent = node.getparent()
        while parent is not None:
            tag = parent.tag.lower() if isinstance(parent.tag, str) else ''
            if tag in ('table', 'td', 'th'):
                return None
            if tag == 'div':
                span = self._col_span(parent)
                if span:
                    return span
            parent = parent.getparent()
        return None

    def _col_span(self, node):
        """div.col… 佔 12 等分的幾份；col／col-auto 回 None；不是欄回 False。"""
        span, is_col = None, False
        for token in self._class_tokens(node):
            m = self._COL_CLASS_RE.match(token)
            if not m:
                continue
            is_col = True
            n = m.group('n')
            # PDF 用的是不帶斷點的寫法（col-6）；只有斷點版時退而求其次
            if n and n.isdigit() and (span is None or not m.group('bp')):
                span = int(n)
        return span if is_col else False

    def _grid_table(self, columns, state):
        """格線列 → 一列多格的無框表格（外框的地址區塊也是這個容器）。

        原生的 col 是彈性寬度：某一欄的條件不成立時，其他欄會往左補滿。
        reflowCols 記下哪幾欄是彈性的，快照時把整欄空白的欄拿掉、寬度分給
        彈性欄（見 _reflow_layout_columns）；固定寬度的欄（col-3）不放大。
        """
        inner = self._inner_width(state)
        fixed = sum(span for _c, span in columns if span)
        flex = [c for c, span in columns if not span]
        flex_units = (max(0, 12 - fixed) / len(flex)) if flex else 0
        if flex and flex_units <= 0:
            flex_units = 1
        units = [span or flex_units for _c, span in columns]
        total = max(12, sum(units))
        widths = [int(inner * u / total) for u in units]
        if total == sum(units):
            # 剛好排滿：最後一欄吸收湊整的誤差
            widths[-1] = inner - sum(widths[:-1])
        cells = []
        for (child, _span), width in zip(columns, widths):
            value = []
            with self._in_width(state, width - self._CELL_PADDING):
                if isinstance(child, list):
                    self._emit_chain(child, value, state)  # 二選一的欄
                else:
                    self._emit(child, value, state)
            if not value or (value[-1].get('value') or '') != '\n':
                value.append(self._newline())
            cell = {'colspan': 1, 'rowspan': 1, 'value': value}
            # 欄自己的下邊距（出貨單資訊欄的 col mb-2）不會跟外面合併，官方算在
            # 這一列的高度裡；不到一列空白列的高度補不出來，記成格子的下內距
            first = child[0][1] if isinstance(child, list) else child
            col_mb = self._spacing_px(first, 'bottom')
            if 0 < col_mb < self._SPACER_MIN_PX:
                cell['extension'] = {'paddingBottom': round(col_mb, 1)}
            cells.append(cell)
        state['stats']['table'] += 1
        return {
            'type': 'table', 'value': '',
            'extension': {'dobtorBlock': 'layout', 'fixedCols': True,
                          'reflowCols': [not span for _c, span in columns]},
            'borderType': 'empty',
            'colgroup': [{'width': w} for w in widths],
            'trList': [{'tdList': cells}],
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
                    pill = self._barcode_value_pill(node, expr, state)
                else:
                    cond = node.get('t-if')
                    if cond and not node.get('t-foreach'):
                        # <span t-if="o.ref" t-field="o.ref"/>：條件與值在同一個
                        # 節點上。原本只收值、條件整個不見——欄位有值時剛好一樣，
                        # 沒值時會印出一段本來不該出現的東西。
                        pill = self._ternary_pill(
                            node, self._branch_value(node, expr, state),
                            cond, state,
                        )
                    else:
                        pill = self._value_pill(node, expr, state)
                        if attr == 't-field':
                            self._set_empty_text(node, pill)
                # 取值節點自己的樣式：<span class="fw-bold" t-field="o.payment_reference">
                # 以前只看外層容器，發票付款說明裡的單號印成一般字
                own_style = self._node_style(node, tag)
                if own_style and self._takes_style(pill):
                    pill.update(own_style)
                role = self._company_color_role(node, tag)
                if role and self._takes_style(pill):
                    self._mark_company_color(pill, role)
                self._append_value(node, tag, pill, out)
                return

        # ── 圖片
        if tag == 'img':
            out.append(self._image_pill(node, state))
            state['stats']['image'] += 1
            return

        # ── 換行與分頁
        if tag == 'br':
            self._keep_line_before_break(out)
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
            table_cond = node.get('t-if')
            # 表格的上邊距（出貨單的 table.mt48）：有條件時跟著表格進條件區塊
            top = self._top_spacer_rows(node, out, state)
            if top and out and (out[-1].get('value') or '') != '\n':
                out.append(self._newline())
            # 有條件時表格會放進條件區塊裡，寬度要扣掉區塊的內距
            with self._in_width(state, self._block_body_width(state)
                                if table_cond else self._inner_width(state)):
                pieces = top + self._table_pieces(node, rows, totals_mode,
                                                  totals_first, state)
            # <table t-if="…"> 的條件原本被丟掉（表格分支排在條件分支前面）。
            # 出貨單的兩張明細表就是這個形狀。
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

        # ── Bootstrap 格線列（div.row ＞ div.col…）→ 並排的無框表格
        #    排在區塊條件之前：整列帶 t-if 時要先排成並排，再包條件
        cond = node.get('t-if')
        columns = self._grid_columns(node)
        if columns:
            top = self._top_spacer_rows(node, out, state)
            if top and out and (out[-1].get('value') or '') != '\n':
                out.append(self._newline())
            if cond:
                with self._in_width(state, self._block_body_width(state)):
                    grid = self._grid_table(columns, state)
                out.append(self._condition_wrap(
                    cond, top + [grid, self._newline()]
                    + self._spacer_rows(node, 'bottom'), state))
                out.append(self._newline())
            else:
                out.extend(top)
                out.append(self._grid_table(columns, state))
                out.append(self._newline())
                out.extend(self._spacer_rows(node, 'bottom'))
            return

        # ── 區塊條件：t-if 掛在區塊元素上 → 條件區塊
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
            out.extend(self._top_spacer_rows(node, out, state))
            start = len(out)
            block_markers, block_static = self._format_markers_for(node, state)
            out.extend(block_markers)
            self._emit_children(node, out, state)
            style = dict(self._node_style(node, tag) or {})
            style.update({k: v for k, v in block_static.items()
                          if k != 'align'})
            if style:
                for el in out[start:]:
                    if self._takes_style(el):
                        el.update(style)
            role = self._company_color_role(node, tag)
            if role:
                for el in out[start:]:
                    if self._takes_style(el):
                        self._mark_company_color(el, role)
            align = self._node_align(node)
            if out and (out[-1].get('value') or '') != '\n':
                out.append(self._newline())
            if align and len(out) > start:
                # 段落的對齊掛在結尾那個換行元素上（_elements_to_html 就是
                # 讀它的 rowFlex 決定 text-align）
                out[-1]['rowFlex'] = align
            if tag in self._HEADING_SCALE and len(out) > start:
                self._heading_paragraph(out[start:])
                if not self._spacing_px(node, 'bottom'):
                    # 標題自己寫了 mb-N 時照它（Bootstrap 是取代，不是疊加）
                    out.extend(self._spacer_rows_px(self._HEADING_GAP_PX))
            out.extend(self._spacer_rows(node, 'bottom'))
            return

        # span / strong / t 等行內容器
        inline = []
        self._emit_children(node, inline, state)
        style = self._node_style(node, tag)
        role = self._company_color_role(node, tag)
        for el in inline:
            # 欄位藥丸也要套（規則同 _takes_style）：<strong> 包著的
            # 「發票地址／發票及送貨地址」三元式藥丸以前不會變粗
            if style and self._takes_style(el):
                el.update(style)
            if role and self._takes_style(el):
                self._mark_company_color(el, role)
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

    # t-attf-class 裡的動態片段：{{ … }} 與 #{ … }
    _ATTF_DYNAMIC_RE = re.compile(r'\{\{.*?\}\}|#\{.*?\}', re.S)

    def _class_tokens(self, node):
        """節點的 class，含 t-attf-class 裡寫死的那幾個。

        原生的數量欄、稅別欄寫成 t-attf-class="text-end {{ 'text-nowrap' if … }}"：
        只讀 class 的話右對齊整個不見。動態片段（text-nowrap 這類）沒有對應物，丟掉。
        """
        tokens = set((node.get('class') or '').split())
        attf = node.get('t-attf-class')
        if attf:
            tokens.update(self._ATTF_DYNAMIC_RE.sub(' ', attf).split())
        return tokens

    def _attf_dynamic_matters(self, raw):
        """t-attf-class 的動態片段裡有沒有「看得出差別」的 class。

        只有排版用的（text-nowrap、col-6、ms-auto…）時，轉不過去也不影響
        單據長相，不必列進待辦。
        """
        visible = set(self._CLASS_STYLE) | set(self._CLASS_ALIGN)
        for piece in self._ATTF_DYNAMIC_RE.findall(raw or ''):
            for literal in re.findall(r"'([^']*)'|\"([^\"]*)\"", piece):
                words = ' '.join(literal).split()
                if visible.intersection(words):
                    return True
            if not re.search(r"'|\"", piece):
                # 動態片段直接輸出變數（{{ cls }}）——看不出是什麼，當作有影響
                return True
        return False

    # Bootstrap 的上下留白 class（mb-4 這類）：數字 → 幾倍 rem
    _SPACING_CLASS_RE = re.compile(r'^(?P<prop>m[tby]?)-(?P<n>[0-5])$')
    _SPACING_REM = {'0': 0, '1': 0.25, '2': 0.5, '3': 1, '4': 1.5, '5': 3}
    # 官方報表 1rem 印出來約 12.8px（16px 縮到 0.8 倍，見 doc.template
    # 的 _OFFICIAL_TEXT_STYLE），一列空白約 19.5px
    _SPACING_REM_PX = 12.8
    _SPACING_ROW_PX = 19.5

    def _spacing_px(self, node, side):
        """節點上 mb-N／mt-N（含 my-N、m-N）的留白（px，已換算成官方印出來的大小）。

        官方的地址區、資訊欄都是 mb-4——少了這段留白，地址、標題、資訊欄、
        明細表整張擠在一起。
        """
        wanted = 'b' if side == 'bottom' else 't'
        px = 0.0
        if side == 'bottom' and isinstance(node.tag, str) and node.tag.lower() == 'address':
            # 實測官方發票：<address class="mb-0" t-field="o.partner_id"> 下方仍留
            # 1rem（瀏覽器量到 margin-bottom 16px，mb-0 沒有生效），統編那一行
            # 跟地址之間空一段。訂單的地址用 <div t-field>，沒有這段留白
            px = self._SPACING_REM['3'] * self._SPACING_REM_PX
        for token in self._class_tokens(node):
            legacy = self._LEGACY_SPACING_RE.match(token)
            if legacy and legacy.group('side') == wanted:
                # Odoo 舊寫法 mt16／mb48：直接是 px，印出來一樣縮到 0.8 倍
                px = max(px, int(legacy.group('px')) * self._SPACING_REM_PX / 16)
                continue
            m = self._SPACING_CLASS_RE.match(token)
            if not m:
                continue
            prop = m.group('prop')
            if prop == 'm' or prop == 'my' or prop == 'm' + wanted:
                px = max(px, self._SPACING_REM[m.group('n')] * self._SPACING_REM_PX)
        return px

    # Odoo 自己的舊式留白 class（web 的 utils：mt8／mt16／mt32／mt48…，單位 px）
    _LEGACY_SPACING_RE = re.compile(r'^m(?P<side>[tb])(?P<px>\d{1,3})$')

    def _trailing_spacer_px(self, out):
        """out 結尾那幾列空白列合起來多高（px）。"""
        px = 0.0
        for el in reversed(out):
            if not el.get('_spacer'):
                break
            px += (el['size'] * self._SPACER_LINE_FACTOR if el.get('size')
                   else self._SPACING_ROW_PX)
        return px

    def _top_spacer_rows(self, node, out, state):
        """上邊距的空白列，扣掉前面已經留的下邊距（瀏覽器的上下邊距會合併取大的）。

        出貨單的明細表是 table.mt48，前面的資訊欄是 mb-4：官方兩段併成 48px，
        不是相加。前面是條件區塊的開頭（out 裡只有標記）時，看進區塊前外面的。
        """
        Mixin = self.env['doc.render.mixin']
        content = [el for el in out if not Mixin._is_marker_element(el)]
        tail = (self._trailing_spacer_px(content) if content
                else state.get('outer_tail_px') or 0.0)
        return self._spacer_rows_px(max(0.0, self._spacing_px(node, 'top') - tail))

    # 空白列的行高是字級的幾倍：官方樣式 13px、每列上下各 1.6px（見
    # doc.report._report_text_css），1.25 ＋ 3.2 ÷ 13 ≈ 1.5
    _SPACER_LINE_FACTOR = 1.5
    # 不到這麼多的留白不補（mb-2 是 6.4px，補了反而比官方鬆）
    _SPACER_MIN_PX = 8

    def _spacer_rows(self, node, side):
        """留白 → 空白列。整行的用一般字級，剩下的一截用小字級的空白列補。

        編輯器沒有「段落下方留多少 px」，只能用空白列表達；空白列有多高看
        開頭那個換行的字級，所以 12.8px 的留白（mb-3、address）用 9px 的空白列，
        不必撐成一整行 19.5px。
        _spacer：讓 _paragraph_ends_to_starts 知道這是空白列，不是收掉表格的換行。
        """
        return self._spacer_rows_px(self._spacing_px(node, side))

    def _spacer_rows_px(self, px):
        """px 的留白 → 空白列（規則同 _spacer_rows）。"""
        rows = []
        while px >= self._SPACING_ROW_PX:
            rows.append(dict(self._newline(), _spacer=True))
            px -= self._SPACING_ROW_PX
        if px >= self._SPACER_MIN_PX:
            size = max(5, int(round(px / self._SPACER_LINE_FACTOR)))
            rows.append(dict(self._newline(), _spacer=True, size=size))
        return rows

    # 官方報表的標題字級是內文的幾倍（Bootstrap：h1 2.5、h2 2、h3 1.75…）。
    # 粗細是 500，編輯器只有一般與粗體，取一般——印成粗體反而比官方重
    _HEADING_SCALE = {'h1': 2.5, 'h2': 2, 'h3': 1.75, 'h4': 1.5,
                      'h5': 1.25, 'h6': 1}

    def _heading_size(self, tag):
        base = self.env['doc.template']._OFFICIAL_TEXT_STYLE['text_size']
        return int(round(base * self._HEADING_SCALE.get(tag, 1)))

    # 標題下方的留白（px）：Bootstrap h1–h6 是 margin-bottom .5rem，照官方
    # PDF 實測標題到下一段要 9px 位置才對（.5rem 只有 6.4px，字型字身的差補在這裡）
    _HEADING_GAP_PX = 9
    # 標題本身的下邊距（.5rem）；外面包的空 div 上邊距比它大時才要多留
    _HEADING_MARGIN_PX = 6.4

    def _heading_paragraph(self, elements):
        """標題段落照 Bootstrap 的行高（1.2 倍，比內文緊）。

        canvas-editor 的段落行距是逐元素算的（每個元素「字高＋上下各
        8px × 行距」，整列取最高），所以字和結尾換行（轉成編輯器格式後是
        段落開頭）都要設行距 0；PDF 照段落開頭的行距印行高 1.25 倍。
        以前沿用內文行距，26px 的標題上下各多 4px，標題整個往下掉一截。
        """
        for el in elements:
            if isinstance(el, dict) and el.get('type') not in ('table', 'image'):
                el['rowMargin'] = 0

    def _node_style(self, node, tag):
        """標籤與 class 一起決定的文字屬性。"""
        style = {}
        if tag in self._HEADING_SCALE:
            style['size'] = self._heading_size(tag)
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
        取值節點（t-field／t-out）的子節點是官方放的示範內容，印的時候會被值
        取代，不看：揀貨作業的收件地址裡放了一塊 text-center 的示範框，
        以前地址整段被印成置中。
        """
        is_value = any(node.get(a) for a in ('t-field', 't-out', 't-esc'))
        for candidate in [node] + ([] if is_value else list(node)[:1]):
            if not isinstance(candidate.tag, str):
                continue
            for token in self._class_tokens(candidate):
                if token in self._CLASS_ALIGN:
                    return self._CLASS_ALIGN[token]
        return None

