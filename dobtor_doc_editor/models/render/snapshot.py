"""RenderSnapshot — 快照管線（pass 鏈）。

「把藥丸換成值」的那條鏈：展開重複列 → 展開稅額彙總 → 條件（列／欄／
段落）→ 條件式格式 → 清空表格 → 純量求值 → 收合空段落。

**順序是這個模組唯一的硬約束**，權威寫在 _snapshot_content_json 的註解裡，
並由 TestSnapshotPassOrder 斷言。加新的 pass 要同時改那段註解，
否則測試會紅——那是故意的。
"""
import base64


from odoo import fields
from odoo.tools.misc import format_amount
from odoo.tools.image import FILETYPE_BASE64_MAGICWORD, image_data_uri
from odoo.tools.mail import html_sanitize


class RenderSnapshot:

    def _drop_empty_tables(self, tree):
        """移除 trList 已空的表格，連同其後的孤兒換行。

        會變成空表格的兩種情況：條件區塊整塊被移除、重複列零筆明細。
        不一起吃掉後面那個換行的話，版面會留下一個空段落——使用者看到的是
        「條件為假時多了一行空白」，而且完全看不出來那行空白是怎麼來的。

        只吃「緊跟其後」的那一個換行：使用者自己在表格後面多按的 Enter
        是他要的空行，不該被當成殘渣清掉。
        """
        removed = 0
        for elements in self._iter_element_lists(tree):
            # 由後往前刪，避免索引位移
            for idx in range(len(elements) - 1, -1, -1):
                el = elements[idx]
                if not isinstance(el, dict) or el.get('type') != 'table':
                    continue
                rows = el.get('trList') or []
                # 欄條件可能把每一列的格子都刪掉——列還在但一格不剩，
                # _table_to_html 會輸出空字串，留著只會變成一個空段落
                if rows and any((r.get('tdList') or []) for r in rows
                                if isinstance(r, dict)):
                    continue
                stop = idx + 1
                nxt = elements[stop] if stop < len(elements) else None
                if isinstance(nxt, dict) and (nxt.get('value') or '') == '\n':
                    stop += 1
                del elements[idx:stop]
                removed += 1
        return removed

    def _image_data_uri(self, record, meta):
        """binary 欄位 → data: URI。取不到一律回空字串。

        用 path 走欄位而不是求 expression：binary 欄位的值是 base64 bytes，
        經過 Jinja 會變成 "b'iVBOR...'" 這種 repr——印出來是一串看不懂的文字，
        而且不會報錯。路徑直接取值才拿得到原始 bytes。

        刻意只接受 binary 欄位與既成的 data URI，不抓外部 URL：匯出不該在
        使用者按下載時去連外，那會讓匯出時間取決於第三方網站，在無外網的
        容器還會直接卡住（與 doc_document._emit_image 同一個決定）。
        """
        if record is None:
            return ''
        if (meta.get('barcodeType') or '').strip():
            return self._barcode_data_uri(record, meta)
        path = (meta.get('path') or '').strip()
        expression = (meta.get('expression') or '').strip()
        if path:
            value = self._traverse_path(record, path)
        elif expression:
            # 表達式來源：發票的付款 QR 是
            # partner_bank_id.build_qr_code_base64(...) 算出來的 data URI，
            # 不是某個 binary 欄位。一樣用 compile_expression 取真值——
            # from_string 會把 bytes 變成 "b'iVBOR...'" 的 repr。
            value = self._eval_raw(expression, record)
        else:
            return ''
        if not value:
            return ''
        if isinstance(value, str):
            if value.startswith('data:'):
                return value
            value = value.encode()
        if not isinstance(value, bytes):
            return ''
        # image_data_uri() 不驗證內容——認不出型別就一律當 png。所以把一個
        # 文字欄位誤設成圖片來源時，它會回 'data:image/png;base64,壞圖'，
        # 印出一張破圖而且不報錯。這裡先確認首位元組落在 Odoo 自己的
        # magic word 表裡（jpg/gif/png/svg/webp），認不出來就當沒有圖。
        if value[:1] not in FILETYPE_BASE64_MAGICWORD:
            return ''
        try:
            return image_data_uri(value)
        except Exception:
            # base64 壞了 → 空字串。單一壞圖不該讓整份文件產不出來
            return ''

    def _html_field_value(self, record, meta):
        """Html 欄位 → 可直接嵌入的 HTML 片段（已消毒）。

        一定要過 html_sanitize：這些值最後會進 PDF（wkhtmltopdf 會執行 JS）
        與 doc.output.content_json（後台編輯器裡瀏覽），而 Odoo 並非所有
        Html 欄位在寫入時都有 sanitize。

        內容沒有可見文字也沒有圖時回空字串——Odoo 的 Html 編輯器留下的
        '<p><br></p>' 這類空殼若原樣輸出，自動收合空段落會判斷成「有值」，
        於是單據上多出一段看不見的空白。
        """
        expression = self._field_meta_expression(meta)
        if not expression or record is None:
            return ''
        env_j = self._get_sandbox_env(record)
        try:
            raw = env_j.from_string('{{ %s }}' % expression).render(
                object=record, user=self.env.user,
            )
        except Exception:
            return ''
        if not raw or raw in ('False', 'None'):
            return ''
        clean = html_sanitize(raw)
        if not self._html_has_content(clean):
            return ''
        return clean

    # Odoo 自己的條碼 API 支援的型別（ir_actions_report.barcode()）。
    # 揀貨單用了 16 處條碼、發票有付款 QR——所以這不是發票專屬的需求。
    _BARCODE_TYPES = ('QR', 'Code128', 'Code39', 'EAN13', 'EAN8', 'UPCA')

    def _barcode_data_uri(self, record, meta):
        """條碼／QR → data: URI。委派 ir.actions.report.barcode()。

        原生報表用 o._generate_qr_code()，但底線開頭的方法被沙箱擋死（刻意的）。
        barcode() 是公開 API，而且同時支援 QR / Code128 / EAN13，涵蓋範圍比
        單一個 QR helper 大得多。

        掛在「圖片藥丸」上而不是做成沙箱 helper：藥丸的值是文字，helper 回
        data URI 的話會在單據上印出一長串 base64——實測過的那個失敗模式。
        """
        barcode_type = (meta.get('barcodeType') or 'QR').strip()
        expression = (meta.get('expression') or '').strip()
        if not expression:
            path = (meta.get('path') or '').strip()
            expression = 'object.%s' % path if path else ''
        if not expression:
            return ''
        env_j = self._get_sandbox_env(record)
        try:
            value = env_j.from_string('{{ %s }}' % expression).render(
                object=record, user=self.env.user,
            )
        except Exception:
            return ''
        value = (value or '').strip()
        if not value or value in ('False', 'None'):
            return ''
        try:
            raw = self.env['ir.actions.report'].barcode(
                barcode_type, value,
                width=int(meta.get('barcodeWidth') or 300),
                height=int(meta.get('barcodeHeight') or 100),
                humanreadable=1 if meta.get('barcodeText') else 0,
            )
        except Exception:
            # 條碼型別與值不相容（EAN13 要 12-13 位數字之類）→ 不印。
            # 這裡刻意不 raise：一個打錯的料號不該讓整張揀貨單印不出來。
            return ''
        return 'data:image/png;base64,%s' % base64.b64encode(raw).decode()

    def _snapshot_content_json(self, tree, record, only_pending=False):
        """把模型變數藥丸求值後寫進 label 的 value（就地改寫並回傳 tree）。

        決策一（建立時快照）：值在此凍結一次，之後改記錄不會動到文件。
        決策三（空值印空白）：求值為 falsy 一律寫空字串，不印底線也不擋。

        藥丸結構刻意保留——凍結後仍看得出哪些字是帶進來的、右側面板仍能顯示
        來源欄位、也仍然可以按「重新帶值」重跑。快照時就攤平的話這三件事全失去。

        only_pending=True 時只處理「還沒凍結過」的藥丸（meta 無 frozenAt）。
        這是匯出路徑用的：文件級的 snapshot_date 當開關會漏掉「快照之後才新增
        的藥丸」——它們會以標籤文字原樣印進 PDF，而且沒有任何錯誤訊息。
        改以逐元素標記，既有凍結值不動（決策一保住），新加的會補上值。
        """
        if not tree or record is None:
            return tree

        # ─── Pass 鏈（順序有意義，不可對調）───────────────────────
        #
        # 這段註解是權威：TestSnapshotPassOrder 會斷言實際呼叫順序等於這裡
        # 寫的，而且斷言每一關的**方法名**都出現在這段註解裡。加新的 pass
        # 一定要同時改這裡——「順序約束只存在於某人腦袋裡」是這個管線最容易
        # 壞掉的方式（實測發生過一次：條件式格式加進去但沒寫進來）。
        #
        #   1.   _expand_repeat_rows
        #        要在純量求值前：展開產生的列裡 source='line' 藥丸必須以
        #        各自的明細記錄求值，不是主記錄。
        #        重複列內「沒有 groupId」的條件標記與條件式格式也在這一步
        #        就地解決——那兩種要逐筆判斷，而第 2 關只有 object 可用
        #        （見 _resolve_line_row_conditions / _resolve_format_markers）
        #   1.5  _expand_tax_totals_rows
        #        同樣會產生新的列（每個稅別一列），要在條件之前，
        #        產生出來的列才能被條件處理到
        #   2.   _condition_group_results → _apply_row_conditions
        #        if/else 群組先一次求完值再傳下去：兩個 pass 共用同一份結果，
        #        否則列條件移走 if 標記後，段落裡的 else 就找不到配對了
        #   3.   _apply_column_conditions → _apply_paragraph_conditions
        #        條件自成一體、不依賴藥丸的值，放在求值前可以少算被移除那部分。
        #        欄一定排在列之後：列條件的標記可能就放在某一欄裡，
        #        先刪欄會讓那個列條件無聲消失
        #   3.6  _apply_format_markers
        #        排在條件之後（被移除的列不必再算格式），排在求值之前
        #       （格式與值無關）。重複列內的格式標記在第 1 關就處理掉了，
        #        這一關只處理重複列以外的
        #   3.5  _drop_empty_tables
        #        1 與 2 都可能把表格的列全部移除（零筆明細、條件區塊為假），
        #        留著空表格會在版面上印出一個空段落
        #   4.   純量藥丸求值（下方既有迴圈，不是獨立方法）
        #   5.   _collapse_empty_paragraphs
        #        必須在求值後——要有值才知道是不是空的
        if not only_pending:
            self._expand_repeat_rows(tree, record)
            self._expand_tax_totals_rows(tree, record)
            # if/else 群組先一次求完值再傳下去：兩個 pass 共用同一份結果，
            # 否則列條件移走 if 標記後，段落裡的 else 就找不到配對了。
            groups = self._condition_group_results(tree, record)
            self._apply_row_conditions(tree, record, groups)
            self._apply_column_conditions(tree, record, groups)
            self._apply_paragraph_conditions(tree, record, groups)
            # 3.6 條件式格式——排在條件之後（被移除的列不必再算格式），
            #     排在求值之前（格式與值無關，先算完後面就不用管它）
            self._apply_format_markers(tree, record)
            self._drop_empty_tables(tree)

        env_j = self._get_sandbox_env(record)
        cache = {}

        def _eval(expression):
            if expression in cache:
                return cache[expression]
            try:
                rendered = env_j.from_string('{{ %s }}' % expression).render(
                    object=record, user=self.env.user,
                )
            except Exception:
                # 求值失敗（欄位被刪、表達式壞掉）→ 空字串。
                # 這裡刻意不 raise：一個壞欄位不該讓整份文件產不出來。
                rendered = ''
            rendered = self._fix_recordset_repr(rendered, expression, record)
            value = '' if rendered in (None, 'False', 'None') else str(rendered)
            cache[expression] = value
            return value

        stamp = fields.Datetime.to_string(fields.Datetime.now())
        for element in self._iter_elements(tree):
            meta = self._element_field_meta(element)
            if not meta:
                continue
            if only_pending and meta.get('frozenAt'):
                continue  # 已凍結過：維持原值，不重新求值
            src = meta.get('source') or 'record'
            if self._is_marker_element(element):
                # 標記不是取值。走到這裡表示它沒被自己那一關處理掉
                #（only_pending 的匯出路徑），不可以把條件的求值結果寫成它的
                # 值——那會變成單據上一段看起來像內容的東西。攤平時會丟掉。
                continue
            if src in self._EXPANSION_SOURCES:
                # 由 _expand_repeat_rows 負責。走到這裡只有兩種情況：
                #   1. 展開已處理過（那時已蓋 frozenAt，上一個 continue 就擋掉了）
                #   2. 使用者把 line / running / 分組藥丸放在重複列之外——設定錯誤
                # 第 2 種刻意保留標籤文字不動，讓錯誤在文件上看得見而不是變空白。
                continue
            if src == 'static':
                element['value'] = meta.get('static') or ''
            elif src == self._IMAGE_SOURCE:
                element['value'] = self._image_data_uri(record, meta)
            elif src == self._HTML_SOURCE:
                element['value'] = self._html_field_value(record, meta)
            elif src == self._I18N_SOURCE:
                element['value'] = self._i18n_text(record, meta)
            else:
                expression = self._field_meta_expression(meta)
                element['value'] = _eval(expression) if expression else ''
            meta['frozenAt'] = stamp

        # 5. 自動收合空段落（規則 A）。只在完整快照時做——only_pending 是匯出時
        #    補值用的，那時版面早已定案，不該再動結構。
        if not only_pending:
            self._collapse_empty_paragraphs(tree)
        return tree

    def _sort_lines(self, lines, sort_by, desc=False):
        """依指定欄位排序明細。

        對應原生報表的 sorted(key=lambda …)——那在 Jinja 裡語法上就不存在
        （實測 TemplateSyntaxError），所以改成設定欄位名。多鍵排序請用
        「來源表達式」鏈接 |sort（Jinja 的 sort 是穩定排序，由低位往高位鏈即可）。

        排序失敗（型別混雜）時回原順序：排序壞掉不該讓整份文件產不出來，
        而順序不對至少看得出來。
        """
        key = (sort_by or '').strip()
        if not key or not lines:
            return lines

        def _k(item):
            value = self._line_key(item, key)
            if value is False or value is None or value == '':
                # 空值一律排最後，不管升降——空白夾在中間最難看
                return (1, '')
            if isinstance(value, bool):
                return (0, str(value))
            if isinstance(value, (int, float)):
                return (0, value)
            if hasattr(value, '_name'):
                try:
                    return (0, value.display_name or '')
                except Exception:
                    return (0, '')
            return (0, str(value))

        try:
            return sorted(lines, key=_k, reverse=bool(desc))
        except Exception:
            return lines

    def _resolve_repeat_records(self, record, meta, apply_filter=True):
        """求出重複的來源 recordset，並套用明細篩選。取不到回空清單。

        filter 對應原生報表的 lines_to_report（那個 t-set 做的就是這件事）：
        section / note / 預付款這類行不該印成空白列。
        表達式裡 line 與 object 都指向當前明細，兩種寫法都接受。

        apply_filter=False 是分隔列分組用的：分隔列（line_section）一定會被
        「not line.display_type」這類篩選排除掉，先篩就再也找不到分隔點了。
        分組必須先看到完整的明細序列，篩選改在分組後對組內明細做。
        """
        if record is None:
            return []
        source_expr = (meta.get('sourceExpression') or '').strip()
        if source_expr:
            # 進階來源：排序（|sort）與非 recordset 的來源（發票的付款紀錄、
            # 分期明細、稅別都是 list of dict）都靠這條
            lines = self._eval_collection(source_expr, record)
        else:
            path = (meta.get('path') or '').strip()
            if not path:
                return []
            target = self._traverse_path(record, path)
            if hasattr(target, '_name') and hasattr(target, 'ids'):
                lines = list(target)
            elif isinstance(target, dict):
                lines = list(target.values())
            elif isinstance(target, (list, tuple)):
                # 計算欄位回傳 list of dict 的情形：發票的 payment_term_details
                # （分期明細）就是這樣。原本只收 recordset，結果明細整個不印
                # 而且沒有任何訊息——那是最難追的一種壞法。
                # 字串／位元組刻意不收：Char 欄位設成重複來源會逐字展開成
                # 一列一個字，比直接不印更難懂。
                lines = list(target)
            else:
                # 純量欄位設成重複來源是設定錯誤
                return []
        lines = self._sort_lines(
            lines, meta.get('sortBy'), meta.get('sortDesc'),
        )
        expr = (meta.get('filter') or '').strip()
        if apply_filter and expr:
            lines = self._filter_lines(lines, expr)
        return lines

    def _filter_lines(self, lines, expression):
        return [
            ln for ln in lines
            if self._eval_condition(expression, ln, extra={'line': ln})
        ]

    # ─── 分組 ────────────────────────────────────────────────────────

    def _group_key_label(self, value):
        """分組鍵要可雜湊、標籤要可讀。recordset 用 (model, ids) 當鍵。"""
        if value is False or value is None:
            return False, ''
        if hasattr(value, '_name') and hasattr(value, 'ids'):
            try:
                names = value.mapped('display_name')
            except Exception:
                names = []
            return (value._name, tuple(value.ids)), ', '.join(n for n in names if n)
        return value, str(value)

    def _marker_group_label(self, line):
        """分隔列模式下該組的標籤。

        取 name 再退回 display_name：sale 的 line_section 把章節文字放在 name，
        display_name 會變成「訂單編號 - 章節」這種對單據沒意義的字串。
        真正可靠的做法是在標題列放一顆 source='line' 藥丸明確指定欄位，
        group.label 只是個不必設定的方便值。
        """
        for attr in ('name', 'display_name'):
            try:
                value = line[attr]
            except Exception:
                continue
            if value:
                return str(value)
        return ''

    def _repeat_group_mode(self, meta):
        """有效的分組模式（設了模式但沒設依據＝等於不分組）。"""
        mode = (meta.get('groupMode') or '').strip()
        if mode == 'field' and not (meta.get('groupBy') or '').strip():
            return ''
        if mode == 'marker' and not (meta.get('groupSplitOn') or '').strip():
            return ''
        return mode if mode in ('field', 'marker') else ''

    def _resolve_repeat_groups(self, record, meta):
        """取明細並切成組：[{'key','label','header','lines','index','count'}]。

        沒設定分組時回「單一組包全部明細」，展開邏輯因此只有一條路徑；
        副作用是未分組時的小計列會變成總計列——那正是使用者會期待的行為。
        """
        mode = self._repeat_group_mode(meta)
        group_by = (meta.get('groupBy') or '').strip()
        split_on = (meta.get('groupSplitOn') or '').strip()
        flt = (meta.get('filter') or '').strip()
        # 分隔列模式要看到完整序列才找得到分隔點，篩選延後到分組之後
        lines = self._resolve_repeat_records(
            record, meta, apply_filter=(mode != 'marker'),
        )

        if not mode:
            groups = [{'key': False, 'label': '', 'header': None, 'lines': lines}]
        elif mode == 'field':
            groups = []
            seen = {}
            for line in lines:
                key, label = self._group_key_label(
                    self._traverse_path(line, group_by),
                )
                if key not in seen:
                    seen[key] = {
                        'key': key, 'label': label, 'header': None, 'lines': [],
                    }
                    groups.append(seen[key])
                seen[key]['lines'].append(line)
        else:
            groups = []
            current = None
            include_header = bool(meta.get('groupIncludeHeader'))
            for line in lines:
                is_split = self._try_eval_condition(
                    split_on, line, extra={'line': line},
                )
                if is_split:
                    current = {
                        'key': line.id, 'label': self._marker_group_label(line),
                        'header': line, 'lines': [],
                    }
                    groups.append(current)
                    if include_header:
                        current['lines'].append(line)
                    continue
                if current is None:
                    # 第一個分隔列之前就有明細：給一個無標題的組，不要丟掉資料
                    current = {
                        'key': False, 'label': '', 'header': None, 'lines': [],
                    }
                    groups.append(current)
                current['lines'].append(line)

        if mode == 'marker' and flt:
            for group in groups:
                group['lines'] = self._filter_lines(group['lines'], flt)
        # 空組不印：原生報表的 _get_order_lines_to_report 也會丟掉空章節，
        # 印一個標題配 0 元小計只會讓人以為資料掉了。
        groups = [g for g in groups if g['lines']]
        total = len(groups)
        for idx, group in enumerate(groups, start=1):
            group['index'] = idx
            group['count'] = total
        return groups

    def _running_value(self, meta, line, state_bank, key, eval_line):
        """流水藥丸的值。state_bank 是 {'never': {}, 'group': {}} 兩本帳。"""
        op = (meta.get('op') or 'index').strip()
        bucket = state_bank['group' if (meta.get('resetOn') or '') == 'group'
                            else 'never']
        if op == 'index':
            bucket[key] = int(bucket.get(key) or 0) + 1
            return str(bucket[key])
        if op == 'sum':
            expression = (meta.get('expression') or '').strip()
            raw = eval_line(expression) if expression else ''
            try:
                delta = float(raw)
            except (TypeError, ValueError):
                delta = 0.0
            bucket[key] = float(bucket.get(key) or 0.0) + delta
            if meta.get('asMoney'):
                # 累計金額欄跟其他金額欄必須用同一套格式，否則同一張單上
                # 「金額」有幣別符號、「累計」沒有，看起來像兩個系統拼起來的
                cur = self._resolve_currency(line)
                if cur:
                    return format_amount(self.env, bucket[key], cur)
            spec = (meta.get('numberFormat') or ',.2f').strip()
            try:
                return format(bucket[key], spec)
            except (TypeError, ValueError):
                return str(bucket[key])
        return ''

    def _loop_context(self, index, size):
        """QWeb 的迴圈位置變數。轉換器會把 <迴圈變數>_index 改成 loop_index。

        原生報表的「章節小計」就靠它：
            lines[line_index+1].display_type == 'line_section'
        沒有這組變數的話那個條件求值失敗 → 策略是當真 → 每一列後面都印一次
        小計。index 與 QWeb 一致是 0 起算。
        """
        return {
            'loop_index': index,
            'loop_first': index == 0,
            'loop_last': index == max(0, size - 1),
            'loop_size': size,
        }

    def _fill_line_row(self, row, line, marker_el, stamp, state_bank=None,
                       variant=0, loop=None):
        """對複製出來的一列求值：source='line' 的藥丸以該明細為 object。

        流水藥丸（source='running'）的累加器以「列型索引 + 該藥丸在範本列中的
        位置」當鍵——每個複製出來的列都源自同一個範本列，位置因此是穩定且不必
        前端配 id 的識別方式。位置要在過濾標記藥丸「之前」算，否則索引會跟
        範本列對不上。
        列型索引也要進鍵裡：商品列的項次不該被備註列的流水藥丸影響，而兩者
        在各自版面裡的位置很可能剛好相同。
        """
        extra = dict(loop or {})
        extra['line'] = line
        eval_line = self._eval_for(line, extra=extra)
        for td_idx, cell in enumerate(row.get('tdList') or []):
            if not isinstance(cell, dict):
                continue
            values = cell.get('value')
            if not isinstance(values, list):
                continue
            cell['value'] = self._fill_line_values(
                values, line, stamp, state_bank, eval_line, variant,
                # 鍵一定要含 variant：商品列的項次不該被備註列的流水藥丸
                # 影響，而兩者在各自版面裡的位置很可能剛好相同
                (variant, td_idx),
            )

    def _fill_line_values(self, elements, line, stamp, state_bank, eval_line,
                          variant, path):
        """對一串元素求值（遞迴進巢狀表格）。

        要遞迴的理由：轉換器會把「列內的條件」做成條件區塊，而那是一個巢狀
        表格。不往裡面走的話，區塊裡的 source='line' 藥丸不會被求值，
        最後把標籤文字原樣印進單據——實測在出貨單的包裝說明欄印出
        「aggregated_lines__c8」這種變數名。
        """
        keep = []
        for pos, el in enumerate(elements):
            if not isinstance(el, dict):
                continue
            meta = self._element_field_meta(el)
            src = (meta.get('source') or '').strip() if meta else ''
            if src == self._REPEAT_SOURCE:
                # 標記藥丸不進成品——它是設計期的宣告，不是內容
                continue
            if src == self._LINE_SOURCE:
                expression = self._field_meta_expression(meta)
                el['value'] = eval_line(expression) if expression else ''
                meta['frozenAt'] = stamp
            elif src == self._RUNNING_SOURCE and state_bank is not None:
                el['value'] = self._running_value(
                    meta, line, state_bank, path + (pos,), eval_line,
                )
                meta['frozenAt'] = stamp
            elif (el.get('type') or '') == 'table':
                for r_idx, inner in enumerate(el.get('trList') or []):
                    if not isinstance(inner, dict):
                        continue
                    for c_idx, inner_cell in enumerate(inner.get('tdList') or []):
                        if not isinstance(inner_cell, dict):
                            continue
                        inner_cell['value'] = self._fill_line_values(
                            inner_cell.get('value') or [], line, stamp,
                            state_bank, eval_line, variant,
                            path + (pos, r_idx, c_idx),
                        )
            keep.append(el)
        return keep

    def _fill_group_row(self, row, group, record, stamp):
        """對分組標題／小計列求值。

        群組上下文 group 是個 dict（Jinja 的屬性查找會退回 item 查找，所以
        group.lines 寫得通）。另外允許列內放 source='line' 藥丸指向分隔列本身
        ——章節標題文字要用 line.name 這種明確欄位才可靠，group.label 只是方便值。
        """
        eval_group = self._eval_for(record, extra={'group': group})
        header = group.get('header')
        eval_header = self._eval_for(header, extra={'line': header}) if header else None
        for cell in (row.get('tdList') or []):
            if not isinstance(cell, dict):
                continue
            values = cell.get('value')
            if not isinstance(values, list):
                continue
            keep = []
            for el in values:
                meta = self._element_field_meta(el)
                src = (meta.get('source') or '').strip() if meta else ''
                if src in (self._GROUP_HEADER_SOURCE,
                           self._GROUP_FOOTER_SOURCE,
                           self._GROUP_VALUE_SOURCE):
                    if meta.get('isMarker'):
                        # 宣告用的標記藥丸（「分組標題列」字樣）不進成品
                        continue
                    expression = (meta.get('expression') or '').strip()
                    el['value'] = eval_group(expression) if expression else ''
                    meta['frozenAt'] = stamp
                elif src == self._LINE_SOURCE:
                    expression = self._field_meta_expression(meta)
                    el['value'] = (
                        eval_header(expression)
                        if (eval_header and expression) else ''
                    )
                    meta['frozenAt'] = stamp
                keep.append(el)
            cell['value'] = keep

    def _pick_row_variant(self, variants, line):
        """依列型條件挑出這筆明細該用哪一個列模板。

        對應原生報表在迴圈裡的 t-if / t-elif / t-else（sale 的
        ir_actions_report_templates.xml:130,137 —— 商品列／章節列／備註列
        各自不同版面，而且必須保持原本的交錯順序）。

        規則：
          1. 依文件順序，第一個「列型條件成立」的列型勝出
          2. 都不成立 → 第一個「沒有列型條件」的列型（相當於 t-else）
          3. 連那個都沒有 → 第一個列型（寧可多印，不要靜默漏印）

        刻意不用單純的「第一個符合就勝出」（留空＝一律符合）：那會迫使使用者
        把新加的列型搬到主要列上面去，否則永遠不會生效——而「加了設定卻沒反應」
        是最難自己看出來的一種錯。有條件的優先、無條件的當 else，加列型就不必
        搬動任何東西。

        用 _try_eval_condition 而不是 _eval_condition：壞掉的列型條件應該
        「不要攔截」這筆明細，讓它落到 else；若沿用「失敗當真」，一個寫壞的
        條件會把所有明細都吃進那個列型。
        """
        fallback = None
        for item in variants:
            expr = (item[1].get('rowFilter') or '').strip()
            if not expr:
                if fallback is None:
                    fallback = item
                continue
            if self._try_eval_condition(expr, line, extra={'line': line}) is True:
                return item
        return fallback if fallback is not None else variants[0]

    def _expand_repeat_rows(self, tree, record):
        """把重複列展開成每筆明細一列（就地改寫 tree）。回傳展開的列數。

        零筆明細時整列移除——留一列空白會在單據上印出一條空的表格列，
        看起來像資料掉了。整個表格只剩空的 trList 時由 _drop_empty_tables 收尾。

        輸出順序固定為 分組標題 → 明細 → 分組小計，不管使用者把模板列放在
        表格的哪裡。理由：那是唯一說得通的語意，而要求使用者把三列排對順序
        只會製造一種「看起來沒錯但印出來順序不對」的錯誤。

        同一個 repeatId 可以有多個重複列（列型）：來源／篩選／分組一律取
        **第一個**的設定，其餘只貢獻自己的 rowFilter 與版面。否則兩個列型
        各設一個不同的 path，結果會是哪個生效取決於列的先後——那種不確定性
        在範本裡完全看不出來。
        """
        import copy as _copy
        if not tree or record is None:
            return 0
        stamp = fields.Datetime.to_string(fields.Datetime.now())
        total = 0

        for table in self._iter_tables(tree):
            rows = table.get('trList') or []
            # 先把分組標題／小計列抽出來當模板（依 repeatId 歸戶）
            templates = {'header': {}, 'footer': {}}
            body_rows = []
            for row in rows:
                _el, g_meta, role = self._row_group_meta(row)
                if role:
                    rid = (g_meta.get('repeatId') or '').strip()
                    templates[role].setdefault(rid, row)
                    continue
                body_rows.append(row)
            changed = bool(templates['header'] or templates['footer'])

            # 重複列依 repeatId 歸戶成「列型」清單，保留文件順序。
            # 沒帶 repeatId 的各自成一組（以列物件的 id() 當鍵），維持舊行為。
            variants = {}
            order = []
            for row in body_rows:
                marker_el, meta = self._row_repeat_meta(row)
                if not marker_el:
                    continue
                rid = (meta.get('repeatId') or '').strip() or 'anon-%d' % id(row)
                if rid not in variants:
                    variants[rid] = []
                    order.append(rid)
                variants[rid].append((row, meta, len(variants[rid])))

            expanded = set()
            new_rows = []
            for row in body_rows:
                marker_el, meta = self._row_repeat_meta(row)
                if not marker_el:
                    new_rows.append(row)
                    continue
                rid = (meta.get('repeatId') or '').strip() or 'anon-%d' % id(row)
                if rid in expanded:
                    # 同一組的其他列型只是模板，不在原位輸出
                    continue
                expanded.add(rid)
                changed = True
                group_of = variants[rid]
                primary_meta = group_of[0][1]

                hdr_tmpl = templates['header'].get(rid)
                ftr_tmpl = templates['footer'].get(rid)
                if rid:
                    # 分組列沒帶 repeatId（單一重複列時前端可省）也要能配對
                    hdr_tmpl = hdr_tmpl or templates['header'].get('')
                    ftr_tmpl = ftr_tmpl or templates['footer'].get('')

                groups = self._resolve_repeat_groups(record, primary_meta)
                state_bank = {'never': {}, 'group': {}}
                for group in groups:
                    state_bank['group'] = {}
                    if hdr_tmpl is not None:
                        clone = _copy.deepcopy(hdr_tmpl)
                        clone.pop('id', None)
                        self._fill_group_row(clone, group, record, stamp)
                        new_rows.append(clone)
                    for idx, line in enumerate(group['lines']):
                        tmpl, _m, v_idx = self._pick_row_variant(group_of, line)
                        clone = _copy.deepcopy(tmpl)
                        clone.pop('id', None)
                        loop = self._loop_context(idx, len(group['lines']))
                        self._fill_line_row(
                            clone, line, marker_el, stamp, state_bank,
                            variant=v_idx, loop=loop,
                        )
                        if not self._resolve_line_row_conditions(
                                clone, record, line, loop):
                            continue
                        # 條件式格式要逐筆算：原生的
                        # t-att-class="'fw-bold' if line.display_type == …"
                        # 就是每一列各自判斷
                        self._resolve_format_markers(clone, record, line, loop)
                        new_rows.append(clone)
                        total += 1
                    if ftr_tmpl is not None:
                        clone = _copy.deepcopy(ftr_tmpl)
                        clone.pop('id', None)
                        self._fill_group_row(clone, group, record, stamp)
                        new_rows.append(clone)
            if changed:
                table['trList'] = new_rows
        return total

    def _resolve_line_row_conditions(self, row, record, line, loop=None):
        """重複列內的條件標記：以該筆明細求值，不成立就整列不輸出。

        為什麼要在展開階段處理，而不是交給後面的 _apply_row_conditions：
        那一關只有 object 可用（_condition_marker_result 不帶 line），
        所以同一個條件在每一列都得到同一個答案——要嘛全留要嘛全刪。
        而原生報表裡「逐列條件」很常見（發票的付款列
        <tr t-if="payment_vals['is_exchange'] == 0">），那種一定得逐筆判斷。

        若／否則配對（groupId）不在這裡處理：它的另一半在別的列上，
        展開階段看不到，留給 _apply_row_conditions。
        """
        def _plain_markers(cell):
            out = []
            for el in (cell.get('value') or []):
                meta = self._element_condition_meta(el)
                if meta and not (meta.get('groupId') or '').strip():
                    out.append((el, meta))
            return out

        cells = [c for c in (row.get('tdList') or []) if isinstance(c, dict)]
        found = [(el, meta) for cell in cells for el, meta in _plain_markers(cell)]
        # 巢狀表格（轉換器把「列內的條件」做成條件區塊）裡的條件，也要以
        # 這筆明細求值。交給後面那一關的話那裡只有 object，帶 line 的條件
        # 求值失敗 → 當成真 → 條件靜默失效。
        for cell in cells:
            for el in (cell.get('value') or []):
                if isinstance(el, dict) and (el.get('type') or '') == 'table':
                    self._resolve_nested_conditions(el, record, line, loop)
        if not found:
            return True
        extra = dict(loop or {})
        extra['line'] = line
        for _el, meta in found:
            expr = meta.get('expression') or meta.get('path') or ''
            # _eval_condition 求值失敗回 True（寧可多印），所以只在明確為
            # False 時才丟掉這一列。
            if self._eval_condition(expr, record, extra=extra) is False:
                return False
        # 條件成立 → 把標記清掉。不清的話後面那一關會用「只有 object」的
        # 環境再判一次，帶 line 的條件在那裡求值失敗 → 當成真 → 看起來沒事，
        # 但條件其實從此沒有作用。
        ids = {id(el) for el, _m in found}
        for cell in cells:
            if isinstance(cell.get('value'), list):
                cell['value'] = [el for el in cell['value']
                                 if id(el) not in ids]
        return True

    def _resolve_nested_conditions(self, table, record, line, loop=None):
        """重複列裡的巢狀表格：逐列以該筆明細求值，不成立就移除那一列。"""
        kept = []
        for row in (table.get('trList') or []):
            if not isinstance(row, dict):
                continue
            keep = True
            markers = []
            for cell in (row.get('tdList') or []):
                if not isinstance(cell, dict):
                    continue
                for el in (cell.get('value') or []):
                    meta = self._element_condition_meta(el)
                    if meta and not (meta.get('groupId') or '').strip():
                        markers.append((el, meta))
                    elif isinstance(el, dict) and (el.get('type') or '') == 'table':
                        self._resolve_nested_conditions(el, record, line, loop)
            extra = dict(loop or {})
            extra['line'] = line
            for _el, meta in markers:
                expr = meta.get('expression') or meta.get('path') or ''
                if self._eval_condition(expr, record, extra=extra) is False:
                    keep = False
                    break
            if not keep:
                continue
            ids = {id(el) for el, _m in markers}
            for cell in (row.get('tdList') or []):
                if isinstance(cell, dict) and isinstance(cell.get('value'), list):
                    cell['value'] = [el for el in cell['value']
                                     if id(el) not in ids]
            kept.append(row)
        table['trList'] = kept

    def _count_repeat_rows(self, tree):
        """統計樹中的重複列數（給 UI 顯示「此範本有 N 個重複列」用）。"""
        if not tree:
            return 0
        count = 0
        for table in self._iter_tables(tree):
            for row in (table.get('trList') or []):
                if self._row_repeat_meta(row)[0]:
                    count += 1
        return count
    # Odoo 18 的鍵名（已實測）：
    #   頂層    has_tax_groups / base_amount_currency / tax_amount_currency /
    #           total_amount_currency
    #   小計    name / base_amount_currency / tax_amount_currency / tax_groups
    #   稅別    group_name / group_label / tax_amount_currency /
    #           display_base_amount_currency
    _TAX_PARTS = ('untaxed', 'groups', 'rounding', 'total')

    def _tax_totals_data(self, record, meta):
        path = (meta.get('path') or 'tax_totals').strip()
        data = self._traverse_path(record, path)
        return data if isinstance(data, dict) else {}

    def _fill_tax_row(self, row, values, stamp, currencies=None):
        """填一列稅額彙總。

        values 的形狀是 {'document': {...}, 'company': {...}}，每個藥丸依自己的
        currencyMode 取——對應原生發票的 document_tax_totals_company_currency_template
        （外幣發票同時印公司幣別）。兩種幣別的數字都在 tax_totals 裡，差別只是
        鍵名有沒有 _currency 後綴。

        金額預設走 format_amount（幣別符號 + 幣別小數位）而不是 ',.2f'：
        稅額彙總一定是金額，預設值應該直接可用。使用者給了 numberFormat
        才改用純數字格式。
        """
        currencies = currencies or {}
        for cell in (row.get('tdList') or []):
            if not isinstance(cell, dict):
                continue
            items = cell.get('value')
            if not isinstance(items, list):
                continue
            keep = []
            for el in items:
                meta = self._element_field_meta(el)
                src = (meta.get('source') or '').strip() if meta else ''
                if src == self._TAX_TOTALS_SOURCE:
                    if meta.get('isMarker'):
                        continue
                    mode = (meta.get('currencyMode') or 'document').strip()
                    if mode not in values:
                        mode = 'document'
                    bucket = values.get(mode) or {}
                    currency = currencies.get(mode)
                    field = (meta.get('field') or 'amount').strip()
                    raw = bucket.get(field)
                    if raw is None or raw is False:
                        el['value'] = ''
                    elif field == 'label':
                        el['value'] = str(raw)
                    else:
                        spec = (meta.get('numberFormat') or '').strip()
                        try:
                            amount = float(raw)
                        except (TypeError, ValueError):
                            el['value'] = str(raw)
                            meta['frozenAt'] = stamp
                            keep.append(el)
                            continue
                        if not spec and currency:
                            el['value'] = format_amount(
                                self.env, amount, currency,
                            )
                        else:
                            try:
                                el['value'] = format(amount, spec or ',.2f')
                            except (TypeError, ValueError):
                                el['value'] = str(raw)
                    meta['frozenAt'] = stamp
                keep.append(el)
            cell['value'] = keep

    def _expand_tax_totals_rows(self, tree, record):
        """展開稅額彙總區塊：稅別列依稅別數複製，稅前小計／總計列原地填值。

        刻意不要求表格帶 dobtorBlock='taxTotals'——標記藥丸在哪裡就在哪裡展開。
        區塊標記只負責「輸出時不印框線」，兩件事分開，使用者把標記貼到別的
        表格裡時也還是會動，而不是靜默不生效。
        """
        import copy as _copy
        if not tree or record is None:
            return 0
        stamp = fields.Datetime.to_string(fields.Datetime.now())
        count = 0

        for table in self._iter_tables(tree):
            rows = table.get('trList') or []
            if not any(self._row_tax_totals_meta(r)[1] for r in rows):
                continue
            new_rows = []
            for row in rows:
                _el, meta = self._row_tax_totals_meta(row)
                if not meta:
                    new_rows.append(row)
                    continue
                data = self._tax_totals_data(record, meta)
                # tax_totals 帶的是 currency_id / company_currency_id
                # （整數 id，不是 recordset）
                currencies = {
                    'document': self._resolve_currency(
                        record, data.get('currency_id'),
                    ),
                    'company': self._resolve_currency(
                        record, data.get('company_currency_id'),
                    ),
                }
                part = (meta.get('part') or 'total').strip()
                if part not in self._TAX_PARTS:
                    part = 'total'
                if part == 'untaxed':
                    # 原生是 for subtotal in tax_totals['subtotals']——
                    # 多個稅基時（含稅與未稅混用）會有好幾列小計。
                    # 原本只取 subtotals[0]，那時後面幾列整個不見。
                    for sub in (data.get('subtotals') or []):
                        clone = _copy.deepcopy(row)
                        clone.pop('id', None)
                        self._fill_tax_row(clone, {
                            'document': {
                                'label': sub.get('name') or '',
                                'amount': sub.get('base_amount_currency'),
                                'base': sub.get('base_amount_currency'),
                            },
                            'company': {
                                'label': sub.get('name') or '',
                                'amount': sub.get('base_amount'),
                                'base': sub.get('base_amount'),
                            },
                        }, stamp, currencies)
                        new_rows.append(clone)
                        count += 1
                elif part == 'rounding':
                    # 現金捨入列：沒設定現金捨入時 tax_totals 裡沒有這個鍵，
                    # 那一列就不該出現（與零稅別時稅別列消失同一個規則）
                    if 'cash_rounding_base_amount_currency' in data:
                        self._fill_tax_row(row, {
                            'document': {
                                'label': '',
                                'amount': data.get(
                                    'cash_rounding_base_amount_currency'),
                                'base': data.get(
                                    'cash_rounding_base_amount_currency'),
                            },
                            'company': {
                                'label': '',
                                'amount': data.get(
                                    'cash_rounding_base_amount'),
                                'base': data.get('cash_rounding_base_amount'),
                            },
                        }, stamp, currencies)
                        new_rows.append(row)
                        count += 1
                elif part == 'groups':
                    # 零稅別時整列消失——印一列 0 元的稅額比不印更容易被誤讀
                    for sub in (data.get('subtotals') or []):
                        for grp in (sub.get('tax_groups') or []):
                            clone = _copy.deepcopy(row)
                            clone.pop('id', None)
                            label = (grp.get('group_label')
                                     or grp.get('group_name') or '')
                            self._fill_tax_row(clone, {
                                'document': {
                                    'label': label,
                                    'amount': grp.get('tax_amount_currency'),
                                    'base': grp.get(
                                        'display_base_amount_currency',
                                        grp.get('base_amount_currency'),
                                    ),
                                },
                                'company': {
                                    'label': label,
                                    'amount': grp.get('tax_amount'),
                                    'base': grp.get(
                                        'display_base_amount',
                                        grp.get('base_amount'),
                                    ),
                                },
                            }, stamp, currencies)
                            new_rows.append(clone)
                            count += 1
                else:
                    self._fill_tax_row(row, {
                        'document': {
                            'label': '',
                            'amount': data.get('total_amount_currency'),
                            'base': data.get('base_amount_currency'),
                        },
                        'company': {
                            'label': '',
                            'amount': data.get('total_amount'),
                            'base': data.get('base_amount'),
                        },
                    }, stamp, currencies)
                    new_rows.append(row)
                    count += 1
            table['trList'] = new_rows
        return count
    _FORMAT_KEYS = ('bold', 'italic', 'underline', 'strikeout',
                    'color', 'highlight', 'size', 'font')

    def _format_style(self, meta):
        """標記上要套用的屬性（不含對齊）。"""
        return {key: meta[key] for key in self._FORMAT_KEYS
                if meta.get(key) not in (None, '', False)}

    def _apply_format_to(self, elements, meta, align_on=None):
        """把格式套到一串元素上（表格元素不碰，它自己的格子會各自處理）。

        align_on 是「段落結尾的那個換行元素」——對齊掛在它身上
        （_elements_to_html 讀它的 rowFlex）。段落區間不含那個換行，
        所以要另外傳進來。
        """
        style = self._format_style(meta)
        align = (meta.get('align') or '').strip()
        for el in elements:
            if not isinstance(el, dict):
                continue
            if self._element_format_meta(el):
                continue
            if (el.get('type') or '') == 'table':
                continue
            if style:
                el.update(style)
            if align and (el.get('value') or '') == '\n':
                el['rowFlex'] = align
        if align and isinstance(align_on, dict):
            align_on['rowFlex'] = align

    def _resolve_format_markers(self, row, record, line=None, loop=None):
        """表格列裡的條件式格式標記：成立就套用到整列，然後移除標記。"""
        cells = [c for c in (row.get('tdList') or []) if isinstance(c, dict)]
        found = [(el, meta) for cell in cells
                 for el in (cell.get('value') or [])
                 for meta in [self._element_format_meta(el)] if meta]
        if not found:
            return
        extra = dict(loop or {})
        if line is not None:
            extra['line'] = line
        for _el, meta in found:
            expression = (meta.get('expression') or '').strip()
            # 格式的失敗策略與條件相反：算不出來就不套用
            if expression and self._try_eval_condition(
                    expression, record, extra) is not True:
                continue
            for cell in cells:
                self._apply_format_to(cell.get('value') or [], meta)
        ids = {id(el) for el, _m in found}
        for cell in cells:
            if isinstance(cell.get('value'), list):
                cell['value'] = [el for el in cell['value']
                                 if id(el) not in ids]

    def _apply_format_markers(self, tree, record):
        """重複列以外的條件式格式：表格列套整列、段落套整段。"""
        if not tree:
            return 0
        count = 0
        for table in self._iter_tables(tree):
            for row in (table.get('trList') or []):
                if isinstance(row, dict):
                    before = sum(len(c.get('value') or [])
                                 for c in (row.get('tdList') or [])
                                 if isinstance(c, dict))
                    self._resolve_format_markers(row, record)
                    after = sum(len(c.get('value') or [])
                                for c in (row.get('tdList') or [])
                                if isinstance(c, dict))
                    if after != before:
                        count += 1
        for elements in self._iter_element_lists(tree):
            for span in reversed(self._iter_paragraph_spans(elements)):
                start, end, _nl = span
                markers = [(elements[i], self._element_format_meta(elements[i]))
                           for i in range(start, end)
                           if self._element_format_meta(elements[i])]
                if not markers:
                    continue
                nl = elements[_nl] if _nl is not None and _nl < len(
                    elements) else None
                for _el, meta in markers:
                    expression = (meta.get('expression') or '').strip()
                    if expression and self._try_eval_condition(
                            expression, record) is not True:
                        continue
                    self._apply_format_to(elements[start:end], meta,
                                          align_on=nl)
                ids = {id(el) for el, _m in markers}
                elements[start:end] = [el for el in elements[start:end]
                                       if id(el) not in ids]
                count += 1
        return count

    # ─── if / else 配對 ──────────────────────────────────────────────
    #
    # 兩個標記共用一個 groupId；else 那個不帶自己的表達式，求值時取同群 if
    # 的反值。這樣只有一處表達式要維護。
    #
    # 為什麼不讓使用者自己放兩段互補條件（這是改版前的建議作法）：
    #   改一個忘了改另一個時，結果是兩段都印或兩段都不印，而且不會報錯。
    #   二擇一的語意本來就該由程式保證互斥，不該靠使用者維護兩份真值表。
    #
    # 刻意不做 elif 鏈：三擇一以上在單據上極少見，而鏈結的中斷（使用者刪掉
    # 中間那段）會讓剩下的分支語意靜默改變。需要多擇一就用多張範本由
    # doc.report 依 lang / company 挑。

    def _condition_group_results(self, tree, record):
        """先求出每個條件群組的 if 結果：{groupId: bool}。

        同群有多個 if 標記時只採第一個——群組的定義是「一個條件、兩個分支」，
        第二個 if 是使用者複製貼上造成的，採第一個比較接近他的意圖。
        """
        results = {}
        for element in self._iter_elements(tree):
            meta = self._element_condition_meta(element)
            if not meta:
                continue
            gid = (meta.get('groupId') or '').strip()
            if not gid or (meta.get('role') or 'if') == 'else':
                continue
            if gid in results:
                continue
            results[gid] = self._eval_condition(
                meta.get('expression') or meta.get('path') or '', record,
            )
        return results

    def _condition_marker_result(self, meta, record, group_results):
        """單一條件標記要不要保留。"""
        gid = (meta.get('groupId') or '').strip()
        if gid and (meta.get('role') or 'if') == 'else':
            if gid not in group_results:
                # 配對的 if 被刪掉了 → 當成恆真。與 _eval_condition 的失敗
                # 策略一致：寧可多印也不要靜默少印。
                return True
            return not group_results[gid]
        if gid and gid in group_results:
            return group_results[gid]
        return self._eval_condition(
            meta.get('expression') or meta.get('path') or '', record,
        )

    # ─── ② 明確條件 ──────────────────────────────────────────────────

    def _apply_paragraph_conditions(self, tree, record, group_results=None):
        """處理段落層級的 condition 標記：條件為假整段移除，為真則移除標記本身。"""
        removed = 0
        if group_results is None:
            group_results = self._condition_group_results(tree, record)
        for elements in self._iter_element_lists(tree):
            # 由後往前刪，避免索引位移
            for span in reversed(self._iter_paragraph_spans(elements)):
                start, end, _nl = span
                markers = [
                    (i, self._element_condition_meta(elements[i]))
                    for i in range(start, end)
                ]
                markers = [(i, m) for i, m in markers if m]
                if not markers:
                    continue
                keep = all(
                    self._condition_marker_result(m, record, group_results)
                    for _i, m in markers
                )
                if not keep:
                    self._drop_span(elements, span)
                    removed += 1
                else:
                    # 條件成立：標記藥丸是宣告不是內容，不留在成品裡
                    for i, _m in reversed(markers):
                        del elements[i]
        return removed

    def _apply_row_conditions(self, tree, record, group_results=None):
        """處理表格列層級的 condition 標記。"""
        removed = 0
        if group_results is None:
            group_results = self._condition_group_results(tree, record)
        for table in self._iter_tables(tree):
            rows = table.get('trList') or []
            kept = []
            for row in rows:
                markers = []
                for cell in (row.get('tdList') or []):
                    if not isinstance(cell, dict):
                        continue
                    for el in (cell.get('value') or []):
                        m = self._element_condition_meta(el)
                        if m:
                            markers.append(m)
                if not markers:
                    kept.append(row)
                    continue
                keep = all(
                    self._condition_marker_result(m, record, group_results)
                    for m in markers
                )
                if not keep:
                    removed += 1
                    continue
                # 條件成立：清掉標記藥丸
                for cell in (row.get('tdList') or []):
                    if isinstance(cell, dict) and isinstance(cell.get('value'), list):
                        cell['value'] = [
                            el for el in cell['value']
                            if not self._element_condition_meta(el)
                        ]
                kept.append(row)
            if removed:
                table['trList'] = kept
        return removed

    def _column_condition_markers(self, table):
        """回傳 [(欄索引, meta)]。欄索引以 colspan 累加算出。"""
        found = []
        for row in (table.get('trList') or []):
            if not isinstance(row, dict):
                continue
            col = 0
            for cell in (row.get('tdList') or []):
                if not isinstance(cell, dict):
                    continue
                span = max(1, int(cell.get('colspan') or 1))
                for el in (cell.get('value') or []):
                    meta = self._element_field_meta(el)
                    if meta and (meta.get('source') or '') == self._COLUMN_SOURCE:
                        found.append((col, meta))
                col += span
        return found

    def _strip_column_markers(self, table):
        """清掉表格內所有欄條件標記（宣告不是內容）。"""
        for row in (table.get('trList') or []):
            for cell in (row.get('tdList') or []):
                if not isinstance(cell, dict):
                    continue
                items = cell.get('value')
                if not isinstance(items, list):
                    continue
                cell['value'] = [
                    el for el in items
                    if ((self._element_field_meta(el) or {}).get('source') or '')
                    != self._COLUMN_SOURCE
                ]

    def _drop_column(self, table, target):
        """移除第 target 欄（含 colgroup）。

        跨欄的格子不刪，改成 colspan 減一——那一格橫跨多欄（例如小計列的
        「小計」標題），整格刪掉會讓該列少一欄，表格對不齊。
        """
        for row in (table.get('trList') or []):
            if not isinstance(row, dict):
                continue
            col = 0
            keep = []
            for cell in (row.get('tdList') or []):
                if not isinstance(cell, dict):
                    keep.append(cell)
                    continue
                span = max(1, int(cell.get('colspan') or 1))
                if col <= target < col + span:
                    if span > 1:
                        cell['colspan'] = span - 1
                        keep.append(cell)
                else:
                    keep.append(cell)
                col += span
            row['tdList'] = keep
        cg = table.get('colgroup')
        if isinstance(cg, list) and 0 <= target < len(cg):
            removed = cg.pop(target)
            # 被移除的寬度補給最後一欄，表格總寬維持不變——否則刪一欄
            # 整張表就縮一截，使用者會以為版面壞了
            if cg and isinstance(removed, dict) and removed.get('width'):
                last = cg[-1]
                if isinstance(last, dict) and last.get('width'):
                    last['width'] = last['width'] + removed['width']

    def _apply_column_conditions(self, tree, record, group_results=None):
        """處理欄層級的 condition 標記。"""
        removed = 0
        if group_results is None:
            group_results = self._condition_group_results(tree, record)
        for table in self._iter_tables(tree):
            markers = self._column_condition_markers(table)
            if not markers:
                continue
            drops = {
                col for col, meta in markers
                if not self._condition_marker_result(meta, record, group_results)
            }
            # 由右往左刪，避免索引位移
            for col in sorted(drops, reverse=True):
                self._drop_column(table, col)
                removed += 1
            self._strip_column_markers(table)
        return removed

    # ─── ① 自動收合空段落（規則 A）─────────────────────────────────────

    def _collapse_empty_paragraphs(self, tree):
        """段落內含藥丸且所有藥丸求值皆為空 → 整段移除（含靜態標籤）。

        規則 A（已定案）：「客戶統編：」這類標籤會連著一起消失，否則沒統編的
        單據上會留一個孤零零的標籤，那是最常見的難看問題。

        退出方式：任一藥丸的 meta 帶 keepEmpty=True 時該段不收合——
        給「重要靜態文字配一個可選藥丸」那種少數情況用。

        必須在純量求值之後跑：要有值才知道是不是空的。
        """
        removed = 0
        for elements in self._iter_element_lists(tree):
            for span in reversed(self._iter_paragraph_spans(elements)):
                start, end, _nl = span
                pills = []
                for i in range(start, end):
                    meta = self._element_field_meta(elements[i])
                    if meta:
                        pills.append((elements[i], meta))
                if not pills:
                    continue
                if any(m.get('keepEmpty') for _el, m in pills):
                    continue
                # 段落裡有表格就不收合。表格是獨立的區塊容器（條件區塊、
                # 巢狀的重複清單），它的內容跟同段落那幾顆藥丸沒有關係。
                # 段落邊界只認 value == '\n'，而表格元素的 value 是空字串，
                # 所以它會被算進同一段——實測到的後果是發票的分期清單被旁邊
                # 求值為空的「提前付款折扣」藥丸連帶整段刪掉。
                if any((elements[i].get('type') or '') == 'table'
                       for i in range(start, end)):
                    continue
                if all(not (el.get('value') or '').strip() for el, _m in pills):
                    self._drop_span(elements, span)
                    removed += 1
        return removed
