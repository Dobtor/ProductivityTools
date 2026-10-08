"""RenderFields — 欄位清單、型別→格式表、別名（alias 退場中）。

給編輯器左欄用的欄位清單、**唯一一份「欄位型別該怎麼格式化」的表**
（_type_format_expression），以及 L2-v2 的 alias 對映。

型別表放在這一層而不是 sandbox：讀程式的人問「date 欄位為什麼印成
10/08/2026」時，會先找「欄位」而不是「沙箱」。sandbox 的
_field_meta_expression 呼叫它。

alias 機制退場中（視圖已移除「新增對映」入口），這裡保留的是讀取與清除
路徑，給既有資料用。新範本一律用藥丸。
"""
import re


from odoo import api
from odoo.exceptions import UserError, AccessError


# 中文 token 標記符號。前後綴用《》（U+300A / U+300B），降低與正文衝突機率。
# 若 token 內含 》 會被 _ALIAS_PATTERN 提前終止，這是刻意行為（避免巢狀解析歧義）。
_ALIAS_PATTERN = re.compile(r'《([^》]+)》')

# 純變數名 Jinja 表達式（不含 object. 前綴的舊式變數）。
# 例：{{ project_name }} 會被當作可替換 token；{{ object.partner_id.name }} 不會（保留給 Jinja2）。
_VAR_NAME_RE = re.compile(r'^[A-Za-z_][\w]*$')
_JINJA_VARNAME_PATTERN = re.compile(r'\{\{\s*([A-Za-z_][\w]*)\s*\}\}')


class RenderFields:


    # ═══ 型別 → 格式：唯一一份 ═══════════════════════════════════════
    #
    # 這張表原本有五份，互不相交，於是同一個欄位走不同路徑印出不同結果：
    #
    #   doc_qweb_converter._auto_format      monetary/float/integer/date/datetime
    #   doc_editor.js _metaForModelField     selection（只有頂層）/monetary
    #   doc_editor.js _metaForLineField      monetary
    #   doc_editor.js onInsertGroupSubtotal  monetary；其餘固定兩位小數
    #   fields._expr_for（已退場的 alias）    date/datetime/selection/many2one
    #
    # 實際症狀：
    #   * 轉換器不補 selection → t-field="o.state" 印 done 而不是「完成」
    #     （stock 的 report_stockpicking_operations 與 report_stock_reception）
    #   * 編輯器左欄拖一個 date 進去印 2026-10-08 00:00:00、float 印 100.0
    #     ——同一個欄位，走轉換器對、手工拉錯
    #   * 巢狀 selection（客戶-狀態）印代碼，因為那三份都只處理頂層
    #   * 數量欄位 digits=(16,3) 時明細三位小數、小計兩位
    #
    # 現在只有這一份，而且在渲染層：藥丸只要帶 path，格式就是對的。
    # 明寫 expression 的藥丸不受影響（原範本有 widget、或使用者自己打的）。
    _TYPE_FORMAT = {
        'monetary': 'format_money(%s)',
        'integer': "format_number(%s, ',.0f')",
        'date': "format_date(%s, 'lang')",
        'datetime': "format_date(%s, 'lang_datetime')",
        'many2one': '%s.display_name',
        'many2many': 'names(%s)',
        'one2many': 'names(%s)',
        # float 要讀欄位自己的 digits、selection 要欄位名 → 在下面另外處理
    }
    # 轉換器只套這幾個。理由寫在 doc_qweb_converter._auto_format 的呼叫處：
    # 它要對齊的是原生 QWeb，而原生對 t-out 的數字也不格式化——這組的範圍
    # 是已經量過保真度的現狀，不在這次一併改。
    _TYPE_FORMAT_NUMERIC = ('monetary', 'float', 'integer', 'date', 'datetime')

    def _type_format_expression(self, model_name, path, base, numeric_only=False):
        """依欄位型別把 base 包成帶格式的表達式；不用包時回 None。

        查不到模型或欄位就回 None——查不到不要猜，印原值至少看得出是什麼。
        刻意不含 boolean：原生 QWeb 對布林沒有 field converter（True 印
        "True"、False 印空白），放進來會讓轉換的報表與原生不一致。要方框的
        範本明寫 checkmark(object.x)。
        """
        field = self._resolve_path_field(model_name, path)
        ttype = getattr(field, 'type', None)
        if not ttype:
            return None
        if numeric_only and ttype not in self._TYPE_FORMAT_NUMERIC:
            return None
        if ttype == 'float':
            return "format_number(%s, ',.%df')" % (base, self._field_scale(field))
        if ttype == 'selection':
            # selection_label 吃路徑（不是 base）：它要自己走到擁有那個欄位的
            # 記錄身上讀 _description_selection，拿不到已格式化的字串。
            return "selection_label('%s')" % path.replace("'", '')
        wrapper = self._TYPE_FORMAT.get(ttype)
        return (wrapper % base) if wrapper else None

    def _field_label_text(self, record, meta):
        """欄位標籤藥丸的文字（fields_get 的 string，已翻譯）。

        語言：取 record 身上的 lang（_record_in_lang 已經把渲染語言套進去了）
        再餵給 fields_get。這就是不用 i18n 藥丸的理由——翻譯是 Odoo 自己的，
        不必請使用者逐語言輸入，也不會和 Odoo 的 .po 漂移。

        model 由 meta 明講而不是從 record 推：表頭的「單價」是**明細**的欄位
        標籤，而那顆藥丸放在重複列外面，求值時的 record 是主記錄。推斷的話
        整排表頭都會查不到欄位而落空。

        查不到時回 labelText（編輯器裡顯示的那串字）而不是空字串：一個看得懂
        的字比一格空白好，而且使用者看得出是哪一顆藥丸要修。
        """
        path = (meta.get('path') or '').strip()
        model_name = (meta.get('labelModel') or '').strip()
        fallback = meta.get('labelText') or ''
        if not path:
            return fallback
        if not model_name and record is not None:
            model_name = getattr(record, '_name', '')
        field = self._resolve_path_field(model_name, path)
        if field is None:
            return fallback
        # 擁有這個欄位的模型（路徑最後一段的擁有者），不是起點模型
        owner = field.model_name if hasattr(field, 'model_name') else model_name
        Model = self.env.get(owner)
        if Model is None:
            return fallback
        # 跟著渲染語言：record 已經是 _record_in_lang 處理過的。
        # 只在真的有 lang 時才覆寫——明寫 lang=None 會讓 fields_get 回原文，
        # 把使用者自己的語言也一起蓋掉。
        lang = record.env.context.get('lang') if record is not None else None
        if lang:
            Model = Model.with_context(lang=lang)
        try:
            info = Model.fields_get([field.name], ['string'])
        except Exception:
            return fallback
        return (info.get(field.name) or {}).get('string') or fallback

    def _field_scale(self, field, default=2):
        """欄位的小數位數。

        一定要走 get_digits(env)：digits 可以是 decimal.precision 的**名字**
        （數量欄位就是 'Product Unit of Measure'），直接讀 field.digits 拿到
        的是那個字串，isinstance(tuple) 不成立就退回兩位——於是數量印兩位
        小數而原生印三位。這是原本轉換器裡那份複本的既有錯誤，一起修掉。
        """
        try:
            digits = field.get_digits(self.env)
        except Exception:
            digits = getattr(field, 'digits', None)
        if isinstance(digits, (tuple, list)) and len(digits) == 2:
            return int(digits[1])
        return default

    def _resolve_path_field(self, model_name, path):
        """沿著帶點的路徑走到最後一段的 field 物件；走不到回 None。"""
        if not model_name or not path:
            return None
        Model = self.env.get(model_name)
        if Model is None:
            return None
        field = None
        parts = str(path).split('.')
        for idx, part in enumerate(parts):
            if Model is None:
                return None
            field = Model._fields.get(part)
            if field is None:
                return None
            if idx < len(parts) - 1:
                comodel = getattr(field, 'comodel_name', None)
                if not comodel:
                    return None
                Model = self.env.get(comodel)
        return field
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

    # 可放進文件的欄位型別。
    #
    # one2many / many2many 一定要在清單裡——左欄「明細（一對多）」那一組是靠
    # 它們產生的，漏掉的話整個重複列功能在 UI 上沒有入口（後端跑得動、使用者
    # 點不到）。binary 則是圖片藥丸（客戶簽名、公司 logo）的來源。
    # 前端負責把這三種分流到各自的面板，不要混進「主記錄欄位」的純量清單。
    _FIELD_TTYPES = (
        'char', 'text', 'integer', 'float', 'monetary',
        'date', 'datetime', 'boolean', 'selection', 'many2one',
        'one2many', 'many2many', 'binary', 'html',
    )
    # 純量（可直接當變數印出來）的型別——其餘要走專屬面板
    _SCALAR_TTYPES = (
        'char', 'text', 'html', 'integer', 'float', 'monetary',
        'date', 'datetime', 'boolean', 'selection', 'many2one',
    )

    def _get_fields_for_model(self, model_name, max_depth=2, current_depth=0):
        """遞迴取得模型欄位，限制深度以防止無限遞迴。"""
        IrModelFields = self.env['ir.model.fields']
        fields = IrModelFields.search([
            ('model', '=', model_name),
            ('store', '=', True),
            ('ttype', 'in', self._FIELD_TTYPES),
        ], order='field_description asc')

        result = []
        for f in fields:
            field_info = {
                'name': f.name,
                'label': f.field_description,
                'type': f.ttype,
                'expression': '{{{{ object.{} }}}}'.format(f.name),
            }
            # 小數位。前端的聚合藥丸（累計／本組小計）需要它：那些藥丸的
            # 來源是 sum(...) 而不是一條欄位路徑，_type_format_expression
            # 查不到型別，所以格式必須在插入時寫進 meta。至少讓它和明細欄
            # 讀同一個權威來源（ir.model.fields），不要再各自寫死兩位。
            if f.ttype in ('float', 'monetary'):
                real = self._resolve_path_field(model_name, f.name)
                field_info['digits'] = (
                    self._field_scale(real) if real is not None else 2)
            if f.relation:
                field_info['relation'] = f.relation
            # Many2one：若未達深度限制，遞迴取子欄位。
            # 刻意不遞迴 x2many——一對多的子欄位由「明細欄位」面板在設好
            # 重複列之後另外載入，在這裡展開只會讓 payload 爆掉。
            if f.ttype == 'many2one' and f.relation and current_depth < max_depth:
                if f.relation in self.env:
                    try:
                        self.env[f.relation].check_access('read')
                        field_info['sub_fields'] = self._get_fields_for_model(
                            f.relation, max_depth, current_depth + 1
                        )
                    except AccessError:
                        field_info['sub_fields'] = []
            result.append(field_info)
        return result
