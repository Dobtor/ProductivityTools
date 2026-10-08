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
    # 日期一律走語言格式：原生印 10/08/2026，ISO 的 2026-10-08 在單據上
    # 是看得出來的差別（實測比對原生輸出時第一個跳出來的就是它）
    'date': "format_date(%s, 'lang')",
    'datetime': "format_date(%s, 'lang_datetime')",
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
# 表達式有沒有綁到沙箱裡的根變數（object / line）。
# 一律用 token 比對，不要寫 'line.' in expr：迴圈變數是 dict 時 QWeb 寫
# 下標（line['date']），帶點的字串比對會判成「不是明細欄位」，
# 藥丸的 source 就變成 record——印出來是空的，而且沒有任何訊息。
_ROOT_TOKEN_RE = re.compile(r'\b(object|line)\b')
_LINE_TOKEN_RE = re.compile(r'\bline\b')


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

    def convert_report(self, report, page_format='A4', validate_with=None):
        """report（ir.actions.report）→ {'content_json', 'notes', 'stats'}。

        validate_with 給一筆樣本記錄時，轉換後會把每個藥丸的表達式試算一遍
        （見 validate_tree）。強烈建議給——那是把「規則表猜的」變成
        「實測過的」唯一方法。
        """
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
                      'unbound': 0, 'image': 0, 'taxTotals': 0,
                      'validated': 0, 'validate_failed': 0,
                      'validate_skipped': 0},
            'loop_vars': [],
            'loop_sources': [],
            'loop_models': [],
            'model': report.model,
            # 樣本記錄：迴圈來源是「白名單方法」或算式時，路徑查不出模型，
            # 只能實際跑一次拿第一筆的 _name（見 _loop_model）
            'sample': validate_with[:1] if validate_with else None,
            'page_format': page_format,
            'view': view,
        }
        # 先把子範本併進來再收符號表：子範本自己的 t-set 要被看到，
        # 而且併入後整棵樹就是 QWeb 實際渲染的那一棵。
        self._inline_calls(root, state)
        self._collect_symbols(root, state)
        body_node, blocks = self._split_layout(root, state)

        main = []
        self._emit_layout_blocks(blocks, main, state)
        self._emit_children(body_node, main, state)
        self._trim(main)

        # 頁首頁尾一律留空，交給外框範本——公司 logo、公司資訊、頁碼對所有
        # 報表都一樣，複製進每一張範本的話改公司地址要改 N 張。
        tree = {'header': [], 'main': main, 'footer': []}
        needs_layout = bool(
            root.xpath('//t[@t-call="web.external_layout"'
                       ' or @t-call="web.internal_layout"]')
        )
        if validate_with is not None and validate_with:
            try:
                self.validate_tree(tree, validate_with[:1], state)
            except Exception as e:
                _logger.warning('[qweb-import] 試算失敗：%s', e)
                self._note(state, '無法用樣本記錄試算（%s）。'
                                  '請自行印一張比對。' % e)
        return {
            'content_json': json.dumps(tree, ensure_ascii=False),
            'notes': state['notes'],
            'stats': state['stats'],
            'needs_layout': needs_layout,
        }

    # ─── 轉換後試算 ─────────────────────────────────────────────────
    #
    # 轉換器唯一會「猜」的地方是 _REWRITE_RULES。猜完就拿一筆真實記錄把每個
    # 藥丸的表達式跑一遍——算得出來的把「待確認」拿掉，算不出來的留著並附上
    # 真正的錯誤訊息。
    #
    # 這一步把待辦清單從「我改寫了，你自己確認」變成「我改寫了，而且試算過，
    # 這幾個算不出來」。差別在於使用者要檢查的項目數，以及他是否得回去讀
    # 原生範本才知道該檢查什麼。

    def _iter_validation_targets(self, tree, record):
        """yield (元素, 該元素所在重複列的一筆明細 or None)。

        不能全樹共用一筆明細：同一張單據上可以有好幾個不同形狀的重複
        （發票同時有「明細列」與「付款列」，後者的一筆是 dict），
        拿明細列的那一筆去試算付款列的 line 藥丸，會得到一整批假失敗，
        而假失敗會把藥丸標成待確認——使用者去檢查一個其實沒問題的地方。
        """
        Mixin = self.env['doc.render.mixin']

        def walk(elements, line, loop):
            for element in elements:
                yield element, line, loop
                if element.get('type') != 'table':
                    continue
                for row in (element.get('trList') or []):
                    if not isinstance(row, dict):
                        continue
                    row_line, row_loop = line, loop
                    marker, meta = Mixin._row_repeat_meta(row)
                    if marker:
                        lines = Mixin._resolve_repeat_records(record, meta)
                        row_line = lines[0] if lines else None
                        # 用「最後一筆」的迴圈位置試算：原生的章節小計條件寫
                        #   line_last or lines[line_index+1].display_type == …
                        # 假裝在中間的話 lines[index+1] 會超出範圍，變成一個
                        # 假失敗；假裝在最後一筆則 or 會短路，跟原生一樣。
                        row_loop = Mixin._loop_context(
                            max(0, len(lines) - 1), len(lines))
                    for cell in (row.get('tdList') or []):
                        if isinstance(cell, dict):
                            yield from walk(cell.get('value') or [],
                                            row_line, row_loop)

        for zone in ('header', 'main', 'footer'):
            yield from walk(tree.get(zone) or [], None, None)

    def validate_tree(self, tree, record, state):
        """拿一筆記錄試算所有藥丸的表達式。回傳 {'ok', 'failed'}。

        只有「求值丟例外」才算失敗。求出空值不算——那一筆記錄那個欄位本來
        就可能是空的，把它當失敗會製造一堆假待辦。
        """
        Mixin = self.env['doc.render.mixin']
        ok = failed = skipped = 0
        for element, line, loop in self._iter_validation_targets(tree, record):
            meta = Mixin._element_field_meta(element)
            if not meta:
                continue
            source = (meta.get('source') or 'record').strip()
            if source in ('page', 'taxTotals', 'groupHeader',
                          'groupFooter', 'group', 'running', 'html'):
                continue
            if source == 'image' and not (meta.get('expression') or '').strip():
                # 路徑型圖片不必試算（取值走 _traverse_path，不經沙箱）；
                # 算出來的圖片來源會，而那正是最需要試算的一種。
                continue
            target = line if source == 'line' else record
            if target is None:
                # 取不到樣本明細（這筆記錄還沒有付款紀錄之類）→ 沒試算。
                # 不可當失敗：那會把正常的藥丸標成待確認。
                skipped += 1
                continue
            expression = (meta.get('expression') or '').strip()
            if not expression:
                path = (meta.get('path') or '').strip()
                if not path:
                    continue
                expression = ('line.%s' % path) if source == 'line' \
                    else ('object.%s' % path)
            # 條件藥丸的 source 是 'condition'，但它的表達式可能引用 line
            # （<tr t-if="line.xxx"> 轉過來的列條件就是）。只看 source 的話
            # 會拿「只有 object」的環境去試算，結果是一批假失敗。
            extra = {}
            if _LINE_TOKEN_RE.search(expression):
                if line is None:
                    skipped += 1
                    continue
                extra['line'] = line
            if 'loop_' in expression:
                if loop is None:
                    skipped += 1
                    continue
                extra.update(loop)
            error = self._try_expression(expression, target, extra)
            if error:
                failed += 1
                meta['unbound'] = True
                element['label'] = {'backgroundColor': '#ffe0b2',
                                    'color': '#bf360c'}
                self._note(
                    state, '試算失敗（%s）：%s'
                    % (error[:60], expression[:80]),
                )
            else:
                ok += 1
                # 試算過了就不是「待確認」——規則表猜對了
                if meta.pop('unbound', None):
                    element['label'] = {'backgroundColor': '#e3f2fd',
                                        'color': '#1976d2'}
        state['stats']['validated'] = ok
        state['stats']['validate_failed'] = failed
        state['stats']['validate_skipped'] = skipped
        if skipped:
            self._note(
                state,
                '有 %d 顆藥丸沒試算：它們所在的重複列在這筆樣本上取不到明細'
                '（例如這張單還沒有付款紀錄）。換一筆有資料的樣本再轉一次'
                '才驗得到。' % skipped,
            )
        # unbound 重算：上面可能清掉了一些
        state['stats']['unbound'] = sum(
            1 for el in Mixin._iter_elements(tree)
            if (Mixin._element_field_meta(el) or {}).get('unbound')
        )
        return {'ok': ok, 'failed': failed, 'skipped': skipped}

    def _try_expression(self, expression, record, extra=None):
        """試算一段表達式；成功回 None，失敗回錯誤字串。"""
        Mixin = self.env['doc.render.mixin']
        try:
            env_j = Mixin._get_sandbox_env(record)
            env_j.from_string('{{ %s }}' % expression).render(
                object=record, user=self.env.user, **(extra or {}),
            )
        except Exception as e:
            return '%s: %s' % (type(e).__name__, e)
        return None

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

    def _inline_calls(self, root, state, seen=(), depth=0):
        """把 t-call 的子範本內容就地併入樹裡。回傳併入的次數。

        QWeb 的語意就是「把子範本在這裡渲染」，所以改樹最貼近原意。
        不在呼叫點另外輸出的理由：子範本的內容常常是 <tr> 或 <td>
        （出貨單的序號明細列是 <td>、彙總明細列是 <tr>），那些格子屬於
        呼叫端那張表格。另外輸出的話 _emit_table 找不到它們——它找列用的是
        「同一棵樹裡最近的 table 祖先」——明細整批消失。

        呼叫節點原有的屬性（t-if / t-foreach）一定要留著：所以直接拿呼叫
        節點當容器，只拿掉 t-call，子範本內容接在它原有的 t-set 參數後面
        （參數要在前面，子範本才看得到）。
        """
        if depth > 3:
            self._note(state, '子範本嵌太深（超過 4 層），最內層沒有展開。')
            return 0
        count = 0
        for node in list(root.xpath('//*[@t-call]')):
            key = (node.get('t-call') or '').strip()
            if (not key or key in _WRAPPER_TEMPLATES
                    or key in _LAYOUT_TEMPLATES
                    or key in _TAX_TOTALS_TEMPLATES
                    or key in _TAX_TOTALS_COMPANY_TEMPLATES):
                continue
            if key in seen:
                self._note(
                    state,
                    '子範本 t-call="%s" 形成循環呼叫，已停止展開。' % key,
                )
                continue
            view = self._view_by_key(key)
            sub = self._parse_arch(view) if view is not None else None
            if sub is None:
                self._note(
                    state,
                    '找不到子範本 t-call="%s"，那一段沒有轉換。' % key,
                )
                continue
            self._inline_calls(sub, state, seen=tuple(seen) + (key,),
                               depth=depth + 1)
            # 同一個子範本常在好幾處被呼叫，各處的參數值不同（出貨單的
            # aggregated_lines 就有三處）。不改名的話同一個名字被賦值多次，
            # 會被當成 QWeb 累加器而不內聯——那一整段的取值全部變成待確認。
            # 所以每個呼叫點給自己的變數加一個序號後綴。
            self._scope_call_vars(node, sub, state)
            del node.attrib['t-call']
            if sub.text and sub.text.strip():
                children = list(node)
                if children:
                    children[-1].tail = (children[-1].tail or '') + sub.text
                else:
                    node.text = (node.text or '') + sub.text
            for child in list(sub):
                node.append(child)
            count += 1
            self._note(state, '子範本 t-call="%s" 已展開併入。' % key)
        return count

    def _tset_names(self, root):
        return {(el.get('t-set') or '').strip()
                for el in root.xpath('.//t[@t-set]')
                if (el.get('t-set') or '').strip()}

    def _tree_references(self, root, name):
        """子樹的屬性值裡有沒有引用這個變數名。"""
        pattern = re.compile(r'(?<![\w.])%s\b' % re.escape(name))
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            for attr, value in el.attrib.items():
                if attr in ('t-set', 't-call', 't-as'):
                    continue
                if pattern.search(value or ''):
                    return True
        return False

    def _call_param_scopes(self, node, sub, limit=3):
        """[(變數名, t-set 節點, 它所在層的「到呼叫點為止」的節點清單)]。

        原生範本很常把參數寫成 t-call 的「前一個兄弟」而不是子節點：
            <t t-set="aggregated_lines" t-value="…"/>
            <t t-call="stock.stock_report_delivery_aggregated_move_lines"/>

        只改「最靠近的那一個 t-set」與「它到呼叫點之間」的引用，不要整層一起
        改：同一層可能有好幾組（set + call）成對出現，整層一起改會把後面那組
        的 t-set 也改掉，於是後面那組反而找不到自己的參數——兩組都壞掉。
        """
        found = []
        taken = set()
        current = node
        for _level in range(limit):
            parent = current.getparent()
            if parent is None:
                break
            siblings = []
            for sib in parent:
                if sib is current:
                    break
                siblings.append(sib)
            # 由近而遠找，最靠近的那一個才是這次呼叫的參數
            for idx in range(len(siblings) - 1, -1, -1):
                sib = siblings[idx]
                tag = sib.tag if isinstance(sib.tag, str) else ''
                if not (tag == 't' and sib.get('t-set')
                        and sib.get('t-value') is not None):
                    continue
                name = (sib.get('t-set') or '').strip()
                if (not name or name in taken
                        or not self._tree_references(sub, name)):
                    continue
                taken.add(name)
                found.append((name, sib, siblings[idx + 1:] + [current]))
            current = parent
        return found

    def _scope_call_vars(self, node, sub, state):
        """把這個呼叫點用到的變數改成獨一無二的名字。"""
        state['call_seq'] = state.get('call_seq', 0) + 1
        suffix = '__c%d' % state['call_seq']

        # ① 子範本自己的 t-set、以及寫成 t-call 子節點的參數
        local = self._tset_names(node) | self._tset_names(sub)
        if local:
            mapping = {n: n + suffix for n in local}
            self._rename_vars(node, mapping)
            self._rename_vars(sub, mapping)

        # ② 寫在 t-call 前面的參數
        for name, tset, between in self._call_param_scopes(node, sub):
            if name in local:
                continue
            mapping = {name: name + suffix}
            tset.set('t-set', name + suffix)
            self._rename_vars(tset, mapping)
            for sib in between:
                self._rename_vars(sib, mapping)
            self._rename_vars(sub, mapping)

    def _rename_vars(self, root, mapping):
        """在整棵子樹的屬性值（與 t-set 名稱）裡改名。

        t-as 與 t-call 不動：前者是迴圈變數（另一個命名空間，改了會讓
        「來源[迴圈變數]」的配對失效），後者是範本 key。
        """
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            for attr, value in list(el.attrib.items()):
                if attr in ('t-as', 't-call'):
                    continue
                if attr == 't-set':
                    if value.strip() in mapping:
                        el.set(attr, mapping[value.strip()])
                    continue
                new = value
                for old, repl in mapping.items():
                    new = re.sub(r'(?<![\w.])%s\b' % re.escape(old),
                                 repl, new)
                if new != value:
                    el.set(attr, new)

    def _split_layout(self, root, state):
        """拆出 (本文節點, {區塊名: 節點})。

        <t t-call="web.external_layout"> 裡的 t-set 區塊**不是頁首頁尾**——
        看 external_layout_standard 的結構就知道：
          div.header  公司 logo／公司資訊／統編（所有報表都一樣）
          div.article t-call address_layout（address 與 information_block）
                      → h2 layout_document_title → t-out="0"（本文）
          div.footer  公司頁尾文字／頁碼（所有報表都一樣）

        所以 address / information_block / 標題屬於**本文頂端**。
        放進頁首會變成每頁重複——而那在單頁的單據上看不出來。
        真正的頁首頁尾由外框範本提供（文件管理 ▸ 外框範本）。
        """
        layout_calls = root.xpath(
            '//t[@t-call="web.external_layout" or @t-call="web.internal_layout"]'
        )
        if not layout_calls:
            return root, {}
        call = layout_calls[0]
        blocks = {}
        # 往下找、不只看直接子節點：information_block 在銷售訂單裡是包在
        # <t t-if="partner_shipping == partner_invoice"> 裡面的，只看直接
        # 子節點會抓不到，那一格就是空的——而空白格在版面上看不出少了什麼。
        for node in call.xpath('.//t[@t-set][not(@t-value)]'):
            name = node.get('t-set')
            if not name or name in blocks:
                continue
            blocks[name] = node
            # 包在條件裡的區塊：內容取進來，但條件取不進來（它決定的是
            # 「要放哪一份內容」，而我們只能取第一份）
            cond = self._enclosing_condition(node, call)
            if cond:
                self._note(
                    state,
                    '「%s」區塊原本依條件而有不同內容（%s），已取第一份。'
                    '需要兩種版本請用「若／否則區塊」。' % (name, cond[:60]),
                )
        body_holder = self._new_element('t')
        for child in list(call):
            if child.tag == 't' and child.get('t-set') is not None \
                    and child.get('t-value') is None:
                continue
            body_holder.append(child)
        # 被條件包住的區塊仍留在 body_holder 裡（它們的祖先被搬進去了），
        # 必須拆掉，否則同一段內容會在本文中出現兩次
        for name, node in blocks.items():
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
        return body_holder, blocks

    def _enclosing_condition(self, node, stop_at):
        """node 到 stop_at 之間最近的 t-if／t-elif 條件；沒有回 ''。"""
        parent = node.getparent()
        while parent is not None and parent is not stop_at:
            cond = parent.get('t-if') or parent.get('t-elif')
            if cond:
                return cond
            if parent.get('t-else') is not None:
                return '（否則分支）'
            parent = parent.getparent()
        return ''

    def _emit_layout_blocks(self, blocks, out, state):
        """把 address / information_block / 標題放到本文頂端。

        address_layout 的排法是 information_block 左（col-6）、address 右
        （col-5 ms-auto）。canvas-editor 沒有 CSS 格線概念，用無框線表格
        做兩欄——就是條件區塊那個容器機制，零新增。
        """
        info = blocks.get('information_block')
        addr = blocks.get('address')
        if info is not None or addr is not None:
            inner = self._inner_width(state)
            left_w = int(inner * 0.5)
            left, right = [], []
            if info is not None:
                self._emit_children(info, left, state)
            if addr is not None:
                self._emit_children(addr, right, state)
            for cell in (left, right):
                if not cell or (cell[-1].get('value') or '') != '\n':
                    cell.append(self._newline())
            # address 靠右，與原生的 ms-auto 一致
            right[-1]['rowFlex'] = 'right'
            out.append({
                'type': 'table', 'value': '',
                'extension': {'dobtorBlock': 'layout'},
                'borderType': 'empty',
                'colgroup': [{'width': left_w}, {'width': inner - left_w}],
                'trList': [{'tdList': [
                    {'colspan': 1, 'rowspan': 1, 'value': left},
                    {'colspan': 1, 'rowspan': 1, 'value': right},
                ]}],
            })
            out.append(self._newline())
            state['stats']['table'] += 1

        title = blocks.get('layout_document_title')
        if title is not None:
            piece = []
            self._emit_children(title, piece, state)
            for el in piece:
                # 單據標題：原生是 <h2>，這裡用字級與粗體表達
                if el.get('value') != '\n':
                    el.setdefault('size', 24)
                    el.setdefault('bold', True)
            out.extend(piece)
            if not out or (out[-1].get('value') or '') != '\n':
                out.append(self._newline())

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

    # ─── t-set 符號表 ───────────────────────────────────────────────
    #
    # QWeb 報表大量使用中間變數（lines_to_report、display_discount、taxes…）。
    # 不解析的話，每一個引用都只能標成待辦——實測佔了待辦清單的大半，
    # 而且使用者還得自己回去讀原生範本才知道那個變數是什麼。
    #
    # 兩段處理：
    #   1. 單次賦值的變數 → 直接內聯它的值（遞迴一層）
    #   2. Odoo 的慣用寫法 → 改寫成模組的等價寫法（下方的規則表）
    #
    # 規則表是**啟發式**的：對的時候省掉一條待辦，錯的時候會產生錯誤的取值。
    # 所以凡是走了規則表的藥丸一律標成「待確認」——表達式幫使用者填好，
    # 但要他看過。這是這支轉換器唯一一處「猜」，所以猜完必須說。

    # 多次賦值的變數是累加器（current_subtotal 那類），由分組機制取代，
    # 不能內聯——內聯只會拿到其中一次賦值。
    _ACCUMULATOR_HINT = (
        '「%s」是 QWeb 的累加器，本模組改用「分組重複」：在重複列設定分組，'
        '再放一列分組小計（表達式用 group.lines|sum(attribute=...)）。'
    )

    # (正則, 取代, 說明)。每一條都會試，不是第一個命中就停。
    _REWRITE_RULES = (
        # _generate_qr_code 不能走白名單：它在回傳前 self.qr_code_method = …
        # （account_move.py:6032），渲染一張 PDF 會改資料。
        # build_qr_code_base64 是公開方法、只讀，參數與原生相同；
        # qr_method 留空時它自己挑第一個可用的（_build_qr_code_vals 的文件
        # 就是這樣寫的），差別只在不回寫。
        (r'\b([\w\.]+)\._generate_qr_code\([^()]*\)',
         lambda m: (
             '%(o)s.partner_bank_id.build_qr_code_base64('
             '%(o)s.amount_residual, '
             '%(o)s.payment_reference or %(o)s.name, '
             '%(o)s.payment_reference, %(o)s.currency_id, %(o)s.partner_id)'
             % {'o': m.group(1)}),
         '_generate_qr_code() 會在回傳前回寫 qr_code_method（印一張 PDF 就'
         '改資料），所以不呼叫它，改用公開的 build_qr_code_base64()：'
         '參數與原生相同，只是不回寫 qr_method'),
        (r'([\w\.]+)\.sudo\(\s*\)',
         r'\1',
         'sudo() 已移除（沙箱不開放提權）。若該欄位受 ACL 限制可能讀不到，'
         '需要的話請在 doc.report 層先算好'),
        # filtered(lambda …) 是 Odoo 最常見的慣用寫法，而 Jinja 沒有 lambda
        # ——留著就是 TemplateSyntaxError，而條件求值失敗是「當真」，
        # 結果是該濾掉的列全部印出來。只改寫看得懂的三種形狀，其餘留原樣。
        (r"([\w\.]+)\.filtered\(\s*lambda\s+(\w+)\s*:\s*\2\.(\w+)\s+not\s+in\s+"
         r"(\([^()]*\)|\[[^\[\]]*\])\s*\)",
         r"\1|rejectattr('\3', 'in', \4)|list",
         'filtered(lambda … : … not in (…)) 已改寫成 rejectattr'),
        (r"([\w\.]+)\.filtered\(\s*lambda\s+(\w+)\s*:\s*\2\.(\w+)\s+in\s+"
         r"(\([^()]*\)|\[[^\[\]]*\])\s*\)",
         r"\1|selectattr('\3', 'in', \4)|list",
         'filtered(lambda … : … in (…)) 已改寫成 selectattr'),
        (r"([\w\.]+)\.filtered\(\s*lambda\s+(\w+)\s*:\s*not\s+\2\.(\w+)\s*\)",
         r"\1|rejectattr('\3')|list",
         'filtered(lambda … : not …) 已改寫成 rejectattr'),
        (r"([\w\.]+)\.filtered\(\s*lambda\s+(\w+)\s*:\s*\2\.(\w+)\s*"
         r"(==|!=)\s*('[^']*'|\"[^\"]*\"|\d+(?:\.\d+)?|True|False)\s*\)",
         r"\1|selectattr('\3', '\4', \5)|list",
         'filtered(lambda … : … == …) 已改寫成 selectattr'),
        (r"([\w\.]+)\.filtered\(\s*lambda\s+(\w+)\s*:\s*\2\.(\w+)\s*\)",
         r"\1|selectattr('\3')|list",
         'filtered(lambda … : …) 已改寫成 selectattr'),
        (r'([\w\.]+)\.sorted\(\s*key\s*=\s*lambda.*?\)\s*(?:,\s*reverse\s*=\s*\w+\s*)?\)',
         r'\1',
         'sorted(key=lambda …) 在 Jinja 不存在，排序已移除。'
         '請在重複列的「排序欄位」設定，或用 |sort 鏈接多鍵'),
        (r"any\(\s*(\w+)\.(\w+)[^)]*?\s+for\s+\1\s+in\s+([\w\.\|\'\(\)]+)\s*\)",
         r"\3|selectattr('\2')|list|length > 0",
         'any(… for … in …) 已改寫成 selectattr'),
        # 取 or 鏈的**最後**一個屬性當欄位：原生寫法是
        # (tax.invoice_label or tax.name)，最後那個才是一定有值的備援。
        # 取第一個會在備援生效的資料上印出空白——實測 invoice_label 多半是空的。
        # 用函式替換而不是字串：沒有 or 鏈時第三組會是 None，
        # re.sub 會把它當空字串塞進去，變成 map(attribute='')。
        (r"['\"](.*?)['\"]\.join\(\s*\[\(?\s*(\w+)\.(\w+)"
         r"(?:[^\]]*?\bor\s+\2\.(\w+))?[^\]]*?for\s+\2\s+in\s+"
         r"([\w\.]+)\s*\]\s*\)",
         lambda m: "%s|map(attribute='%s')|join('%s')" % (
             m.group(5), m.group(4) or m.group(3), m.group(1)),
         "', '.join([…]) 已改寫成 map|join，取 or 鏈最後一個欄位當值。"
         '若原式還有其他邏輯請自行確認'),
        # 擺在最後：走到這裡還留著生成式，表示上面的規則都沒認出來
        #（例如 any(u._is_portal() for u in …) 裡面是方法呼叫）。
        # 取代成自己＝不改內容，只為了留下一條說得清楚的待辦。
        (r'\bfor\s+\w+\s+in\b',
         lambda m: m.group(0),
         'Jinja 沒有 Python 的生成式（any(… for … in …) 這種），而這一段'
         '無法自動改寫（裡面可能是方法呼叫）。已原樣保留：條件求值會失敗，'
         '而失敗時的策略是「當真」，所以那一段會照印。'
         '請改寫成 selectattr，或在模型上加一個 compute 欄位。'),
    )

    def _collect_symbols(self, root, state):
        """掃出所有 t-set 的值；多次賦值的記成累加器。"""
        symbols = {}
        counts = {}
        for node in root.xpath('//t[@t-set]'):
            name = (node.get('t-set') or '').strip()
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
            value = node.get('t-value')
            if value is None:
                # 區塊型 t-set（address / information_block / 標題）——
                # 它們是外框的內容，由 _split_layout 處理
                symbols.setdefault(name, None)
                continue
            symbols[name] = value.strip()
        state['accumulators'] = {n for n, c in counts.items() if c > 1}
        # 根變數的 with_context 重新賦值不算累加器，也不必內聯
        state['accumulators'] -= set(_ROOT_VARS)
        state['symbols'] = symbols
        return symbols

    def _apply_rules(self, expr, state):
        """套用慣用寫法改寫表。回 (改寫後, 是否命中)。"""
        used = False
        for pattern, replace, hint in self._REWRITE_RULES:
            if re.search(pattern, expr, re.S):
                expr = re.sub(pattern, replace, expr, flags=re.S)
                self._note(state, hint)
                used = True
        expr, used_safe = self._apply_safe_methods(expr, state)
        return expr, used or used_safe

    def _apply_safe_methods(self, expr, state):
        """白名單內的底線方法 → report_helper(...)。回 (改寫後, 是否命中)。

        沙箱擋掉所有底線開頭的方法（提權的主要入口），但原生報表會呼叫幾個
        純計算的輔助方法，擋掉的後果是單據上那一段印成空白。白名單在
        doc.render.mixin._SAFE_REPORT_METHODS（逐一讀過實作確認不寫資料），
        這裡只改寫語法——模型對不對由 report_helper 在渲染時再查一次，
        所以就算這裡的正則認錯對象，也不會真的呼叫到不該呼叫的東西。
        """
        names = {name for _model, name
                 in self.env['doc.render.mixin']._SAFE_REPORT_METHODS}
        if not names:
            return expr, False
        pattern = r'([\w\.]+)\.(%s)\(([^()]*)\)' % '|'.join(
            re.escape(n) for n in sorted(names)
        )
        hits = []

        def _sub(m):
            hits.append(m.group(2))
            args = (m.group(3) or '').strip()
            return "report_helper(%s, '%s'%s)" % (
                m.group(1), m.group(2), (', %s' % args) if args else '',
            )

        out = re.sub(pattern, _sub, expr)
        for name in dict.fromkeys(hits):
            self._note(
                state,
                '%s() 是底線方法（沙箱擋），已改成經白名單呼叫 '
                'report_helper()。白名單只收讀過實作、確認不寫資料的方法。'
                % name,
            )
        return out, bool(hits)

    def _inline_symbols(self, expr, state, depth, seen=()):
        """把 t-set 變數替換成它們的值（遞迴）。回 (展開後, 是否命中規則表)。

        seen 擋的是「自我指涉的 t-set」——QWeb 很常寫
            <t t-set="payment_term_details" t-value="o.payment_term_details"/>
        名稱出現在自己的值裡面。不擋的話展開會一路套到 depth 上限，
        轉出來的是 object.(object.(object.(...)))（實測過）。
        """
        symbols = state.get('symbols') or {}
        used = False
        for name in sorted(symbols, key=len, reverse=True):
            if name in _ROOT_VARS or name in (state.get('accumulators') or ()):
                continue
            if name in seen:
                continue
            value = symbols.get(name)
            if not value:
                continue
            pattern = r'\b%s\b' % re.escape(name)
            if re.search(pattern, expr):
                inner, inner_rule = self._expand_symbols(
                    value, state, depth + 1, seen=tuple(seen) + (name,),
                )
                expr = re.sub(pattern, '(%s)' % inner, expr)
                used = used or inner_rule
        return expr, used

    def _expand_symbols(self, expr, state, depth=0, seen=()):
        """把表達式裡的 t-set 變數替換成它們的值。回 (展開後, 是否用了規則表)。

        順序是「改寫 → 內聯 → 再改寫」，不是「內聯 → 改寫」：
        any(l.discount for l in lines_to_report) 這類寫法，等 lines_to_report
        被展開成帶逗號的 rejectattr(...) 之後，any 的正則就匹配不到了
        （實測過的失敗：TemplateSyntaxError expected ',' got 'for'）。
        先改寫時中間變數還只是一個單純識別字，正則才抓得住。
        最後再跑一次是為了處理展開後才出現的慣用寫法（_get_order_lines_to_report）。
        """
        expr = (expr or '').strip()
        if not expr or depth > 3:
            return expr, False

        # 「來源[迴圈變數]」要在展開前收斂（見 _collapse_loop_subscript）
        expr = self._collapse_loop_subscript(expr, state)
        expr, used_a = self._apply_rules(expr, state)
        expr, used_b = self._inline_symbols(expr, state, depth, seen=seen)
        expr, used_c = self._apply_rules(expr, state)
        used_rule = used_a or used_b or used_c

        # 累加器：內聯不了，給明確的替代方案
        for name in (state.get('accumulators') or ()):
            if re.search(r'\b%s\b' % re.escape(name), expr):
                self._note(state, self._ACCUMULATOR_HINT % name)
                used_rule = True

        return expr, used_rule

    def _unwrap_parens(self, expr):
        """剝掉「把整個表達式包起來」的外層括號。

        t-set 內聯一律加括號（(o.payment_term_details)），不剝的話
        _strip_root 認不出它是一條單純路徑，明細來源就變成待設定的待辦。
        只在第一個括號與最後一個括號配對時才剝——(a or b).x 不能剝。
        """
        while expr.startswith('(') and expr.endswith(')'):
            depth = 0
            for idx, ch in enumerate(expr):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        break
            if idx != len(expr) - 1:
                break
            expr = expr[1:-1].strip()
        return expr

    def _strip_root(self, expr, state):
        """把 doc.partner_id → partner_id、line.name → name（迴圈內）。

        回 (path, kind)，kind 為 'record' / 'line' / None（對不上根變數）。
        """
        expr = self._unwrap_parens((expr or '').strip())
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

    def _option_date_only(self, node):
        """t-options 裡的 date_only。

        採購單用 t-options="{'date_only': 'true'}" 把 datetime 印成日期，
        那不是 widget，所以不能只看 widget 名稱——不處理的話我們會印出
        「Oct 8, 2026 3:36:48 AM」而原生印「10/08/2026」。
        """
        raw = node.get('t-options') or ''
        m = re.search(r'["\']date_only["\']\s*:\s*([^,}]+)', raw)
        if not m:
            return False
        return (m.group(1) or '').strip().strip('\'"').lower() in (
            'true', '1', 'yes')

    def _parse_option_fields(self, node):
        """t-options 裡 "fields": [...] 的欄位名清單（沒寫回空清單）。"""
        raw = node.get('t-options') or ''
        m = re.search(r'["\']fields["\']\s*:\s*\[([^\]]*)\]', raw)
        if not m:
            return []
        return re.findall(r'["\'](\w+)["\']', m.group(1))

    def _wrap_widget(self, node, base):
        """把節點上的 t-options widget 套到表達式外面（沒有就原樣回）。"""
        widget = self._parse_options(node)
        wrapped = self._widget_expr(widget, node, base) if widget else None
        return wrapped if wrapped is not None else base

    def _widget_expr(self, widget, node, base):
        """widget → 包裝後的表達式；不認得的 widget 回 None。"""
        if widget == 'contact':
            # 原生 contact widget 的 fields 預設含 "name"，所以沒寫 fields
            # 就是要印名稱。寫了就照它寫的來——這是從 arch 讀出來的事實，
            # 不是猜的。
            opt = self._parse_option_fields(node)
            if ('name' in opt) if opt else True:
                return 'format_address(%s, with_name=True)' % base
            return 'format_address(%s)' % base
        if widget in _WIDGET_WRAPPERS:
            return _WIDGET_WRAPPERS[widget] % base
        return None

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
        wrapped = self._widget_expr(widget, node, base) if widget else None
        if wrapped is None and not widget:
            # 分支（三元式）裡的取值也要補格式：明細的折扣、金額、單價都是
            # 「有條件的取值」，少了這一步那幾欄會印成 10.0 / 180.0。
            wrapped = self._auto_format(node, state, path, kind, base)
        return wrapped if wrapped is not None else base

    def _resolve_field(self, model, path):
        """沿著 a.b.c 查最後一個欄位。查不到回 None。"""
        if not model or not path:
            return None
        Model = self.env.get(model)
        field = None
        parts = path.split('.')
        for idx, part in enumerate(parts):
            if Model is None:
                return None
            field = Model._fields.get(part)
            if field is None:
                return None
            if idx < len(parts) - 1:
                if not getattr(field, 'comodel_name', None):
                    return None
                Model = self.env.get(field.comodel_name)
        return field

    def _path_model(self, state, kind):
        """路徑是相對於哪個模型。"""
        if kind == 'line':
            models = state.get('loop_models') or []
            return models[-1] if models else None
        return state.get('model')

    def _auto_format(self, node, state, path, kind, base):
        """沒有 t-options 時，依欄位型別補上格式。回 None 表示不用補。

        原生報表大量依賴 widget 來格式化，但也有一堆欄位**沒有**帶 widget
        ——那時 QWeb 仍然會依欄位型別印（float 看 digits、date 看語言格式），
        而我們是直接 str()。實測差異：`100.0` vs `100.00`、
        `1000.0` vs `1,000.00`、`2026-10-08` vs `10/08/2026`。
        每一行數字都不一樣，單據直接不能用。
        """
        field = self._resolve_field(self._path_model(state, kind), path)
        ttype = getattr(field, 'type', None)
        if ttype == 'monetary':
            return 'format_money(%s)' % base
        if ttype == 'float':
            digits = getattr(field, 'digits', None)
            spec = ',.%df' % (digits[1] if isinstance(digits, tuple) else 2)
            return "format_number(%s, '%s')" % (base, spec)
        if ttype == 'integer':
            return "format_number(%s, ',.0f')" % base
        if ttype == 'date':
            return "format_date(%s, 'lang')" % base
        if ttype == 'datetime':
            fmt = 'lang' if self._option_date_only(node) else 'lang_datetime'
            return "format_date(%s, '%s')" % (base, fmt)
        return None

    def _value_pill(self, node, expr, state):
        """t-field / t-out / t-esc → 藥丸。"""
        index_pill = self._loop_index_pill(expr, state)
        if index_pill is not None:
            return index_pill
        path, kind = self._strip_root(expr, state)
        widget = self._parse_options(node)
        label = (path or expr).split('.')[-1] or expr

        if path is None or not _SIMPLE_PATH_RE.match(path or 'x'):
            # 先試著把 t-set 中間變數展開（lines_to_report / taxes / …）。
            # 展開後常常就變成可用的表達式，不必丟給使用者自己讀原生範本。
            expanded, used_rule = self._expand_symbols(expr, state)
            path2, kind2 = self._strip_root(expanded, state)
            if path2 is not None and _SIMPLE_PATH_RE.match(path2 or 'x'):
                source = 'line' if kind2 == 'line' else 'record'
                base = ('line.%s' % path2) if kind2 == 'line' \
                    else ('object.%s' % path2)
                wrapped = self._widget_expr(widget, node, base) if widget \
                    else None
                if wrapped is not None:
                    base = wrapped
                # 走過規則表的要人工確認——那是這支轉換器唯一一處「猜」
                return self._pill(label[:20], state, source=source,
                                  expression=base, unbound=used_rule)
            mapped = self._wrap_widget(node, self._map_condition(expanded, state))
            # 用 token 比對而不是 'object.' / 'line.'：迴圈變數是 dict 時
            # QWeb 寫下標（payment_vals['date'] → line['date']），
            # 比對帶點的字串會漏掉它，整條表達式原樣留著變成待確認藥丸。
            if mapped and mapped != expr and _ROOT_TOKEN_RE.search(mapped):
                self._note(
                    state, '已自動改寫，請確認取值：%s → %s'
                    % (expr[:60], mapped[:80]),
                )
                return self._pill(
                    label[:20], state,
                    source='line' if _LINE_TOKEN_RE.search(mapped)
                    else 'record',
                    expression=mapped, unbound=True,
                )
            # 真的對不上：原樣保留並標成待辦。使用者看得到原始 QWeb 寫法，
            # 比我猜一個錯的路徑好得多。
            self._note(
                state,
                '表達式需要人工確認：%s' % (expr[:120]),
            )
            return self._pill('待確認：%s' % label[:20], state,
                              source='record', expression=expr, unbound=True)

        source = 'line' if kind == 'line' else 'record'
        base = ('line.%s' % path) if kind == 'line' else ('object.%s' % path)

        wrapped = self._widget_expr(widget, node, base) if widget else None
        if wrapped is None and not widget:
            wrapped = self._auto_format(node, state, path, kind, base)
        if wrapped is not None:
            return self._pill(label, state, source=source,
                              path=path, expression=wrapped)
        if widget:
            self._note(state, '未支援的 widget「%s」，已改為直接輸出欄位值。'
                              % widget)
        return self._pill(label, state, source=source, path=path)

    def _loop_index_pill(self, expr, state):
        """QWeb 的 <迴圈變數>_index → 流水序號藥丸（op='index'）。

        t-foreach 會順便給 <t-as>_index（0 起算），範本裡幾乎都寫
        「term_index + 1」當項次。原本這整串對不上任何路徑，轉出來是一顆
        待確認藥丸——而項次是明細表最顯眼的一欄。
        流水藥丸的 index 是 1 起算，所以「_index + 1」完全等價。
        """
        text = (expr or '').strip()
        for var in reversed(state.get('loop_vars') or []):
            name = '%s_index' % var
            if text in ('%s + 1' % name, '%s+1' % name, '1 + %s' % name):
                return self._pill('項次', state, source='running', op='index')
            if text == name:
                # 0 起算：原生印的是 0,1,2…，這裡的流水是 1,2,3…
                self._note(
                    state,
                    '「%s」是 0 起算的迴圈索引，已轉成流水序號（1 起算）。'
                    '要保持 0 起算請改用表達式。' % name,
                )
                return self._pill('項次', state, source='running', op='index')
        return None

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
        return self._wrap_widget(node, self._map_condition(expr, state))

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
        label = ' '.join((''.join(node.itertext()) or '').split())[:20]
        if not label:
            label = (value_expr or '').split('.')[-1].strip('()\'"')[:20]
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
        state['loop_vars'].append(as_var)
        state.setdefault('loop_sources', []).append((expr or '').strip())
        state.setdefault('loop_models', []).append(self._loop_model(state, expr))
        try:
            inner = []
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
            'colgroup': [{'width': self._inner_width(state)}],
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

    def _inner_width(self, state):
        page_w = 1123 if state.get('page_format') == 'A4_landscape' else 794
        return max(200, page_w - 192)

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
            wrapper_conds = self._row_wrapper_conditions(tr, node)
            repeat = foreach_rows.get(tr)
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
                    )
                    if row is not None:
                        tr_list.append(row)
                state['notes'].append(
                    '明細有 %d 種列型（商品／章節／備註…），已各自建一列。'
                    '有條件的列型優先，條件留空的那一列接住其餘。' % len(branches)
                )
                continue
            row = self._table_row(tr, state, repeat, th_conds, max_cols,
                                  wrapper_conds=wrapper_conds)
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
                   row_filter='', with_marker=None, wrapper_conds=()):
        pushed = False
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
                            expression=self._map_condition(
                                cond, state, expand=True),
                        ))
                        state['stats']['condition'] += 1
                    else:
                        self._note(
                            state,
                            '儲存格條件「%s」已轉成列型條件的候選，'
                            '請在右欄確認（或改用欄條件）。' % cond[:70],
                        )
                if first:
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
        if path and _SIMPLE_PATH_RE.match(path):
            return self._pill(label, state, source='repeat',
                              path=path, repeatId=repeat_id,
                              rowFilter=row_filter)

        # lines_to_report / lines 這類中間變數：展開後多半就是真正的
        # 一對多欄位（或帶篩選／排序的表達式）
        expanded, used_rule = self._expand_symbols(expr, bare)
        path2, _k2 = self._strip_root(expanded, bare)
        if path2 and _SIMPLE_PATH_RE.match(path2):
            return self._pill(
                ('列型 × %s' if row_filter else '明細 × %s') % path2,
                state, source='repeat', path=path2,
                repeatId=repeat_id, rowFilter=row_filter,
                unbound=used_rule,
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
                unbound=True,
            )
        self._note(
            state,
            '重複來源「%s」是範本內的中間變數，請在右欄改成實際的一對多欄位'
            '（或填「來源表達式」）。' % expr[:70],
        )
        return self._pill(
            '列型（待設定）' if row_filter else '明細（待設定）',
            state, source='repeat', path='', repeatId=repeat_id,
            rowFilter=row_filter, unbound=True,
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
