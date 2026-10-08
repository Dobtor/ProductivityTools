"""RenderI18n — 多語文字工具。

把範本裡的靜態文字抽成多語藥丸、匯出／匯入 CSV。

沒有這組工具，i18n 藥丸不會被用起來：沒人會回頭把一張做好的中文範本裡
幾十段文字一個一個改成藥丸，也沒人會為了翻譯讓譯者登入 Odoo。
"""
import csv
import io
import json


class RenderI18n:

    def extract_static_texts(self):
        """列出範本裡的靜態文字（給「抽出靜態文字」面板用）。

        回傳 [{'text', 'count'}]，依出現次數遞減。同一段文字出現多次時只列
        一筆——使用者勾一次就全部轉換，不必一段一段找。
        """
        self.ensure_one()
        tree = self._parse_content_json(self.content_json)
        if tree is None:
            return []
        counts = {}
        for _els, _s, _e, text in self._iter_text_runs(tree):
            key = text.strip()
            counts[key] = counts.get(key, 0) + 1
        return [
            {'text': t, 'count': c}
            for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    def convert_texts_to_i18n(self, texts, lang=None):
        """把指定的靜態文字轉成 i18n 藥丸（就地改寫 content_json）。

        轉換時把當前語言填進 texts，其他語言留空——留空的語言在渲染時會
        fallback 到有值的那個，所以半成品狀態下單據仍然印得出字。
        """
        self.ensure_one()
        if not texts:
            return {'converted': 0}
        wanted = {t.strip() for t in texts if (t or '').strip()}
        lang = lang or self.env.context.get('lang') or 'en_US'
        tree = self._parse_content_json(self.content_json)
        if tree is None:
            return {'converted': 0}

        converted = 0
        # 由後往前改寫：run 的索引會因替換而位移
        for elements, start, end, text in reversed(list(
                self._iter_text_runs(tree))):
            key = text.strip()
            if key not in wanted:
                continue
            # 保留第一個元素的字型樣式——轉成藥丸不該順手改掉字級與顏色
            base = {
                k: v for k, v in elements[start].items()
                if k in ('font', 'size', 'bold', 'italic', 'color',
                         'underline', 'strikeout', 'rowFlex')
            }
            pill = dict(base)
            pill.update({
                'type': 'label',
                'value': key,
                'label': {'backgroundColor': '#fff3e0', 'color': '#e65100'},
                'extension': {self.DOBTOR_FIELD_KEY: {
                    'source': self._I18N_SOURCE,
                    'labelText': key,
                    'texts': {lang: key},
                }},
            })
            elements[start:end] = [pill]
            converted += 1

        if converted:
            self.content_json = json.dumps(tree, ensure_ascii=False)
        return {'converted': converted}

    def i18n_entries(self):
        """範本裡所有 i18n 藥丸的翻譯表：[{'key', 'texts'}]。"""
        self.ensure_one()
        tree = self._parse_content_json(self.content_json)
        if tree is None:
            return []
        out = []
        seen = set()
        for element in self._iter_elements(tree):
            meta = self._element_field_meta(element)
            if not meta or (meta.get('source') or '') != self._I18N_SOURCE:
                continue
            texts = meta.get('texts') if isinstance(meta.get('texts'), dict) else {}
            key = (meta.get('key') or '').strip() or (meta.get('labelText') or '')
            if key in seen:
                continue
            seen.add(key)
            out.append({'key': key, 'texts': texts})
        return out

    def export_i18n_csv(self, langs=None):
        """翻譯表 → CSV 字串（第一欄是 key，其餘每欄一個語言）。"""
        self.ensure_one()
        entries = self.i18n_entries()
        langs = list(langs or [])
        if not langs:
            # 已安裝語言優先（維持 Odoo 的排序），再補上範本裡出現過但尚未
            # 安裝的語言——不補的話那些既有翻譯會在一次匯出匯入後消失
            found = set()
            for entry in entries:
                found |= set(entry['texts'].keys())
            installed = self.env['res.lang'].search([]).mapped('code')
            langs = installed + sorted(found - set(installed))
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['key'] + langs)
        for entry in entries:
            writer.writerow(
                [entry['key']] + [entry['texts'].get(c, '') for c in langs]
            )
        return buf.getvalue()

    def import_i18n_csv(self, content):
        """CSV → 回填各 i18n 藥丸的 texts。

        以 key 比對，找不到的 key 列在 unknown 回傳——靜默忽略的話，譯者改錯
        一個 key，使用者只會看到「翻譯沒進去」而查不出原因。
        """
        self.ensure_one()
        if not content:
            return {'updated': 0, 'pills': 0, 'unknown': []}
        reader = csv.reader(io.StringIO(content))
        try:
            header = next(reader)
        except StopIteration:
            return {'updated': 0, 'pills': 0, 'unknown': []}
        langs = [c.strip() for c in header[1:]]
        table = {}
        for row in reader:
            if not row or not (row[0] or '').strip():
                continue
            table[row[0].strip()] = {
                langs[i]: (row[i + 1] or '').strip()
                for i in range(min(len(langs), len(row) - 1))
                if langs[i]
            }

        tree = self._parse_content_json(self.content_json)
        if tree is None:
            return {'updated': 0, 'unknown': sorted(table)}

        pills = 0
        hit = set()
        for element in self._iter_elements(tree):
            meta = self._element_field_meta(element)
            if not meta or (meta.get('source') or '') != self._I18N_SOURCE:
                continue
            key = (meta.get('key') or '').strip() or (meta.get('labelText') or '')
            incoming = table.get(key)
            if not incoming:
                continue
            texts = dict(meta.get('texts') or {})
            texts.update({k: v for k, v in incoming.items() if v})
            meta['texts'] = texts
            hit.add(key)
            pills += 1

        if pills:
            self.content_json = json.dumps(tree, ensure_ascii=False)
        # updated 計 key 數而不是藥丸數：同一段文字在範本裡出現兩次就有兩個
        # 藥丸，回報「2」會跟譯者手上 CSV 的 1 列對不上，看起來像多塞了東西。
        # 藥丸數另外回報給需要的人。
        return {
            'updated': len(hit),
            'pills': pills,
            'unknown': sorted(set(table) - hit),
        }

    def _render_lang(self, record):
        """這份文件該用哪個語言渲染。

        順序：呼叫端明確指定（doc.report.lang）→ 記錄的客戶語言 → session。
        綁定上特地設了語言就該聽它（「印給英國客戶的英文版」），沒設則跟隨
        客戶——與原生報表一致（sale 的範本第 5 行就是
        doc.with_context(lang=doc.partner_id.lang)）。
        """
        explicit = self.env.context.get('doc_render_lang')
        if explicit:
            return explicit
        if record is not None and hasattr(record, '_fields'):
            for path in ('partner_id', 'partner_shipping_id'):
                if path in record._fields:
                    try:
                        partner = record[path]
                    except Exception:
                        continue
                    if partner and partner[:1].lang:
                        return partner[:1].lang
        return self.env.context.get('lang')

    def _record_in_lang(self, record, lang=None):
        """把記錄換到渲染語言的 context。

        少了這一步的後果是靜默的：綁定上設了 zh_TW，data-oe-lang 會寫 zh_TW，
        但商品名稱、selection 標籤、付款條件全部印成操作者的語言。
        """
        if record is None:
            return record
        lang = lang or self._render_lang(record)
        if not lang or self.env.context.get('lang') == lang:
            return record
        try:
            return record.with_context(lang=lang)
        except Exception:
            return record

    def _i18n_text(self, record, meta):
        """i18n 藥丸的文字。

        Fallback 刻意不回空字串：空白在單據上看起來像資料掉了，而一個未翻譯
        的英文字串至少讀得懂。順序為 當前語言 → en_US → 第一個有值的 → 標籤文字。
        """
        texts = meta.get('texts')
        if not isinstance(texts, dict):
            texts = {}
        lang = (record.env.context.get('lang')
                if record is not None else None) or self.env.context.get('lang')
        for candidate in (lang, (lang or '').split('_')[0], 'en_US'):
            if candidate and texts.get(candidate):
                return texts[candidate]
        for value in texts.values():
            if value:
                return value
        return meta.get('labelText') or ''
