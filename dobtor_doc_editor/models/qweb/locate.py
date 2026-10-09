"""ConvLocate — 找出要轉哪一段 arch。

☠️ 一定要用 _get_combined_arch() 而不是 view.arch_db：後者看不到任何
模組的視圖繼承擴充（實測 2796 → 3194 個節點）。
外殼範本（external_layout 那一類）的子節點才是本文——不處理的話
36 張裡有 17 張轉成空白。
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


class ConvLocate:

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
        """範本的 arch（**含所有繼承進來的修改**）。

        一定要用 _get_combined_arch()：view.arch_db 只有這張 view 自己寫的
        那一段，模組對報表做的擴充完全看不到。實測後果——採購單少印
        purchase_stock 加上去的「Shipping address」整塊，而普查時看到樹裡有
        <xpath> 與 <attribute> 標籤（那是繼承指令，不該出現在要轉換的樹裡），
        就是這個原因留下的痕跡。
        """
        from lxml import etree
        try:
            root = view.sudo()._get_combined_arch()
            if root is not None:
                # 註解在 combined arch 裡還留著，清掉以免被當成內容
                for comment in root.xpath('//comment()'):
                    parent = comment.getparent()
                    if parent is not None:
                        parent.remove(comment)
                return root
        except Exception as e:
            _logger.warning('[qweb-import] combined arch 取不到 %s：%s',
                            view.key, e)
        try:
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

    def _groups_condition(self, raw):
        """groups="a,!b" → 沙箱條件式。

        QWeb 的語意：逗號是 OR（在其中一個群組就看得到），前面加 ! 是反向。
        """
        pos, neg = [], []
        for part in (raw or '').split(','):
            part = part.strip()
            if not part:
                continue
            if part.startswith('!'):
                neg.append(part[1:].strip())
            else:
                pos.append(part)
        terms = []
        if pos:
            terms.append('(%s)' % ' or '.join(
                "has_group('%s')" % g for g in pos))
        terms.extend("(not has_group('%s'))" % g for g in neg if g)
        return ' and '.join(terms)

    def _rewrite_groups(self, root, state):
        """把 groups 屬性併進同一個節點的 t-if。回傳改寫的處數。

        原本整個被忽略：36 張報表有 52 處，最多的是 uom.group_uom（計量單位
        欄）——沒有那個群組的使用者，單據上那一欄本來不該出現，而我們照印。
        改寫成條件之後就沿用既有的條件機制（列／欄／段落／三元式），
        不必在每一條分支各做一次。
        """
        count = 0
        skipped = 0
        for el in root.xpath('//*[@groups]'):
            raw = (el.get('groups') or '').strip()
            del el.attrib['groups']
            cond = self._groups_condition(raw)
            if not cond:
                continue
            if el.get('t-else') is not None or el.get('t-elif') is not None:
                # t-else 上沒辦法用 and 併條件——併了語意就不是「否則」了
                skipped += 1
                continue
            existing = (el.get('t-if') or '').strip()
            el.set('t-if', '(%s) and %s' % (existing, cond) if existing
                   else cond)
            count += 1
        if count:
            self._note(
                state,
                'groups 屬性 %d 處已改寫成「依群組顯示」的條件（has_group）。'
                '那是原生的語意：沒有該群組的使用者看不到那一段。' % count,
            )
        if skipped:
            self._note(
                state,
                '有 %d 處 groups 掛在 t-else／t-elif 上，沒有改寫（併進去語意'
                '就不是「否則」了）。那幾段會一直印，請自行加條件。' % skipped,
            )
        return count

    # 會影響輸出、但本模組的文件模型表達不了的屬性——逐類留一條待辦，
    # 不要靜默忽略（完整性普查的結論：靜默忽略的那幾類才是真正的風險）
    _UNCONVERTED_ATTRS = (
        ('t-att-style', '節點上的動態 inline 樣式'),
        ('t-attf-style', '節點上的動態 inline 樣式'),
        ('t-att-class', '動態 class（條件式的粗體／對齊）'),
        ('t-attf-class', '動態 class（條件式的粗體／對齊）'),
        ('t-att-colspan', '動態跨欄數'),
    )

    def _known_class_shape(self, raw):
        """這個 t-att-class 的寫法我們轉得掉嗎。"""
        return bool(self._parse_class_chain(raw))

    def _note_unconverted_attrs(self, root, state):
        """數一數「會影響輸出但轉不過去」的屬性，逐類留一條待辦。"""
        counts = {}
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            for name in el.attrib:
                if name == 't-att-class' and self._known_class_shape(
                        el.get(name)):
                    continue  # 這一種我們轉得掉（條件式格式／固定格式）
                for prefix, desc in self._UNCONVERTED_ATTRS:
                    if name == prefix:
                        counts[desc] = counts.get(desc, 0) + 1
            if el.tag.lower() in ('svg', 'canvas'):
                counts['SVG／canvas 繪圖'] = counts.get('SVG／canvas 繪圖', 0) + 1
        for desc, n in sorted(counts.items()):
            self._note(
                state,
                '%s 共 %d 處沒有轉換（文件模型表達不了）。版面可能與原生不同，'
                '請在編輯器裡自行調整。' % (desc, n),
            )
        return counts

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

