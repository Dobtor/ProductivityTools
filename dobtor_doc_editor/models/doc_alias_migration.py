"""Phase 5（藥丸改版）：把舊的 alias token 一次性遷移成自描述藥丸元素。

決策二選了一次性遷移，等於宣告 《中文 token》 與 {{ varname }} 的正則機制退場。
本模組是那支遷移的實作，同時提供 dry_run 供動工前評估。

為什麼不需要建立任何 doc.template.field 記錄：
    模型變數改為自描述元素，定義存在 extension.dobtorField。遷移只做元素置換，
    不碰後端欄位記錄，失敗的爆炸半徑因此小得多——最壞情況是元素沒換到，
    而不是建出一堆錯綁的欄位記錄。

已知限制（會列在報表裡，不會靜默）：
    token 若被樣式切斷（例如《客戶**名稱**》中間有粗體），canvas-editor 的
    getValue() 不會把它們合併成同一個 run，字串比對就找不到。這類 token 會
    留在原地、由退場期的正則路徑繼續處理，報表中列為 skipped_split。

用法：
    # 乾跑（不寫入，只回報）
    env['doc.alias.migration'].run(dry_run=True)
    # 實跑
    env['doc.alias.migration'].run(dry_run=False)
"""
import json
import logging
import re

from odoo import api, models

_logger = logging.getLogger(__name__)

# 與 doc_render_mixin.DOBTOR_FIELD_KEY 一致
DOBTOR_FIELD_KEY = 'dobtorField'

PILL_STYLE = {
    'backgroundColor': '#e3f2fd',
    'color': '#1976d2',
    'borderRadius': 4,
    'padding': [2, 6, 2, 6],
}

_TOKEN_RE = re.compile(r'《([^》]+)》')
_VAR_RE = re.compile(r'\{\{\s*([A-Za-z_]\w*)\s*\}\}')
_VAR_NAME_RE = re.compile(r'^[A-Za-z_]\w*$')
# 能還原成欄位路徑的表達式；其餘一律走 source='expression'
_PLAIN_PATH_RE = re.compile(r'^object\.([A-Za-z_][\w.]*)$')


class DocAliasMigration(models.AbstractModel):
    _name = 'doc.alias.migration'
    _description = 'alias token → 藥丸元素遷移'

    # ─── 綁定定義 ────────────────────────────────────────────────────

    @api.model
    def _meta_from_expression(self, expression, label_text):
        """alias 的 Jinja 表達式 → 綁定 meta。

        三類形態都要接住，否則「遷移看起來成功、但那些變數從此不帶值」——
        又是一個靜默失效。expression 這個逃生口存在的唯一理由就是這個。
        """
        expression = (expression or '').strip()
        if not expression:
            return None
        plain = _PLAIN_PATH_RE.match(expression)
        if plain:
            return {
                'source': 'record',
                'path': plain.group(1),
                'labelText': label_text,
            }
        return {
            'source': 'expression',
            'expression': expression,
            'labelText': label_text,
        }

    @api.model
    def _build_pill(self, meta):
        return {
            'type': 'label',
            'value': meta.get('labelText') or '',
            'label': dict(PILL_STYLE),
            'extension': {DOBTOR_FIELD_KEY: meta},
        }

    # ─── 元素置換 ────────────────────────────────────────────────────

    @api.model
    def _split_element(self, element, aliases):
        """把含 token 的文字元素拆成 [文字, 藥丸, 文字…]。

        沒有可替換的 token 時回 None（呼叫端保留原元素）。
        回傳的文字片段沿用原元素的所有樣式屬性，只換 value——
        否則被拆開的字會掉字型與顏色。
        """
        if not isinstance(element, dict):
            return None
        if element.get('type') and element['type'] != 'text':
            return None
        text = element.get('value') or ''
        if not text or text == '\n':
            return None

        token_map, var_map = aliases
        pieces = []
        cursor = 0

        # 一次掃描同時處理兩種語法，依出現位置排序，避免兩輪替換互相破壞
        matches = []
        for m in _TOKEN_RE.finditer(text):
            if m.group(1).strip() in token_map:
                matches.append((m.start(), m.end(), m.group(1).strip(), 'token'))
        for m in _VAR_RE.finditer(text):
            if m.group(1).strip() in var_map:
                matches.append((m.start(), m.end(), m.group(1).strip(), 'var'))
        if not matches:
            return None
        matches.sort(key=lambda x: x[0])

        base = {k: v for k, v in element.items()
                if k not in ('value', 'type', 'label', 'extension')}

        for start, end, key, kind in matches:
            if start < cursor:
                continue  # 重疊（理論上不會發生），保守跳過
            if start > cursor:
                pieces.append(dict(base, value=text[cursor:start]))
            expression = (token_map if kind == 'token' else var_map)[key]
            meta = self._meta_from_expression(expression, key)
            if meta:
                pieces.append(self._build_pill(meta))
            else:
                pieces.append(dict(base, value=text[start:end]))
            cursor = end
        if cursor < len(text):
            pieces.append(dict(base, value=text[cursor:]))
        return pieces or None

    @api.model
    def _convert_tree(self, tree, aliases, stats):
        """就地把樹中的 token 換成藥丸；回傳是否有改動。"""
        Mixin = self.env['doc.render.mixin']
        changed = False
        for elements in Mixin._iter_element_lists(tree):
            idx = 0
            while idx < len(elements):
                replacement = self._split_element(elements[idx], aliases)
                if replacement:
                    elements[idx:idx + 1] = replacement
                    pills = sum(1 for e in replacement if e.get('type') == 'label')
                    stats['pills_created'] += pills
                    idx += len(replacement)
                    changed = True
                else:
                    idx += 1
        return changed

    @api.model
    def _split_aliases(self, aliases):
        """alias dict → (中文 token map, 變數名 map)。"""
        token_map, var_map = {}, {}
        for key, expression in (aliases or {}).items():
            key = str(key).strip()
            expression = str(expression).strip()
            if not key or not expression:
                continue
            if _VAR_NAME_RE.match(key):
                var_map[key] = expression
            else:
                token_map[key] = expression
        return token_map, var_map

    @api.model
    def _count_remaining_tokens(self, tree, aliases):
        """統計仍留在文件中、但沒被換掉的 token（多半是被樣式切斷）。"""
        Mixin = self.env['doc.render.mixin']
        token_map, var_map = aliases
        remaining = 0
        for el in Mixin._iter_elements(tree):
            text = el.get('value') or ''
            if not text or el.get('type') == 'label':
                continue
            remaining += sum(1 for m in _TOKEN_RE.finditer(text)
                             if m.group(1).strip() in token_map)
            remaining += sum(1 for m in _VAR_RE.finditer(text)
                             if m.group(1).strip() in var_map)
        return remaining

    # ─── field_type='odoo_field' 舊記錄 ───────────────────────────────

    @api.model
    def _build_legacy_map(self):
        """全域收集 field_type='odoo_field' 的舊記錄。

        為什麼要「全域」而不是逐範本處理：這些欄位的 control 元素是插在
        **文件**的 content_json 裡（Phase 8 的流程是在編輯文件時建立範本欄位、
        把 control 插進該文件），不是插在範本裡。逐範本掃描會一個都找不到；
        而且同一個範本被多份文件使用時，處理完第一份就把記錄刪掉，
        後面的文件會失去對照。故先建全域 map、全部掃完再一次刪除。
        """
        legacy = self.env['doc.template.field'].search([
            ('field_type', '=', 'odoo_field'),
        ])
        mapping = {}
        for field in legacy:
            path = (field.odoo_field_name or '').strip()
            if not path:
                continue
            mapping[str(field.id)] = {
                'path': path,
                'labelText': (field.placeholder_text or path).strip(),
            }
        return legacy, mapping

    @api.model
    def _convert_legacy_controls(self, tree, legacy_map, matched, stats):
        """把舊 odoo_field 的 control 元素就地換成藥丸。回傳是否有改動。"""
        if not legacy_map or tree is None:
            return False
        Mixin = self.env['doc.render.mixin']
        changed = False
        for elements in Mixin._iter_element_lists(tree):
            for idx, el in enumerate(elements):
                if not isinstance(el, dict):
                    continue
                concept = (el.get('control') or {}).get('conceptId')
                if concept is None:
                    continue
                info = legacy_map.get(str(concept))
                if not info:
                    continue
                elements[idx] = self._build_pill({
                    'source': 'record',
                    'path': info['path'],
                    'labelText': info['labelText'],
                })
                matched.add(str(concept))
                stats['pills_created'] += 1
                changed = True
        return changed

    # ─── 主流程 ──────────────────────────────────────────────────────

    @api.model
    def run(self, dry_run=True, limit=None):
        """執行遷移（或乾跑）。回傳統計報表 dict。

        報表欄位：
            templates_scanned / documents_scanned  掃過幾筆
            records_changed                        實際會被改寫幾筆
            pills_created                          產生幾個藥丸
            expression_fallbacks                   落入 expression 類的 alias 數
            skipped_no_json                        只有 content_html、需開檔延遲升級
            skipped_split                          token 被樣式切斷、無法比對
            legacy_fields_converted / _orphaned    field_type='odoo_field' 舊記錄
        """
        stats = {
            'dry_run': dry_run,
            'templates_scanned': 0,
            'documents_scanned': 0,
            'records_changed': 0,
            'pills_created': 0,
            'expression_fallbacks': 0,
            'skipped_no_json': 0,
            'skipped_split': 0,
            'legacy_fields_converted': 0,
            'legacy_fields_orphaned': 0,
        }
        Mixin = self.env['doc.render.mixin']
        legacy_records, legacy_map = self._build_legacy_map()
        matched_legacy = set()

        def _process(record, own_aliases):
            tree = Mixin._parse_content_json(record.content_json)
            if tree is None:
                if own_aliases:
                    stats['skipped_no_json'] += 1
                return
            aliases = self._split_aliases(own_aliases)
            stats['expression_fallbacks'] += sum(
                1 for expr in own_aliases.values()
                if self._meta_from_expression(expr, '') and
                not _PLAIN_PATH_RE.match(str(expr).strip())
            )
            changed = self._convert_tree(tree, aliases, stats)
            # 舊 odoo_field control：範本與文件都要掃（元素通常在文件裡）
            if self._convert_legacy_controls(tree, legacy_map, matched_legacy, stats):
                changed = True
            stats['skipped_split'] += self._count_remaining_tokens(tree, aliases)
            if not changed:
                return
            stats['records_changed'] += 1
            if dry_run:
                return
            record.write({'content_json': json.dumps(tree, ensure_ascii=False)})

        templates = self.env['doc.template'].with_context(active_test=False).search(
            [], limit=limit,
        )
        for template in templates:
            stats['templates_scanned'] += 1
            _process(template, template.field_aliases or {})

        documents = self.env['doc.document'].search([], limit=limit)
        for doc in documents:
            stats['documents_scanned'] += 1
            # 文件同時繼承範本層 alias；自身的覆寫範本的（與 _collect_field_aliases 一致）
            merged = dict((doc.template_id.field_aliases or {}) if doc.template_id else {})
            merged.update(doc.field_aliases or {})
            _process(doc, merged)

        # 全部掃完才刪：同一批記錄可能被多份文件引用（見 _build_legacy_map 的說明）。
        # 找不到對應 control 的是孤兒——既有的孤兒清理機制已證實這類資料存在——
        # 一併回報並刪除。
        stats['legacy_fields_converted'] = len(matched_legacy)
        stats['legacy_fields_orphaned'] = len(legacy_records) - len(matched_legacy)
        if not dry_run and legacy_records:
            legacy_records.unlink()

        _logger.info('[doc.alias.migration] %s', stats)
        return stats
