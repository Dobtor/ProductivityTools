"""ConvExpr — 表達式對應與 t-set 符號表。

把 QWeb 的表達式改寫成沙箱吃得下的形式，並把中間變數（t-set）展開。
這一層是「會猜」的那一層——所有改寫都要能被 entry 的試算驗證，
認不出來的寫法原樣保留並標成待確認，**不猜**。
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


class ConvExpr:

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

    # 待辦分級。一張報表最多吐 59 條待辦，而「這一段沒有轉換、版面會不同」
    # 與「我改寫了，你確認一下」的嚴重性差一個級——平鋪 59 條的實務結果是
    # 使用者整段跳過，那等於待辦機制沒有發揮作用。
    #
    # 分級用關鍵詞推斷而不是逐個呼叫點標記：呼叫點有六十幾處，逐個標記的
    # 漏標風險比這張表的誤判風險高。真的推斷錯的那幾處用 level= 明寫覆蓋。
    _NOTE_LEVELS = ('blocker', 'check', 'info')
    _NOTE_BLOCKER_HINTS = (
        '試算失敗', '需要人工確認', '沒有轉換', '未轉換', '找不到',
        '待設定', '請人工', '沒試算',
    )
    _NOTE_CHECK_HINTS = (
        '請確認', '請自行', '請在右欄', '請改寫', '請改用', '請先',
        '已取第一份', '沒有保留',
    )

    def _note_level(self, text):
        """待辦的嚴重度：blocker（內容或版面會不同）／check（改寫了，要確認）
        ／info（只是告知）。"""
        for hint in self._NOTE_BLOCKER_HINTS:
            if hint in text:
                return 'blocker'
        for hint in self._NOTE_CHECK_HINTS:
            if hint in text:
                return 'check'
        return 'info'

    def _note(self, state, text, level=None):
        if text in state['notes']:
            return
        state['notes'].append(text)
        state.setdefault('note_levels', {})[text] = (
            level if level in self._NOTE_LEVELS else self._note_level(text))


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
        # 範本裡直接寫 env.user.has_group(...)（批號標籤就有）。沙箱擋 env，
        # 但我們有同名的 helper，所以這條是等價改寫而不是降級。
        (r'\b(?:env\.user|request\.env\.user)\.has_group\(',
         'has_group(',
         'env.user.has_group(…) 已改用同名的 helper（沙箱不開放 env）'),
        # 渲染時的 context 旗標（proforma 之類）。文件是先存下來再印的，
        # 沒有那個 context，所以一律取 get() 的預設值——這與「使用者直接印
        # 一張普通單據」一致。要兩種版本請複製一份範本。
        (r"\benv\.context\.get\(\s*['\"][^'\"]+['\"]\s*,\s*([^()]*?)\s*\)",
         r'\1',
         'env.context.get(…) 是渲染時的旗標（例如 proforma），文件沒有那個'
         ' context，已取 get() 的預設值。要另一種版本請複製一份範本'),
        (r"\benv\.context\.get\(\s*['\"][^'\"]+['\"]\s*\)",
         'False',
         'env.context.get(…) 沒有預設值，已當成 False（文件沒有渲染時的'
         ' context）'),
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
        state['accumulator_meta'] = self._accumulator_meta(root, state)
        return symbols

    def _accumulator_meta(self, root, state):
        """累加器的「加什麼」與「什麼時候歸零」。

        原生的章節小計是這個形狀：
            <t t-set="current_subtotal" t-value="0"/>
            <t t-foreach="lines" t-as="line">
                <t t-set="current_subtotal"
                   t-value="current_subtotal + line.price_subtotal"/>
                <t t-if="line.display_type == 'line_section'">
                    <t t-set="current_subtotal" t-value="0"/>   ← 歸零＝分組邊界
                </t>
        所以「加什麼」給得出分組小計的聚合欄位，「在什麼條件下歸零」就是
        分組的切分條件。兩者都是從 arch 讀出來的，不是猜的。
        """
        meta = {}
        for name in (state.get('accumulators') or ()):
            info = {}
            for node in root.xpath('//t[@t-set=%s]' % json.dumps(name)):
                value = (node.get('t-value') or '').strip()
                m = re.match(
                    r'^%s\s*\+\s*(.+)$' % re.escape(name), value)
                if m:
                    info['sum'] = m.group(1).strip()
                    continue
                if value in ('0', '0.0', '0.00') and 'reset' not in info:
                    # 歸零通常包在一個 t-if 裡，那個條件就是分組邊界
                    parent = node.getparent()
                    for _level in range(3):
                        if parent is None:
                            break
                        cond = parent.get('t-if')
                        if cond:
                            info['reset'] = cond.strip()
                            break
                        parent = parent.getparent()
            if info.get('sum') and not info.get('reset'):
                info['reset'] = self._section_split_condition(root)
            if info.get('sum'):
                meta[name] = info
        return meta

    # 「這一列是章節列」的慣用判斷：<迴圈變數>.<欄位> == '<值>'。
    # 用 search 而不是 match：原生的章節判斷常是複合條件
    #   line.display_type == 'line_section' or line.product_type == 'combo'
    # 整條都是章節的邊界，所以比對到其中一段就取整條。
    _SECTION_COND_RE = re.compile(r"(?<![\w.])(\w+)\.(\w+)\s*==\s*'([^']+)'")

    def _section_split_condition(self, root):
        """分組邊界：從迴圈裡的「列型判斷」找。找不到回空字串。

        這一版的 Odoo 不是在一個 t-if 裡把累加器歸零（歸零寫在小計列後面、
        沒有條件），所以抓不到「歸零條件」。退而求其次：整棵樹裡找
        `line.display_type == 'line_section'` 這種列型判斷——那就是章節的
        邊界，而且是從 arch 讀出來的。找不到就留空，讓使用者自己指定。
        """
        # t-elif 也要看：列型分派常寫成 t-if（商品）→ t-elif（章節）→
        # t-elif（備註），章節那一條就在 t-elif 上（實測漏過一次）
        fallback = ''
        for node in root.xpath('//*[@t-if] | //*[@t-elif]'):
            cond = ' '.join(
                (node.get('t-if') or node.get('t-elif') or '').split())
            for m in self._SECTION_COND_RE.finditer(cond):
                var, field, value = m.group(1), m.group(2), m.group(3)
                if var in _ROOT_VARS:
                    # doc.company_price_include == 'tax_included' 這種是主記錄
                    # 的設定，不是列型判斷——不可以當分組邊界（實測踩過）
                    continue
                if 'section' in value or 'section' in field:
                    # 章節優先：同一份範本裡 display_type 的比較有好幾條
                    #（章節、備註…），取到備註那一條就會按備註分組（踩過）
                    return cond
                if field == 'display_type' and not fallback:
                    fallback = cond
        return fallback

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
        raw = (node.get('t-options') or '') if node is not None else ''
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
            args = []
            if ('name' in opt) if opt else True:
                args.append('with_name=True')
            # 原生 contact widget 的 fields 常含 phone（採購單、出貨單都有），
            # 不帶的話單據上少一行電話
            if 'phone' in opt or 'mobile' in opt:
                args.append('with_phone=True')
            return 'format_address(%s%s)' % (
                base, (', ' + ', '.join(args)) if args else '')
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
        """沿著 a.b.c 查最後一個欄位。查不到回 None。

        實作在 doc.render.mixin——這支原本是一份一字不差的複本，而它和型別表
        是同一件事的兩半（走路徑、看型別），分開放遲早會只改一邊。
        """
        return self.env['doc.render.mixin']._resolve_path_field(model, path)

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

        型別表本身在 doc.render.mixin（RenderFields._type_format_expression），
        這裡只負責「要不要套」。刻意只套數字與日期（numeric_only）：

          * selection / many2one / x2many **不在這裡套**，而是讓藥丸只帶
            path，由渲染層依型別處理。那條路同時照顧到手工做的範本，而且
            換語言時標籤跟著換（表達式寫死 selection_label 也會，但沒必要
            在兩個地方各做一次）。
          * 不擴大到其他型別：目前這組範圍是已經量過保真度（漏印 2 / 4）的
            現狀。原生 QWeb 對 `t-out` 的數字其實也不格式化，要不要跟著分
            t-field / t-out 是另一件事，要連著重新量一次才能動。
        """
        model = self._path_model(state, kind)
        if (getattr(self._resolve_field(model, path), 'type', None) == 'datetime'
                and self._option_date_only(node)):
            # 原範本明講只要日期（t-options 的 date-only）→ 不走表的預設
            return "format_date(%s, 'lang')" % base
        # t-field 與 t-out / t-esc 的語意其實不同：t-field 會走
        # ir.qweb.field.<型別> 的 converter（float 讀 digits、date 走語言格式），
        # t-out / t-esc 只是把表達式字串化。所以理論上這裡應該分開處理。
        #
        # ☠️ 2026-10-09 實作了那個分界，然後量了一次：**36 張報表裡
        # 「t-out / t-esc 指向數字或日期欄位」的節點是 0 個**，四張報表的
        # 保真度數字一個字都沒變。也就是原生報表的數字與日期一律走 t-field。
        # 所以那個分界是純粹的多餘分支，已經收回。
        # 真的遇到「某張客製報表用 t-out 印金額而我們多格式化了」時再加，
        # 加的時候用同一支量測腳本確認它真的改變了什麼。
        return self.env['doc.render.mixin']._type_format_expression(
            model, path, base, numeric_only=True)

    def _barcode_value_pill(self, node, expr, state):
        """t-options widget="barcode" → 條碼藥丸。

        標籤與條碼類報表的主角（36 張報表裡 44 處）。原本只會變成一顆普通
        取值藥丸，單據上印出來的是條碼的「文字」而不是條碼本身。
        """
        opts = node.get('t-options') or ''
        kinds = self.env['doc.render.mixin']._BARCODE_TYPES
        m = re.search(r'["\']symbology["\']\s*:\s*["\']([\w-]+)["\']', opts)
        kind = (m.group(1) if m else '') or 'Code128'
        if kind not in kinds:
            self._note(
                state,
                '條碼型別「%s」本模組不支援，已改用 Code128。支援的有：%s'
                % (kind, '、'.join(kinds)),
            )
            kind = 'Code128'
        meta = {'source': 'image', 'barcodeType': kind}
        for key in ('width', 'height'):
            num = re.search(r'["\']%s["\']\s*:\s*(\d+)' % key, opts)
            if num:
                meta[key] = int(num.group(1))
        if re.search(r'["\']humanreadable["\']\s*:\s*(1|[\'"]?[Tt]rue)', opts):
            meta['barcodeText'] = True
        path, kind_of = self._strip_root(expr, state)
        if path and _SIMPLE_PATH_RE.match(path):
            meta['path'] = path
        else:
            mapped = self._map_condition(
                self._expand_symbols(expr, state)[0], state)
            meta['expression'] = mapped
            meta['unbound'] = True
            self._note(state, '條碼的取值是算出來的，請確認：%s' % mapped[:80])
        label = '條碼：%s' % (meta.get('path') or '表達式').split('.')[-1]
        return self._pill(label[:20], state, **meta)

    def _accumulator_pill(self, expr, state):
        """累加器的取值 → 分組小計的聚合藥丸。回 None 表示不是累加器。

        current_subtotal 這種值在本模組是「這一組明細的小計」，
        所以取值要換成 group.lines|sum(attribute='…')——聚合而不是累加。
        """
        text = (expr or '').strip()
        meta = state.get('accumulator_meta') or {}
        info = meta.get(text)
        if info is None:
            return None
        # 用現在的 state：這時候我們就在迴圈裡，loop_vars 才是真正的迴圈
        # 變數名（寫死 'line' 的話 kid.credit_limit 不會被換掉——實測踩過）
        summed = self._map_condition(info.get('sum') or '', state)
        m = re.match(r'^line\.(\w+)$', summed.strip())
        if m:
            agg = "group.lines|sum(attribute='%s')" % m.group(1)
        else:
            agg = "group.lines|map(attribute='%s')|sum" % summed
            self._note(
                state,
                '累加器加的是算式（%s），分組小計已改成 map|sum，請確認。'
                % (info.get('sum') or '')[:60],
            )
        return self._pill('本組小計', state, source='group',
                          expression='format_money(%s)' % agg)

    def _value_pill(self, node, expr, state):
        """t-field / t-out / t-esc → 藥丸。"""
        index_pill = self._loop_index_pill(expr, state)
        if index_pill is not None:
            return index_pill
        acc_pill = self._accumulator_pill(expr, state)
        if acc_pill is not None:
            return acc_pill
        if self._parse_options(node) == 'barcode':
            return self._barcode_value_pill(node, expr, state)
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

