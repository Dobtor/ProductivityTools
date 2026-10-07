import json
import logging
import re

from odoo import models

_logger = logging.getLogger(__name__)

# QWeb 報表的根變數。報表範本習慣用 doc / o / docs 當單筆記錄的名字。
_ROOT_VARS = ('doc', 'o', 'object', 'record')

# 只是外殼、不含內容的範本——往下追 t-call 時要跳過它們
_WRAPPER_TEMPLATES = frozenset({
    'web.html_container', 'web.html_preview_container',
    'web.basic_layout', 'web.minimal_layout',
})

# 外框：它的內容對應「外框範本」，本文在 <t t-out="0"/> 的位置
_LAYOUT_TEMPLATES = frozenset({
    'web.external_layout', 'web.internal_layout', 'web.address_layout',
})

# 稅額彙總子範本 → 內建區塊
_TAX_TOTALS_TEMPLATES = frozenset({
    'sale.document_tax_totals', 'account.document_tax_totals',
    'purchase.document_tax_totals',
})
_TAX_TOTALS_COMPANY_TEMPLATES = frozenset({
    'account.document_tax_totals_company_currency_template',
})

# t-options 的 widget → 本模組對應的包法
_WIDGET_WRAPPERS = {
    'monetary': 'format_money(%s)',
    'date': 'format_date(%s)',
    'datetime': "format_date(%s, '%%Y-%%m-%%d %%H:%%M')",
    'integer': "format_number(%s, ',.0f')",
    'float': 'format_number(%s)',
    'contact': 'format_address(%s)',
}

_BLOCK_TAGS = frozenset({
    'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
    'section', 'header', 'footer', 'article', 'blockquote', 'pre',
})
_SKIP_TAGS = frozenset({'script', 'style', 'link', 'meta'})

_SIMPLE_PATH_RE = re.compile(r'^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$')


class DocQwebConverter(models.AbstractModel):
    """把原生 QWeb 報表範本轉成本模組的 content_json。

    這支**只轉版面與結構**，而且會把每一個沒把握的地方列進 notes。
    設計原則只有一條：**寧可標成待辦，也不要猜**。轉錯的版面使用者看得見，
    轉錯的綁定（印出別的欄位的值）看不見。

    與「從渲染結果反推綁定」完全不同：那條路不安全（數量的 "2" 在一份輸出
    裡出現 243 次；qty=1 時 price_unit 與 price_subtotal 數學上不可區分）。
    但從 arch 轉換時 `t-field="doc.partner_id"` 寫得清清楚楚——路徑是讀出來的，
    不是猜的。所以簡單路徑會直接綁好，複雜表達式才標 unbound。
    """
    _name = 'doc.qweb.converter'
    _description = 'QWeb 報表 → 文件範本轉換器'

    # ─── 入口 ───────────────────────────────────────────────────────

    def convert_report(self, report, page_format='A4'):
        """report（ir.actions.report）→ {'content_json', 'notes', 'stats'}。"""
        view = self._resolve_document_view(report)
        if view is None:
            return {
                'content_json': '',
                'notes': ['找不到報表的 QWeb 範本（report_name=%s）'
                          % (report.report_name or '')],
                'stats': {},
            }
        root = self._parse_arch(view)
        if root is None:
            return {'content_json': '', 'notes': ['QWeb arch 解析失敗'],
                    'stats': {}}

        state = {
            'notes': [],
            'stats': {'pill': 0, 'repeat': 0, 'condition': 0, 'table': 0,
                      'unbound': 0, 'image': 0, 'taxTotals': 0},
            'loop_vars': [],
            'page_format': page_format,
            'view': view,
        }
        body_node, layout_nodes = self._split_layout(root, state)

        main = []
        self._emit_children(body_node, main, state)
        self._trim(main)

        header = []
        if layout_nodes:
            for node in layout_nodes:
                self._emit_children(node, header, state)
            self._trim(header)
            state['notes'].append(
                '外框（web.external_layout）的內容已放進「頁首」區。'
                '建議改成獨立的外框範本（文件管理 ▸ 外框範本），'
                '公司資訊改一次就能套用到所有單據。'
            )

        tree = {'header': header, 'main': main, 'footer': []}
        return {
            'content_json': json.dumps(tree, ensure_ascii=False),
            'notes': state['notes'],
            'stats': state['stats'],
        }

    # ─── 範本定位 ───────────────────────────────────────────────────

    def _view_by_key(self, key):
        if not key:
            return None
        View = self.env['ir.ui.view'].sudo()
        view = View.search([('key', '=', key)], limit=1)
        if not view and '.' in key:
            module, _sep, name = key.partition('.')
            ref = self.env.ref('%s.%s' % (module, name),
                               raise_if_not_found=False)
            view = ref if ref and ref._name == 'ir.ui.view' else None
        return view or None

    def _resolve_document_view(self, report):
        """從報表的 report_name 一路追到「真正有內容」的那張範本。

        報表的入口通常只是 html_container + t-foreach docs，內容在它
        t-call 的 *_document 範本裡。不往下追會轉出一張空白範本。
        """
        view = self._view_by_key(report.report_name)
        seen = set()
        for _depth in range(4):
            if view is None or view.id in seen:
                break
            seen.add(view.id)
            root = self._parse_arch(view)
            if root is None:
                break
            targets = [
                t for t in root.xpath('//t[@t-call]/@t-call')
                if t and t not in _WRAPPER_TEMPLATES
                and t not in _LAYOUT_TEMPLATES
                and t not in _TAX_TOTALS_TEMPLATES
            ]
            # 只有外殼（沒有自己的 t-field / 表格）時才往下追
            has_content = bool(root.xpath('//*[@t-field or @t-out] | //table'))
            if has_content or not targets:
                return view
            nxt = self._view_by_key(targets[0])
            if nxt is None:
                return view
            view = nxt
        return view

    def _parse_arch(self, view):
        try:
            from lxml import etree
            return etree.fromstring(
                view.arch_db or view.arch or '<t/>',
                etree.XMLParser(recover=True, remove_comments=True),
            )
        except Exception as e:
            _logger.warning('[qweb-import] arch 解析失敗 %s：%s', view.key, e)
            return None

    def _split_layout(self, root, state):
        """拆出 (本文節點, 外框節點清單)。

        外框的結構是 <t t-call="web.external_layout"> 裡放幾個 t-set 區塊
        （address / information_block / layout_document_title），本文則是
        同一層的其餘內容（對應外框裡的 <t t-out="0"/>）。
        """
        layout_calls = root.xpath(
            '//t[@t-call="web.external_layout" or @t-call="web.internal_layout"]'
        )
        if not layout_calls:
            return root, []
        call = layout_calls[0]
        layout_nodes = []
        body_holder = self._new_element('t')
        for child in list(call):
            if child.tag == 't' and child.get('t-set'):
                # t-set 區塊（address / information_block / 標題）＝外框內容
                layout_nodes.append(child)
            else:
                body_holder.append(child)
        return body_holder, layout_nodes

    def _new_element(self, tag):
        from lxml import etree
        return etree.Element(tag)

    # ─── 元素輸出 ───────────────────────────────────────────────────

    def _text(self, value, **kw):
        return dict({'value': value}, **kw)

    def _newline(self):
        return {'value': '\n'}

    def _trim(self, out):
        """去掉開頭與結尾多餘的換行。"""
        while out and (out[0].get('value') or '') == '\n':
            out.pop(0)
        while len(out) > 1 and (out[-1].get('value') or '') == '\n' \
                and (out[-2].get('value') or '') == '\n':
            out.pop()
        if out and (out[-1].get('value') or '') != '\n':
            out.append(self._newline())

    def _pill(self, label, state, **meta):
        payload = dict(meta)
        payload['labelText'] = label
        if payload.get('unbound'):
            state['stats']['unbound'] += 1
        state['stats']['pill'] += 1
        return {
            'type': 'label', 'value': label,
            'label': ({'backgroundColor': '#ffe0b2', 'color': '#bf360c'}
                      if payload.get('unbound')
                      else {'backgroundColor': '#e3f2fd', 'color': '#1976d2'}),
            'extension': {'dobtorField': payload},
        }

    def _note(self, state, text):
        if text not in state['notes']:
            state['notes'].append(text)

    # ─── 表達式對應 ─────────────────────────────────────────────────

    def _strip_root(self, expr, state):
        """把 doc.partner_id → partner_id、line.name → name（迴圈內）。

        回 (path, kind)，kind 為 'record' / 'line' / None（對不上根變數）。
        """
        expr = (expr or '').strip()
        if not expr:
            return None, None
        for var in reversed(state['loop_vars']):
            if expr == var:
                return '', 'line'
            if expr.startswith(var + '.'):
                return expr[len(var) + 1:], 'line'
        for var in _ROOT_VARS:
            if expr == var:
                return '', 'record'
            if expr.startswith(var + '.'):
                return expr[len(var) + 1:], 'record'
        return None, None

    def _parse_options(self, node):
        """t-options 的 widget 名稱（解析失敗回 None）。"""
        raw = node.get('t-options') or node.get('t-options-widget')
        if not raw:
            return None
        m = re.search(r'["\']widget["\']\s*:\s*["\'](\w+)["\']', raw)
        if m:
            return m.group(1)
        m = re.match(r'^["\'](\w+)["\']$', raw.strip())
        return m.group(1) if m else None

    def _mapped_value_expr(self, node, expr, state):
        """取值節點 → 沙箱表達式字串；對不上根變數回 None。

        與 _value_pill 共用：行內的 t-if/t-else 分支要收成一句三元式時，
        需要的是「表達式」而不是「藥丸」。
        """
        path, kind = self._strip_root(expr, state)
        if path is None or not _SIMPLE_PATH_RE.match(path or 'x'):
            return None
        base = ('line.%s' % path) if kind == 'line' else ('object.%s' % path)
        widget = self._parse_options(node)
        if widget and widget in _WIDGET_WRAPPERS:
            return _WIDGET_WRAPPERS[widget] % base
        return base

    def _value_pill(self, node, expr, state):
        """t-field / t-out / t-esc → 藥丸。"""
        path, kind = self._strip_root(expr, state)
        widget = self._parse_options(node)
        label = (path or expr).split('.')[-1] or expr

        if path is None or not _SIMPLE_PATH_RE.match(path or 'x'):
            # 複雜表達式：原樣保留，標成待辦。使用者看得到原始 QWeb 寫法，
            # 比我猜一個錯的路徑好得多。
            self._note(
                state,
                '表達式需要人工確認：%s' % (expr[:120]),
            )
            return self._pill('待確認：%s' % label[:20], state,
                              source='record', expression=expr, unbound=True)

        source = 'line' if kind == 'line' else 'record'
        base = ('line.%s' % path) if kind == 'line' else ('object.%s' % path)

        if widget and widget in _WIDGET_WRAPPERS:
            return self._pill(label, state, source=source,
                              path=path,
                              expression=_WIDGET_WRAPPERS[widget] % base)
        if widget:
            self._note(state, '未支援的 widget「%s」，已改為直接輸出欄位值。'
                              % widget)
        return self._pill(label, state, source=source, path=path)

    # ─── 走訪 ───────────────────────────────────────────────────────

    def _emit_children(self, node, out, state):
        if node.text and node.text.strip():
            out.append(self._text(node.text.strip()))
        children = list(node)
        idx = 0
        while idx < len(children):
            child = children[idx]
            chain = self._collect_chain(children, idx)
            if chain:
                self._emit_chain(chain, out, state)
                idx += len(chain)
                last = chain[-1][1]
                if last.tail and last.tail.strip():
                    out.append(self._text(last.tail.strip()))
                continue
            self._emit(child, out, state)
            if child.tail and child.tail.strip():
                out.append(self._text(child.tail.strip()))
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
        if node.xpath('.//table | .//img | .//*[@t-field or @t-out or @t-esc'
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
        if len(values) == 1 and not node.xpath('.//table | .//img'):
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
        return self._map_condition(expr, state)

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
            expr = '%s if (%s) else %s' % (
                piece, self._map_condition(cond, state), expr,
            )
        label = ' '.join((''.join(chain[0][1].itertext()) or '').split())
        if not label:
            # 取值型分支沒有文字可當標籤，用第一個分支的欄位名
            label = (exprs[0][1] or '').split('.')[-1].strip('()')
        state['stats']['condition'] += 1
        # 在重複列內要用 line 來源，否則會以主記錄求值、每列同一個值
        source = 'line' if 'line.' in expr else 'record'
        return self._pill(label[:20] or '多重分支', state,
                          source=source, expression=expr,
                          unbound=bool(state.get('chain_unsure')))

    def _chain_blocks(self, chain, state):
        """複雜分支 → 巢狀的若／否則區塊（實測三擇一可行）。"""
        state['chain_seq'] = state.get('chain_seq', 0) + 1
        gid = 'cg%d' % state['chain_seq']
        cond, node = chain[0]
        if_inner = []
        self._emit_children(node, if_inner, state)
        if not if_inner or (if_inner[-1].get('value') or '') != '\n':
            if_inner.append(self._newline())

        rest = chain[1:]
        else_inner = []
        if len(rest) == 1 and rest[0][0] is None:
            self._emit_children(rest[0][1], else_inner, state)
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
                    expression=self._map_condition(cond, state),
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
        if call:
            self._note(state, '子範本 t-call="%s" 未轉換，需要人工處理。' % call)
            return

        # ── 值
        for attr in ('t-field', 't-out', 't-esc'):
            expr = node.get(attr)
            if expr:
                # 節點內的文字是給設計師看的範例值（<span t-field="x">3</span>
                # 裡的那個 3），不可當成內容——原生渲染時也會被值取代
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
            out.append(self._emit_table(node, state))
            state['stats']['table'] += 1
            out.append(self._newline())
            return

        # ── 區塊條件：t-if 掛在區塊元素上 → 條件區塊
        cond = node.get('t-if')
        if cond and tag in _BLOCK_TAGS:
            out.append(self._condition_block(node, cond, state))
            out.append(self._newline())
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

        # ── t-foreach 不在表格列上（罕見：清單、卡片）
        if node.get('t-foreach') and tag != 'tr':
            self._note(
                state,
                '非表格的 t-foreach="%s" 未轉換——重複只支援表格列，'
                '請改用表格呈現。' % (node.get('t-foreach') or '')[:60],
            )

        # ── 一般容器
        if tag in _BLOCK_TAGS:
            if out and (out[-1].get('value') or '') != '\n':
                out.append(self._newline())
            self._emit_children(node, out, state)
            if out and (out[-1].get('value') or '') != '\n':
                out.append(self._newline())
            return

        # span / strong / t 等行內容器
        inline = []
        self._emit_children(node, inline, state)
        style = self._inline_style(tag)
        for el in inline:
            if style and el.get('type') != 'label':
                el.update(style)
        out.extend(inline)

    def _inline_style(self, tag):
        if tag in ('strong', 'b'):
            return {'bold': True}
        if tag in ('em', 'i'):
            return {'italic': True}
        if tag == 'u':
            return {'underline': True}
        return None

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
        self._note(state, '圖片來源需要人工確認：%s' % (src or '（無 src）')[:80])
        return self._pill('圖片（待確認）', state, source='image',
                          path='', unbound=True)

    # ─── 稅額彙總 ───────────────────────────────────────────────────

    def _tax_totals_block(self, state, mode='document'):
        def val(part, field, label):
            return self._pill(label, state, source='taxTotals', part=part,
                              field=field, currencyMode=mode)
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
                {'tdList': [cell(val('untaxed', 'label', '稅前小計')),
                            cell(val('untaxed', 'amount', '金額'))]},
                {'tdList': [cell(val('groups', 'label', '稅別')),
                            cell(val('groups', 'amount', '稅額'))]},
                {'tdList': [cell(self._text('總計')),
                            cell(val('total', 'amount', '總計金額'))]},
            ],
        }

    # ─── 表格 ───────────────────────────────────────────────────────

    def _inner_width(self, state):
        page_w = 1123 if state.get('page_format') == 'A4_landscape' else 794
        return max(200, page_w - 192)

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
        per = inner // max_cols
        colgroup = [{'width': per} for _ in range(max_cols)]
        if colgroup:
            colgroup[-1]['width'] = inner - per * (max_cols - 1)

        # 欄條件：同一個 t-if 同時出現在 th 與 td 上 → 欄層級
        th_conds = {}
        for tr in rows_src:
            for idx, cell in enumerate(tr.xpath('./th')):
                if cell.get('t-if'):
                    th_conds[cell.get('t-if')] = idx

        tr_list = []
        for tr in rows_src:
            repeat = foreach_rows.get(tr)
            branches = self._row_branches(tr)
            if branches and repeat:
                # 迴圈內的 t-if / t-elif / t-else 包住不同的格子組合
                # ——那就是「列型分派」：一筆明細依型別挑一種版面。
                for b_idx, (cond, holder) in enumerate(branches):
                    row = self._table_row(
                        holder, state, repeat, th_conds, max_cols,
                        row_filter=self._map_condition(cond, state)
                        if cond else '',
                        with_marker=True,
                    )
                    if row is not None:
                        tr_list.append(row)
                state['notes'].append(
                    '明細有 %d 種列型（商品／章節／備註…），已各自建一列。'
                    '有條件的列型優先，條件留空的那一列接住其餘。' % len(branches)
                )
                continue
            row = self._table_row(tr, state, repeat, th_conds, max_cols)
            if row is not None:
                tr_list.append(row)
        if foreach_rows:
            state['stats']['repeat'] += 1
        return {
            'type': 'table', 'value': '',
            'colgroup': colgroup,
            'trList': tr_list or [{'tdList': [
                {'colspan': 1, 'rowspan': 1, 'value': [self._newline()]}]}],
        }

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

    def _table_row(self, tr, state, repeat, th_conds, max_cols,
                   row_filter='', with_marker=None):
        pushed = False
        if repeat:
            expr, as_var = repeat
            state['loop_vars'].append(as_var)
            pushed = True
        try:
            # 分支容器（<t t-if>）本身不是 tr，所以 _row_cells 的 closest_row
            # 比對會失敗——那種情況直接取它的直接子格子
            tag = tr.tag if isinstance(tr.tag, str) else ''
            cells = (self._row_cells(tr) if tag.lower() == 'tr'
                     else tr.xpath('./td | ./th'))
            td_list = []
            first = True
            for cell in cells:
                value = []
                # 欄條件 / 格條件
                cond = cell.get('t-if')
                if cond:
                    if cond in th_conds:
                        value.append(self._pill(
                            '欄條件', state, source='column',
                            expression=self._map_condition(cond, state),
                        ))
                        state['stats']['condition'] += 1
                    else:
                        self._note(
                            state,
                            '儲存格條件「%s」已轉成列型條件的候選，'
                            '請在右欄確認（或改用欄條件）。' % cond[:70],
                        )
                if first and repeat and with_marker is not False:
                    # 重複標記放第一格：後端找「含該標記的那一列」，
                    # 放哪一格都可以，第一格最容易被看到
                    value.append(self._repeat_marker(
                        repeat, state, row_filter=row_filter,
                    ))
                    first = False
                self._emit_children(cell, value, state)
                if not value or (value[-1].get('value') or '') != '\n':
                    value.append(self._newline())
                # colspan 夾在欄數內：QWeb 的 colspan="99" 是「跨滿整列」
                td = {'colspan': max(1, min(int(cell.get('colspan') or 1),
                                            max_cols)),
                      'rowspan': int(cell.get('rowspan') or 1),
                      'value': value}
                td_list.append(td)
            if not td_list:
                return None
            return {'tdList': td_list}
        finally:
            if pushed:
                state['loop_vars'].pop()

    def _repeat_marker(self, repeat, state, row_filter=''):
        expr, as_var = repeat
        # t-foreach 的來源常是上面 t-set 出來的變數（lines_to_report），
        # 那個變數在這裡看不到定義 → 標成待辦讓使用者選欄位
        path, kind = self._strip_root(expr, {'loop_vars': []})
        label = ('列型 × %s' % path) if row_filter else ('明細 × %s' % path)
        if path and _SIMPLE_PATH_RE.match(path):
            return self._pill(label, state, source='repeat',
                              path=path, repeatId='rp_%s' % as_var,
                              rowFilter=row_filter)
        self._note(
            state,
            '重複來源「%s」是範本內的中間變數，請在右欄改成實際的一對多欄位'
            '（或填「來源表達式」）。' % expr[:70],
        )
        return self._pill(
            '列型（待設定）' if row_filter else '明細（待設定）',
            state, source='repeat', path='', repeatId='rp_%s' % as_var,
            rowFilter=row_filter, unbound=True,
        )

    # ─── 條件 ───────────────────────────────────────────────────────

    def _map_condition(self, expr, state):
        """QWeb 條件 → 沙箱表達式。只做根變數替換，其餘原樣保留。"""
        out = (expr or '').strip()
        for var in reversed(state.get('loop_vars') or []):
            out = re.sub(r'\b%s\.' % re.escape(var), 'line.', out)
        for var in _ROOT_VARS:
            out = re.sub(r'\b%s\.' % re.escape(var), 'object.', out)
        return out

    def _condition_block(self, node, cond, state):
        inner = []
        # 條件節點本身的內容；條件已經移到標記上，不要再往下看 t-if
        holder = self._new_element('t')
        holder.text = node.text
        for child in list(node):
            holder.append(child)
        self._emit_children(holder, inner, state)
        if not inner or (inner[-1].get('value') or '') != '\n':
            inner.append(self._newline())
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
                    expression=self._map_condition(cond, state),
                )] + inner,
            }]}],
        }
