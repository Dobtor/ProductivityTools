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

    def _report_lang_source(self, report):
        """原生報表用誰的語言印：'customer'（範本指定 t-lang）或 'user'（沒指定）。

        語言寫在報表入口到內容範本之間某一層的 t-call 上
        （sale：t-lang="doc.partner_id.lang"；出貨單：o._get_report_lang()；
        發票寫在入口呼叫內容範本那一層）。一路都沒有＝照列印的人的語言
        （揀貨作業）。路線跟 _resolve_document_view 一樣。
        """
        view = self._view_by_key(report.report_name)
        seen = set()
        for _depth in range(5):
            if view is None or view.id in seen:
                break
            seen.add(view.id)
            root = self._parse_arch(view)
            if root is None:
                break
            if root.xpath('//*[@t-lang]'):
                return 'customer'
            targets = [
                t for t in root.xpath('//t[@t-call]/@t-call')
                if t and t not in _WRAPPER_TEMPLATES
                and t not in _LAYOUT_TEMPLATES
                and t not in _TAX_TOTALS_TEMPLATES
            ]
            if not targets:
                break
            view = self._view_by_key(targets[0])
        return 'user'

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

    _CELL_TAGS = ('td', 'th')

    def _merge_cell_chains(self, root, state):
        """同一個位置二選一的格子 → 一格，內容放分支。回傳合併的處數。

        出貨單的表頭：
            <th t-if="not has_serial_number">Ordered</th>
            <th t-else="">Lot/Serial Number</th>
        印出來永遠只有其中一格。不合併的話兩格都被當成欄，表頭比明細多一欄
        （多印「Lot/Serial Number」、數量對到錯的欄）。
        只合併以 t-else 收尾的鏈：沒有 t-else 時那一格可能整個不見，那是
        欄條件，不是二選一。
        """
        count = 0
        for first in root.xpath('//th[@t-if] | //td[@t-if]'):
            if first.getparent() is None:
                continue
            chain = [first]
            nxt = first.getnext()
            closed = False
            while nxt is not None:
                if not isinstance(nxt.tag, str):
                    nxt = nxt.getnext()
                    continue
                if nxt.tag.lower() not in self._CELL_TAGS:
                    break
                if nxt.get('t-elif') is not None:
                    chain.append(nxt)
                    nxt = nxt.getnext()
                    continue
                if nxt.get('t-else') is not None:
                    chain.append(nxt)
                    closed = True
                break
            if not closed or len({c.get('colspan') or '1' for c in chain}) > 1:
                continue
            merged = self._new_element(first.tag)
            for key, value in first.attrib.items():
                if key != 't-if':
                    merged.set(key, value)
            for branch in chain:
                holder = self._new_element('t')
                for attr in ('t-if', 't-elif', 't-else'):
                    if branch.get(attr) is not None:
                        holder.set(attr, branch.get(attr))
                holder.text = branch.text
                for child in list(branch):
                    holder.append(child)
                merged.append(holder)
            merged.tail = chain[-1].tail
            parent = first.getparent()
            parent.replace(first, merged)
            for branch in chain[1:]:
                parent.remove(branch)
            count += 1
        if count:
            self._note(
                state,
                '有 %d 處「同一格二選一」（<th t-if>…<th t-else>）已併成一格、'
                '內容依條件切換；格子的對齊與樣式取第一個分支的。' % count,
            )
        return count
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
                if name == 't-attf-class' and not self._attf_dynamic_matters(
                        el.get(name)):
                    continue  # 寫死的部分照轉，動態的只是排版用的
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
        # 同名的其他份（發票的地址在三個條件分支裡各寫一份）：內容一樣就只用
        # 第一份，其餘也要從本文拆掉——它們只是「記下地址給外框印」，本身不印
        # 東西，留著的話標題下面又印一次客戶地址
        duplicates = []
        conds = state.setdefault('layout_block_conds', {})
        # 往下找、不只看直接子節點：information_block 在銷售訂單裡是包在
        # <t t-if="partner_shipping == partner_invoice"> 裡面的，只看直接
        # 子節點會抓不到，那一格就是空的——而空白格在版面上看不出少了什麼。
        found_nodes = {}
        for node in call.xpath('.//t[@t-set][not(@t-value)]'):
            if node.get('t-set'):
                found_nodes.setdefault(node.get('t-set'), []).append(node)
        # 同名但內容不同的幾份＝依條件印不同內容（採購單：有指定送貨地址印那個，
        # 否則印收貨倉庫的地址）。以前只取第一份，「否則」那份整段不見
        variants = state.setdefault('layout_block_variants', {})
        for name, nodes in found_nodes.items():
            if len(nodes) < 2 or len({self._block_signature(n)
                                      for n in nodes}) < 2:
                continue
            branch = [(n, self._branch_condition(n, call)) for n in nodes]
            if all(cond is not None for _n, cond in branch):
                variants[name] = branch
        for node in call.xpath('.//t[@t-set][not(@t-value)]'):
            name = node.get('t-set')
            if not name:
                continue
            if name in blocks:
                duplicates.append(node)
                continue
            blocks[name] = node
            if name == 'layout_document_title':
                # 採購單把標題包在 <div class="mt-4"> 裡：標題搬走後那個 div 是空的，
                # 但官方照樣佔 1.5rem 的上邊距（跟標題的下邊距併成一段），
                # 標題到資訊欄比只有標題時遠。拆空殼前先記下來
                holder = node.getparent()
                if (holder is not None and holder is not call
                        and [c for c in holder if isinstance(c.tag, str)] == [node]):
                    state['title_gap_px'] = self._spacing_px(holder, 'top')
            if name in variants:
                continue
            # 包在條件裡的區塊＝「條件成立才有這一塊」（銷售訂單的發票／送貨
            # 地址只在跟客戶地址不同時才印）。以前條件丟掉、內容照印，
            # 單據上左右各一份客戶地址。
            found, ok = self._enclosing_conditions(node, call)
            if ok:
                if found:
                    conds[name] = ' and '.join(
                        '(%s)' % ' '.join(c.split()) for c in found)
            else:
                # elif／else 的分支要跟前面的條件互斥，這裡還原不了
                self._note(
                    state,
                    '「%s」區塊原本依條件而有不同內容（%s），已取第一份。'
                    '需要兩種版本請用「若／否則區塊」。'
                    % (name, (found[-1] if found else '')[:60]),
                )
        body_holder = self._new_element('t')
        for child in list(call):
            if child.tag == 't' and child.get('t-set') is not None \
                    and child.get('t-value') is None:
                continue
            body_holder.append(child)
        # 被條件包住的區塊仍留在 body_holder 裡（它們的祖先被搬進去了），
        # 必須拆掉，否則同一段內容會在本文中出現兩次
        for node in list(blocks.values()) + duplicates:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
                # 只清本文裡的空殼：直接掛在外框呼叫底下的區塊（address），
                # 上一層就是外框呼叫本身，拿掉它之後判斷「要不要掛外框」會找不到
                if any(a is body_holder for a in parent.iterancestors()):
                    self._prune_empty_shells(parent, body_holder)
        return body_holder, blocks

    def _block_signature(self, node):
        """區塊內容的比對用字串：id／name 不算（發票三份地址只差在 id）。"""
        from lxml import etree
        raw = etree.tostring(node, encoding='unicode', with_tail=False)
        return re.sub(r'\s(?:id|name)="[^"]*"', '', ' '.join(raw.split()))

    def _branch_condition(self, node, stop_at):
        """node 到 stop_at 之間的條件合成一句（t-elif／t-else 帶上前面分支不成立）。

        沒有條件回空字串；t-else 前面找不到 t-if 時回 None（還原不了）。
        """
        conds = []
        parent = node.getparent()
        while parent is not None and parent is not stop_at:
            if isinstance(parent.tag, str):
                negation = self._chain_negation(parent)
                if parent.get('t-if'):
                    conds.insert(0, parent.get('t-if'))
                elif parent.get('t-elif') is not None:
                    cond = parent.get('t-elif')
                    conds.insert(0, '(%s) and %s' % (cond, negation)
                                 if negation else cond)
                elif parent.get('t-else') is not None:
                    if not negation:
                        return None
                    conds.insert(0, negation)
            parent = parent.getparent()
        return ' and '.join('(%s)' % ' '.join(c.split()) for c in conds)

    def _prune_empty_shells(self, node, stop_at):
        """區塊搬走後只剩空殼的 <t t-if> 一路往上拿掉。

        不拿掉的話空殼會轉成一顆「"" if 條件」的藥丸，在標題下面多一個
        看不懂的空欄位。<div class="col-6"> 這種純排版的空容器也算空殼
        （發票的地址分支），身上有取值或呼叫的不算。
        """
        while (node is not None and node is not stop_at
               and self._is_empty_shell(node)):
            parent = node.getparent()
            if parent is None:
                return
            parent.remove(node)
            node = parent

    _SHELL_ATTRS = frozenset({'t-if', 't-elif', 't-else', 'class', 'name', 'id',
                              'style', 'groups'})

    def _is_empty_shell(self, node):
        tag = node.tag.lower() if isinstance(node.tag, str) else ''
        return (tag in ('t', 'div') and len(node) == 0
                and not (node.text or '').strip()
                and set(node.attrib) <= self._SHELL_ATTRS)

    def _enclosing_conditions(self, node, stop_at):
        """node 到 stop_at 之間所有的 t-if（由外到內）。

        回 (條件串列, 能不能還原)。路上有 t-elif／t-else 時回 False：那種
        分支要跟前面的條件互斥，單看自己的條件會判錯。
        """
        found = []
        parent = node.getparent()
        while parent is not None and parent is not stop_at:
            if parent.get('t-elif') is not None:
                found.insert(0, parent.get('t-elif'))
                return found, False
            if parent.get('t-else') is not None:
                found.insert(0, '（否則分支）')
                return found, False
            if parent.get('t-if'):
                found.insert(0, parent.get('t-if'))
            parent = parent.getparent()
        return found, True

    def _emit_layout_blocks(self, blocks, out, state):
        """把 address / information_block / 標題放到本文頂端。

        address_layout 的排法：有 information_block 時它在左（col-6）、
        address 空一格後在右（col-5 offset-1）；沒有時 address 單獨靠右
        （col-5 ms-auto）。兩種情況 address 都佔右邊 5/12、文字靠左，
        所以固定切成 7/12 與 5/12 兩格，左格放 information_block（照原本的
        條件包起來，不成立時左格空白）——跟原生一樣不論哪種都對得上。
        canvas-editor 沒有 CSS 格線概念，用無框線表格做兩欄。
        """
        info = blocks.get('information_block')
        addr = blocks.get('address')
        if info is not None or addr is not None:
            inner = self._inner_width(state)
            left_w = int(inner * 7 / 12)
            right_w = inner - left_w
            conds = state.get('layout_block_conds') or {}
            variants = state.get('layout_block_variants') or {}
            left, right = [], []
            if info is not None:
                info_cond = conds.get('information_block')
                if variants.get('information_block'):
                    left.extend(self._block_variant_elements(
                        variants['information_block'], left_w, state))
                elif info_cond:
                    with self._in_width(
                            state, left_w - 2 * self._CELL_PADDING):
                        body = []
                        self._emit_children(info, body, state)
                    if not body or (body[-1].get('value') or '') != '\n':
                        body.append(self._newline())
                    with self._in_width(state, left_w - self._CELL_PADDING):
                        left.append(self._condition_wrap(
                            info_cond, body, state))
                else:
                    with self._in_width(state, left_w - self._CELL_PADDING):
                        self._emit_children(info, left, state)
            if addr is not None and variants.get('address'):
                right.extend(self._block_variant_elements(
                    variants['address'], right_w, state))
            elif addr is not None:
                with self._in_width(state, right_w - self._CELL_PADDING):
                    self._emit_children(addr, right, state)
            for cell in (left, right):
                if not cell or (cell[-1].get('value') or '') != '\n':
                    cell.append(self._newline())
            out.append({
                'type': 'table', 'value': '',
                'extension': {'dobtorBlock': 'layout', 'fixedCols': True},
                'borderType': 'empty',
                'colgroup': [{'width': left_w}, {'width': right_w}],
                'trList': [{'tdList': [
                    {'colspan': 1, 'rowspan': 1, 'value': left},
                    {'colspan': 1, 'rowspan': 1, 'value': right},
                ]}],
            })
            out.append(self._newline())
            # web.address_layout 的外層是寫死的「address row mb-4」：地址區下方
            # 留一列空白再接標題
            out.extend(self._spacer_rows(
                self._new_element_with_class('div', 'mb-4'), 'bottom'))
            state['stats']['table'] += 1

        title = blocks.get('layout_document_title')
        if title is not None:
            piece = []
            self._emit_children(title, piece, state)
            for el in piece:
                # 單據標題：原生是 <h2>（內文兩倍、不是粗體），照官方的字級；
                # 顏色是公司主色（印的時候上）
                if el.get('value') != '\n':
                    el.setdefault('size', self._heading_size('h2'))
                    self._mark_company_color(el, 'primary')
            out.extend(piece)
            if not out or (out[-1].get('value') or '') != '\n':
                out.append(self._newline())
            # 原生是 <h2>：行高與下方留白照 Bootstrap 的標題（見 _heading_paragraph）
            self._heading_paragraph(piece + [out[-1]])
            # 標題外面的空 div 有上邊距（mt-4）時，跟標題的下邊距（.5rem）併成
            # 較大的那一個
            extra = max(0.0, (state.get('title_gap_px') or 0)
                        - self._HEADING_MARGIN_PX)
            out.extend(self._spacer_rows_px(self._HEADING_GAP_PX + extra))

    def _block_variant_elements(self, branch, cell_w, state):
        """同名區塊的每一份各包一個條件區塊（條件互斥，印出來只有一份）。"""
        out = []
        for node, cond in branch:
            body = []
            with self._in_width(state, cell_w - 2 * self._CELL_PADDING):
                self._emit_children(node, body, state)
            if not body or (body[-1].get('value') or '') != '\n':
                body.append(self._newline())
            if not cond:
                out.extend(body)
                continue
            with self._in_width(state, cell_w - self._CELL_PADDING):
                out.append(self._condition_wrap(cond, body, state))
        return out

    def _new_element(self, tag):
        from lxml import etree
        return etree.Element(tag)

    def _new_element_with_class(self, tag, cls):
        node = self._new_element(tag)
        node.set('class', cls)
        return node

