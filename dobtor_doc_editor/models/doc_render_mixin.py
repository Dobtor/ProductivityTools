import html as html_mod
import json
import re

from jinja2.sandbox import SandboxedEnvironment

from odoo import models, api
from odoo.exceptions import UserError, AccessError


# 禁止透過屬性存取觸碰的 ORM 提權／IO 向量。
# SandboxedEnvironment 預設只擋「底線開頭」屬性（_cr、__class__、_fields…），
# 但 env/sudo/browse/search/write 等是公開 recordset 介面 → 預設放行，
# 等於任何有 doc write 權限的內部使用者可在範本寫
#   {{ object.env['res.users'].sudo().browse(1).write({...}) }}
# 以 sudo 跑任意 ORM。故額外黑名單封死這些公開向量。
_UNSAFE_ATTRS = frozenset({
    'env', 'sudo', 'with_user', 'with_env', 'with_company', 'with_context',
    'browse', 'search', 'search_read', 'search_count', 'read', 'read_group',
    'create', 'write', 'unlink', 'copy', 'load', 'fields_get', 'get_metadata',
    'pool', 'cr', 'registry',
})


class _DocSandboxedEnvironment(SandboxedEnvironment):
    """收斂版 Jinja sandbox：在預設防護上額外封死 ORM 提權／IO 公開屬性。

    範本只需欄位讀取（object.<field>、.display_name）與注入的 helper，
    因此把 env/sudo/browse/search/write… 一律視為 unsafe，
    阻止 {{ object.env[...].sudo()... }} 這類 SSTI 提權（非理論，低權編輯者即可觸發）。
    """

    def is_safe_attribute(self, obj, attr, value):
        if attr in _UNSAFE_ATTRS:
            return False
        return super().is_safe_attribute(obj, attr, value)


# 中文 token 標記符號。前後綴用《》（U+300A / U+300B），降低與正文衝突機率。
# 若 token 內含 》 會被 _ALIAS_PATTERN 提前終止，這是刻意行為（避免巢狀解析歧義）。
_ALIAS_PATTERN = re.compile(r'《([^》]+)》')

# 純變數名 Jinja 表達式（不含 object. 前綴的舊式變數）。
# 例：{{ project_name }} 會被當作可替換 token；{{ object.partner_id.name }} 不會（保留給 Jinja2）。
_VAR_NAME_RE = re.compile(r'^[A-Za-z_][\w]*$')
_JINJA_VARNAME_PATTERN = re.compile(r'\{\{\s*([A-Za-z_][\w]*)\s*\}\}')


class DocRenderMixin(models.AbstractModel):
    _name = 'doc.render.mixin'
    _description = '文件渲染 Mixin'

    def _render_template(self, html, record, with_chip=False):
        """使用 Jinja2 SandboxedEnvironment 渲染 {{ field }} 變數，防止 SSTI。

        渲染流程：
          1. 套用 field_aliases 把 《中文 token》 轉成 {{ expression }}
          2. Jinja2 SandboxedEnvironment 渲染（globals 帶 helper）

        參數 with_chip：
          True 時，把 alias 替換結果包進 <span class="doc-field-token">…</span>，
          讓預覽頁面可直觀辨識「這格是動態欄位」。匯出 PDF/DOCX 預設 False，
          避免 span 樣式干擾排版（doc-field-token 樣式在預覽 wrapper 內定義）。
        """
        if not html or not record:
            return html or ''
        try:
            html = self._apply_field_aliases(html, with_chip=with_chip)
            env = self._get_sandbox_env(record)
            template = env.from_string(html)
            return template.render(object=record, user=self.env.user)
        except Exception as e:
            return html  # 渲染失敗時回傳原始 HTML

    def _get_render_helpers(self, record):
        """回傳要注入 Jinja2 globals 的 helper 對映。

        子類別可覆寫加入更多 helper（例如格式化、權限相關 lookup）。
        helper 內避免直接暴露 _fields 等 sandboxed attribute，由本層代為呼叫。
        """
        def selection_label(fieldname):
            """回傳 Selection 欄位的人類可讀標籤；非 Selection 或空值回空字串。"""
            if not record or not fieldname:
                return ''
            field = record._fields.get(fieldname)
            if not field or field.type != 'selection':
                return ''
            selection = field._description_selection(record.env)
            value = record[fieldname]
            return dict(selection).get(value, value or '')

        def format_date(value, fmt='%Y-%m-%d'):
            """安全地格式化 date / datetime；None 與字串原樣回傳。"""
            if value is None or value is False:
                return ''
            if hasattr(value, 'strftime'):
                return value.strftime(fmt)
            return str(value)

        return {
            'selection_label': selection_label,
            'format_date': format_date,
        }

    def _apply_field_aliases(self, html, with_chip=False):
        """掃 html 把 alias 鍵替換成 Jinja2 expression。

        支援兩種 key 形式（同 dict）：
          1) 中文 token（含非 ASCII 字元）：對應文件內 《token》 替換。
          2) 純變數名（[A-Za-z_][\\w]*）：對應文件內 {{ varname }} 替換，
             方便沿用既有「{{ project_name }}」這類舊式範本而不需重寫。

        合併順序（後者覆寫前者）：template.field_aliases ← doc.field_aliases
        with_chip 為 True 時把替換結果包進 doc-field-token span。
        """
        aliases = self._collect_field_aliases()
        if not aliases or not html:
            return html

        # 拆成兩組（token / varname）以分別走兩條替換
        token_map = {}
        var_map = {}
        for key, expr in aliases.items():
            if not key or not expr:
                continue
            if _VAR_NAME_RE.match(key):
                var_map[key] = expr
            else:
                token_map[key] = expr

        def _wrap(expr, token):
            jinja = '{{ ' + expr + ' }}'
            if with_chip:
                return (
                    '<span class="doc-field-token" data-token="'
                    + (token or '').replace('"', '&quot;') + '">'
                    + jinja + '</span>'
                )
            return jinja

        if token_map:
            def _replace_token(m):
                tk = m.group(1).strip()
                expr = token_map.get(tk)
                if not expr:
                    return m.group(0)
                return _wrap(expr, tk)
            html = _ALIAS_PATTERN.sub(_replace_token, html)

        if var_map:
            def _replace_var(m):
                v = m.group(1).strip()
                expr = var_map.get(v)
                if not expr:
                    return m.group(0)
                return _wrap(expr, v)
            html = _JINJA_VARNAME_PATTERN.sub(_replace_var, html)

        return html

    def _collect_field_aliases(self):
        """合併 template 與自身的 alias map（自身覆寫 template）。

        Mixin 端用 _fields 防呆——非 doc.document/doc.template 呼叫時回空 dict。
        """
        merged = {}
        # 範本層級（doc.document 才有 template_id）
        if self._fields.get('template_id') and getattr(self, 'template_id', False):
            tmpl_aliases = getattr(self.template_id, 'field_aliases', None) or {}
            merged.update(tmpl_aliases)
        # 自身（doc.document.field_aliases 或 doc.template.field_aliases）
        if self._fields.get('field_aliases'):
            merged.update(getattr(self, 'field_aliases', None) or {})
        return merged

    def init_aliases_from_model_for(self, model_name, overwrite=False):
        """從給定 model_name 的欄位自動生成 alias，寫入 self.field_aliases。

        生成兩種 key（同個 dict）：
          1) 中文 token（field.field_description）→ 完整 expression
          2) 純變數名（field.name）→ 完整 expression — 沿用既有 {{ varname }} 也能渲染

        參數 overwrite：False=保留既有 token；True=整批以模型欄位重建。
        """
        self.ensure_one()
        if not self._fields.get('field_aliases'):
            return {'success': False, 'error': '此 model 沒有 field_aliases 欄位'}
        if not model_name or model_name not in self.env:
            return {'success': False, 'error': f"模型 '{model_name}' 不存在"}

        existing = dict(self.field_aliases or {})
        added = []
        skipped = []
        IrModelFields = self.env['ir.model.fields']
        ttypes = ('char', 'text', 'integer', 'float', 'monetary',
                  'date', 'datetime', 'boolean', 'selection', 'many2one')
        records = IrModelFields.search([
            ('model', '=', model_name),
            ('store', '=', True),
            ('ttype', 'in', list(ttypes)),
        ], order='field_description asc')

        def _expr_for(f):
            if f.ttype in ('date', 'datetime'):
                return f'format_date(object.{f.name})'
            if f.ttype == 'selection':
                return f"selection_label('{f.name}')"
            if f.ttype == 'many2one':
                return f'object.{f.name}.display_name'
            return f'object.{f.name}'

        for f in records:
            expr = _expr_for(f)
            label = (f.field_description or '').strip()
            # 中文 token alias
            if label:
                if label in existing and not overwrite:
                    skipped.append(label)
                else:
                    existing[label] = expr
                    added.append(label)
            # 純變數名 alias（同 expression）
            varname = f.name
            if varname in existing and not overwrite:
                skipped.append(varname)
            else:
                existing[varname] = expr
                added.append(varname)

        self.write({'field_aliases': existing})
        return {
            'success': True,
            'aliases': existing,
            'added': added,
            'skipped': skipped,
        }

    @api.model
    def get_available_fields(self, model_name, max_depth=2):
        """回傳指定 model 的可用欄位清單（含 Many2one 子欄位，深度限制 2）。"""
        if model_name not in self.env:
            raise UserError(f"模型 '{model_name}' 不存在")

        try:
            self.env[model_name].check_access('read')
        except AccessError:
            raise AccessError(f"您沒有讀取 '{model_name}' 的權限")

        return self._get_fields_for_model(model_name, max_depth=max_depth, current_depth=0)

    def _get_fields_for_model(self, model_name, max_depth=2, current_depth=0):
        """遞迴取得模型欄位，限制深度以防止無限遞迴。"""
        IrModelFields = self.env['ir.model.fields']
        fields = IrModelFields.search([
            ('model', '=', model_name),
            ('store', '=', True),
            ('ttype', 'in', [
                'char', 'text', 'integer', 'float', 'monetary',
                'date', 'datetime', 'boolean', 'selection', 'many2one',
            ]),
        ], order='field_description asc')

        result = []
        for f in fields:
            field_info = {
                'name': f.name,
                'label': f.field_description,
                'type': f.ttype,
                'expression': '{{{{ object.{} }}}}'.format(f.name),
            }
            # Many2one：若未達深度限制，遞迴取子欄位
            if f.ttype == 'many2one' and f.relation and current_depth < max_depth:
                if f.relation in self.env:
                    try:
                        self.env[f.relation].check_access('read')
                        field_info['relation'] = f.relation
                        field_info['sub_fields'] = self._get_fields_for_model(
                            f.relation, max_depth, current_depth + 1
                        )
                    except AccessError:
                        field_info['sub_fields'] = []
            result.append(field_info)
        return result

    # ══════════════════════════════════════════════════════════════════
    # Phase 3（藥丸改版）：content_json 為權威的快照 / 攤平管線
    #
    # 兩個動作，時間上徹底分離：
    #   _snapshot_content_json()  建立文件時求值一次，把值寫進藥丸，藥丸結構保留
    #   _flatten_content_json()   匯出時把藥丸攤平成純文字，不再求值
    #
    # 綁定定義存在元素的 extension.dobtorField（canvas-editor 的官方擴充點，
    # 且在其序列化白名單內），不存在可見文字裡，也不需要後端欄位記錄——
    # 見 security/ir.model.access.csv:25，一般編輯者對 doc.template.field 唯讀。
    # ══════════════════════════════════════════════════════════════════

    def _get_sandbox_env(self, record, undefined=None):
        """唯一的 Jinja 沙箱建構點。

        存在的理由：改版前 doc_controller.preview_content_json 自己 new 了一個
        裸 SandboxedEnvironment，繞過 _DocSandboxedEnvironment 的 ORM 提權黑名單
        （env / sudo / browse / write）。快照管線會執行來自舊 alias 遷移的任意
        Jinja 字串，絕不能重蹈覆轍。所有需要沙箱的地方一律呼叫這裡。
        """
        kwargs = {'undefined': undefined} if undefined is not None else {}
        env_j = _DocSandboxedEnvironment(**kwargs)
        for name, fn in self._get_render_helpers(record).items():
            env_j.globals[name] = fn
        return env_j

    # ─── 元素樹走訪 ──────────────────────────────────────────────────
    #
    # content_json 是 canvas-editor getValue().data，形狀為
    #   {header: [...], main: [...], footer: [...]}
    # 只走 main 會漏掉頁首頁尾的變數；不遞迴 trList/tdList 會漏掉表格內的變數。
    # 快照、攤平、遷移三支共用這裡，不各寫一份。

    _ELEMENT_ZONES = ('header', 'main', 'footer')

    def _iter_element_lists(self, tree):
        """yield 樹中每一個「元素串列」（含頁首/頁尾/表格儲存格/超連結子串）。

        yield 的是 list 物件本身，呼叫端可就地改寫（攤平需要換掉元素）。
        """
        if isinstance(tree, dict):
            roots = [tree[z] for z in self._ELEMENT_ZONES
                     if isinstance(tree.get(z), list)]
            if not roots and not any(z in tree for z in self._ELEMENT_ZONES):
                # 少數舊資料直接存成單一 list 包在 dict 裡的情況，盡量容錯
                roots = [v for v in tree.values() if isinstance(v, list)]
        elif isinstance(tree, list):
            roots = [tree]
        else:
            return

        stack = list(roots)
        while stack:
            elements = stack.pop()
            yield elements
            for el in elements:
                if not isinstance(el, dict):
                    continue
                # 超連結 / 日期等群組元素的子串
                if isinstance(el.get('valueList'), list):
                    stack.append(el['valueList'])
                # 表格：trList → tdList → value（value 在儲存格內是元素串列）
                for row in (el.get('trList') or []):
                    if not isinstance(row, dict):
                        continue
                    for cell in (row.get('tdList') or []):
                        if isinstance(cell, dict) and isinstance(cell.get('value'), list):
                            stack.append(cell['value'])

    def _iter_elements(self, tree):
        """yield 樹中每一個元素 dict。"""
        for elements in self._iter_element_lists(tree):
            for el in elements:
                if isinstance(el, dict):
                    yield el

    # ─── 藥丸綁定 meta ───────────────────────────────────────────────

    DOBTOR_FIELD_KEY = 'dobtorField'

    def _element_field_meta(self, element):
        """取出元素的綁定定義；不是模型變數藥丸就回 None。"""
        if not isinstance(element, dict) or element.get('type') != 'label':
            return None
        meta = (element.get('extension') or {}).get(self.DOBTOR_FIELD_KEY)
        return meta if isinstance(meta, dict) else None

    def _field_meta_expression(self, meta):
        """把綁定 meta 轉成一段 Jinja 表達式；靜態值與空定義回 None。"""
        source = (meta.get('source') or 'record').strip()
        if source == 'static':
            return None
        expression = (meta.get('expression') or '').strip()
        if expression:
            return expression
        path = (meta.get('path') or '').strip()
        if not path:
            return None
        expression = f'object.{path}'
        fmt = (meta.get('format') or '').strip()
        if fmt:
            # 目前只支援 strftime 形態；非日期欄位給了格式也不會炸（helper 會原樣回傳）
            expression = "format_date(%s, '%s')" % (expression, fmt.replace("'", ''))
        return expression

    def _snapshot_content_json(self, tree, record):
        """把模型變數藥丸求值後寫進 label 的 value（就地改寫並回傳 tree）。

        決策一（建立時快照）：值在此凍結一次，之後改記錄不會動到文件。
        決策三（空值印空白）：求值為 falsy 一律寫空字串，不印底線也不擋。

        藥丸結構刻意保留——凍結後仍看得出哪些字是帶進來的、右側面板仍能顯示
        來源欄位、也仍然可以按「重新帶值」重跑。快照時就攤平的話這三件事全失去。
        """
        if not tree or record is None:
            return tree
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
            value = '' if rendered in (None, 'False', 'None') else str(rendered)
            cache[expression] = value
            return value

        for element in self._iter_elements(tree):
            meta = self._element_field_meta(element)
            if not meta:
                continue
            if (meta.get('source') or 'record') == 'static':
                element['value'] = meta.get('static') or ''
                continue
            expression = self._field_meta_expression(meta)
            element['value'] = _eval(expression) if expression else ''
        return tree

    def _flatten_content_json(self, tree):
        """把藥丸攤平成純文字元素（就地改寫並回傳 tree）。

        決策四（只輸出值）：丟掉 label 樣式與 extension，網底屬編輯輔助，
        不進正式文件。**不求值**——值應已由快照凍結在 value 裡。
        """
        if not tree:
            return tree
        for elements in self._iter_element_lists(tree):
            for idx, el in enumerate(elements):
                if not isinstance(el, dict) or el.get('type') != 'label':
                    continue
                plain = {k: v for k, v in el.items()
                         if k not in ('type', 'label', 'extension', 'labelId')}
                plain['value'] = el.get('value') or ''
                elements[idx] = plain
        return tree

    # ─── 元素樹 → HTML（伺服器端匯出鏈用）────────────────────────────
    #
    # 前端有 canvas-editor 的 getHTML()，伺服器端沒有。匯出改以 content_json
    # 為權威之後，這支轉換是必要的。涵蓋本模組實際會產生的元素類型；
    # 未知類型退回「輸出其 value 的逸出文字」——最壞情況是掉格式，不是掉內容。

    _ROW_FLEX_ALIGN = {
        'left': 'left', 'center': 'center', 'right': 'right',
        'alignment': 'justify', 'justify': 'justify',
    }

    def _element_style(self, el):
        parts = []
        if el.get('bold'):
            parts.append('font-weight:bold')
        if el.get('italic'):
            parts.append('font-style:italic')
        decos = []
        if el.get('underline'):
            decos.append('underline')
        if el.get('strikeout'):
            decos.append('line-through')
        if decos:
            parts.append('text-decoration:%s' % ' '.join(decos))
        if el.get('color'):
            parts.append('color:%s' % el['color'])
        if el.get('highlight'):
            parts.append('background-color:%s' % el['highlight'])
        if el.get('size'):
            parts.append('font-size:%spt' % el['size'])
        if el.get('font'):
            parts.append("font-family:'%s'" % str(el['font']).replace("'", ''))
        return ';'.join(parts)

    def _inline_element_html(self, el):
        """單一行內元素 → HTML 片段。"""
        etype = el.get('type') or 'text'
        if etype == 'image':
            src = el.get('value') or ''
            if not src:
                return ''
            w = el.get('width')
            h = el.get('height')
            dims = ''
            if w:
                dims += ' width="%d"' % int(w)
            if h:
                dims += ' height="%d"' % int(h)
            return '<img src="%s"%s/>' % (html_mod.escape(src, quote=True), dims)
        if etype == 'separator':
            return '<hr/>'
        if etype == 'tab':
            return '&emsp;'
        if etype == 'checkbox':
            checked = ((el.get('checkbox') or {}).get('value'))
            return '☑' if checked else '☐'
        if etype == 'radio':
            checked = ((el.get('radio') or {}).get('value'))
            return '◉' if checked else '○'
        if etype == 'hyperlink':
            inner = ''.join(
                self._inline_element_html(c)
                for c in (el.get('valueList') or []) if isinstance(c, dict)
            ) or html_mod.escape(el.get('value') or '')
            url = html_mod.escape(el.get('url') or '', quote=True)
            return '<a href="%s">%s</a>' % (url, inner)

        text = html_mod.escape(el.get('value') or '')
        if not text:
            return ''
        style = self._element_style(el)
        if etype == 'label':
            # 理論上匯出前已攤平；萬一漏了也只輸出文字，不帶網底（決策四）
            return text
        return '<span style="%s">%s</span>' % (style, text) if style else text

    def _table_to_html(self, el):
        rows = []
        for row in (el.get('trList') or []):
            if not isinstance(row, dict):
                continue
            cells = []
            for cell in (row.get('tdList') or []):
                if not isinstance(cell, dict):
                    continue
                attrs = ''
                if (cell.get('colspan') or 1) > 1:
                    attrs += ' colspan="%d"' % int(cell['colspan'])
                if (cell.get('rowspan') or 1) > 1:
                    attrs += ' rowspan="%d"' % int(cell['rowspan'])
                cells.append('<td%s>%s</td>' % (
                    attrs, self._elements_to_html(cell.get('value') or []),
                ))
            if cells:
                rows.append('<tr>%s</tr>' % ''.join(cells))
        return '<table>%s</table>' % ''.join(rows) if rows else ''

    def _elements_to_html(self, elements):
        """元素串列 → HTML。

        canvas-editor 的元素串列是扁平的，用 value == '\\n' 標示換行；
        換行元素身上的 rowFlex 決定該段落的對齊。
        """
        out = []
        buf = []

        def _flush(row_el=None):
            if not buf:
                # 空段落也要保留，否則多個空行會被吃掉、版面走樣
                out.append('<p><br/></p>')
                return
            align = self._ROW_FLEX_ALIGN.get((row_el or {}).get('rowFlex') or '')
            style = ' style="text-align:%s"' % align if align else ''
            out.append('<p%s>%s</p>' % (style, ''.join(buf)))
            buf.clear()

        for el in (elements or []):
            if not isinstance(el, dict):
                continue
            etype = el.get('type') or 'text'
            if etype == 'table':
                if buf:
                    _flush()
                out.append(self._table_to_html(el))
                continue
            if etype == 'pageBreak':
                if buf:
                    _flush()
                out.append('<div class="doc-page-break"></div>')
                continue
            if (el.get('value') or '') == '\n':
                _flush(el)
                continue
            buf.append(self._inline_element_html(el))
        if buf:
            _flush()
        return ''.join(out)

    def _content_json_to_html(self, tree, zone='main'):
        """content_json 的指定區域 → HTML。"""
        if isinstance(tree, dict):
            elements = tree.get(zone)
        elif isinstance(tree, list) and zone == 'main':
            elements = tree
        else:
            elements = None
        return self._elements_to_html(elements or [])

    def _parse_content_json(self, raw):
        """content_json 欄位（字串或已解析物件）→ dict/list；失敗回 None。"""
        if not raw:
            return None
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return None
