"""ConvEntry — 入口與轉換後試算。

convert_report() 是唯一的對外入口；試算那一段是「轉完立刻拿樣本記錄
跑一遍」——轉換器唯一會「猜」的地方（改寫規則表）必須被試算驗過，
猜錯的在待辦裡會變成 blocker。
"""
import ast
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
    _GROUP_TOKEN_RE,
)


class ConvEntry:

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
        built = self._build_tree(view, report, page_format, validate_with)
        if built is None:
            return {'content_json': '', 'notes': ['QWeb arch 解析失敗'],
                    'stats': {}}
        tree, state, root = built
        # 固定文字照各語言的翻譯轉成多語文字（見 _merge_languages）
        self._merge_languages(tree, view, report, page_format, validate_with, state)
        # 藥丸上的名稱比所在的格子寬時縮短，編輯器裡才不會蓋到隔壁欄
        self.env['doc.render.mixin']._fit_pill_labels(
            tree, self._inner_width(state),
            self.env.context.get('doc_convert_text_size') or 16,
            self.env.context.get('doc_convert_text_font'))
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
        levels = state.get('note_levels') or {}
        by_level = {key: [n for n in state['notes']
                          if levels.get(n, 'info') == key]
                    for key in self._NOTE_LEVELS}
        return {
            'content_json': json.dumps(tree, ensure_ascii=False),
            'notes': state['notes'],
            # 分級後的同一份待辦（notes 保持原樣，呼叫端不必改）
            'notes_by_level': by_level,
            'stats': state['stats'],
            'needs_layout': needs_layout,
        }

    def _build_tree(self, view, report, page_format, validate_with):
        """原生範本 → 元素樹（用目前 context 的語言讀 arch）。回 (tree, state, root) 或 None。

        拆出來是為了多語：同一張範本換個語言再跑一次，結構相同、只有文字不同。
        """
        root = self._parse_arch(view)
        if root is None:
            return None

        state = {
            'notes': [],
            'note_levels': {},
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
            # 左右邊距合計（px）。轉換精靈掛「Odoo 標準」外框時是 70（左右各
            # 35px），版面比預設的 1 吋邊距寬；用錯寬度的話，多出來的寬度會被
            # 按比例分給每一欄，品名欄還是不夠寬
            'margin_x': self.env.context.get('doc_convert_margin_x') or 192,
            'view': view,
        }
        # 先把子範本併進來再收符號表：子範本自己的 t-set 要被看到，
        # 而且併入後整棵樹就是 QWeb 實際渲染的那一棵。
        self._inline_calls(root, state)
        self._mark_company_color_nodes(root)
        self._rewrite_groups(root, state)
        self._note_unconverted_attrs(root, state)
        self._collect_symbols(root, state)
        body_node, blocks = self._split_layout(root, state)

        main = []
        self._emit_layout_blocks(blocks, main, state)
        self._emit_children(body_node, main, state)
        self._trim(main)

        # 頁首頁尾一律留空，交給外框範本——公司 logo、公司資訊、頁碼對所有
        # 報表都一樣，複製進每一張範本的話改公司地址要改 N 張。
        tree = {'header': [], 'main': main, 'footer': []}
        # 轉換器內部用「換行收尾一段、對齊寫在收尾換行上」的寫法；
        # 交出去之前轉成編輯器的寫法（換行是下一段的開頭）。試算要用轉好的樹，
        # 才會跟使用者之後在編輯器與 PDF 看到的一樣。
        self.env['doc.render.mixin']._paragraph_ends_to_starts(tree)
        return tree, state, root


    # ─── 多語 ───────────────────────────────────────────────────────
    #
    # 原生報表的固定文字（「說明」「數量」「報價單 #」）在 Odoo 裡本來就有各語言
    # 的翻譯，跟著 arch 存。只用目前語言轉一次就只拿到一種語言，中文範本印給
    # 英文客戶會中英混雜。做法：每個已啟用的語言各轉一次——結構完全相同、只有
    # 文字不同——再逐個位置對齊：
    #   純文字段落                                → 多語文字藥丸
    #   算式裡的字串（"報價單 #" if … else "訂單 #"）→ translated({...})
    # 某一串對不上（譯者改了行內標記之類）就那一串不帶翻譯，記一條待辦。

    _STRING_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')

    def _merge_languages(self, tree, view, report, page_format, validate_with,
                         state):
        Mixin = self.env['doc.render.mixin']
        base_lang = self.env.lang or 'en_US'
        installed = dict(self.env['res.lang'].get_installed())
        others = [code for code in installed if code != base_lang]
        if not others:
            return
        base_lists = list(Mixin._iter_element_lists(tree))
        text_tr = {}   # (串列序, 起, 迄) → {語言: 文字}
        expr_tr = {}   # (串列序, 元素序) → {語言: 算式}
        for code in others:
            name = installed.get(code, code)
            sample = (validate_with.with_context(lang=code)
                      if validate_with else validate_with)
            built = self.with_context(lang=code)._build_tree(
                view.with_context(lang=code), report, page_format, sample)
            other_lists = (list(Mixin._iter_element_lists(built[0]))
                           if built else [])
            if len(other_lists) != len(base_lists):
                self._note(state, '「%s」的版面跟原本對不上，固定文字沒有帶入這個'
                                  '語言的翻譯。' % name, level='check')
                continue
            self._merge_fit_widths(tree, built[0])
            mismatched = 0
            for li, (base, other) in enumerate(zip(base_lists, other_lists)):
                if not self._same_shape(base, other):
                    mismatched += 1
                    continue
                for start, end in self._style_runs(base):
                    text_tr.setdefault((li, start, end), {})[code] = ''.join(
                        other[i].get('value') or '' for i in range(start, end))
                for ei, (b_el, o_el) in enumerate(zip(base, other)):
                    b_meta = Mixin._element_field_meta(b_el) or {}
                    o_meta = Mixin._element_field_meta(o_el) or {}
                    b_expr = b_meta.get('expression')
                    o_expr = o_meta.get('expression')
                    if b_expr and o_expr and b_expr != o_expr:
                        expr_tr.setdefault((li, ei), {})[code] = o_expr
                    # 欄位沒值時印的範例字也有翻譯（units → 單位）
                    if b_meta.get('emptyText') and o_meta.get('emptyText'):
                        b_meta['emptyText'].update(o_meta['emptyText'])
            if mismatched:
                self._note(state, '有 %d 處的「%s」翻譯跟原本的版面對不上，那幾處'
                                  '固定文字只有一種語言。' % (mismatched, name),
                           level='check')

        rewritten = 0
        for (li, ei), by_lang in expr_tr.items():
            meta = Mixin._element_field_meta(base_lists[li][ei])
            expression = self._translate_literals(
                meta['expression'], base_lang, by_lang)
            if expression != meta['expression']:
                meta['expression'] = expression
                rewritten += 1

        by_list = {}
        for (li, start, end), by_lang in text_tr.items():
            by_list.setdefault(li, []).append((start, end, by_lang))
        converted = 0
        for li, runs in by_list.items():
            elements = base_lists[li]
            # 由後往前換：前面的索引才不會位移
            for start, end, by_lang in sorted(runs, key=lambda r: r[0], reverse=True):
                text = ''.join(elements[i].get('value') or ''
                               for i in range(start, end))
                core = text.strip()
                texts = {base_lang: core}
                texts.update({code: value.strip()
                              for code, value in by_lang.items() if value.strip()})
                if len(set(texts.values())) <= 1:
                    # 各語言都一樣（符號、數字、專有名詞）→ 維持純文字
                    continue
                lead = text[:len(text) - len(text.lstrip())]
                trail = text[len(text.rstrip()):]
                replacement = []
                if lead:
                    replacement.append(dict(elements[start], value=lead))
                replacement.append(Mixin._i18n_pill(elements[start], core, texts))
                if trail:
                    replacement.append(dict(elements[end - 1], value=trail))
                elements[start:end] = replacement
                converted += 1
        if converted or rewritten:
            self._note(
                state,
                '固定文字已帶入 %s 的翻譯：%d 段轉成多語文字、%d 個算式裡的字串改成'
                '依語言挑字。列印時依客戶語言自動切換。'
                % ('、'.join(installed.get(c, c) for c in others),
                   converted, rewritten),
                level='info',
            )

    def _merge_fit_widths(self, base_tree, other_tree):
        """照內容估的窄欄取各語言裡最寬的，寬欄平分剩下的（就地改 base_tree）。

        表頭的長短隨語言變：用中文轉換時「單價」只有兩個字，那一欄只估到
        放得下數字的寬度，印給英文客戶時「Unit Price」就擠成兩行。
        寬欄裡有巢狀表格時不動：那些表格的寬度是照原本的欄寬排的，欄變窄會
        超出格子。
        """
        Mixin = self.env['doc.render.mixin']

        def fitted(tree):
            return [t for t in Mixin._iter_tables(tree)
                    if (t.get('extension') or {}).get('fitCols')]

        base_tables, other_tables = fitted(base_tree), fitted(other_tree)
        if len(base_tables) != len(other_tables):
            return
        for base, other in zip(base_tables, other_tables):
            flags = base['extension']['fitCols']
            b_cols, o_cols = base.get('colgroup') or [], other.get('colgroup') or []
            if (flags != other['extension'].get('fitCols')
                    or len(b_cols) != len(flags) or len(o_cols) != len(flags)):
                continue
            if any(cell_el.get('type') == 'table'
                   for row in base.get('trList') or []
                   for col, cell in enumerate(row.get('tdList') or [])
                   if col < len(flags) and not flags[col]
                   and int(cell.get('colspan') or 1) == 1
                   for cell_el in cell.get('value') or []):
                continue
            widths = [max(b['width'], o['width']) if fit else 0
                      for b, o, fit in zip(b_cols, o_cols, flags)]
            inner = sum(b['width'] for b in b_cols)
            for col, new in zip(b_cols, self._fit_widths(widths, flags, inner)):
                col['width'] = new['width']

    def _same_shape(self, base, other):
        """兩個元素串列結構相同（只有文字可以不同）才能逐位置對齊。"""
        if len(base) != len(other):
            return False
        for b_el, o_el in zip(base, other):
            if not (isinstance(b_el, dict) and isinstance(o_el, dict)):
                return False
            if (b_el.get('type') or 'text') != (o_el.get('type') or 'text'):
                return False
            if (b_el.get('value') == '\n') != (o_el.get('value') == '\n'):
                return False
            if (b_el.get('type') or 'text') == 'text':
                if self._style_of(b_el) != self._style_of(o_el):
                    return False
        return True

    def _style_of(self, element):
        return {k: v for k, v in element.items() if k != 'value'}

    def _style_runs(self, elements):
        """yield (起, 迄)：連續、樣式相同的純文字元素。

        樣式不同就分開：一段粗體一段不粗合成一顆藥丸，會把粗體弄丟。
        """
        start = None
        for idx, el in enumerate(list(elements) + [None]):
            is_text = (isinstance(el, dict)
                       and (el.get('type') or 'text') == 'text'
                       and el.get('value') and el.get('value') != '\n')
            if (start is not None
                    and (not is_text
                         or self._style_of(el) != self._style_of(elements[start]))):
                if ''.join(elements[i].get('value') or ''
                           for i in range(start, idx)).strip():
                    yield start, idx
                start = None
            if is_text and start is None:
                start = idx

    def _translate_literals(self, expression, base_lang, by_lang):
        """算式裡各語言不同的字串 → translated({語言: 字串})。

        只有「字串以外完全相同」的語言才對得上；字串位置一一對應。
        """
        literals = self._STRING_LITERAL_RE.findall(expression)
        skeleton = self._STRING_LITERAL_RE.sub('\x00', expression)
        per_lang = {
            code: self._STRING_LITERAL_RE.findall(other)
            for code, other in by_lang.items()
            if self._STRING_LITERAL_RE.sub('\x00', other) == skeleton
        }
        if not per_lang:
            return expression
        pieces = self._STRING_LITERAL_RE.split(expression)
        out = [pieces[0]]
        for idx, literal in enumerate(literals):
            try:
                texts = {base_lang: ast.literal_eval(literal)}
                for code, values in per_lang.items():
                    texts[code] = ast.literal_eval(values[idx])
            except (ValueError, SyntaxError):
                texts = {}
            if len(set(texts.values())) > 1:
                out.append('translated(%s)'
                           % json.dumps(texts, ensure_ascii=False))
            else:
                out.append(literal)
            out.append(pieces[idx + 1])
        return ''.join(out)


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
        """yield (元素, 該元素所在重複列的一筆明細 or None, 迴圈位置, 分組 or None)。

        不能全樹共用一筆明細：同一張單據上可以有好幾個不同形狀的重複
        （發票同時有「明細列」與「付款列」，後者的一筆是 dict），
        拿明細列的那一筆去試算付款列的 line 藥丸，會得到一整批假失敗，
        而假失敗會把藥丸標成待確認——使用者去檢查一個其實沒問題的地方。

        分組標題／小計列不是重複列，但印的時候帶著這一組的明細與 group：
        用同一張表重複列的明細當樣本（小計列取最後一筆，跟渲染時一樣），
        否則小計列上「訂金那一節不印」這種條件永遠被算成「沒試算」。
        """
        Mixin = self.env['doc.render.mixin']

        def walk(elements, line, loop, group):
            for element in elements:
                yield element, line, loop, group
                if element.get('type') != 'table':
                    continue
                rows = [r for r in (element.get('trList') or [])
                        if isinstance(r, dict)]
                table_lines = None
                for row in rows:
                    marker, meta = Mixin._row_repeat_meta(row)
                    if marker:
                        table_lines = Mixin._resolve_repeat_records(record, meta)
                        break
                for row in rows:
                    row_line, row_loop, row_group = line, loop, group
                    marker, meta = Mixin._row_repeat_meta(row)
                    _g_el, _g_meta, role = Mixin._row_group_meta(row)
                    if marker:
                        lines = Mixin._resolve_repeat_records(record, meta)
                        row_line = lines[0] if lines else None
                        # 用「最後一筆」的迴圈位置試算：原生的章節小計條件寫
                        #   line_last or lines[line_index+1].display_type == …
                        # 假裝在中間的話 lines[index+1] 會超出範圍，變成一個
                        # 假失敗；假裝在最後一筆則 or 會短路，跟原生一樣。
                        row_loop = Mixin._loop_context(
                            max(0, len(lines) - 1), len(lines))
                    elif role and table_lines is not None:
                        lines = list(table_lines)
                        idx = len(lines) - 1 if role == 'footer' else 0
                        row_line = lines[idx] if lines else None
                        row_loop = Mixin._loop_context(max(0, idx), len(lines))
                        row_group = {
                            'key': False, 'label': '', 'header': row_line,
                            'lines': lines, 'index': 1, 'count': 1,
                        } if lines else None
                    for cell in (row.get('tdList') or []):
                        if isinstance(cell, dict):
                            yield from walk(cell.get('value') or [],
                                            row_line, row_loop, row_group)

        for zone in ('header', 'main', 'footer'):
            yield from walk(tree.get(zone) or [], None, None, None)

    def validate_tree(self, tree, record, state):
        """拿一筆記錄試算所有藥丸的表達式。回傳 {'ok', 'failed'}。

        只有「求值丟例外」才算失敗。求出空值不算——那一筆記錄那個欄位本來
        就可能是空的，把它當失敗會製造一堆假待辦。
        """
        Mixin = self.env['doc.render.mixin']
        ok = failed = skipped = 0
        for element, line, loop, group in self._iter_validation_targets(
                tree, record):
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
            if _GROUP_TOKEN_RE.search(expression):
                if group is None:
                    skipped += 1
                    continue
                extra['group'] = group
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

