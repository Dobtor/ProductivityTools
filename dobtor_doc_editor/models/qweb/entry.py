"""ConvEntry — 入口與轉換後試算。

convert_report() 是唯一的對外入口；試算那一段是「轉完立刻拿樣本記錄
跑一遍」——轉換器唯一會「猜」的地方（改寫規則表）必須被試算驗過，
猜錯的在待辦裡會變成 blocker。
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
        root = self._parse_arch(view)
        if root is None:
            return {'content_json': '', 'notes': ['QWeb arch 解析失敗'],
                    'stats': {}}

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
            'view': view,
        }
        # 先把子範本併進來再收符號表：子範本自己的 t-set 要被看到，
        # 而且併入後整棵樹就是 QWeb 實際渲染的那一棵。
        self._inline_calls(root, state)
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

